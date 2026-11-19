#!/usr/bin/env python3
"""Назвать установку игры по отпечаткам архивов, не выкладывая её целиком.

    python3 tools/retail_fingerprint.py "D:/Games/BFME2"
    python3 tools/retail_fingerprint.py "D:/RotWK" --game rotwk
    python3 tools/retail_fingerprint.py <папка> --json отчёт.json

Сверяет КАЖДЫЙ архив с политикой (`contracts/*.json`: путь, размер, md5) и
печатает таблицу: что совпало, что отличается и чего нет. Это отвечает на
вопрос «та ли у меня версия игры» за секунды и по числам, а не «на глаз».

Зачем: файлы игры — гигабайты, и их не нужно передавать, чтобы понять, годится
ли установка. Достаточно отпечатка. Если политика совпала хотя бы по размеру
на всех крупных архивах, а по md5 — на всех, установка ровно та, под которую
написан импортёр.

Полный md5 читает каждый архив целиком; на 4 ГБ это единицы минут. Если нужен
только быстрый ответ, добавьте --sizes-only: сверяются лишь размеры (мгновенно)
и крупные расхождения видно сразу.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICIES = {
    "bfme2": ROOT / "contracts" / "bfme2-106-english-archives.json",
    "rotwk": ROOT / "contracts" / "rotwk-201-english-archives.json",
}


def md5_of(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def index_install(root: Path) -> dict[str, Path]:
    """Все .big под папкой, ключ — путь в нижнем регистре.

    Регистр важен: на Windows путь безразличен, на Linux — нет, поэтому
    политика (`Textures2.big`) и файл на диске (`textures2.big`) должны
    сопоставляться без учёта регистра, иначе всё «отсутствует».
    """
    found: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".big":
            found[path.relative_to(root).as_posix().casefold()] = path
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install", type=Path, help="папка установки игры (где game.dat)")
    parser.add_argument("--game", choices=sorted(POLICIES), default="bfme2")
    parser.add_argument("--sizes-only", action="store_true", help="не читать md5, только размеры")
    parser.add_argument("--json", type=Path, help="записать отчёт в файл JSON")
    args = parser.parse_args(argv)

    root = args.install.expanduser().resolve()
    if not root.is_dir():
        print(f"НЕТ ПАПКИ: {root}", file=sys.stderr)
        return 2

    document = json.loads(POLICIES[args.game].read_text(encoding="utf-8"))
    archives = document["archives"]
    have = index_install(root)

    exact, size_only, differ, missing = [], [], [], []
    for member in archives:
        path = have.get(member["path"].casefold())
        if path is None:
            missing.append(member)
            continue
        if path.stat().st_size != member["size"]:
            differ.append((member, path))
            continue
        if args.sizes_only:
            size_only.append(member["path"])
            continue
        if md5_of(path) == member["md5"]:
            exact.append(member["path"])
        else:
            differ.append((member, path))

    known = {m["path"].casefold() for m in archives}
    extra = [p for key, p in have.items() if key not in known]

    print(f"Установка: {root}")
    print(f"Политика:  {document['game']} {document['patch']} — {len(archives)} архивов")
    print()
    print(f"  совпало точь-в-точь (md5): {len(exact)}")
    if args.sizes_only:
        print(f"  совпало по размеру:        {len(size_only)}")
    print(f"  отличается:                {len(differ)}")
    print(f"  отсутствует:               {len(missing)}")
    print(f"  лишних .big в папке:       {len(extra)}")

    if differ:
        print("\nОТЛИЧАЕТСЯ (размер не тот или содержимое другое):")
        for member, path in sorted(differ, key=lambda item: -item[0]["size"])[:20]:
            print("  {:34s} ждали {:>7.1f} МБ, у вас {:>7.1f} МБ".format(
                member["path"], member["size"] / 1048576, path.stat().st_size / 1048576))

    if missing:
        total = sum(m["size"] for m in missing)
        print("\nОТСУТСТВУЕТ ({:.0f} МБ всего):".format(total / 1048576))
        for member in sorted(missing, key=lambda m: -m["size"])[:20]:
            print("  {:34s} {:>7.1f} МБ".format(member["path"], member["size"] / 1048576))

    if extra:
        print("\nЛИШНИЕ (их нет в политике — моды или другой патч):")
        for path in sorted(extra)[:20]:
            print("  {}".format(path.relative_to(root).as_posix()))

    matched = len(exact) + len(size_only)
    verdict = "СОВПАДАЕТ С ПОЛИТИКОЙ" if matched == len(archives) else "НЕ СОВПАДАЕТ"
    print("\nВЕРДИКТ: {} ({}/{})".format(verdict, matched, len(archives)))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "install": str(root),
            "game": document["game"],
            "patch": document["patch"],
            "policy_archives": len(archives),
            "exact": exact,
            "size_only": size_only,
            "differ": [m["path"] for m, _p in differ],
            "missing": [m["path"] for m in missing],
            "extra": [p.relative_to(root).as_posix() for p in extra],
            "verdict": verdict,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Отчёт записан: {args.json}")

    return 0 if verdict.startswith("СОВПАДАЕТ") else 1


if __name__ == "__main__":
    raise SystemExit(main())
