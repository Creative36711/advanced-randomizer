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
import math
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

import tree_package
from pinned import (
    CONTENT_PACKS_RELATIVE,
    SEVEN_ZR,
    FFMPEG_7Z,
    FFMPEG_8_1_1_ZIP,
    FFMPEG_EXE_SHA256,
    FFMPEG_URL_CANDIDATES,
    FFPROBE_EXE_SHA256,
    GODOT_WIN64_ZIP,
    MINGIT_64_ZIP,
    OPENBFME_SOURCE_RELATIVE,
    PINNED_PYTHON,
    SEVEN_ZR,
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


class Progress:
    """Where "how far along this step is" goes.

    The window renders it as a growing bar; a terminal run renders it as plain
    text.  Everything is optional: a missing or silent sink must never break a
    step, because a launcher that dies while reporting progress is worse than
    one that reports nothing.
    """

    def __init__(self, sink=None) -> None:
        self.sink = sink

    def start(self, label: str) -> None:
        self._emit({"kind": "begin", "label": label})

    def update(self, label: str, done: int, total: int = 0, *, rate: float = 0.0) -> None:
        self._emit({
            "kind": "progress",
            "label": label,
            "done": int(done),
            "total": int(total),
            # Bytes per second and the remaining seconds let the window say
            # "3.2 МБ/с, ещё ~1 мин" instead of only a moving bar - the player
            # asked to know whether the download is really going.
            "rate": int(rate),
            # Rounded UP: 0.6 s of remaining download is still time left, and
            # flooring it to 0 read as "finished" on screen.
            "eta": (
                math.ceil((total - done) / rate) if rate > 0 and total > done else 0
            ),
        })

    def finish(self, label: str) -> None:
        self._emit({"kind": "end", "label": label})

    def _emit(self, event: dict) -> None:
        if self.sink is None:
            return
        try:
            self.sink(event)
        except Exception:  # noqa: BLE001 - progress must never abort a step
            pass


class FileProgressSink:
    """JSON-lines sink a GUI can tail without a pipe.

    A pipe would need the writer to keep flushing and the reader to keep
    draining; a growing file is inert, survives a window that stalls, and can
    be inspected after the fact.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def __call__(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()


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
    progress: "Progress | None" = None,
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
    progress = progress or Progress()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    if not expected_sha256 and not allow_unpinned:
        raise DownloadError(
            f"{label}: SHA-256 не закреплён в лаунчере, скачивание не начато."
        )
    echo(f"Скачиваю {label}…")
    progress.start(label)
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
                    # From the first block: a rate that only appears after
                    # half a second leaves the first, most anxious moments
                    # blank - and it is exactly when the player is wondering
                    # whether anything is happening.
                    elapsed = time.monotonic() - started
                    rate = written / elapsed if elapsed > 0.0 else 0.0
                    if total:
                        progress.update(label, written, total, rate=rate)
                        # A text line every 16 MiB as well: the window shows a
                        # bar, but a terminal run and the log file need words.
                        if written % (16 * 1024 * 1024) < len(block):
                            echo(f"  {human_bytes(written)} из {human_bytes(total)}")
                    else:
                        # No Content-Length (chunked response) - and a sink
                        # with no total draws only a marquee, so the player
                        # sees "nothing is happening".  Print bytes every
                        # 4 MiB and report a growing figure instead.
                        progress.update(label, written, 0, rate=rate)
                        if written % (4 * 1024 * 1024) < len(block):
                            echo(f"  скачано {human_bytes(written)}")
    except DownloadError:
        temporary.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        # A blocked or dropped connection must arrive as a sentence the player
        # can act on, not as a Python traceback in the log box.
        temporary.unlink(missing_ok=True)
        raise DownloadError(
            f"{label}: не удалось скачать.\n"
            f"  адрес: {url}\n"
            f"  причина: {error}\n\n"
            "Проверьте интернет. Если адрес недоступен (бывает у некоторых "
            "провайдеров), скачайте файл вручную и положите его сюда:\n"
            f"  {destination}"
        ) from error
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
    progress.finish(label)
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
            if not tree_package.inside(root, target):
                raise LauncherError(
                    f"{label or archive.name}: архив пытается писать вне папки назначения."
                )
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)


def seven_zr_path(directory: Path) -> Path:
    return directory / "7zr.exe"


def extract_7z(archive: Path, destination: Path, *, label: str = "", echo=print) -> None:
    """Unpack a .7z with what the machine already has.

    The FFmpeg build is a third the size packed as 7z, but Windows has no
    standard-library reader for it.  Three routes, in order of availability:

    1. ``py7zr`` when it is importable (installed by hand by a player, or
       present in the launcher's own environment);
    2. ``tar.exe`` - Windows 10 1803+ ships bsdtar, which reads 7z;
    3. nothing: raise with the exact command to run by hand, because a
       launcher that silently gives up is the failure mode being fixed.

    Extraction is a copy into our own staging folder, so the archive never
    decides where files go: the caller only reads specific names afterwards.
    """

    destination.mkdir(parents=True, exist_ok=True)
    label = label or archive.name

    try:
        import py7zr  # type: ignore
    except ImportError:
        py7zr = None

    if py7zr is not None:
        with py7zr.SevenZipFile(archive, "r") as archive_file:
            names = archive_file.getnames()
            for name in names:
                target = (destination / name).resolve()
                if not tree_package.inside(destination, target):
                    raise LauncherError(
                        f"{label}: архив пытается писать вне папки назначения."
                    )
        with py7zr.SevenZipFile(archive, "r") as archive_file:
            archive_file.extractall(destination)
        return

    # bsdtar reads 7z; GNU tar does not.  Ask the tool instead of guessing
    # from its name, because "tar exists" is not "tar can open this".
    tar = shutil.which("tar")
    if tar:
        result = subprocess.run(
            [tar, "-x", "-f", str(archive), "-C", str(destination)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and any(destination.rglob("*.exe")):
            return

    # Last resort, and the one that makes the small archive usable on a clean
    # Windows: 600 KB of 7-Zip's own extractor, pinned by digest.
    extractor = seven_zr_path(archive.parent)
    if not extractor.is_file():
        try:
            download(
                SEVEN_ZR.url,
                extractor,
                expected_sha256=SEVEN_ZR.sha256,
                expected_size=SEVEN_ZR.size,
                label=SEVEN_ZR.label,
                echo=echo,
            )
        except LauncherError:
            extractor = None
    if extractor is not None and extractor.is_file():
        result = subprocess.run(
            [str(extractor), "x", "-y", f"-o{destination}", str(archive)],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return

    raise LauncherError(
        f"{label}: .7z не открылся (нет py7zr, tar не читает 7z, 7zr.exe не скачался)."
    )


def extract_tar_gz(archive: Path, destination: Path, *, label: str = "") -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            target = (destination / member.name).resolve()
            if not tree_package.inside(root, target):
                raise LauncherError(
                    f"{label or archive.name}: архив пытается писать вне папки назначения."
                )
        # Python 3.12+ wants the extraction filter spelled out; without it the
        # log gets a DeprecationWarning and the player reads it as a problem.
        # "data" is the safe default: it drops absolute paths, links and the
        # other tricks, which is exactly what the check above enforces.
        if hasattr(tarfile, "data_filter"):
            tf.extractall(destination, filter="data")
        else:
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


def patch202_root(settings: "Settings") -> Path | None:
    """Where the 2.02 overlay actually lives.

    Patch 2.02 is a fan mod installed by REPLACING files inside the RotWK 2.01
    folder - like every other mod there.  It is therefore not a separate
    install and is never asked for: if the chosen RotWK folder carries the
    overlay files, that folder is the overlay.  An explicit path is still
    honoured for the rare case of a copy kept somewhere else.
    """

    if has_patch202(settings.patch202_root):
        return settings.patch202_root
    if has_patch202(settings.rotwk_install):
        return settings.rotwk_install
    # A path that was set but does not carry the files is NOT an overlay.
    # Returning it here made "папка указана, но пуста" look like 2.02 present.
    return None


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
    """The tree is complete AND is Advanced Randomizer, not plain OpenBFME.

    A package built from the wrong commit, or with our ``game/`` folder copied
    one level too deep, passes every structural check and still starts a game
    without the mod - which reads as "the randomizer does nothing".
    """

    tree = source_tree(install_root)
    if not (tree / "game" / "project.godot").is_file():
        return False
    if not (tree / "tools" / "openbfme_import.py").is_file():
        return False
    return not tree_package.mod_problems(tree)


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


def with_overrides(settings: Settings, overrides: dict) -> Settings:
    """A copy of ``settings`` with the given fields replaced, nothing saved.

    The window must be able to ask "what would the state be if these folders
    were chosen", because its fields can be ahead of the saved file.
    """

    clone = Settings(
        install_root=settings.install_root,
        bfme2_install=settings.bfme2_install,
        rotwk_install=settings.rotwk_install,
        patch202_root=settings.patch202_root,
        seed=settings.seed,
        auto_seed=settings.auto_seed,
    )
    for name, value in overrides.items():
        setattr(clone, name, value)
    return clone


def status_overrides(arguments) -> dict:
    """Map the CLI ``--*`` options onto Settings fields, skipping empty ones."""

    mapping = {
        "install_root": "install_root",
        "bfme2_install": "bfme2_install",
        "rotwk_install": "rotwk_install",
        "patch202_root": "patch202_root",
    }
    result: dict = {}
    for option, field in mapping.items():
        value = getattr(arguments, option, None)
        if value not in (None, ""):
            result[field] = Path(value)
    seed = getattr(arguments, "seed", None)
    if seed:
        result["seed"] = seed
    return result


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
    report["previousInstall"] = previous_install(root)
    report["treeVersion"] = tree_version(root)
    if report["previousInstall"]:
        # A folder built by the pre-release launcher has the tree but not our
        # mod, so it reads as "ничего не собрано" and sends the player into a
        # local build. Say what it is and that it is safe to replace.
        built = report["previousInstall"]
        when = f" ({built})" if built != "неизвестно" else ""
        report["notes"].append(
            f"В этой папке лежит установка прежней версии лаунчера{when}. "
            "Очищать её не нужно: лаунчер сам заменит код игры, а "
            "сконвертированный контент и Python-окружение оставит на месте."
        )
    elif not report["sourceReady"]:
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


def tree_version(install_root: Path) -> str | None:
    """What the tree says it is; the version is written in two places.

    ``.launcher-assembled`` is the file inside the tree, the ``assembled``
    marker is the launcher's own record. They can disagree - an interrupted
    unpack writes one and not the other - so both are read and the file wins.
    """

    candidates = [markers_dir(install_root) / "assembled"]
    candidates.append(source_tree(install_root) / ".launcher-assembled")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        # The old path wrote a sentence, the release path writes the version.
        first = text.splitlines()[0].strip() if text else ""
        if first:
            return first
    return None


def previous_install(install_root: Path) -> str | None:
    """Describe an installation made by the launcher before the release model.

    The marker ``assembled`` was written by the old local-build path, and the
    tree it produced has no randomizer files, so ``source_ready`` says no. That
    answer is technically right and practically useless: the player needs to
    know the folder is a working install, not that it is empty.
    """

    if not marker(install_root, "assembled"):
        return None
    if source_ready(install_root):
        return None
    tree = source_tree(install_root)
    if not (tree / "game" / "project.godot").is_file():
        return None
    return tree_version(install_root) or "неизвестно"


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

    def __init__(self, echo=print, progress: "Progress | None" = None) -> None:
        self.echo = echo
        self.progress = progress or Progress()

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
        # A subprocess that runs for minutes (a converter, a Blender pass, a
        # 17 MB download) must not look like a frozen window.  Two signals:
        # its output is streamed as it arrives, and the progress sink is told
        # the step began and ended.
        progress = getattr(self, "progress", None)
        label = Path(args[0]).stem if args else "step"
        if progress is not None:
            progress.start(label)
        try:
            streamed = bool(capture)
            if capture:
                process = self._run_streaming(
                    args, cwd, merged, creationflags
                )
            else:
                process = subprocess.run(
                    args,
                    cwd=str(cwd) if cwd else None,
                    env=merged,
                    text=True,
                    capture_output=False,
                    check=False,
                    creationflags=creationflags,
                )
        finally:
            if progress is not None:
                progress.finish(label)
        # Streaming already echoed every line; echoing the collected copy
        # again would print the step's whole output twice in the log.
        if capture and not streamed and getattr(process, "stdout", None):
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


    def _run_streaming(self, args, cwd, merged, creationflags):
        """Run a child, echoing each line as it arrives, and keep the text.

        ``subprocess.run(capture_output=True)`` returns nothing until the
        process exits, which is why a long step used to show a single ``$``
        line and then nothing.  Here stdout and stderr are read line by line
        while the child works; the collected text is still available to the
        caller for an error message.
        """

        process = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd else None,
            env=merged,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        collected_out: list[str] = []
        collected_err: list[str] = []
        # stderr is drained on its own thread: a child that writes a lot to
        # either pipe would block on a full buffer otherwise.
        def drain_err() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                line = line.rstrip("\n")
                collected_err.append(line)
                self.echo("! " + line)

        import threading

        thread = threading.Thread(target=drain_err, daemon=True)
        thread.start()
        try:
            assert process.stdout is not None
            for line in process.stdout:
                line = line.rstrip("\n")
                collected_out.append(line)
                self.echo(line)
            code = process.wait()
            thread.join(timeout=5)
        finally:
            # Explicit, because a leaked pipe is a real defect on Windows: it
            # keeps the handle open and Windows refuses to delete a file the
            # process still holds. Python's own test runner reported it as
            # "unclosed file" the first time this ever ran on Windows.
            for pipe in (process.stdout, process.stderr):
                try:
                    if pipe is not None:
                        pipe.close()
                except OSError:
                    pass
        return subprocess.CompletedProcess(
            args, code, "\n".join(collected_out), "\n".join(collected_err)
        )


def _quote(part: str) -> str:
    return f'"{part}"' if " " in part else part


# ---------------------------------------------------------------------------
# Pinned Python
# ---------------------------------------------------------------------------


def pinned_python_archive(install_root: Path) -> Path:
    return downloads_dir(install_root) / PINNED_PYTHON.archive_name


def ensure_python(settings: Settings, runner: Runner, *, echo=print, progress=None) -> Path:
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
                progress=progress,
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


def ensure_git(settings: Settings, *, echo=print, progress=None) -> Path:
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
            progress=progress,
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


def ensure_ffmpeg(settings: Settings, *, echo=print, opener=urllib.request.urlopen, progress=None) -> Path:
    """Install the one FFmpeg build the importer will accept.

    Tried in order of how much they cost the player:

    1. the pinned 8.1.1 ``.7z`` (32 MB, digest pinned by GitHub);
    2. the same 8.1.1 as ``.zip`` (104 MB) - only when the 7z cannot be
       unpacked on this machine;
    3. gyan.dev's moving "latest" zip, unpinnable, last resort.

    Every route ends the same way: ``ffmpeg.exe`` and ``ffprobe.exe`` are
    checked against the digests the importer itself accepts.  The archive
    digest is a convenience; these two are the fact that matters.
    """

    root = _install_root(settings)
    target = ffmpeg_exe(root)
    if target.is_file() and sha256_file(target) == FFMPEG_EXE_SHA256:
        return target

    last_error: Exception | None = None
    attempts: list[str] = []

    def collect(archive: Path, staging: Path) -> bool:
        """Pull the two executables out of an unpacked archive."""

        nonlocal last_error
        candidates = list(staging.rglob("ffmpeg.exe"))
        if not candidates:
            last_error = DownloadError("в архиве FFmpeg нет ffmpeg.exe")
            return False
        source = candidates[0]
        probe = source.with_name("ffprobe.exe")
        if not probe.is_file():
            last_error = DownloadError("в архиве FFmpeg нет ffprobe.exe")
            return False
        if sha256_file(source) != FFMPEG_EXE_SHA256:
            last_error = DownloadError(
                "ffmpeg.exe из этого архива не совпадает с закреплённым импортёром:\n"
                f"  ожидалось {FFMPEG_EXE_SHA256}\n  получено  {sha256_file(source)}"
            )
            return False
        if sha256_file(probe) != FFPROBE_EXE_SHA256:
            last_error = DownloadError("ffprobe.exe не совпадает с закреплённым хешем.")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        shutil.copyfile(probe, target.with_name("ffprobe.exe"))
        return True

    def attempt(artifact, unpack) -> bool:
        nonlocal last_error
        archive = downloads_dir(root) / Path(artifact.url).name
        archive.unlink(missing_ok=True)
        try:
            download(
                artifact.url,
                archive,
                expected_sha256=artifact.sha256,
                expected_size=artifact.size,
                label=artifact.label,
                echo=echo,
                progress=progress,
                opener=opener,
                allow_unpinned=artifact.sha256 is None,
            )
            staging = root / ".launcher" / "ffmpeg-extract"
            if staging.exists():
                shutil.rmtree(staging)
            unpack(archive, staging)
            if not collect(archive, staging):
                return False
            shutil.rmtree(staging, ignore_errors=True)
            archive.unlink(missing_ok=True)
            echo(f"FFmpeg установлен: {target}")
            return True
        except LauncherError as exc:
            last_error = exc
            attempts.append(f"  {artifact.url}\n    {exc}")
            echo(f"  не вышло: {artifact.url}")
            echo(f"    {exc}")
            return False
        except Exception as exc:  # network, disk, anything
            last_error = exc
            attempts.append(f"  {artifact.url}\n    {exc}")
            echo(f"  не вышло: {artifact.url}")
            echo(f"    {exc}")
            return False

    # 1. 32 MB, pinned.
    if attempt(FFMPEG_7Z, lambda a, d: extract_7z(a, d, label="FFmpeg 8.1.1", echo=echo)):
        return target
    # 2. The same build as a zip: 72 MB more, but every machine can open it.
    echo("Архив .7z не распаковался — качаю тот же FFmpeg в ZIP (больше по размеру).")
    if attempt(FFMPEG_8_1_1_ZIP, lambda a, d: extract_zip(a, d, label="FFmpeg 8.1.1")):
        return target
    # 3. Upstream "latest", unpinnable: the executables are still verified.
    for url in FFMPEG_URL_CANDIDATES:
        archive = downloads_dir(root) / "ffmpeg.zip"
        archive.unlink(missing_ok=True)
        try:
            download(
                url,
                archive,
                expected_sha256=None,
                label="FFmpeg (последняя сборка)",
                echo=echo,
                progress=progress,
                opener=opener,
                allow_unpinned=True,
            )
            staging = root / ".launcher" / "ffmpeg-extract"
            if staging.exists():
                shutil.rmtree(staging)
            extract_zip(archive, staging, label="FFmpeg")
            if collect(archive, staging):
                shutil.rmtree(staging, ignore_errors=True)
                archive.unlink(missing_ok=True)
                echo(f"FFmpeg установлен: {target}")
                return target
        except Exception as exc:
            last_error = exc
            attempts.append(f"  {url}\n    {exc}")
            echo(f"  не вышло: {url}")
            echo(f"    {exc}")

    archive = downloads_dir(root) / "ffmpeg.zip"
    detail = "\n".join(attempts) if attempts else (str(last_error) if last_error else "неизвестно")
    raise DownloadError(
        "Не удалось получить FFmpeg. Что пробовал:\n"
        f"{detail}\n\n"
        "Если ни один адрес не открывается (бывает у некоторых провайдеров), "
        "скачайте ffmpeg-8.1.1-essentials_build.7z со страницы "
        "https://github.com/GyanD/codexffmpeg/releases/tag/8.1.1 вручную и положите сюда:\n"
        f"  {archive}\n"
        "Лаунчер проверит его и продолжит."
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


def tree_manifest_url() -> str:
    """Where the assembled tree is published: our own repository, latest-release tag."""

    return (
        "https://github.com/Creative36711/advanced-randomizer/releases/latest/download/"
        + tree_package.MANIFEST_NAME
    )


def published_tree_version(opener=urllib.request.urlopen) -> str | None:
    """Версия дерева, опубликованная в релизе; None, если списка нет.

    Манифест крошечный, поэтому его не жалко читать при каждом запуске — так
    и делает install_tree_package. Здесь нужен только номер версии.
    """

    url = tree_manifest_url()
    try:
        with opener(
            urllib.request.Request(url, headers={"User-Agent": "AdvancedRandomizer/1.0"}),
            timeout=30,
        ) as response:
            text = response.read(1 << 20).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    try:
        return tree_package.read_manifest(text, source=url).version
    except tree_package.TreeError:
        return None


def _tree_is_stale(install_root: Path, *, echo=print) -> bool:
    """Собранное дерево старше опубликованного?

    Сеть недоступна — считаем дерево годным: пересборка без сети всё равно
    невозможна, а отказ на ровном месте запретил бы играть офлайн.
    """

    local = tree_version(install_root)
    published = published_tree_version()
    if published is None:
        return False
    if local is None:
        # Дерево есть, но не называет версию: это сборка старого образца.
        echo(f"  дерево не называет версию, а опубликована {published}")
        return True
    if local != published:
        echo(f"  у вас {local}, опубликована {published}")
        return True
    return False


def step_prepare(
    settings: Settings,
    runner: Runner,
    *,
    echo=print,
    opener=urllib.request.urlopen,
    progress=None,
) -> Path:
    """Get the game tree: the published package first, local assembly as fallback.

    Assembling locally means downloading 17 MB of OpenBFME sources on EVERY
    install, applying the patch and copying our game folder. The same tree is
    built once in CI from the same commit, so a player downloads it ready-made
    and the local path is only a fallback for a build that has no release yet.
    """

    root = _install_root(settings)
    tree = source_tree(root)
    if source_ready(root):
        # Собранное дерево НЕ пересобирается само. Это верно для «уже готово»
        # и неверно, когда в нём исправление, без которого конвертация падает:
        # игрок обновляет лаунчер, видит ту же ошибку и решает, что починили
        # не то. Поэтому версию дерева сверяем с опубликованным манифестом, а
        # не полагаемся на «файл на месте = всё хорошо».
        stale = _tree_is_stale(root, echo=echo)
        if not stale:
            echo(f"Исходники уже собраны: {tree}")
            return tree
        echo("Дерево игры устарело — скачиваю собранное заново.")
    try:
        return install_tree_package(
            settings, echo=echo, opener=opener, progress=progress
        )
    except (tree_package.TreeError, DownloadError) as error:
        echo("")
        echo("Готовый архив дерева получить не удалось:")
        for line in str(error).splitlines():
            echo("  " + line)
        echo("")
        echo("Собираю дерево на этом компьютере — это дольше, но работает "
             "без готового релиза.")
    return assemble_tree_locally(settings, runner, echo=echo)


def install_tree_package(
    settings: Settings, *, echo=print, opener=urllib.request.urlopen, progress=None
) -> Path:
    """Download, verify and unpack the assembled tree (the normal first run)."""

    root = _install_root(settings)
    tree = source_tree(root)
    manifest_path = downloads_dir(root) / tree_package.MANIFEST_NAME
    url = tree_manifest_url()
    # The manifest is tiny and carries the digest of everything else, so it is
    # fetched fresh every time; a stale copy would pin an old tree forever.
    echo(f"Читаю список файлов: {url}")
    try:
        with opener(
            urllib.request.Request(url, headers={"User-Agent": "AdvancedRandomizer/1.0"}),
            timeout=60,
        ) as response:
            text = response.read(1 << 20).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise DownloadError(f"{url}: не удалось прочитать список файлов ({error})")
    package = tree_package.read_manifest(text, source=url)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(text, encoding="utf-8")
    archive = downloads_dir(root) / f"tree-{package.version}.zip"
    if archive.is_file():
        try:
            tree_package.verify_file(archive, package)
            echo(f"Архив уже скачан и совпал с манифестом: {archive.name}")
        except tree_package.TreeError:
            archive.unlink(missing_ok=True)
    if not archive.is_file():
        download(
            package.url,
            archive,
            expected_sha256=package.sha256,
            expected_size=package.size,
            label=f"дерево игры {package.version}",
            echo=echo,
            opener=opener,
            progress=progress,
        )
    echo("Распаковываю…")
    root.mkdir(parents=True, exist_ok=True)
    tree_package.unpack(archive, tree)
    problems = tree_package.mod_problems(tree)
    if problems or not (tree / "game" / "project.godot").is_file():
        missing = problems or ["game/project.godot"]
        raise tree_package.TreeError(
            "архив распакован, но это не Advanced Randomizer. Не хватает:\n  "
            + "\n  ".join(missing)
            + "\nСкорее всего, релиз собран из другого коммита. "
            "Напишите об этом — сборку надо переделать."
        )
    mark(root, "assembled", package.version)
    (tree / ".launcher-assembled").write_text(
        f"Собрано CI Advanced Randomizer, версия {package.version}.\n",
        encoding="utf-8",
    )
    echo(f"Дерево готово: {tree} ({package.version})")
    return tree


def assemble_tree_locally(settings: Settings, runner: Runner, *, echo=print) -> Path:
    """The old path: pin, patch and copy by hand. Used when no release exists."""

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
    # prepare.py applies the repository's patches with tools/apply_patch.py,
    # which is pure standard library.  It used to call `git apply`, and git was
    # only fetched three steps later - and could not be fetched at all, because
    # the MinGit archive is not pinned.  The failure was also invisible: the
    # child's output was not captured, so the player saw "код 1" and nothing.
    result = runner.run(
        [str(python), str(prepare), "--output", str(tree)],
        cwd=repo_root,
        capture=True,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        tail = "\n".join(details.splitlines()[-12:]) if details else "(вывод пуст)"
        raise LauncherError(
            "Не удалось собрать исходники OpenBFME "
            f"(код {result.returncode}). Последние строки вывода:\n{tail}",
            EXIT_TOOL,
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


def step_godot(settings: Settings, *, echo=print, opener=urllib.request.urlopen, progress=None) -> Path:
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
            progress=progress,
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
    python = ensure_python(settings, runner, echo=echo, progress=getattr(runner, "progress", None))
    script = tree / "tools" / "bootstrap-importer-python.ps1"
    if not script.is_file():
        raise LauncherError(f"В дереве нет {script}.", EXIT_STATE)
    environment = {
        "OPENBFME_IMPORT_ROOT": str(state_root(root)),
        # The script prefers OPENBFME_PYTHON when set, which is exactly the
        # pinned interpreter this launcher just verified.
        "OPENBFME_PYTHON": str(python),
        # The step spends its time waiting on pip.  Download the wheels in
        # parallel and keep every line output: pip hides its progress bar when
        # it thinks it is talking to a pipe, and the step then looks dead.
        "PIP_PROGRESS_BAR": "on",
        "PIP_NO_INPUT": "1",
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
    # The importer's Blender bootstrap clones the W3D plugin, so git is still
    # welcome here - but only when the machine has one.  Without it the
    # importer reports what it skipped, and the conversion below still works
    # for everything that does not need Blender.
    git = find_system_git()
    environment = {
        "OPENBFME_IMPORT_ROOT": str(state_root(root)),
        "PYTHONPATH": str(tree / "importer"),
    }
    if git is not None:
        environment["PATH"] = git_environment(git)["PATH"]
        echo(f"git: {git}")
    else:
        echo("git не найден — Blender-плагин не будет скачан, остальное не зависит от него.")
    ffmpeg = ensure_ffmpeg(settings, echo=echo, progress=getattr(runner, "progress", None))
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


def last_importer_refusal(root: Path) -> str:
    """Return the converter's own last refusal line, or an empty string.

    The line is long by design - it carries the audit's error list - so it is
    clipped to something a message box can show while keeping the beginning,
    which is where the first mismatched file is named.
    """

    logs = root / ".launcher" / "logs"
    if not logs.is_dir():
        return ""
    runs = sorted(
        (path for path in logs.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for run in runs:
        log = run / "run.log"
        if not log.is_file():
            continue
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        # The converter writes one line per event and ends with "run.end
        # exit_code=1". Taking the LAST error line returned exactly that, so
        # the player was shown "exit_code=1" instead of the reason. The line
        # that carries the cause is the `refusal` event, and it sits ABOVE the
        # exit line - it is searched for first and by name.
        for line in reversed(lines):
            if " refusal " in line or line.lstrip().startswith("refusal "):
                return line.strip()[:4000]
        # Nothing called `refusal`: take what the converter said was wrong.
        for line in reversed(lines):
            if "ERROR" in line and "run.end" not in line:
                return line.strip()[:2000]
    return ""


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
        # The converter keeps its full run log OFF by default, so the reason
        # behind "failed its internal hash audit" - the audit's own list of
        # mismatched files - was never written anywhere. This turns it on and
        # points it at our own folder.
        "OPENBFME_DIAGNOSTICS": "1",
        "OPENBFME_LOG_DIR": str(root / ".launcher" / "logs"),
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
        detail = last_importer_refusal(root)
        extra = f"\n\n{detail}" if detail else ""
        raise LauncherError(
            "Конвертация завершилась с кодом "
            f"{result.returncode}.{extra}\n"
            f"Полный лог конвертера: {root / '.launcher' / 'logs'}",
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
    overlay = patch202_root(settings)
    if overlay is None:
        raise LauncherError(
            "Полный контент RotWK требует патч 2.02 v9.7.7 — он ставится поверх 2.01, "
            "заменой файлов в её папке.\n"
            f"  В выбранной папке RotWK нет __patch202.big: {settings.rotwk_install}\n"
            "Поставьте 2.02 в эту папку (как любой другой мод) и повторите.\n"
            "Отдельного поля для 2.02 больше нет: он определяется по папке 2.01.",
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
            str(overlay),
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
    # The step no longer builds anything when a release exists: it installs the
    # tree CI published. The old title promised a build the player never sees.
    "prepare": "Готовлю дерево игры (сборка CI)",
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
        if patch202_root(settings) is not None and settings.rotwk_install:
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
            ensure_python(settings, runner, echo=echo, progress=getattr(runner, "progress", None))
        elif step == "prepare":
            step_prepare(settings, runner, echo=echo)
        elif step == "venv":
            step_bootstrap_venv(settings, runner, echo=echo)
        elif step == "tools":
            step_bootstrap_tools(settings, runner, echo=echo)
        elif step == "godot":
            step_godot(settings, echo=echo, progress=getattr(runner, "progress", None))
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
    parser.add_argument(
        "--progress",
        type=Path,
        help="write progress events (JSON lines) here, for a GUI to read",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser("status", help="report every readiness flag as JSON")
    # The window asks about the folders currently ON SCREEN, which may not be
    # saved yet.  Without this the answer described the previous settings and
    # said "install folder not chosen" while the field visibly contained one.
    status_parser.add_argument("--install-root", type=Path)
    status_parser.add_argument("--bfme2-install", type=Path)
    status_parser.add_argument("--rotwk-install", type=Path)
    status_parser.add_argument("--patch202-root", type=Path)
    status_parser.add_argument("--seed")
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


def _make_output_utf8_safe() -> None:
    """Never let a message about a problem become a second problem.

    On Windows the console code page is often cp1252, and printing the
    engine's Russian text to it raises UnicodeEncodeError - so a player who ran
    the engine by hand got a traceback instead of the sentence explaining what
    went wrong. The window avoided this by exporting PYTHONUTF8, which meant
    the bug was invisible exactly where it was most likely.
    """

    for stream in (sys.stdout, sys.stderr):
        try:
            # line_buffering, not just the encoding: the window tails a FILE
            # (stdout redirected by Start-Process), and a redirected Python
            # buffers 8 KB before writing anything. The player then watches
            # "Подготовка игры" and a moving clock for minutes with no idea
            # whether anything is happening - the exact report that made this
            # change: five minutes, no sign of a process. Every line must reach
            # the file when it is printed.
            stream.reconfigure(  # type: ignore[attr-defined]
                encoding="utf-8", errors="replace", line_buffering=True
            )
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _make_output_utf8_safe()
    parser = build_parser()
    args = parser.parse_args(argv)
    settings_path = (args.settings or default_settings_path()).expanduser()
    settings = load_settings(settings_path)
    sink = FileProgressSink(args.progress) if getattr(args, "progress", None) else None
    runner = Runner(echo=print, progress=Progress(sink))
    try:
        if args.command == "status":
            overrides = status_overrides(args)
            if overrides:
                settings = with_overrides(settings, overrides)
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
            # One short line: `set` is called before every button press, and a
            # full status dump here turned the log box into a wall of JSON the
            # player cannot read.  `status` still prints the whole document.
            report = status(settings)
            active = report.get("activePack") or "нет"
            print(
                f"Настройки сохранены. Папка лаунчера: {report.get('installRoot')}. "
                f"Пак: {active}."
            )
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
            # One short line: `set` runs before every button press, and a full
            # status dump here turned the log box into a wall of JSON the player
            # cannot read.  `status` still prints the whole document.
            report = status(settings)
            active = report.get("activePack") or "нет"
            print(
                f"Настройки сохранены. Папка лаунчера: {report.get('installRoot')}. "
                f"Пак: {active}."
            )
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
        # The window reads this file and shows the reason in a message box; the
        # player reported that "код 1" alone explains nothing.
        sink = getattr(args, "progress", None)
        if sink is not None:
            try:
                reason = sink.with_name(sink.name + ".error")
                reason.write_text(str(error), encoding="utf-8")
            except OSError:
                pass
        return error.code
    except KeyboardInterrupt:
        print("Отменено игроком.", file=sys.stderr)
        return 1
    parser.error("unknown command")
    return EXIT_USAGE


if __name__ == "__main__":
    _make_output_utf8_safe()
    raise SystemExit(main())
