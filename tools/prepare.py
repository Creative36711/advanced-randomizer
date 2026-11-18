"""Assemble a playable OpenBFME source tree without vendoring the port or game data."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REV = 'bf06a22baab9713ca51cfa03d017534e3b4f752c'  # legacy-final, the GDScript Skirmish
SHA256 = 'aeab1032d6ae7e47fad04aa485044fa0171a3e1f3175a516810a4a60e710bd08'
URL = f'https://codeload.github.com/Open-BFME/openbfme-godot/tar.gz/{REV}'


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
            archive = Path(tmp) / 'source.tar.gz'
            print(f'Downloading {REV}…', flush=True)
            with urllib.request.urlopen(URL, timeout=90) as response, archive.open('wb') as out:
                shutil.copyfileobj(response, out)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            parser.error('upstream archive SHA-256 mismatch')
        with tarfile.open(archive) as tar:
            # Also works on pre-3.12 Python. No links/devices or paths outside tmp.
            for entry in tar:
                path = (Path(tmp) / entry.name).resolve()
                if not path.is_relative_to(tmp) or not (entry.isdir() or entry.isfile()):
                    parser.error(f'unexpected archive entry: {entry.name}')
                tar.extract(entry, tmp)
        tree = Path(tmp) / f'openbfme-godot-{REV}'
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=tmp)
        for patch in sorted((ROOT / 'patches').glob('*.patch')):
            subprocess.run(['git', 'apply', '--whitespace=nowarn', str(patch)], cwd=tree, env=env, check=True)
        if (ROOT / 'game').is_dir():
            shutil.copytree(ROOT / 'game', tree / 'game', dirs_exist_ok=True)
        tree.rename(dest)
    print(f'Open {dest / "game/project.godot"} with Godot 4.7.2.')


if __name__ == '__main__':
    main()
