"""Assemble a playable OpenBFME source tree without vendoring the port or game data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import zipfile

# The patch engine is this repository's own: `git apply` would make git a hard
# requirement for a player who has only the game installed.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_patch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REV = 'bf06a22baab9713ca51cfa03d017534e3b4f752c'  # legacy-final, the GDScript Skirmish
# The commit ZIP, not the tag tarball: GitHub re-packs tagged tarballs on demand,
# so their bytes (and therefore any hash pin) can change, while a commit ZIP is
# stable. codeload is also plain HTTPS, which is what the one-click launcher can
# rely on without the release-asset host.
SHA256 = '8a84c07fcca5d09549ed6c8582a70060ed58d4bd8ee38983f09e729a392446c8'
URL = f'https://codeload.github.com/Open-BFME/openbfme-godot/zip/{REV}'
# codeload answers with `Transfer-Encoding: chunked` and NO Content-Length, so
# a downloader that waits for the header shows nothing at all - which is what
# the player saw as "15 minutes and no sign of life".  The size is a property
# of the pinned revision, so it is measured once and stated here.
SIZE = 17301881


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='use a previously downloaded pinned source archive')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/openbfme', help='new output directory')
    args = parser.parse_args()
    dest = args.output.resolve()
    if dest.exists():
        parser.error(f'{dest} exists; choose a new --output (never overwrite a game or its packs)')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        archive = args.archive
        if archive is None:
            archive = Path(tmp) / 'source.zip'
            print(f'Скачиваю исходники OpenBFME ({REV[:8]})…', flush=True)
            with urllib.request.urlopen(URL, timeout=90) as response, archive.open('wb') as out:
                # Fall back to the pinned size when the server does not say:
                # chunked responses carry no Content-Length, and "0 bytes of
                # unknown" is exactly the silence being fixed here.
                expected = int(response.headers.get('Content-Length') or 0) or SIZE
                written = 0
                reported = -1
                while block := response.read(1024 * 1024):
                    out.write(block)
                    written += len(block)
                    megabytes = written // 1048576
                    if megabytes > reported:
                        reported = megabytes
                        print(f'  {megabytes} МБ из {expected // 1048576} МБ', flush=True)
        digest = hashlib.sha256()
        with archive.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != SHA256:
            parser.error(
                f'контрольная сумма архива не совпала.\n  ожидали: {SHA256}\n'
                f'  получили: {digest.hexdigest()}\n  файл: {archive}'
            )
        with zipfile.ZipFile(archive) as zf:
            # Regular files only; nothing may land outside tmp.
            for info in zf.infolist():
                path = (Path(tmp) / info.filename).resolve()
                if not path.is_relative_to(tmp):
                    parser.error(f'unexpected archive entry: {info.filename}')
                if info.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, path.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
        print('Распаковано.', flush=True)
        tree = Path(tmp) / f'openbfme-godot-{REV}'
        if not tree.is_dir():
            parser.error('в архиве нет ожидаемого дерева исходников')
        patches = sorted((ROOT / 'patches').glob('*.patch'))
        if not patches:
            parser.error('в репозитории нет patches/*.patch — собирать нечего')
        for patch in patches:
            print(f'Применяю {patch.name}…', flush=True)
            try:
                changed = apply_patch.apply_patch_file(patch, tree)
            except apply_patch.PatchError as error:
                parser.error(f'{patch.name}: {error}')
            print(f'  изменено файлов: {len(changed)}', flush=True)
        if (ROOT / 'game').is_dir():
            shutil.copytree(ROOT / 'game', tree / 'game', dirs_exist_ok=True)
        stamp_release_identity(tree)
        tree.rename(dest)
    print(f'Готово: {dest}')
    print(f'Открывать в Godot 4.7.2: {dest / "game/project.godot"}')


# Импортёр штампует происхождение конвертации в provenance-манифест и ОТКАЗЫВАЕТ,
# если дерево не может назвать свой точный коммит: `_importer_recipe_report()`
# ищет `release-identity.json`, а без него требует, чтобы собранное дерево само
# было корнем git-репозитория (см. `git_revision_at_exact_root` — чужой HEAD
# брать запрещено). У игрока git нет по правилу, поэтому дерево обязано нести
# штамп: без него сборка пака падает на аудите
#   "retail provenance importer recipe has no exact git commit"
RELEASE_IDENTITY_SCHEMA = 'openbfme.bundled-source-identity'
RELEASE_IDENTITY_SCHEMA_VERSION = 1
#: Снимок версии этого репозитория: сюда пишется коммит, из которого собран
#: релиз. Это ФАЙЛ, а не результат вызова git — prepare.py запускается на
#: машине игрока, где git нет и не должно быть (тест
#: `test_prepare_does_not_call_git` запрещает здесь внешние процессы).
VERSION_STAMP = ROOT / 'release-identity.json'


def stamp_release_identity(tree):
    """Положить в дерево происхождение — из снимка версии, без вызова git.

    Источник штампа — `release-identity.json` в нашем репозитории, который
    обновляет CI при сборке пакета. Если снимка нет (сборка из рабочей копии),
    штамп всё равно пишется, но честно помечается `sourceClean: false`:
    импортёр в этом случае откажет, а не подпишет дерево чужими руками.
    """
    source = VERSION_STAMP
    if source.is_file():
        try:
            identity = json.loads(source.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise SystemExit(f'снимок версии не читается: {source}: {error}')
    else:
        identity = {
            'schema': RELEASE_IDENTITY_SCHEMA,
            'schemaVersion': RELEASE_IDENTITY_SCHEMA_VERSION,
            'commit': None,
            'sourceClean': False,
            'note': 'снимок версии отсутствовал при сборке дерева',
        }
    identity['upstream'] = f'Open-BFME/openbfme-godot@{REV}'
    identity['stampedBy'] = 'tools/prepare.py'
    (tree / 'release-identity.json').write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    if identity.get('sourceClean') is True and identity.get('commit'):
        print(f"  Происхождение: {str(identity['commit'])[:12]} (чистое дерево)", flush=True)
    else:
        print('  ВНИМАНИЕ: версия не подтверждена (нет снимка версии) — '
              'конвертация откажет на аудите происхождения.', flush=True)


if __name__ == '__main__':
    main()
