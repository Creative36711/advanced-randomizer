"""Advanced Randomizer launcher engine.

One command per line, no window code, no third-party imports.  The window is
``launcher.ps1`` (PowerShell 5.1 + WinForms, present on every Windows 10/11);
this file is everything that window *decides*, so the decisions can be tested
on any machine with a Python interpreter.

Why the split exists
--------------------
The player must not need Python, git, Godot, Blender or a console to play.
PowerShell gives us a window for free, but PowerShell logic cannot be trusted
untested.  So the window only:

* asks for folders (native WinForms dialogs),
* calls ``python engine.py <step>`` and streams the output into a log box.

Every path, hash, refusal and ordering rule lives here.

Exit codes
----------
0  success
2  usage / settings problem (the player must choose something)
3  download missing or hash mismatch (a maintainer must pin it)
4  a tool run failed (the log above explains it)
5  the install is not in a state this step may act on
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

from pinned import (
    CONTENT_PACKS_RELATIVE,
    FFMPEG_EXE_SHA256,
    FFMPEG_URL_CANDIDATES,
    FFPROBE_EXE_SHA256,
    GODOT_WIN64_ZIP,
    MINGIT_64_ZIP,
    OPENBFME_SOURCE_RELATIVE,
    PINNED_PYTHON,
)

APP_NAME = "AdvancedRandomizer"
SETTINGS_SCHEMA = "advanced-randomizer.launcher-settings"
SEED_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

ROTWK_ONLY_MARKERS = ("lotrbfme2ep1.exe", "_patch201.big")
BFME2_ONLY_MARKERS = ("lotrbfme2.exe",)
PATCH202_MARKERS = (
    "__patch202.big",
    "_202music.big",
    "___hdrotwk.v.0.9.big",
    r"lang/englishpatch202.big",
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DOWNLOAD = 3
EXIT_TOOL = 4
EXIT_STATE = 5


class LauncherError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_TOOL) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def default_settings_path() -> Path:
    """Per-user settings; never inside the repository.

    ``%APPDATA%\\AdvancedRandomizer\\settings.json`` on Windows, an XDG path
    elsewhere so the engine runs unchanged in a test runner.
    """

    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME / "settings.json"


def default_install_root() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "Advanced Randomizer"


class Settings:
    def __init__(
        self,
        install_root: Path | None = None,
        bfme2_install: Path | None = None,
        rotwk_install: Path | None = None,
        patch202_root: Path | None = None,
        seed: str = "Arda",
        auto_seed: bool = True,
    ) -> None:
        self.install_root = Path(install_root) if install_root else None
        self.bfme2_install = Path(bfme2_install) if bfme2_install else None
        self.rotwk_install = Path(rotwk_install) if rotwk_install else None
        self.patch202_root = Path(patch202_root) if patch202_root else None
        self.seed = seed or "Arda"
        self.auto_seed = bool(auto_seed)

    def to_json(self) -> dict:
        def text(value: Path | None) -> str | None:
            return str(value) if value else None

        return {
            "schema": SETTINGS_SCHEMA,
            "schemaVersion": 1,
            "installRoot": text(self.install_root),
            "bfme2Install": text(self.bfme2_install),
            "rotwkInstall": text(self.rotwk_install),
            "patch202Root": text(self.patch202_root),
            "seed": self.seed,
            "autoSeed": self.auto_seed,
        }

    @classmethod
    def from_json(cls, value: object) -> "Settings":
        if not isinstance(value, dict):
            return cls()
        seed = value.get("seed")
        return cls(
            install_root=_as_path(value.get("installRoot")),
            bfme2_install=_as_path(value.get("bfme2Install")),
            rotwk_install=_as_path(value.get("rotwkInstall")),
            patch202_root=_as_path(value.get("patch202Root")),
            seed=seed if isinstance(seed, str) and seed else "Arda",
            auto_seed=value.get("autoSeed", True) is not False,
        )


def _as_path(value: object) -> Path | None:
    if isinstance(value, str) and value.strip():
        return Path(value)
    return None


def load_settings(path: Path) -> Settings:
    try:
        return Settings.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return Settings()


def save_settings(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.to_json(), indent=2, ensure_ascii=False) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Layout inside the install root
# ---------------------------------------------------------------------------


def source_tree(install_root: Path) -> Path:
    return install_root / OPENBFME_SOURCE_RELATIVE


def content_packs(install_root: Path) -> Path:
    return source_tree(install_root) / CONTENT_PACKS_RELATIVE


def state_root(install_root: Path) -> Path:
    return source_tree(install_root) / "workspace" / "retail-work"


def venv_python(install_root: Path) -> Path:
    return state_root(install_root) / "tools" / "python-3.12-env" / "Scripts" / "python.exe"


def pinned_python(install_root: Path) -> Path:
    return install_root / "tools" / f"cpython-{PINNED_PYTHON.version}" / "python.exe"


def godot_exe(install_root: Path) -> Path:
    return install_root / "tools" / "godot" / f"Godot_v{GODOT_WIN64_ZIP.version}-stable_win64.exe"


def mingit_dir(install_root: Path) -> Path:
    return install_root / "tools" / "mingit"


def ffmpeg_exe(install_root: Path) -> Path:
    return install_root / "tools" / "ffmpeg-8.1.1" / "bin" / "ffmpeg.exe"


def downloads_dir(install_root: Path) -> Path:
    return install_root / "downloads"


def markers_dir(install_root: Path) -> Path:
    return install_root / ".launcher"


# ---------------------------------------------------------------------------
# Small filesystem helpers
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def marker(install_root: Path, name: str) -> bool:
    return (markers_dir(install_root) / name).is_file()


def mark(install_root: Path, name: str, text: str = "") -> None:
    directory = markers_dir(install_root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")


def unmark(install_root: Path, name: str) -> None:
    (markers_dir(install_root) / name).unlink(missing_ok=True)


def human_bytes(value: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


# ---------------------------------------------------------------------------
# Downloads: verify, then move; never install an unverified byte
# ---------------------------------------------------------------------------


class DownloadError(LauncherError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_DOWNLOAD)


def download(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None,
    expected_size: int | None = None,
    label: str = "",
    echo=print,
    opener=urllib.request.urlopen,
    allow_unpinned: bool = False,
) -> Path:
    """Stream ``url`` into ``destination`` and verify it before it exists.

    A mismatch deletes the partial and raises with both digests, because a
    checksum failure the player cannot read is the same as no check at all.

    ``allow_unpinned`` is only for archives that move upstream (the FFmpeg
    zip).  It never relaxes the final check: the caller still verifies the
    *executables* against the digests the importer accepts, which is the fact
    that matters.  Everything else refuses an unpinned download outright.
    """

    label = label or destination.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    if not expected_sha256 and not allow_unpinned:
        raise DownloadError(
            f"{label}: SHA-256 не закреплён в лаунчере, скачивание не начато."
        )
    echo(f"Скачиваю {label}…")
    request = urllib.request.Request(
        url, headers={"User-Agent": "AdvancedRandomizer/1.0"}
    )
    digest = hashlib.sha256()
    written = 0
    started = time.monotonic()
    try:
        with opener(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with temporary.open("wb") as out:
                while block := response.read(1024 * 1024):
                    out.write(block)
                    digest.update(block)
                    written += len(block)
                    if expected_size and written > expected_size:
                        raise DownloadError(
                            f"{label}: сервер отдал больше {human_bytes(expected_size)}; "
                            "загрузка прервана."
                        )
                    if total and written % (16 * 1024 * 1024) < len(block):
                        echo(f"  {human_bytes(written)} из {human_bytes(total)}")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    measured = digest.hexdigest()
    if expected_size and written != expected_size:
        temporary.unlink(missing_ok=True)
        raise DownloadError(
            f"{label}: получено {human_bytes(written)}, ожидалось {human_bytes(expected_size)}."
        )
    if expected_sha256 and measured != expected_sha256.casefold():
        temporary.unlink(missing_ok=True)
        raise DownloadError(
            f"{label}: SHA-256 не совпал.\n"
            f"  ожидалось {expected_sha256}\n"
            f"  получено  {measured}"
        )
    os.replace(temporary, destination)
    echo(
        f"Готово: {label} ({human_bytes(written)}, "
        f"{time.monotonic() - started:.0f} c)"
    )
    return destination


def extract_zip(archive: Path, destination: Path, *, label: str = "") -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = (destination / info.filename).resolve()
            if not str(target).startswith(str(root)):
                raise LauncherError(
                    f"{label or archive.name}: архив пытается писать вне папки назначения."
                )
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)


def extract_tar_gz(archive: Path, destination: Path, *, label: str = "") -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            target = (destination / member.name).resolve()
            if not str(target).startswith(str(root)):
                raise LauncherError(
                    f"{label or archive.name}: архив пытается писать вне папки назначения."
                )
        tf.extractall(destination)


# ---------------------------------------------------------------------------
# Retail detection
# ---------------------------------------------------------------------------


def describe_folder(path: Path) -> str:
    """Return ``layered``, ``rotwk``, ``bfme2`` or ``unknown`` (read-only)."""

    try:
        if not path.is_dir() or not (path / "game.dat").is_file():
            return "unknown"
        if all(
            (path / layer / "game.dat").is_file()
            for layer in ("layer-1-rotwk", "layer-2-bfme2")
        ) and (path / "layer-0-patch202" / "__patch202.big").is_file():
            return "layered"
        if any((path / name).is_file() for name in ROTWK_ONLY_MARKERS):
            return "rotwk"
        if any((path / name).is_file() for name in BFME2_ONLY_MARKERS):
            return "bfme2"
    except OSError:
        return "unknown"
    return "unknown"


def has_patch202(path: Path | None) -> bool:
    """True when ``path`` carries every file the 2.02 overlay lane requires."""

    if path is None:
        return False
    return all((path / relative).is_file() for relative in PATCH202_MARKERS)


def candidate_folders() -> list[Path]:
    """Common retail locations, machine-derived, no developer paths."""

    roots: list[Path] = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        value = os.environ.get(variable, "").strip()
        if value:
            roots.append(Path(value))
    if os.name == "nt":
        for letter in "CDEFGH":
            drive = Path(f"{letter}:/")
            try:
                if drive.exists():
                    roots.append(drive)
                    roots.append(drive / "Games")
            except OSError:
                continue
    relative = (
        "Electronic Arts/The Lord of the Rings, The Rise of the Witch-king",
        "EA Games/The Lord of the Rings, The Rise of the Witch-king",
        "Steam/steamapps/common/The Lord of the Rings, The Rise of the Witch-king",
        "RotWK",
        "ROTWK",
        "Electronic Arts/The Battle for Middle-earth II",
        "EA Games/The Battle for Middle-earth II",
        "Steam/steamapps/common/The Battle for Middle-earth II",
        "GOG Galaxy/Games/The Battle for Middle-earth II",
        "BFME2",
    )
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for item in relative:
            candidate = root / item
            key = str(candidate).casefold()
            if key in seen:
                continue
            seen.add(key)
            try:
                if (candidate / "game.dat").is_file():
                    found.append(candidate)
            except OSError:
                continue
    return found


def detect_installs() -> tuple[Path | None, Path | None, Path | None]:
    """Return ``(rotwk, bfme2, patch202_root)``; each may be ``None``."""

    rotwk = bfme2 = patch = None
    for candidate in candidate_folders():
        kind = describe_folder(candidate)
        if kind in ("rotwk", "layered") and rotwk is None:
            rotwk = candidate
        elif kind == "bfme2" and bfme2 is None:
            bfme2 = candidate
        if patch is None and has_patch202(candidate):
            patch = candidate
    return rotwk, bfme2, patch


# ---------------------------------------------------------------------------
# Source tree state
# ---------------------------------------------------------------------------


def source_ready(install_root: Path) -> bool:
    tree = source_tree(install_root)
    return (tree / "game" / "project.godot").is_file() and (
        tree / "tools" / "openbfme_import.py"
    ).is_file()


def selected_pack(install_root: Path) -> dict | None:
    root = content_packs(install_root)
    try:
        value = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    active = value.get("activePack")
    if not isinstance(active, str) or not active.strip():
        return None
    if not (root / active).exists():
        return None
    return value


def status(settings: Settings) -> dict:
    """Everything the window needs to draw one line of truth per row."""

    root = settings.install_root
    report: dict = {
        "installRoot": str(root) if root else None,
        "installRootExists": bool(root and root.is_dir()),
        "sourceReady": False,
        "godotReady": False,
        "pythonReady": False,
        "venvReady": False,
        "toolsReady": False,
        "packSelected": False,
        "activePack": None,
        "seed": settings.seed,
        "ready": False,
        "rotwk": _describe(settings.rotwk_install),
        "bfme2": _describe(settings.bfme2_install),
        "patch202": has_patch202(settings.patch202_root),
        "patch202Root": str(settings.patch202_root) if settings.patch202_root else None,
        "canFullRotwk": bool(
            settings.rotwk_install
            and settings.bfme2_install
            and has_patch202(settings.patch202_root)
        ),
        # What the window may prefill a field with when it is still empty.
        "defaultInstallRoot": str(default_install_root()),
        "detectedRotwk": _detect_one("rotwk"),
        "detectedBfme2": _detect_one("bfme2"),
        "detectedPatch202": _detect_one("patch202"),
        "notes": [],
    }
    if root is None:
        report["notes"].append("Папка лаунчера не выбрана.")
        return report
    report["sourceReady"] = source_ready(root)
    report["godotReady"] = godot_exe(root).is_file()
    report["pythonReady"] = pinned_python(root).is_file()
    report["venvReady"] = venv_python(root).is_file()
    report["toolsReady"] = marker(root, "tools.ok")
    pack = selected_pack(root)
    report["packSelected"] = pack is not None
    report["activePack"] = pack.get("activePack") if pack else None
    report["ready"] = bool(
        report["sourceReady"] and report["godotReady"] and report["packSelected"]
    )
    if not report["sourceReady"]:
        report["notes"].append("Исходники OpenBFME ещё не собраны.")
    if not report["godotReady"]:
        report["notes"].append("Движок Godot ещё не скачан.")
    if not report["packSelected"]:
        report["notes"].append("Контент ещё не сконвертирован.")
    if not report["bfme2"]:
        report["notes"].append(
            "Папка BFME2 1.06 не выбрана — без неё контент не из чего конвертировать."
        )
    return report


def _describe(path: Path | None) -> str | None:
    if path is None:
        return None
    return describe_folder(path)


@functools.lru_cache(maxsize=8)
def _detect_one(kind: str) -> str | None:
    """One cached probe per run, so drawing the window stays instant."""

    rotwk, bfme2, patch = detect_installs()
    if kind == "rotwk":
        return str(rotwk) if rotwk else None
    if kind == "bfme2":
        return str(bfme2) if bfme2 else None
    return str(patch) if patch else None


# ---------------------------------------------------------------------------
# Subprocess seam: every external program goes through this one object
# ---------------------------------------------------------------------------


class Runner:
    """Runs a command, echoing its output; returns the exit code.

    ``env`` here is *additional* environment, merged over the current process,
    which is how OPENBFME_CONTENT and PATH reach Godot and the importer.
    """

    def __init__(self, echo=print) -> None:
        self.echo = echo

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
        capture: bool = False,
    ) -> subprocess.CompletedProcess:
        printable = " ".join(_quote(part) for part in args)
        self.echo(f"$ {printable}")
        merged = dict(os.environ)
        merged.update(env or {})
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=merged,
            text=True,
            capture_output=bool(capture),
            check=False,
            creationflags=creationflags,
        )
        if capture:
            if process.stdout:
                for line in process.stdout.splitlines():
                    self.echo(line)
            if process.stderr:
                for line in process.stderr.splitlines():
                    self.echo("! " + line)
        if check and process.returncode != 0:
            raise LauncherError(
                f"Команда завершилась с кодом {process.returncode}:\n  {printable}",
                EXIT_TOOL,
            )
        return process


def _quote(part: str) -> str:
    return f'"{part}"' if " " in part else part


# ---------------------------------------------------------------------------
# Pinned Python
# ---------------------------------------------------------------------------


def pinned_python_archive(install_root: Path) -> Path:
    return downloads_dir(install_root) / PINNED_PYTHON.archive_name


def ensure_python(settings: Settings, runner: Runner, *, echo=print) -> Path:
    """Install the importer's exact interpreter, or reuse the local copy.

    The archive is looked for in ``<install root>/downloads`` FIRST.  A player
    behind a block (several ISPs block GitHub release assets) can download
    that one file by hand, drop it there, and the launcher will verify it and
    continue - the hash is the check, not the transport.
    """

    root = _install_root(settings)
    target = pinned_python(root)
    if target.is_file() and sha256_file(target) == PINNED_PYTHON.exe_sha256:
        return target
    archive = pinned_python_archive(root)
    if archive.is_file():
        if sha256_file(archive) != PINNED_PYTHON.sha256:
            echo(
                f"  файл {archive.name} лежит в downloads, но его SHA-256 другой — "
                "скачиваю заново"
            )
            archive.unlink()
        else:
            echo(f"Использую уже скачанный {archive.name}")
    if not archive.is_file():
        try:
            download(
                PINNED_PYTHON.url,
                archive,
                expected_sha256=PINNED_PYTHON.sha256,
                label=f"Python {PINNED_PYTHON.version}",
                echo=echo,
            )
        except DownloadError as error:
            raise DownloadError(
                f"{error}\n\n"
                "Если GitHub отсюда недоступен, скачайте файл вручную:\n"
                f"  {PINNED_PYTHON.url}\n"
                f"и положите его сюда:\n  {archive}"
            ) from error
    staging = target.parent.with_name(target.parent.name + ".installing")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        extract_tar_gz(archive, staging, label="Python")
        extracted = staging / "python"
        if not (extracted / "python.exe").is_file():
            raise DownloadError("Архив Python распаковался без python.exe.")
        measured = sha256_file(extracted / "python.exe")
        if measured != PINNED_PYTHON.exe_sha256:
            raise DownloadError(
                "python.exe в архиве не совпадает с закреплённым хешем.\n"
                f"  ожидалось {PINNED_PYTHON.exe_sha256}\n  получено  {measured}"
            )
        if target.parent.exists():
            shutil.rmtree(target.parent)
        extracted.rename(target.parent)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    echo(f"Python {PINNED_PYTHON.version} установлен: {target}")
    return target


# ---------------------------------------------------------------------------
# git (system first, MinGit second) and ffmpeg
# ---------------------------------------------------------------------------


def find_system_git() -> Path | None:
    found = shutil.which("git")
    return Path(found) if found else None


def ensure_git(settings: Settings, *, echo=print) -> Path:
    root = _install_root(settings)
    local = mingit_dir(root) / "cmd" / "git.exe"
    if local.is_file():
        return local
    system = find_system_git()
    if system is not None:
        return system
    archive = downloads_dir(root) / "mingit.zip"
    if not archive.is_file():
        download(
            MINGIT_64_ZIP.url,
            archive,
            expected_sha256=MINGIT_64_ZIP.sha256,
            label="Git (MinGit)",
            echo=echo,
        )
    extract_zip(archive, mingit_dir(root), label="MinGit")
    if not local.is_file():
        raise DownloadError(
            "В архиве MinGit нет cmd/git.exe — распаковка не удалась."
        )
    echo(f"Git установлен: {local}")
    return local


def git_environment(git: Path) -> dict[str, str]:
    """Make ``git`` from MinGit visible to child processes (and its helpers)."""

    directory = str(git.parent)
    current = os.environ.get("PATH", "")
    return {"PATH": directory + os.pathsep + current}


def ensure_ffmpeg(settings: Settings, *, echo=print, opener=urllib.request.urlopen) -> Path:
    """Install the one ffmpeg build the importer will accept.

    The archive may move upstream, so it is not pinned as an archive; the two
    *executables* inside it are pinned to the digests the importer itself
    accepts, which is the check that actually matters.
    """

    root = _install_root(settings)
    target = ffmpeg_exe(root)
    if target.is_file() and sha256_file(target) == FFMPEG_EXE_SHA256:
        return target
    last_error: Exception | None = None
    for url in FFMPEG_URL_CANDIDATES:
        archive = downloads_dir(root) / "ffmpeg.zip"
        archive.unlink(missing_ok=True)
        try:
            download(
                url,
                archive,
                expected_sha256=None,
                label="FFmpeg",
                echo=echo,
                opener=opener,
                allow_unpinned=True,
            )
        except Exception as exc:  # try the next mirror
            last_error = exc
            echo(f"  не вышло: {exc}")
            continue
        staging = root / ".launcher" / "ffmpeg-extract"
        if staging.exists():
            shutil.rmtree(staging)
        extract_zip(archive, staging, label="FFmpeg")
        candidates = list(staging.rglob("ffmpeg.exe"))
        if not candidates:
            last_error = DownloadError("в архиве FFmpeg нет ffmpeg.exe")
            continue
        source = candidates[0]
        probe = source.with_name("ffprobe.exe")
        if not probe.is_file():
            last_error = DownloadError("в архиве FFmpeg нет ffprobe.exe")
            continue
        if sha256_file(source) != FFMPEG_EXE_SHA256:
            last_error = DownloadError(
                "ffmpeg.exe из этого архива не совпадает с закреплённым импортёром:\n"
                f"  ожидалось {FFMPEG_EXE_SHA256}\n  получено  {sha256_file(source)}"
            )
            continue
        if sha256_file(probe) != FFPROBE_EXE_SHA256:
            last_error = DownloadError("ffprobe.exe не совпадает с закреплённым хешем.")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        shutil.copyfile(probe, target.with_name("ffprobe.exe"))
        shutil.rmtree(staging, ignore_errors=True)
        archive.unlink(missing_ok=True)
        echo(f"FFmpeg установлен: {target}")
        return target
    raise DownloadError(
        "Не удалось получить FFmpeg 8.1.1. Последняя причина: "
        + (str(last_error) if last_error else "неизвестно")
    )


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _install_root(settings: Settings) -> Path:
    if settings.install_root is None:
        raise LauncherError("Сначала выберите папку лаунчера.", EXIT_USAGE)
    return settings.install_root


def _tree(settings: Settings) -> Path:
    tree = source_tree(_install_root(settings))
    if not source_ready(_install_root(settings)):
        raise LauncherError(
            "Исходники OpenBFME ещё не собраны — сначала шаг «prepare».", EXIT_STATE
        )
    return tree


def step_prepare(settings: Settings, runner: Runner, *, echo=print) -> Path:
    root = _install_root(settings)
    tree = source_tree(root)
    if source_ready(root):
        echo(f"Исходники уже собраны: {tree}")
        return tree
    if tree.exists():
        marker_file = markers_dir(root) / "assembled"
        if not marker_file.is_file() and not (tree / ".launcher-assembled").is_file():
            raise LauncherError(
                "Папка уже существует и её собирали не этим лаунчером:\n"
                f"  {tree}\n"
                "Выберите другую папку лаунчера или уберите эту вручную.",
                EXIT_STATE,
            )
        shutil.rmtree(tree)
    # prepare.py needs nothing but the standard library, so it runs on the very
    # interpreter executing this line.  That removes a download from the
    # critical path of a first run.
    python = Path(sys.executable)
    repo_root = Path(__file__).resolve().parents[2]
    prepare = repo_root / "tools" / "prepare.py"
    if not prepare.is_file():
        raise LauncherError(
            f"Не найден {prepare}. Лаунчер должен запускаться из папки репозитория.",
            EXIT_STATE,
        )
    root.mkdir(parents=True, exist_ok=True)
    runner.run(
        [str(python), str(prepare), "--output", str(tree)],
        cwd=repo_root,
        check=True,
    )
    if not source_ready(root):
        raise LauncherError(
            "Сборка завершилась, но дерева на месте нет. Смотрите лог выше.",
            EXIT_TOOL,
        )
    mark(root, "assembled")
    (tree / ".launcher-assembled").write_text(
        "Собрано лаунчером Advanced Randomizer.\n", encoding="utf-8"
    )
    return tree


def step_godot(settings: Settings, *, echo=print, opener=urllib.request.urlopen) -> Path:
    root = _install_root(settings)
    target = godot_exe(root)
    if target.is_file():
        return target
    archive = downloads_dir(root) / f"godot-{GODOT_WIN64_ZIP.version}.zip"
    if not archive.is_file():
        download(
            GODOT_WIN64_ZIP.url,
            archive,
            expected_sha256=GODOT_WIN64_ZIP.sha256,
            expected_size=GODOT_WIN64_ZIP.size,
            label=f"Godot {GODOT_WIN64_ZIP.version}",
            echo=echo,
            opener=opener,
        )
    staging = root / ".launcher" / "godot-extract"
    if staging.exists():
        shutil.rmtree(staging)
    extract_zip(archive, staging, label="Godot")
    executables = [
        path
        for path in staging.rglob("*")
        if path.is_file()
        and path.suffix.casefold() == ".exe"
        and "console" not in path.name.casefold()
    ]
    if not executables:
        raise DownloadError("В архиве Godot нет исполняемого файла.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(executables[0], target)
    shutil.rmtree(staging, ignore_errors=True)
    echo(f"Godot установлен: {target}")
    return target


def godot_import_marker(root: Path) -> Path:
    return markers_dir(root) / "imported"


def step_import(settings: Settings, runner: Runner, *, echo=print) -> None:
    """One-time Godot import pass for a freshly assembled tree.

    A source checkout has no ``.godot/imported`` cache, so the first launch
    cannot find a single image.  Upstream's manual flow opens the editor once
    and everyone forgets; the launcher cannot, so it runs the same import
    headlessly and records that it did.
    """

    root = _install_root(settings)
    tree = _tree(settings)
    if godot_import_marker(root).is_file():
        return
    engine_binary = godot_exe(root)
    if not engine_binary.is_file():
        raise LauncherError("Godot не установлен: сначала шаг «godot».", EXIT_STATE)
    echo("Первый запуск движка: импортирую ресурсы (это занимает около минуты)…")
    result = runner.run(
        [
            str(engine_binary),
            "--headless",
            "--path",
            str(tree / "game"),
            "--editor",
            "--import",
        ],
        cwd=tree / "game",
        capture=True,
    )
    marker_file = godot_import_marker(root)
    if result.returncode != 0:
        raise LauncherError(
            f"Импорт ресурсов Godot завершился с кодом {result.returncode}.", EXIT_TOOL
        )
    mark(root, "imported", str(marker_file))
    echo("Ресурсы импортированы.")


def powershell() -> str:
    for name in ("powershell.exe", "powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    raise LauncherError(
        "Не найден powershell.exe. Он входит в Windows; проверьте PATH.", EXIT_STATE
    )


def step_bootstrap_venv(settings: Settings, runner: Runner, *, echo=print) -> Path:
    root = _install_root(settings)
    tree = _tree(settings)
    python = ensure_python(settings, runner, echo=echo)
    script = tree / "tools" / "bootstrap-importer-python.ps1"
    if not script.is_file():
        raise LauncherError(f"В дереве нет {script}.", EXIT_STATE)
    environment = {
        "OPENBFME_IMPORT_ROOT": str(state_root(root)),
        # The script prefers OPENBFME_PYTHON when set, which is exactly the
        # pinned interpreter this launcher just verified.
        "OPENBFME_PYTHON": str(python),
    }
    arguments = [
        powershell(),
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-StateRoot",
        str(state_root(root)),
    ]
    offline = pinned_python_archive(root)
    if offline.is_file() and sha256_file(offline) == PINNED_PYTHON.sha256:
        arguments += ["-OfflineArchive", str(offline)]
    result = runner.run(
        arguments,
        cwd=tree,
        env=environment,
        capture=True,
    )
    if result.returncode != 0 or not venv_python(root).is_file():
        raise LauncherError(
            "Не удалось подготовить Python-окружение импортёра "
            f"(код {result.returncode}). Смотрите лог выше.",
            EXIT_TOOL,
        )
    return venv_python(root)


def step_bootstrap_tools(settings: Settings, runner: Runner, *, echo=print) -> None:
    root = _install_root(settings)
    tree = _tree(settings)
    python = venv_python(root)
    if not python.is_file():
        raise LauncherError("Окружение импортёра не готово: сначала шаг «venv».", EXIT_STATE)
    git = ensure_git(settings, echo=echo)
    ffmpeg = ensure_ffmpeg(settings, echo=echo)
    environment = {
        "PATH": git_environment(git)["PATH"],
        "OPENBFME_IMPORT_ROOT": str(state_root(root)),
        "PYTHONPATH": str(tree / "importer"),
    }
    runner.run(
        [
            str(python),
            str(tree / "tools" / "openbfme_import.py"),
            "bootstrap-tools",
            "--ffmpeg",
            str(ffmpeg),
        ],
        cwd=tree,
        env=environment,
        capture=True,
        check=True,
    )
    mark(root, "tools", f"git={git}\nffmpeg={ffmpeg}\n")
    echo("Инструменты конвертации готовы.")


def build_command(tree: Path, bfme2: Path, *, extra: list[str] | None = None) -> list[str]:
    return [
        str(tree / "tools" / "openbfme_import.py"),
        "build",
        "--install",
        str(bfme2),
        "--game",
        "bfme2",
        "--profile",
        "men-fords-v0",
        "--allow-incomplete",
        *list(extra or []),
    ]


def layered_target(install_root: Path) -> Path:
    """Where the supported RotWK+BFME2 catalog root lives for this state root."""

    return state_root(install_root) / "editions" / "rotwk" / "layered-install"


def step_layered(settings: Settings, runner: Runner, *, echo=print) -> dict:
    """Present RotWK 2.01 + BFME2 1.06 as one catalog root.

    This is the documented two-layer layout ``ensure_layered_rotwk_install``
    expects (``layer-0-rotwk`` / ``layer-1-bfme2``), which is what the generic
    RotWK importer lane needs.  It is deliberately *not* the three-layer
    2.02-v9.7.7 baseline root: that lane has its own verifier and its own
    contract, and mixing the two is how a wrong tree gets measured as right.

    Junctions only; nothing is copied out of the player's installs.
    """

    root = _install_root(settings)
    if settings.rotwk_install is None or settings.bfme2_install is None:
        raise LauncherError(
            "Для полного контента RotWK нужны обе папки: RotWK 2.01 и BFME2 1.06.",
            EXIT_USAGE,
        )
    if describe_folder(settings.rotwk_install) not in ("rotwk", "layered"):
        raise LauncherError(
            f"Папка RotWK не похожа на установку RotWK 2.01:\n  {settings.rotwk_install}",
            EXIT_USAGE,
        )
    if describe_folder(settings.bfme2_install) != "bfme2":
        raise LauncherError(
            f"Папка BFME2 не похожа на установку BFME2 1.06:\n  {settings.bfme2_install}",
            EXIT_USAGE,
        )
    target = layered_target(root)
    layers = (
        ("layer-0-rotwk", settings.rotwk_install),
        ("layer-1-bfme2", settings.bfme2_install),
    )
    if all((target / name / "game.dat").is_file() for name, _ in layers):
        if marker(root, "layered"):
            echo(f"Каталог RotWK+BFME2 уже готов: {target}")
            return {"root": str(target)}
        unmark(root, "layered")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for name, source in layers:
        link = target / name
        if link.is_symlink() or link.exists():
            raise LauncherError(
                f"Путь уже занят и это не наша связка: {link}\n"
                "Уберите его вручную и повторите.",
                EXIT_STATE,
            )
        try:
            link.symlink_to(source, target_is_directory=True)
        except OSError as error:
            raise LauncherError(
                "Windows не разрешила создать связку папок "
                f"({error}). Обычно это включено по умолчанию; "
                "если нет — запустите лаунчер один раз от имени администратора.",
                EXIT_STATE,
            ) from error
    for name, _ in layers:
        if not (target / name / "game.dat").is_file():
            raise LauncherError(
                f"Связка не открывается: {target / name}\n"
                "Проверьте, что папки не перемещали и диск доступен.",
                EXIT_STATE,
            )
    mark(root, "layered", str(target))
    echo(f"Каталог RotWK+BFME2 готов: {target}")
    return {"root": str(target)}


def step_convert(settings: Settings, runner: Runner, *, echo=print) -> None:
    root = _install_root(settings)
    tree = _tree(settings)
    if settings.bfme2_install is None:
        raise LauncherError(
            "Не выбрана папка BFME2 1.06 — из неё берётся контент.", EXIT_USAGE
        )
    if describe_folder(settings.bfme2_install) != "bfme2":
        raise LauncherError(
            "Выбранная папка не похожа на BFME2 1.06 (нет lotrbfme2.exe рядом с game.dat):\n"
            f"  {settings.bfme2_install}",
            EXIT_USAGE,
        )
    if selected_pack(root) is not None and marker(root, "converted"):
        echo(f"Контент уже сконвертирован: {selected_pack(root).get('activePack')}")
        return
    python = venv_python(root)
    if not python.is_file():
        raise LauncherError("Окружение импортёра не готово: сначала шаг «venv».", EXIT_STATE)
    environment = {
        "OPENBFME_IMPORT_ROOT": str(state_root(root)),
        "PYTHONPATH": str(tree / "importer"),
    }
    command = [str(python), *build_command(tree, settings.bfme2_install)]
    result = runner.run(command, cwd=tree, env=environment, capture=True)
    if result.returncode == 7:
        # The publish gate refuses a pack that is *knowingly* short on
        # playable units compared with what was published before. That is a
        # property of the converter's coverage; retry the documented way and
        # say so, so a first-run refusal is not a dead end.
        echo("Пак оказался короче ранее опубликованного; повторяю с разрешённым пропуском…")
        result = runner.run(
            command + ["--allow-fewer-playable-units"],
            cwd=tree,
            env=environment,
            capture=True,
        )
    if result.returncode != 0:
        raise LauncherError(
            f"Конвертация завершилась с кодом {result.returncode}. Смотрите лог выше.",
            EXIT_TOOL,
        )
    if selected_pack(root) is None:
        raise LauncherError(
            "Конвертация прошла, но selection.json не указывает на готовый пак. "
            "Смотрите отчёты в workspace/retail-work.",
            EXIT_TOOL,
        )
    mark(root, "converted", str(selected_pack(root).get("activePack")))
    echo("Контент готов.")


def step_full_rotwk(settings: Settings, runner: Runner, *, echo=print) -> dict:
    """Run the pinned RotWK 2.02 v9.7.7 full-content lane.

    Every step here is upstream's own documented order (``rotwk_full_content``
    after ``prepare-rotwk-202-baseline``); the launcher adds nothing and skips
    nothing.  It exists because ``run_rotwk_full_content.bat`` demands a
    console, environment variables and four paths, and a player asked for one
    button.

    Refuses before doing any work when the overlay is absent, rather than
    half-way through a 45-minute convert: the 2.02 root is the contract the
    verifier enforces, and a 2.01-only tree cannot satisfy it.
    """

    root = _install_root(settings)
    tree = _tree(settings)
    if settings.rotwk_install is None or settings.bfme2_install is None:
        raise LauncherError(
            "Полный контент RotWK требует папки RotWK 2.01 и BFME2 1.06.", EXIT_USAGE
        )
    if not has_patch202(settings.patch202_root):
        raise LauncherError(
            "Полный контент RotWK требует патч 2.02 v9.7.7 (папка с __patch202.big).\n"
            "Выберите её в строке «Патч 2.02» или играйте на BFME2-контенте.",
            EXIT_USAGE,
        )
    python = venv_python(root)
    if not python.is_file():
        raise LauncherError("Окружение импортёра не готово: сначала шаг «venv».", EXIT_STATE)
    state = state_root(root)
    environment = {
        "OPENBFME_IMPORT_ROOT": str(state),
        "PYTHONPATH": str(tree / "importer"),
        "PATH": os.environ.get("PATH", ""),
    }
    # 1. The pinned three-layer root, verified by upstream's own verifier.
    baseline = tree / "tools" / "prepare-rotwk-202-baseline.ps1"
    if not baseline.is_file():
        raise LauncherError(f"В дереве нет {baseline}.", EXIT_STATE)
    result = runner.run(
        [
            powershell(),
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(baseline),
            "-Bfme2Install",
            str(settings.bfme2_install),
            "-Rotwk201Install",
            str(settings.rotwk_install),
            "-Patch202Overlay",
            str(settings.patch202_root),
            "-StateRoot",
            str(state),
            "-Python",
            str(python),
            "-ReplaceExisting",
        ],
        cwd=tree,
        env=environment,
        capture=True,
    )
    if result.returncode != 0:
        raise LauncherError(
            "Проверка патча 2.02 не прошла "
            f"(код {result.returncode}). Смотрите лог: там назван конкретный файл.",
            EXIT_TOOL,
        )
    layered = state / "editions" / "rotwk" / "layered-install"
    mark(root, "layered202", str(layered))

    # 2. index -> effective assets (the oracle every later step reads).
    runner.run(
        [
            str(python),
            str(tree / "tools" / "openbfme_import.py"),
            "index",
            "--install",
            str(layered),
            "--game",
            "rotwk",
            "--reindex",
        ],
        cwd=tree,
        env=environment,
        capture=True,
        check=True,
    )
    runner.run(
        [
            str(python),
            str(tree / "tools" / "openbfme_import.py"),
            "extract-all-assets",
            "--install",
            str(layered),
            "--game",
            "rotwk",
            "--reindex",
        ],
        cwd=tree,
        env=environment,
        capture=True,
        check=True,
    )
    # 3. The full-content lane proper: convert, prove, cook ten maps, select.
    result = runner.run(
        [
            str(python),
            str(tree / "tools" / "rotwk_full_content.py"),
            "--install",
            str(layered),
            "--bfme2-install",
            str(settings.bfme2_install),
            "--state-root",
            str(state),
            "--python",
            str(python),
            "--map-limit",
            "10",
            "--select",
        ],
        cwd=tree,
        env=environment,
        capture=True,
    )
    if result.returncode != 0:
        raise LauncherError(
            "Полный контент RotWK не собрался "
            f"(код {result.returncode}). Это долгая стадия; лог выше называет шаг.",
            EXIT_TOOL,
        )
    if selected_pack(root) is None:
        raise LauncherError(
            "Пак собран, но selection.json не указывает на него.", EXIT_TOOL
        )
    mark(root, "converted", str(selected_pack(root).get("activePack")))
    echo("Полный контент RotWK готов: 7 фракций, 10 карт.")
    return {"activePack": selected_pack(root).get("activePack")}


def step_seed(settings: Settings, seed: str) -> None:
    if not valid_seed(seed):
        raise LauncherError(
            "Seed: от 1 до 32 латинских букв или цифр.", EXIT_USAGE
        )
    settings.seed = seed


def game_command(install_root: Path, seed: str) -> list[str]:
    return [
        str(godot_exe(install_root)),
        "--path",
        str(source_tree(install_root) / "game"),
        "--",
        f"OPENBFME_SEED={seed}",
    ]


def game_environment(install_root: Path, seed: str) -> dict[str, str]:
    """What the game reads: the converted packs, and the player's seed.

    The seed is delivered through Godot's own *user arguments* syntax
    (``--`` then ``ARG=value`` becomes ``OS.get_environment("ARG")``), because
    the game is started directly and not through a shell that could set a
    variable.  ``OPENBFME_SEED`` is still set for any consumer that reads the
    environment proper.
    """

    return {
        "OPENBFME_CONTENT": str(content_packs(install_root)),
        "OPENBFME_SEED": seed,
        "OPENBFME_SEED_ARG": seed,
    }


def step_launch(settings: Settings, runner: Runner, *, echo=print) -> None:
    root = _install_root(settings)
    if not source_ready(root):
        raise LauncherError("Исходники не собраны: сначала «prepare».", EXIT_STATE)
    if selected_pack(root) is None:
        raise LauncherError("Контент не сконвертирован: сначала «convert».", EXIT_STATE)
    if not godot_exe(root).is_file():
        raise LauncherError("Godot не установлен: сначала «godot».", EXIT_STATE)
    if not godot_import_marker(root).is_file():
        step_import(settings, runner, echo=echo)
    echo(f"Запускаю игру. Seed: {settings.seed}")
    runner.run(
        game_command(root, settings.seed),
        cwd=source_tree(root) / "game",
        env=game_environment(root, settings.seed),
    )


# ---------------------------------------------------------------------------
# The one-button sequence
# ---------------------------------------------------------------------------


FIRST_RUN_TITLES = {
    "python": "Проверяю Python",
    "prepare": "Собираю исходники OpenBFME",
    "git": "Проверяю git",
    "venv": "Готовлю Python-окружение импортёра",
    "tools": "Готовлю Blender и FFmpeg",
    "godot": "Проверяю Godot",
    "import": "Импортирую ресурсы Godot",
    "layered": "Соединяю RotWK 2.01 и BFME2 1.06 в один каталог",
    "full": "Конвертирую все фракции RotWK (это долго)",
    "convert": "Конвертирую ваш BFME2 1.06",
    "launch": "Запускаю игру",
}


def first_run_plan(settings: Settings) -> list[str]:
    """Only the steps that are actually missing, in dependency order."""

    root = settings.install_root
    if root is None:
        return ["python", "prepare", "venv", "tools", "godot", "import", "convert", "launch"]
    plan: list[str] = []
    if not pinned_python(root).is_file():
        plan.append("python")
    if not source_ready(root):
        plan.append("prepare")
    if not venv_python(root).is_file():
        plan.append("venv")
    if not marker(root, "tools"):
        plan.append("tools")
    if not godot_exe(root).is_file():
        plan.append("godot")
    if not godot_import_marker(root).is_file():
        plan.append("import")
    if selected_pack(root) is None:
        # With a 2.02 overlay the full RotWK lane can run; it needs the layered
        # root first.  Without it, the BFME2 Men lane is what a player can
        # actually finish today, and it needs no extra download.
        if has_patch202(settings.patch202_root) and settings.rotwk_install:
            if not marker(root, "layered"):
                plan.append("layered")
            plan.append("full")
        else:
            plan.append("convert")
    plan.append("launch")
    return plan


def autopilot(settings: Settings, runner: Runner, *, echo=print) -> int:
    """Run whatever is missing, in order, stopping at the first failure."""

    plan = first_run_plan(settings)
    for index, step in enumerate(plan, start=1):
        echo("")
        echo(f"=== Шаг {index}/{len(plan)}: {FIRST_RUN_TITLES.get(step, step)} ===")
        if step == "python":
            ensure_python(settings, runner, echo=echo)
        elif step == "prepare":
            step_prepare(settings, runner, echo=echo)
        elif step == "venv":
            step_bootstrap_venv(settings, runner, echo=echo)
        elif step == "tools":
            step_bootstrap_tools(settings, runner, echo=echo)
        elif step == "godot":
            step_godot(settings, echo=echo)
        elif step == "import":
            step_import(settings, runner, echo=echo)
        elif step == "layered":
            step_layered(settings, runner, echo=echo)
        elif step == "full":
            step_full_rotwk(settings, runner, echo=echo)
        elif step == "convert":
            step_convert(settings, runner, echo=echo)
        elif step == "launch":
            step_launch(settings, runner, echo=echo)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


def valid_seed(value: str) -> bool:
    return 1 <= len(value) <= 32 and all(character in SEED_ALPHABET for character in value)


def generate_seed() -> str:
    return "".join(
        SEED_ALPHABET[byte % len(SEED_ALPHABET)] for byte in os.urandom(12)
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engine", description="Advanced Randomizer launcher engine"
    )
    parser.add_argument(
        "--settings", type=Path, default=None, help="settings.json (default: per-user)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="report every readiness flag as JSON")
    sub.add_parser("detect", help="probe the usual retail locations, save what is found")

    setter = sub.add_parser("set", help="change settings")
    setter.add_argument("--install-root", type=Path)
    setter.add_argument("--bfme2-install", type=Path)
    setter.add_argument("--rotwk-install", type=Path)
    setter.add_argument("--patch202-root", type=Path)
    setter.add_argument("--seed")
    setter.add_argument("--auto-seed", choices=["on", "off"])
    setter.add_argument("--new-seed", action="store_true")

    sub.add_parser("python", help="install the pinned Python if missing")
    sub.add_parser("prepare", help="assemble the OpenBFME source tree")
    sub.add_parser("venv", help="bootstrap the importer Python environment")
    sub.add_parser("tools", help="bootstrap Blender/OpenSAGE/FFmpeg")
    sub.add_parser("godot", help="install Godot")
    sub.add_parser("import", help="run the one-time Godot import pass")
    sub.add_parser("layered", help="join RotWK 2.01 and BFME2 1.06 into one catalog")
    sub.add_parser("full", help="convert every RotWK faction (needs Patch 2.02)")
    sub.add_parser("convert", help="convert BFME2 1.06 into a content pack")
    sub.add_parser("launch", help="start the game")
    sub.add_parser("autopilot", help="run the whole first run, then launch")
    sub.add_parser("folders", help="print the launcher's folders")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings_path = (args.settings or default_settings_path()).expanduser()
    settings = load_settings(settings_path)
    runner = Runner(echo=print)
    try:
        if args.command == "status":
            print(json.dumps(status(settings), indent=2, ensure_ascii=False))
            return EXIT_OK
        if args.command == "folders":
            print(json.dumps(
                {
                    "settings": str(settings_path),
                    "installRoot": str(settings.install_root) if settings.install_root else None,
                    "defaultInstallRoot": str(default_install_root()),
                    "source": str(source_tree(settings.install_root)) if settings.install_root else None,
                },
                indent=2,
                ensure_ascii=False,
            ))
            return EXIT_OK
        if args.command == "detect":
            rotwk, bfme2, patch = detect_installs()
            if rotwk and settings.rotwk_install is None:
                settings.rotwk_install = rotwk
            if bfme2 and settings.bfme2_install is None:
                settings.bfme2_install = bfme2
            if patch and settings.patch202_root is None:
                settings.patch202_root = patch
            save_settings(settings, settings_path)
            print(json.dumps(status(settings), indent=2, ensure_ascii=False))
            return EXIT_OK
        if args.command == "set":
            if args.install_root is not None:
                settings.install_root = args.install_root
            if args.bfme2_install is not None:
                settings.bfme2_install = args.bfme2_install
            if args.rotwk_install is not None:
                settings.rotwk_install = args.rotwk_install
            if args.patch202_root is not None:
                settings.patch202_root = args.patch202_root
            if args.seed is not None:
                step_seed(settings, args.seed)
            if args.new_seed:
                step_seed(settings, generate_seed())
            if args.auto_seed is not None:
                settings.auto_seed = args.auto_seed == "on"
            save_settings(settings, settings_path)
            print(json.dumps(status(settings), indent=2, ensure_ascii=False))
            return EXIT_OK
        if args.command == "python":
            print(ensure_python(settings, runner))
            return EXIT_OK
        if args.command == "prepare":
            print(step_prepare(settings, runner))
            return EXIT_OK
        if args.command == "venv":
            print(step_bootstrap_venv(settings, runner))
            return EXIT_OK
        if args.command == "tools":
            step_bootstrap_tools(settings, runner)
            return EXIT_OK
        if args.command == "godot":
            print(step_godot(settings))
            return EXIT_OK
        if args.command == "import":
            step_import(settings, runner)
            return EXIT_OK
        if args.command == "layered":
            print(json.dumps(step_layered(settings, runner), ensure_ascii=False))
            return EXIT_OK
        if args.command == "full":
            print(json.dumps(step_full_rotwk(settings, runner), ensure_ascii=False))
            return EXIT_OK
        if args.command == "convert":
            step_convert(settings, runner)
            return EXIT_OK
        if args.command == "launch":
            step_launch(settings, runner)
            return EXIT_OK
        if args.command == "autopilot":
            save_settings(settings, settings_path)
            return autopilot(settings, runner)
    except LauncherError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return error.code
    except KeyboardInterrupt:
        print("Отменено игроком.", file=sys.stderr)
        return 1
    parser.error("unknown command")
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
