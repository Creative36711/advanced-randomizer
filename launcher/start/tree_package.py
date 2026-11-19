"""Раздача собранного дерева: манифест, проверка размера и SHA-256, распаковка.

Модель взята у Open-BFME: игрок не собирает дерево из исходников и патча, а
скачивает готовое и проверяет его по манифесту.  Их схема (``manifest.json`` +
Ed25519) здесь без подписи: подписывать нечем, пока у нас нет ключа, а
неподписанный ключ в лаунчере хуже его отсутствия - он создаёт видимость
проверки, которой нет.  Всё остальное их: манифест, размер, SHA-256, и отказ
ставить что-либо, что не сошлось.

Что это меняет для игрока: шаг ``prepare`` (скачать 17 МБ исходников на КАЖДОЙ
установке, наложить патч, скопировать наш ``game/``) заменяется одним архивом,
который собран один раз в CI из того же коммита.  Патч перестаёт быть частью
первого запуска и становится частью сборки релиза.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "tree.json"
# The tree is our code plus OpenBFME's GDScript game: no retail data, ever.
# A package that grows past this is a packaging mistake, not a download.
MAX_UNPACKED = 400 * 1024 * 1024

# What makes a tree OURS rather than plain OpenBFME.  A package that passes the
# size and digest checks can still be the wrong game: built from the wrong
# commit, or with our game/ folder copied one level too deep.  Both look ready
# (game/project.godot exists) and both leave the player in a game without the
# randomizer, which is indistinguishable from "the mod does nothing".
MOD_FILES = (
    "game/scripts/modes/randomizer/seeded_rng.gd",
    "game/scripts/modes/randomizer/randomizer_match.gd",
    "game/scripts/modes/randomizer/ui/lobby_panel.gd",
)
# Proof that patches/skirmish.patch was applied rather than merely shipped.
PATCH_EVIDENCE = ("game/src/core/game_state.gd", "retail_randomizer")


def inside(base: Path, target: Path) -> bool:
    """``target`` is ``base`` or below it, compared as paths and not as text.

    The text form ``str(t).startswith(str(b) + "/")`` is wrong on Windows,
    where str(Path) uses a backslash: every entry then "escapes" the folder and
    nothing can be unpacked at all. That is how the Godot archive, every mod
    package and this tree failed on the first Windows run.
    """

    base = base.resolve()
    target = target.resolve()
    return target == base or base in target.parents


class TreeError(Exception):
    """The package cannot be trusted or used."""


@dataclass(frozen=True)
class TreePackage:
    url: str
    sha256: str
    size: int
    version: str

    @classmethod
    def from_dict(cls, data: dict, *, source: str = "tree.json") -> "TreePackage":
        try:
            url = str(data["url"])
            sha256 = str(data["sha256"]).lower()
            size = int(data["size"])
            version = str(data["version"])
        except (KeyError, TypeError, ValueError) as error:
            raise TreeError(f"{source}: не хватает поля ({error})") from None
        if not url.startswith("https://"):
            raise TreeError(f"{source}: адрес должен быть https, а не {url}")
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise TreeError(f"{source}: sha256 должен быть 64 шестнадцатеричных знака")
        if size <= 0:
            raise TreeError(f"{source}: размер должен быть больше нуля")
        return cls(url=url, sha256=sha256, size=size, version=version)


def read_manifest(text: str, *, source: str = "tree.json") -> TreePackage:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise TreeError(f"{source}: это не JSON ({error})") from None
    if not isinstance(data, dict):
        raise TreeError(f"{source}: ожидался объект JSON")
    return TreePackage.from_dict(data, source=source)


def mod_problems(tree: Path) -> list[str]:
    """Everything that says this tree is not Advanced Randomizer (empty = it is)."""

    problems = [name for name in MOD_FILES if not (tree / name).is_file()]
    evidence_file, evidence_text = PATCH_EVIDENCE
    evidence = tree / evidence_file
    if not evidence.is_file():
        problems.append(evidence_file)
    elif evidence_text not in evidence.read_text(encoding="utf-8", errors="replace"):
        problems.append(f"{evidence_file} (без нашей правки)")
    return problems


def verify_file(path: Path, package: TreePackage) -> None:
    """Size and digest, both from the manifest; a mismatch deletes nothing here."""

    actual = path.stat().st_size
    if actual != package.size:
        raise TreeError(
            f"размер архива не совпал: ожидали {package.size} байт, получили {actual}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != package.sha256:
        raise TreeError(
            f"контрольная сумма не совпала.\n  ожидали: {package.sha256}\n"
            f"  получили: {digest.hexdigest()}\n  файл: {path}"
        )


def unpack(archive: Path, destination: Path) -> None:
    """Extract into ``destination``; nothing may land outside it.

    A zip entry named ``../x`` or an absolute path is the one way a package can
    write outside the launcher folder, so every entry is resolved first.  The
    archive holds ONE top-level folder (``openbfme``), which becomes
    ``destination`` itself: the engine and every marker expect the tree there.
    """

    destination = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if not names:
            raise TreeError("архив пуст")
        tops = {name.split("/", 1)[0] for name in names}
        if len(tops) != 1:
            raise TreeError(
                "в архиве должна быть одна папка верхнего уровня, а их "
                f"{len(tops)}: {', '.join(sorted(tops)[:5])}"
            )
        top = tops.pop()
        total = 0
        # Every entry must be under that one folder. Checking the resolved path
        # alone is not enough: `openbfme/../x` resolves inside the destination
        # and passes, even though it escapes the folder the archive declares.
        planned: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in zf.infolist():
            if not (info.filename == top or info.filename.startswith(top + "/")):
                raise TreeError(
                    f"архив выходит за свою папку {top}/: {info.filename}"
                )
            relative = Path(info.filename).relative_to(top)
            if ".." in relative.parts or relative.is_absolute():
                raise TreeError(f"архив пишет вне папки лаунчера: {info.filename}")
            target = (destination / relative).resolve()
            # Compared as paths, never as strings with a hard-coded "/": on
            # Windows str(Path) uses "\\", and every entry looked like it was
            # escaping the folder - the player could not install anything.
            if target != destination and destination not in target.parents:
                raise TreeError(f"архив пишет вне папки лаунчера: {info.filename}")
            planned.append((info, relative))
            total += info.file_size
        # Checked before a single byte is written, so a bombshell zip cannot
        # fill the disk first and fail afterwards.
        if total > MAX_UNPACKED:
            raise TreeError(
                f"распакованное дерево было бы {total // (1024 * 1024)} МБ "
                f"(предел {MAX_UNPACKED // (1024 * 1024)} МБ)"
            )
        if destination.exists():
            shutil.rmtree(destination)
        staging = destination.parent / (destination.name + ".unpacking")
        if staging.exists():
            shutil.rmtree(staging)
        for info, relative in planned:
            with zf.open(info) as src:
                if not relative.parts:
                    continue
                target = staging / relative
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        staging.rename(destination)
