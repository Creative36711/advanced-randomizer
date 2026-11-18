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

#: The exact FFmpeg build the importer demands, already packed by its author.
#:
#: THREE reasons this is not `release-essentials.zip` any more:
#:   * that URL means "the LATEST build", while the pinned digests belong to
#:     8.1.1 - a player downloaded 104 MB only to be told the hash mismatch;
#:   * the same 8.1.1 is 32 MB as .7z and 104 MB as .zip;
#:   * a third of the unpacked archive is ffplay.exe, which nothing here uses.
#:
#: The archive digest is published by GitHub for this release, so unlike the
#: moving gyan.dev URL it can be pinned - and is.
FFMPEG_7Z = Artifact(
    key="ffmpeg",
    label="FFmpeg 8.1.1",
    url=(
        "https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/"
        "ffmpeg-8.1.1-essentials_build.7z"
    ),
    sha256="23ad8969fbe701d44e6e7e2b97c5fae4a71224fc33a2560a9034e5110d029d15",
    size=33_664_824,
    version="8.1.1",
)

#: 7-Zip's own console extractor: 600 KB, reads 7z, needs no install.
#: Downloaded only when the .7z route is used and nothing else can open it.
#: Its digest is published by GitHub for this release, so it is pinned too.
SEVEN_ZR = Artifact(
    key="7zr",
    label="7-Zip extractor",
    url=(
        "https://github.com/ip7z/7zip/releases/download/26.06/7zr.exe"
    ),
    sha256="e80db2dad715a6c5adabe292d31ed54e11f4e9b99ca349827b50573b175891bc",
    size=600_064,
    version="26.06",
)

#: The same release as a ZIP, for machines without a 7z-capable archiver.
#: Verified end to end: archive digest pinned, then both executables pinned.
FFMPEG_8_1_1_ZIP = Artifact(
    key="ffmpeg-zip",
    label="FFmpeg 8.1.1 (ZIP)",
    url=(
        "https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/"
        "ffmpeg-8.1.1-essentials_build.zip"
    ),
    sha256="6f58ce889f59c311410f7d2b18895b33c03456463486f3b1ebc93d97a0f54541",
    size=109_282_242,
    version="8.1.1",
)

#: Last resort: gyan.dev's moving "latest" URL.  The archive cannot be pinned
#: there, so only the executables are checked - which is still the check that
#: matters, but it costs a 109 MB download to discover a mismatch.
FFMPEG_URL_CANDIDATES: tuple[str, ...] = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
)

OPENBFME_SOURCE_RELATIVE = Path("openbfme")
CONTENT_PACKS_RELATIVE = Path("workspace") / "content-packs"
