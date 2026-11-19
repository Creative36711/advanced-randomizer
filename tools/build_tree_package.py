"""Build the tree package that launcher/start/tree_package.py installs.

The launcher used to assemble the game on every player's machine: download 17 MB
of OpenBFME sources, apply ``patches/*.patch``, copy our ``game/``.  The same
three steps, run once here from the same commit, produce a tree that is checked
into a release instead - the model Open-BFME uses for its own packages.

    python3 tools/build_tree_package.py --output dist/tree --version v0.3.0

Writes ``<output>/tree-<version>.zip`` (one top-level folder, ``openbfme``) and
``<output>/tree.json``: the manifest the launcher reads before downloading a
byte.  No signature: a key we do not have would only look like a check.

The zip is built deterministically (fixed timestamps, sorted names), so the same
commit produces the same digest and a release can be rebuilt and compared.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher' / 'start'))
sys.path.insert(0, str(ROOT / 'tools'))

import apply_patch  # noqa: E402
import tree_package  # noqa: E402

TOP = 'openbfme'
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def assemble(source: Path, destination: Path) -> None:
    """Copy OpenBFME's tree, apply our patches, then lay our game/ on top."""

    if not source.is_file():
        raise SystemExit(f'нет архива исходников: {source}')
    with zipfile.ZipFile(source) as zf:
        for info in zf.infolist():
            target = (destination / info.filename).resolve()
            if not tree_package.inside(destination, target):
                raise SystemExit(f'архив исходников пишет вне папки: {info.filename}')
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open('wb') as out:
                out.write(src.read())
    trees = [p for p in destination.iterdir() if p.is_dir()]
    if len(trees) != 1:
        raise SystemExit(f'в исходниках ожидалась одна папка, а их {len(trees)}')
    tree = trees[0]
    for patch in sorted((ROOT / 'patches').glob('*.patch')):
        apply_patch.apply_patch_file(patch, tree)
    # dirs_exist_ok merges our files INTO game/: the mod is a set of new files
    # plus edits already made by the patch, not a replacement of the folder.
    import shutil

    shutil.copytree(ROOT / 'game', tree / 'game', dirs_exist_ok=True)
    # Дерево обязано назвать свой коммит: без release-identity.json импортёр
    # отказывает на аудите происхождения ("has no exact git commit"), и
    # конвертация у игрока падает на последнем шаге после 216 с работы.
    # Источник — release-identity.json нашего репозитория (его обновляет CI);
    # сам здесь git не вызывается: на машине игрока его нет.
    stamp = ROOT / 'release-identity.json'
    if stamp.is_file():
        shutil.copyfile(stamp, tree / 'release-identity.json')
    else:
        print('ВНИМАНИЕ: нет release-identity.json — пакет откажет на аудите')
    if tree != destination:
        for item in tree.iterdir():
            item.rename(destination / item.name)
        tree.rmdir()


def safe_version(version: str) -> str:
    """A version that can be a file name.

    A pull request's GITHUB_REF_NAME is "123/merge": the slash made the zip
    path a directory that does not exist, and the build failed with a
    FileNotFoundError that named nothing.
    """

    cleaned = ''.join(c if c.isalnum() or c in '._-' else '-' for c in version).strip('-')
    return cleaned or 'build'


def write_zip(tree: Path, archive: Path) -> int:
    """Deterministic zip with one top-level folder; returns its size."""

    entries = sorted(
        (p for p in tree.rglob('*') if p.is_file()),
        key=lambda p: p.relative_to(tree).as_posix(),
    )
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in entries:
            name = TOP + '/' + path.relative_to(tree).as_posix()
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with path.open('rb') as handle:
                zf.writestr(info, handle.read())
    return archive.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='the pinned OpenBFME source zip (same commit as tools/prepare.py)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True, help='tag or build id in the manifest')
    parser.add_argument('--url-base',
                        default='https://github.com/Creative36711/advanced-randomizer/releases/download',
                        help='where the archive will be downloadable')
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    staging = output / 'staging'
    if staging.exists():
        import shutil

        shutil.rmtree(staging)
    staging.mkdir()
    assemble(args.source, staging)

    problems = tree_package.mod_problems(staging)
    if problems:
        raise SystemExit(
            'собранное дерево — это не Advanced Randomizer, релиз не выпускаю:\n  '
            + '\n  '.join(problems)
        )

    version = safe_version(args.version)
    if version != args.version:
        print(f'версия для имени файла: {version} (было {args.version})')
    archive = output / f'tree-{version}.zip'
    size = write_zip(staging, archive)
    digest = hashlib.sha256()
    with archive.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    manifest = {
        'schema': 'advanced-randomizer.tree',
        'schemaVersion': 1,
        'version': args.version,
        'url': f'{args.url_base}/{args.version}/{archive.name}',
        'sha256': digest.hexdigest(),
        'size': size,
    }
    (output / tree_package.MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    print(f'{archive.name}: {size} байт, sha256 {digest.hexdigest()}')
    import shutil

    shutil.rmtree(staging)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
