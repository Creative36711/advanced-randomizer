"""Every byte the launcher may download is pinned here.

Nothing in this file is a secret and none of it is retail content: these are
public tool archives.  A hash that has not been established on a real machine
stays ``None``, and the engine then *reports the measured hash and deletes the
download* instead of installing something unverified.  That is a one-line fix
for a maintainer, not a silent trust hole.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Artifact:
    key: str
    label: str
    url: str
    sha256: str | None
    size: int | None = None
    version: str = ""


@dataclass(frozen=True)
class PinnedPython:
    version: str
    url: str
    sha256: str
    exe_sha256: str
    archive_name: str


#: The interpreter the importer's own bootstrap expects (3.12.x, build
#: 20260718), with the digests upstream already pins.  Reusing upstream's pins
#: means a mismatch fails here *and* there, for the same reason.
PINNED_PYTHON = PinnedPython(
    version="3.12.13",
    url=(
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        "20260718/cpython-3.12.13%2B20260718-x86_64-pc-windows-msvc-install_only.tar.gz"
    ),
    sha256="56c9dd9681c4810cb8bfdec277ee2606d8ab17e678e5bc2bd138eb8098e330b6",
    exe_sha256="32783151cd5dcf5196ff2fa342c11fc0909436531d4deec7824cbc29fd8c1a0c",
    archive_name="cpython-3.12.13-20260718.tar.gz",
)

#: The tested engine.  ``version`` is read by the engine to name the extracted
#: executable; keep the two in step.
GODOT_WIN64_ZIP = Artifact(
    key="godot",
    label="Godot 4.7.2",
    url=(
        "https://github.com/godotengine/godot-builds/releases/download/"
        "4.7.2-stable/Godot_v4.7.2-stable_win64.exe.zip"
    ),
    sha256="731980f9608d61333e5baf54a2ef17210acc7a538446c0cb9969f002aca1e953",
    size=86_013_866,
    version="4.7.2",
)

MINGIT_64_ZIP = Artifact(
    key="mingit",
    label="Git for Windows (MinGit)",
    url=(
        "https://github.com/git-for-windows/git/releases/download/"
        "v2.56.1.windows.1/MinGit-2.56.1-64-bit.zip"
    ),
    # Listed in the official release notes; not re-verified here, so the
    # engine refuses it until someone measures it on a real machine.
    sha256=None,
)

#: ffmpeg/ffprobe digests the importer accepts (bootstrap.py owns the
#: authoritative copy; these mirror it).
FFMPEG_EXE_SHA256 = "228d7a8556258de907fdb55f36850078ebc7680b84ec30d84ea02e99bec1d1eb"
FFPROBE_EXE_SHA256 = "0fde260f5abd35c9cafd96f594cc76365a780c1b73a90e35b6a3409ea1db1bf0"

#: Mirrors, in order.  The archive changes upstream, so it is not pinned; the
#: two executables inside it are (they must equal the importer's constants).
FFMPEG_URL_CANDIDATES: tuple[str, ...] = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
)

OPENBFME_SOURCE_RELATIVE = Path("openbfme")
CONTENT_PACKS_RELATIVE = Path("workspace") / "content-packs"
