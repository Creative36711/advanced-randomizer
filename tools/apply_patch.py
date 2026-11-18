"""Apply a unified diff without git.

``git apply`` needs git, and a Windows machine with only the game installed has
none.  Shipping MinGit instead means pulling a ~50 MB archive from the same
host that is blocked for some players, and an archive that cannot be pinned
because its bytes move between releases - so the launcher refused it and the
first run died at step 2.

This module applies the repository's own patches (plain additions and context
edits, no renames, no binary hunks) with the standard library only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


class PatchError(Exception):
    """A patch could not be applied; the message says where and why."""


def parse_patch(text: str) -> list[dict]:
    """Split a unified diff into files, each with its hunks."""

    files: list[dict] = []
    current: dict | None = None
    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                raise PatchError(f"битый заголовок файла: {line.rstrip()}")
            source = line[4:].strip()
            target = lines[index + 1][4:].strip()
            if source == "/dev/null":
                raise PatchError("создание файлов патчем не поддерживается")
            if target == "/dev/null":
                raise PatchError("удаление файлов патчем не поддерживается")
            name = source[2:] if source.startswith("a/") else source
            name_target = target[2:] if target.startswith("b/") else target
            if name != name_target:
                raise PatchError(f"переименование не поддерживается: {name} -> {name_target}")
            current = {"path": name, "hunks": []}
            files.append(current)
            index += 2
            continue
        if line.startswith("@@"):
            if current is None:
                raise PatchError("фрагмент @@ без заголовка файла")
            header = line.rstrip("\n")
            try:
                ranges, _, _ = header[2:].partition("@@")
                old_part, new_part = ranges.split()
                old_start = int(old_part[1:].split(",")[0])
            except ValueError as error:
                raise PatchError(f"не разобрать заголовок фрагмента: {header}") from error
            index += 1
            body: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                if candidate.startswith(("@@", "--- ", "diff ")):
                    break
                body.append(candidate)
                index += 1
            current["hunks"].append({"old_start": old_start, "lines": body})
            continue
        index += 1
    if not files:
        raise PatchError("в патче нет ни одного файла")
    return files


def _apply_hunk(original: list[str], hunk: dict, where: str) -> list[str]:
    position = hunk["old_start"] - 1
    result: list[str] = []
    cursor = 0
    lines = hunk["lines"]

    def matches(index: int, expected: str) -> bool:
        return 0 <= index < len(original) and original[index].rstrip("\r\n") == expected

    # Search near the recorded position first, then anywhere: a patch written
    # against a slightly different revision should still find its context
    # rather than demanding a byte-identical file.
    context = [line[1:].rstrip("\n") for line in lines if line[:1] in (" ", "-")]
    start = -1
    if position + len(context) <= len(original):
        if all(matches(position + offset, text) for offset, text in enumerate(context)):
            start = position
    if start < 0:
        for candidate in range(0, len(original) - len(context) + 1):
            if all(matches(candidate + offset, text) for offset, text in enumerate(context)):
                start = candidate
                break
    if start < 0:
        raise PatchError(
            f"{where}: не найден контекст фрагмента @@ -{hunk['old_start']}\n"
            f"  искали строку: {context[0] if context else '(пусто)'}"
        )

    result.extend(original[:start])
    index = start
    for raw in lines:
        marker, text = raw[:1], raw[1:]
        if marker == " ":
            if not matches(index, text.rstrip("\n")):
                raise PatchError(f"{where}: контекст не совпал на строке {index + 1}")
            result.append(original[index])
            index += 1
        elif marker == "-":
            if not matches(index, text.rstrip("\n")):
                raise PatchError(f"{where}: удаляемая строка не совпала: {index + 1}")
            index += 1
        elif marker == "+":
            result.append(text if text.endswith("\n") else text + "\n")
        elif marker == "\\":
            continue  # "\ No newline at end of file"
        elif raw.strip() == "":
            continue
    result.extend(original[index:])
    return result


def apply_files(root: Path, files: list[dict]) -> list[str]:
    """Apply every file hunk; return the paths that changed."""

    changed: list[str] = []
    for entry in files:
        target = root / entry["path"]
        if not target.is_file():
            raise PatchError(f"нет файла, к которому применяется патч: {target}")
        original = target.read_text(encoding="utf-8").splitlines(keepends=True)
        result = original
        for hunk in entry["hunks"]:
            result = _apply_hunk(result, hunk, entry["path"])
        if result != original:
            target.write_text("".join(result), encoding="utf-8")
            changed.append(entry["path"])
    return changed


def apply_patch_file(patch: Path, root: Path) -> list[str]:
    return apply_files(root, parse_patch(patch.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patch", type=Path, help="unified diff to apply")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="tree the patch applies to")
    arguments = parser.parse_args(argv)
    try:
        changed = apply_patch_file(arguments.patch, arguments.root)
    except PatchError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1
    for name in changed:
        print(f"изменён {name}")
    print(f"готово: {len(changed)} файл(ов)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
