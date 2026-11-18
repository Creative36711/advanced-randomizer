"""Assemble a playable OpenBFME source tree without vendoring the port or game data."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REV = 'bf06a22baab9713ca51cfa03d017534e3b4f752c'  # legacy-final, the GDScript Skirmish
# The commit ZIP, not the tag tarball: GitHub re-packs tagged tarballs on demand,
# so their bytes (and therefore any hash pin) can change, while a commit ZIP is
# stable. codeload is also plain HTTPS, which is what the one-click launcher can
# rely on without the release-asset host.
SHA256 = '8a84c07fcca5d09549ed6c8582a70060ed58d4bd8ee38983f09e729a392446c8'
URL = f'https://codeload.github.com/Open-BFME/openbfme-godot/zip/{REV}'


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
            print(f'Downloading {REV}…', flush=True)
            with urllib.request.urlopen(URL, timeout=90) as response, archive.open('wb') as out:
                shutil.copyfileobj(response, out)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            parser.error('upstream archive SHA-256 mismatch')
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
        tree = Path(tmp) / f'openbfme-godot-{REV}'
        if not tree.is_dir():
            parser.error('archive does not contain the pinned source tree')
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=tmp)
        for patch in sorted((ROOT / 'patches').glob('*.patch')):
            subprocess.run(['git', 'apply', '--whitespace=nowarn', str(patch)], cwd=tree, env=env, check=True)
        if (ROOT / 'game').is_dir():
            shutil.copytree(ROOT / 'game', tree / 'game', dirs_exist_ok=True)
        tree.rename(dest)
    print(f'Open {dest / "game/project.godot"} with Godot 4.7.2.')


if __name__ == '__main__':
    main()
