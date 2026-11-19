"""Каких записей не хватает профилю men-fords-v0 — за секунды, без конвертации.

Запуск (подставьте свои пути):
  "<python>" diag_fords.py --install C:\\BFME2 --tree "C:\\Users\\Creative\\Advanced Randomizer\\openbfme"

Ничего не конвертирует и не пишет на диск: только строит каталог (он уже в
кэше после ваших прогонов) и сравнивает по каждому правилу.
"""
import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", required=True)
    parser.add_argument("--game", default="bfme2")
    parser.add_argument(
        "--tree", required=True,
        help="папка openbfme/openbfme из лаунчера (внутри неё лежит importer/)")
    parser.add_argument("--profile", default="men-fords-v0")
    args = parser.parse_args()

    tree = Path(args.tree)
    sys.path.insert(0, str(tree / "importer"))
    from openbfme_importer.catalog import (
        DEFAULT_BFME2_ARCHIVE_POLICY,
        ArchivePolicy,
        InstallCatalog,
    )
    from openbfme_importer.profile import ImportProfile, resolve_profile

    policy = ArchivePolicy.load(DEFAULT_BFME2_ARCHIVE_POLICY)
    profile = ImportProfile.load(tree / "importer" / "profiles" / f"{args.profile}.json")
    try:
        catalog = InstallCatalog.build(Path(args.install), source_policy=policy)
    except (FileNotFoundError, ValueError) as error:
        print(f"каталог не построился: {error}")
        print("Скорее всего, --install указывает не на ту папку BFME2 1.06.")
        return 2
    resolved = resolve_profile(profile, catalog)

    got_total = 0
    want_total = 0
    problems = []
    for item in resolved.resources:
        got = len(item.entries)
        want = item.rule.expected_count or len(item.rule.patterns)
        got_total += got
        want_total += want
        if got != want:
            problems.append((item.rule.id, got, want, item.missing_patterns))

    print(f"записей найдено:  {got_total}")
    print(f"профиль ожидает:  {want_total}")
    print(f"аудит требует:    396")
    print()
    if not problems:
        print("все правила совпали с профилем.")
        print("Значит расхождение не в профиле: 396 — константа в коде,")
        print("и она не сходится с самим профилем.")
        return 0
    for rid, got, want, missing in problems:
        print(f"{rid}: {got} из {want}")
        for pattern in missing:
            print(f"    НЕТ В КАТАЛОГЕ: {pattern}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
