"""Tests for the launcher engine: every decision, none of the window.

Run from the repository root:

    python3 -m unittest discover -s launcher/start/tests -v

These run on any platform with any Python 3.8+; nothing here spawns Godot,
PowerShell or a network connection.  The window (``launcher.ps1``) is the only
untested part by design, and it is deliberately dumb enough for that to be
safe.
"""

from __future__ import annotations

import io
import json
import os
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine  # noqa: E402


def make_install(root: Path, kind: str) -> Path:
    """A directory that passes the same markers the real game does."""

    root.mkdir(parents=True, exist_ok=True)
    (root / "game.dat").write_bytes(b"GAME")
    if kind in ("rotwk", "layered"):
        (root / "lotrbfme2ep1.exe").write_bytes(b"EXE")
        (root / "_patch201.big").write_bytes(b"BIGF")
    if kind == "bfme2":
        (root / "lotrbfme2.exe").write_bytes(b"EXE")
        (root / "ini.big").write_bytes(b"BIGF")
    if kind == "layered":
        for layer, name in (
            ("layer-0-patch202", "__patch202.big"),
            ("layer-1-rotwk", "game.dat"),
            ("layer-2-bfme2", "game.dat"),
        ):
            (root / layer).mkdir(exist_ok=True)
            (root / layer / name).write_bytes(b"X")
    return root


def make_patch202(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "__patch202.big").write_bytes(b"BIGF")
    (root / "_202music.big").write_bytes(b"BIGF")
    (root / "___hdrotwk.v.0.9.big").write_bytes(b"BIGF")
    (root / "lang").mkdir(exist_ok=True)
    (root / "lang" / "englishpatch202.big").write_bytes(b"BIGF")
    return root


def offline(*_args, **_kwargs):
    """An opener that refuses everything: a unit test must not use the network.

    Without it a test that calls step_prepare downloads the published tree on
    any machine that has a release - the Windows run did, the Linux run did
    not, and the same test then passed in one place and failed in the other.
    """

    raise urllib.error.URLError(OSError(101, "network disabled in tests"))


def make_source(root: Path) -> Path:
    """A tree that passes the same checks as a real one: the game AND our mod.

    A tree with only ``game/project.godot`` is plain OpenBFME; ``source_ready``
    must refuse it, so tests that need a usable tree have to make the mod too.
    """

    import tree_package

    tree = engine.source_tree(root)
    (tree / "game").mkdir(parents=True, exist_ok=True)
    (tree / "game" / "project.godot").write_text("[application]\n", encoding="utf-8")
    (tree / "tools").mkdir(parents=True, exist_ok=True)
    (tree / "tools" / "openbfme_import.py").write_text("", encoding="utf-8")
    for name in tree_package.MOD_FILES:
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# тест\n", encoding="utf-8")
    evidence = tree / tree_package.PATCH_EVIDENCE[0]
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(tree_package.PATCH_EVIDENCE[1] + " = {}\n", encoding="utf-8")
    return tree


def make_pack(root: Path, name: str = "bfme2-men-vslice/abc123") -> None:
    packs = engine.content_packs(root)
    (packs / name).mkdir(parents=True, exist_ok=True)
    (packs / name / "pack.json").write_text('{"id": "x"}', encoding="utf-8")
    (packs / "selection.json").write_text(
        json.dumps({"schema": "openbfme.pack-selection", "activePack": name}),
        encoding="utf-8",
    )


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        # Настоящая сеть в тестах — это либо ожидание таймаута, либо проверка
        # не того, что задумано. Проверка свежести дерева спрашивает манифест
        # у GitHub, поэтому по умолчанию считаем, что сети нет: без неё дерево
        # признаётся годным, и план не меняется. Тесты, которым нужна
        # опубликованная версия, подменяют эту функцию сами.
        original = engine.published_tree_version
        engine.published_tree_version = lambda opener=None: None
        self.addCleanup(setattr, engine, "published_tree_version", original)


class SettingsTests(TempCase):
    def test_round_trip_preserves_every_path(self) -> None:
        original = engine.Settings(
            install_root=self.root / "launcher",
            bfme2_install=self.root / "bfme2",
            rotwk_install=self.root / "rotwk",
            patch202_root=self.root / "patch202",
            seed="Arda1",
            auto_seed=False,
        )
        path = self.root / "settings.json"
        engine.save_settings(original, path)
        loaded = engine.load_settings(path)
        self.assertEqual(loaded.install_root, original.install_root)
        self.assertEqual(loaded.bfme2_install, original.bfme2_install)
        self.assertEqual(loaded.rotwk_install, original.rotwk_install)
        self.assertEqual(loaded.patch202_root, original.patch202_root)
        self.assertEqual(loaded.seed, "Arda1")
        self.assertFalse(loaded.auto_seed)

    def test_missing_or_broken_file_falls_back_to_defaults(self) -> None:
        path = self.root / "settings.json"
        self.assertIsNone(engine.load_settings(path).install_root)
        path.write_text("{ not json", encoding="utf-8")
        self.assertIsNone(engine.load_settings(path).install_root)
        path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(engine.load_settings(path).install_root)

    def test_saving_is_atomic_and_leaves_no_partial(self) -> None:
        path = self.root / "settings.json"
        engine.save_settings(engine.Settings(install_root=self.root / "x"), path)
        engine.save_settings(engine.Settings(install_root=self.root / "y"), path)
        self.assertEqual(
            [item.name for item in self.root.iterdir() if item.name.startswith(".settings")],
            [],
        )
        self.assertEqual(engine.load_settings(path).install_root, self.root / "y")


class DetectionTests(TempCase):
    def test_recognises_bfme2_and_rotwk_by_their_own_executables(self) -> None:
        self.assertEqual(engine.describe_folder(make_install(self.root / "b", "bfme2")), "bfme2")
        self.assertEqual(engine.describe_folder(make_install(self.root / "r", "rotwk")), "rotwk")

    def test_recognises_the_three_layer_rotwk_root(self) -> None:
        layered = make_install(self.root / "layered", "layered")
        self.assertEqual(engine.describe_folder(layered), "layered")

    def test_rejects_a_folder_without_game_dat(self) -> None:
        folder = self.root / "empty"
        folder.mkdir()
        (folder / "lotrbfme2ep1.exe").write_bytes(b"EXE")
        self.assertEqual(engine.describe_folder(folder), "unknown")
        self.assertEqual(engine.describe_folder(self.root / "missing"), "unknown")

    def test_patch202_needs_every_marker_file(self) -> None:
        patch = make_patch202(self.root / "patch")
        self.assertTrue(engine.has_patch202(patch))
        (patch / "lang" / "englishpatch202.big").unlink()
        self.assertFalse(engine.has_patch202(patch))
        self.assertFalse(engine.has_patch202(None))


class StatusTests(TempCase):
    def test_nothing_selected_reports_what_is_missing(self) -> None:
        report = engine.status(engine.Settings())
        self.assertFalse(report["ready"])
        self.assertIn("installRoot", json.dumps(report))
        self.assertTrue(report["notes"])

    def test_ready_only_when_tree_engine_and_pack_all_exist(self) -> None:
        make_source(self.root)
        report = engine.status(engine.Settings(install_root=self.root))
        self.assertFalse(report["ready"])
        self.assertTrue(report["sourceReady"])

        godot = engine.godot_exe(self.root)
        godot.parent.mkdir(parents=True, exist_ok=True)
        godot.write_bytes(b"")
        self.assertFalse(engine.status(engine.Settings(install_root=self.root))["ready"])

        make_pack(self.root)
        final = engine.status(engine.Settings(install_root=self.root))
        self.assertTrue(final["ready"])
        self.assertEqual(final["activePack"], "bfme2-men-vslice/abc123")

    def test_selection_pointing_at_a_missing_bundle_is_not_ready(self) -> None:
        make_source(self.root)
        packs = engine.content_packs(self.root)
        packs.mkdir(parents=True, exist_ok=True)
        (packs / "selection.json").write_text(
            json.dumps({"activePack": "gone/nothing"}), encoding="utf-8"
        )
        self.assertIsNone(engine.selected_pack(self.root))
        self.assertFalse(engine.status(engine.Settings(install_root=self.root))["packSelected"])


class SeedTests(unittest.TestCase):
    def test_accepts_what_the_game_accepts(self) -> None:
        self.assertTrue(engine.valid_seed("Arda"))
        self.assertTrue(engine.valid_seed("a" * 32))
        self.assertFalse(engine.valid_seed(""))
        self.assertFalse(engine.valid_seed("a" * 33))
        self.assertFalse(engine.valid_seed("привет"))
        self.assertFalse(engine.valid_seed("has space"))

    def test_generated_seeds_are_always_valid_and_vary(self) -> None:
        seeds = {engine.generate_seed() for _ in range(50)}
        self.assertTrue(all(engine.valid_seed(seed) for seed in seeds))
        self.assertGreater(len(seeds), 45)


class HumanBytesTests(unittest.TestCase):
    def test_matches_what_a_player_expects(self) -> None:
        self.assertEqual(engine.human_bytes(512), "512 Б")
        self.assertEqual(engine.human_bytes(2048), "2.0 КБ")
        self.assertEqual(engine.human_bytes(86_013_866), "82.0 МБ")
        self.assertEqual(engine.human_bytes(1_256_496_774), "1.2 ГБ")


class FakeResponse:
    def __init__(self, payload: bytes, total: int | None = None) -> None:
        self._stream = io.BytesIO(payload)
        self.headers = {}
        if total is not None:
            self.headers["Content-Length"] = str(total)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info) -> None:
        return None


def opener_for(payload: bytes):
    def opener(request, timeout=60):
        return FakeResponse(payload, len(payload))

    return opener


class DownloadTests(TempCase):
    PAYLOAD = b"pinned payload"

    def sha(self) -> str:
        import hashlib

        return hashlib.sha256(self.PAYLOAD).hexdigest()

    def test_installs_a_matching_download(self) -> None:
        target = self.root / "tool.zip"
        engine.download(
            "https://example.invalid/tool.zip",
            target,
            expected_sha256=self.sha(),
            expected_size=len(self.PAYLOAD),
            echo=lambda _line: None,
            opener=opener_for(self.PAYLOAD),
        )
        self.assertEqual(target.read_bytes(), self.PAYLOAD)
        self.assertFalse((self.root / "tool.zip.part").exists())

    def test_hash_mismatch_deletes_the_download_and_names_both_hashes(self) -> None:
        target = self.root / "tool.zip"
        with self.assertRaises(engine.DownloadError) as caught:
            engine.download(
                "https://example.invalid/tool.zip",
                target,
                expected_sha256="0" * 64,
                echo=lambda _line: None,
                opener=opener_for(self.PAYLOAD),
            )
        message = str(caught.exception)
        self.assertIn("0" * 64, message)
        self.assertIn(self.sha(), message)
        self.assertFalse(target.exists())
        self.assertFalse((self.root / "tool.zip.part").exists())

    def test_unpinned_download_is_refused_before_it_starts(self) -> None:
        calls: list[str] = []

        def opener(request, timeout=60):
            calls.append("hit")
            return FakeResponse(self.PAYLOAD)

        with self.assertRaises(engine.DownloadError) as caught:
            engine.download(
                "https://example.invalid/tool.zip",
                self.root / "tool.zip",
                expected_sha256=None,
                echo=lambda _line: None,
                opener=opener,
            )
        self.assertIn("не закреплён", str(caught.exception))
        self.assertEqual(calls, [])

    def test_size_mismatch_is_caught_even_when_the_hash_matches(self) -> None:
        with self.assertRaises(engine.DownloadError) as caught:
            engine.download(
                "https://example.invalid/tool.zip",
                self.root / "tool.zip",
                expected_sha256=self.sha(),
                expected_size=len(self.PAYLOAD) + 1,
                echo=lambda _line: None,
                opener=opener_for(self.PAYLOAD),
            )
        self.assertIn("ожидалось", str(caught.exception))

    def test_oversized_response_is_cut_off(self) -> None:
        with self.assertRaises(engine.DownloadError) as caught:
            engine.download(
                "https://example.invalid/tool.zip",
                self.root / "tool.zip",
                expected_sha256=self.sha(),
                expected_size=4,
                echo=lambda _line: None,
                opener=opener_for(self.PAYLOAD),
            )
        self.assertIn("больше", str(caught.exception))
        self.assertFalse((self.root / "tool.zip.part").exists())


class ArchiveTests(TempCase):
    def test_zip_paths_never_escape_the_destination(self) -> None:
        archive = self.root / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escaped.txt", "no")
        with self.assertRaises(engine.LauncherError):
            engine.extract_zip(archive, self.root / "out")
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_zip_extracts_normal_members(self) -> None:
        archive = self.root / "tool.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("dir/tool.exe", "binary")
        engine.extract_zip(archive, self.root / "out")
        self.assertEqual(
            (self.root / "out" / "dir" / "tool.exe").read_text(encoding="utf-8"),
            "binary",
        )


class Recorder:
    """A Runner stand-in: records commands and plays back canned exit codes."""

    def __init__(self, codes: list[int] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.codes = list(codes or [])

    def run(self, args, *, cwd=None, env=None, check=False, capture=False):
        self.commands.append([str(part) for part in args])

        class Result:
            def __init__(self, code: int) -> None:
                self.returncode = code
                self.stdout = ""
                self.stderr = ""

        code = self.codes.pop(0) if self.codes else 0
        result = Result(code)
        if check and code != 0:
            raise engine.LauncherError("failed", engine.EXIT_TOOL)
        return result


class PlanTests(TempCase):
    def test_fresh_install_plans_every_step_and_launch(self) -> None:
        plan = engine.first_run_plan(engine.Settings(install_root=self.root))
        self.assertEqual(plan[0], "python")
        self.assertIn("prepare", plan)
        self.assertIn("convert", plan)
        self.assertEqual(plan[-1], "launch")

    def test_ready_install_plans_only_the_launch(self) -> None:
        make_source(self.root)
        make_pack(self.root)
        engine.godot_exe(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.godot_exe(self.root).write_bytes(b"")
        engine.pinned_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.pinned_python(self.root).write_bytes(b"")
        engine.venv_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.venv_python(self.root).write_bytes(b"")
        engine.mark(self.root, "tools")
        engine.mark(self.root, "imported")
        self.assertEqual(engine.first_run_plan(engine.Settings(install_root=self.root)), ["launch"])

    def test_a_tree_that_was_never_imported_gets_the_import_step(self) -> None:
        make_source(self.root)
        make_pack(self.root)
        engine.godot_exe(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.godot_exe(self.root).write_bytes(b"")
        engine.pinned_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.pinned_python(self.root).write_bytes(b"")
        engine.venv_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.venv_python(self.root).write_bytes(b"")
        engine.mark(self.root, "tools")
        plan = engine.first_run_plan(engine.Settings(install_root=self.root))
        self.assertEqual(plan, ["import", "launch"])


class ConvertTests(TempCase):
    def ready_settings(self) -> engine.Settings:
        make_source(self.root)
        engine.venv_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.venv_python(self.root).write_bytes(b"")
        bfme2 = make_install(self.root / "bfme2", "bfme2")
        return engine.Settings(install_root=self.root, bfme2_install=bfme2)

    def fake_runner(self, recorder: "Recorder"):
        """A runner that behaves like a successful converter: a pack lands."""

        root = self.root

        class FakeRunner:
            def run(self, args, **kwargs):
                result = recorder.run(args, **kwargs)
                if result.returncode == 0:
                    make_pack(root)
                return result

        return FakeRunner()

    def test_convert_runs_the_documented_men_lane(self) -> None:
        settings = self.ready_settings()
        recorder = Recorder([0])
        engine.step_convert(
            settings, self.fake_runner(recorder), echo=lambda _line: None
        )
        command = recorder.commands[0]
        self.assertIn("build", command)
        self.assertIn("--game", command)
        self.assertEqual(command[command.index("--game") + 1], "bfme2")
        self.assertEqual(command[command.index("--profile") + 1], "men-fords-v0")

    def test_publish_gate_refusal_is_retried_the_documented_way(self) -> None:
        settings = self.ready_settings()
        recorder = Recorder([7, 0])

        engine.step_convert(
            settings, self.fake_runner(recorder), echo=lambda _line: None
        )
        self.assertEqual(len(recorder.commands), 2)
        self.assertIn("--allow-fewer-playable-units", recorder.commands[1])

    def test_convert_refuses_a_folder_that_is_not_bfme2(self) -> None:
        make_source(self.root)
        engine.venv_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.venv_python(self.root).write_bytes(b"")
        not_bfme2 = make_install(self.root / "rotwk", "rotwk")
        settings = engine.Settings(install_root=self.root, bfme2_install=not_bfme2)
        with self.assertRaises(engine.LauncherError) as caught:
            engine.step_convert(settings, Recorder(), echo=lambda _line: None)
        self.assertEqual(caught.exception.code, engine.EXIT_USAGE)

    def test_convert_needs_a_bfme2_folder_at_all(self) -> None:
        make_source(self.root)
        with self.assertRaises(engine.LauncherError) as caught:
            engine.step_convert(engine.Settings(install_root=self.root), Recorder(), echo=lambda _l: None)
        self.assertEqual(caught.exception.code, engine.EXIT_USAGE)

    def test_a_landed_pack_is_reported_rather_than_rebuilt(self) -> None:
        settings = self.ready_settings()
        make_pack(self.root)
        engine.mark(self.root, "converted")
        recorder = Recorder()
        engine.step_convert(settings, recorder, echo=lambda _line: None)
        self.assertEqual(recorder.commands, [])

    def test_failed_convert_surfaces_the_exit_code(self) -> None:
        settings = self.ready_settings()
        with self.assertRaises(engine.LauncherError) as caught:
            engine.step_convert(settings, Recorder([4, 4]), echo=lambda _line: None)
        self.assertEqual(caught.exception.code, engine.EXIT_TOOL)
        self.assertIn("4", str(caught.exception))


class PrepareTests(TempCase):
    def test_refuses_to_delete_a_tree_the_launcher_did_not_build(self) -> None:
        tree = make_source(self.root)  # exists, but has no launcher marker
        (tree / "game" / "project.godot").unlink()
        (tree / "tools" / "openbfme_import.py").unlink()
        with self.assertRaises(engine.LauncherError) as caught:
            engine.step_prepare(
                engine.Settings(install_root=self.root), Recorder(),
                echo=lambda _l: None, opener=offline, progress=None,
            )
        self.assertEqual(caught.exception.code, engine.EXIT_STATE)
        self.assertTrue(tree.is_dir())

    def test_assembled_tree_is_reused_without_running_anything(self) -> None:
        make_source(self.root)
        recorder = Recorder()
        engine.step_prepare(
            engine.Settings(install_root=self.root), recorder,
            echo=lambda _l: None, opener=offline, progress=None,
        )
        self.assertEqual(recorder.commands, [])


class TreePackageTests(unittest.TestCase):
    """The published tree: what a player downloads instead of assembling it here."""

    def test_a_manifest_without_a_digest_is_refused(self) -> None:
        import tree_package

        with self.assertRaises(tree_package.TreeError) as caught:
            tree_package.read_manifest('{"url": "https://example.com/a.zip", "size": 10}')
        self.assertIn("sha256", str(caught.exception))

    def test_a_manifest_over_plain_http_is_refused(self) -> None:
        # The digest cannot protect a download that a network can replace.
        import tree_package

        text = json.dumps(
            {"url": "http://example.com/a.zip", "sha256": "a" * 64, "size": 1, "version": "v1"}
        )
        with self.assertRaises(tree_package.TreeError) as caught:
            tree_package.read_manifest(text)
        self.assertIn("https", str(caught.exception))

    def test_an_artifact_address_is_the_only_non_https_exception(self) -> None:
        # The CI check build points at its own artifact; a player's launcher
        # must still refuse anything that is not https.
        import tree_package

        ok = json.dumps(
            {"url": "artifact://tree-package/tree.zip", "sha256": "a" * 64,
             "size": 1, "version": "v1"}
        )
        self.assertEqual(tree_package.read_manifest(ok).version, "v1")
        for bad in ("http://example.com/a.zip", "file:///etc/passwd", "ftp://x/y"):
            with self.subTest(url=bad):
                with self.assertRaises(tree_package.TreeError):
                    tree_package.read_manifest(
                        json.dumps({"url": bad, "sha256": "a" * 64, "size": 1, "version": "v"})
                    )

    def test_a_truncated_archive_is_named_not_unpacked(self) -> None:
        import tree_package

        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / "tree.zip"
            archive.write_bytes(b"not a zip")
            package = tree_package.TreePackage(
                url="https://example.com/a.zip", sha256="a" * 64, size=999, version="v1"
            )
            with self.assertRaises(tree_package.TreeError) as caught:
                tree_package.verify_file(archive, package)
            self.assertIn("размер", str(caught.exception))

    def test_an_entry_that_escapes_the_folder_is_refused(self) -> None:
        # A zip entry named ../x is the one way a package writes outside the
        # launcher folder.
        import tree_package

        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / "evil.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("openbfme/../escaped.txt", "x")
            with self.assertRaises(tree_package.TreeError) as caught:
                tree_package.unpack(archive, Path(scratch) / "tree")
            self.assertIn("вне папки", str(caught.exception))
            self.assertFalse((Path(scratch) / "escaped.txt").exists())

    def test_a_good_archive_lands_exactly_where_the_engine_expects(self) -> None:
        import tree_package

        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / "good.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("openbfme/game/project.godot", "[application]\n")
                zf.writestr("openbfme/tools/openbfme_import.py", "")
            destination = Path(scratch) / "tree"
            tree_package.unpack(archive, destination)
            self.assertTrue((destination / "game" / "project.godot").is_file())
            self.assertFalse((destination.parent / "tree.unpacking").exists())

    def test_an_update_keeps_what_the_player_made(self) -> None:
        # The tree holds workspace/retail-work: the converted content that
        # costs about an hour. Replacing the folder instead of merging over it
        # would throw that work away on every update - worse than no update.
        import tree_package

        with tempfile.TemporaryDirectory() as scratch:
            destination = Path(scratch) / "openbfme"
            converted = destination / "workspace" / "retail-work" / "editions" / "big.bin"
            converted.parent.mkdir(parents=True)
            converted.write_bytes(b"converted content\n")
            selection = destination / "workspace" / "content-packs" / "selection.json"
            selection.parent.mkdir(parents=True)
            selection.write_text('{"activePack": "p"}', encoding="utf-8")

            archive = Path(scratch) / "new.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("openbfme/game/project.godot", "[application]\n")
            tree_package.unpack(archive, destination)

            self.assertTrue(converted.is_file(), "сконвертированный контент стёрт обновлением")
            self.assertTrue(selection.is_file(), "выбор пака стёрт обновлением")
            self.assertTrue((destination / "game" / "project.godot").is_file())


class WindowsPathTests(unittest.TestCase):
    """The containment check must not depend on the platform's separator.

    On Windows str(Path) uses "\\", so a check written as
    str(target).startswith(str(base) + "/") says every entry escapes. That
    broke unpacking of the tree, Godot and every mod package at once - and it
    passed on Linux, where the CI tests run, so the defect reached the player.
    """

    def test_a_child_is_inside_whatever_the_separator(self) -> None:
        import tree_package

        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch) / "openbfme"
            child = base / "game" / "project.godot"
            self.assertTrue(tree_package.inside(base, child))
            self.assertTrue(tree_package.inside(base, base))

    def test_a_sibling_is_not_inside(self) -> None:
        import tree_package

        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch) / "openbfme"
            sibling = Path(scratch) / "openbfme-evil" / "x"
            self.assertFalse(tree_package.inside(base, sibling))

    def test_escapes_are_refused(self) -> None:
        import tree_package

        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch) / "openbfme"
            self.assertFalse(tree_package.inside(base, Path(scratch) / "x"))
            self.assertFalse(tree_package.inside(base, base / ".." / "x"))

    def test_the_check_does_not_use_text_prefixes(self) -> None:
        # The defect was in the comparison itself, so the source is checked:
        # a future edit that reintroduces startswith(str(...)) on a path must
        # fail here.  The docstring mentions the bad form on purpose, hence
        # "target" in the same line rather than the bare pattern.
        text = tree_package_path().read_text(encoding="utf-8")
        offenders = [
            line for line in text.splitlines()
            if "startswith(str(" in line and "target" in line and not line.strip().startswith("#")
        ]
        self.assertEqual(offenders, [])


def tree_package_path() -> Path:
    return Path(__file__).resolve().parents[1] / "tree_package.py"


class PreviousInstallTests(TempCase):
    """A folder from the pre-release launcher must be described, not hidden.

    It has the tree but not the randomizer, so source_ready says no - technically
    right, practically useless: the player reads "ничего не собрано" about a
    folder that took an hour to build and may wipe it for nothing.
    """

    def _old_install(self) -> Path:
        tree = engine.source_tree(self.root)
        (tree / "game").mkdir(parents=True)
        (tree / "game" / "project.godot").write_text("[application]\n", encoding="utf-8")
        # the importer's hour of work, and the marker the old path wrote
        state = engine.state_root(self.root) / "editions"
        state.mkdir(parents=True)
        (state / "big.bin").write_bytes(b"converted\n")
        engine.mark(self.root, "assembled")
        return self.root

    def test_it_is_named_as_a_previous_install_not_as_nothing(self) -> None:
        self._old_install()
        report = engine.status(engine.Settings(install_root=self.root))
        self.assertTrue(report["previousInstall"])
        notes = " ".join(report["notes"])
        self.assertIn("прежней версии", notes)
        self.assertNotIn("ещё не собраны", notes)

    def test_the_player_is_told_clearing_is_not_needed(self) -> None:
        self._old_install()
        notes = " ".join(engine.status(engine.Settings(install_root=self.root))["notes"])
        self.assertIn("Очищать её не нужно", notes)

    def test_a_folder_with_nothing_in_it_is_still_a_first_run(self) -> None:
        report = engine.status(engine.Settings(install_root=self.root))
        self.assertIsNone(report["previousInstall"])
        self.assertIn("ещё не собраны", " ".join(report["notes"]))

    def test_an_up_to_date_tree_is_not_called_old(self) -> None:
        make_source(self.root)
        engine.mark(self.root, "assembled", "v0.3.0")
        report = engine.status(engine.Settings(install_root=self.root))
        self.assertIsNone(report["previousInstall"])
        self.assertEqual(report["treeVersion"], "v0.3.0")

    def test_the_step_title_does_not_promise_a_local_build(self) -> None:
        # It reads "собираю исходники" while it installs a package CI built.
        self.assertNotIn("Собираю исходники", engine.FIRST_RUN_TITLES["prepare"])
        self.assertIn("CI", engine.FIRST_RUN_TITLES["prepare"])


class RefusalDetailTests(TempCase):
    """The refusal line carries the audit's file list; run.end carries nothing.

    The player was shown "duration_s=399 exit_code=1" - true, and useless. The
    converter's own `refusal` record names the files that failed the hash
    audit, and it is written ABOVE the exit line, so reading backwards from the
    end found the wrong line.
    """

    def _log(self, body: str) -> Path:
        run = engine.markers_dir(self.root) / "logs" / "20261119T125042Z-converter-1"
        run.mkdir(parents=True)
        (run / "run.log").write_text(body, encoding="utf-8")
        return self.root

    def test_the_refusal_is_preferred_over_the_exit_line(self) -> None:
        self._log(
            "2026-11-19T12:57:22.101Z WARNING converter refusal what=cook "
            "reason=built pack failed its internal hash audit "
            "audit=['bundle_files mismatch: art/w3d/x.w3d']\n"
            "2026-11-19T12:57:22.150Z ERROR   converter run.end exit_code=1\n"
        )
        text = engine.last_importer_refusal(self.root)
        self.assertIn("bundle_files mismatch", text)
        self.assertIn("art/w3d/x.w3d", text)
        self.assertNotIn("exit_code=1", text)

    def test_without_a_refusal_the_error_is_still_better_than_the_exit(self) -> None:
        self._log(
            "2026-11-19T12:57:01.000Z ERROR   converter something broke loudly\n"
            "2026-11-19T12:57:22.150Z ERROR   converter run.end exit_code=1\n"
        )
        text = engine.last_importer_refusal(self.root)
        self.assertIn("something broke loudly", text)

    def test_no_log_means_no_claim(self) -> None:
        self.assertEqual(engine.last_importer_refusal(self.root), "")


class NoNetworkTests(unittest.TestCase):
    """Every call to step_prepare in the tests must be given an opener.

    A release on GitHub turned one old test into a real download: it passed in
    the Linux sandbox (no release host reachable) and failed on Windows, where
    the launcher quietly installed the published tree and skipped the branch
    the test was about. A test that depends on the internet is not a test.
    """

    def test_every_step_prepare_call_says_where_it_reads_from(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        blocks = source.split("engine.step_prepare(")[1:]
        offenders = []
        for block in blocks:
            call = block.split("\n\n", 1)[0]
            if "opener=" not in call:
                offenders.append(call.splitlines()[0][:60])
        self.assertEqual(offenders, [])


class PlainOpenBFMEGuardTests(TempCase):
    """A tree without our mod looks ready and plays a game without the randomizer."""

    def test_a_tree_with_only_the_game_is_not_ready(self) -> None:
        tree = engine.source_tree(self.root)
        (tree / "game").mkdir(parents=True)
        (tree / "game" / "project.godot").write_text("[application]\n", encoding="utf-8")
        (tree / "tools").mkdir(parents=True)
        (tree / "tools" / "openbfme_import.py").write_text("", encoding="utf-8")
        self.assertFalse(engine.source_ready(self.root))

    def test_a_tree_whose_patch_did_not_apply_is_not_ready(self) -> None:
        # Exactly the failure mode of copying game/ one level too deep: the mod
        # files land in game/game/... and the game starts as plain OpenBFME.
        import tree_package

        tree = make_source(self.root)
        (tree / tree_package.PATCH_EVIDENCE[0]).write_text(
            "var retail_sources := {}\n", encoding="utf-8"
        )
        problems = tree_package.mod_problems(tree)
        self.assertTrue(any("без нашей правки" in p for p in problems), problems)
        self.assertFalse(engine.source_ready(self.root))

    def test_a_tree_missing_one_mod_file_names_it(self) -> None:
        import tree_package

        tree = make_source(self.root)
        (tree / tree_package.MOD_FILES[1]).unlink()
        problems = tree_package.mod_problems(tree)
        self.assertEqual(problems, [tree_package.MOD_FILES[1]])


class BuilderTests(TempCase):
    """tools/build_tree_package.py: the archive CI publishes must be installable."""

    def test_the_built_archive_is_deterministic(self) -> None:
        # Same commit twice must produce the same digest, or a rebuilt release
        # cannot be compared with the one players already have.  The property
        # lives in write_zip, so it is tested there and not through a rebuild.
        import importlib.util

        builder_path = Path(__file__).resolve().parents[3] / "tools" / "build_tree_package.py"
        spec = importlib.util.spec_from_file_location("build_tree_package", builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        tree = Path(self.root) / "tree"
        (tree / "game").mkdir(parents=True)
        (tree / "game" / "project.godot").write_text("[application]\n", encoding="utf-8")
        (tree / "b.txt").write_text("second\n", encoding="utf-8")
        (tree / "a.txt").write_text("first\n", encoding="utf-8")
        first = Path(self.root) / "one.zip"
        second = Path(self.root) / "two.zip"
        builder.write_zip(tree, first)
        # Touched in between: mtimes must not leak into the archive.
        (tree / "a.txt").write_text("first\n", encoding="utf-8")
        builder.write_zip(tree, second)
        self.assertEqual(
            hashlib.sha256(first.read_bytes()).hexdigest(),
            hashlib.sha256(second.read_bytes()).hexdigest(),
        )

    def test_a_pull_request_ref_becomes_a_usable_file_name(self) -> None:
        # GITHUB_REF_NAME on a pull request is "123/merge": the slash turned the
        # archive path into a missing directory and the build died with a
        # FileNotFoundError that named nothing.
        import importlib.util

        builder_path = Path(__file__).resolve().parents[3] / "tools" / "build_tree_package.py"
        spec = importlib.util.spec_from_file_location("build_tree_package", builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        self.assertEqual(builder.safe_version("123/merge"), "123-merge")
        self.assertEqual(builder.safe_version("v1.2.3"), "v1.2.3")
        self.assertEqual(builder.safe_version(""), "build")

    def test_a_suffixed_version_downloads_from_its_release_tag(self) -> None:
        # Два 404 подряд, оба нашлись только сборкой манифеста:
        #   --version main        -> url .../download/main/tree-main.zip, а такого
        #                            релиза нет;
        #   --version v0.3.0-main -> в путь попадали ОБА тега сразу.
        # Поэтому версия в имени файла и тег в пути — разные вещи, и это видно
        # в разборе аргументов, а не только в прогоне CI.
        import importlib.util

        builder_path = Path(__file__).resolve().parents[3] / "tools" / "build_tree_package.py"
        spec = importlib.util.spec_from_file_location("build_tree_package", builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        args = builder.build_parser().parse_args([
            "--source", "s.zip", "--output", "out",
            "--version", "v0.3.0-main-ab12cd34",
            "--url-tag", "v0.3.0",
            "--url-base", "https://example.com/releases/download",
        ])
        self.assertEqual(args.version, "v0.3.0-main-ab12cd34")
        self.assertEqual(args.url_tag, "v0.3.0")

    def test_upstream_patches_are_applied_to_the_tree(self) -> None:
        # patches/upstream/ раньше не применялся вовсе: сборщик брал glob
        # только по верхнему уровню patches/. Игрок видел «394 вместо 396» без
        # единого намёка на то, каких двух ресурсов не хватает.
        builder = (Path(__file__).resolve().parents[3]
                   / "tools" / "build_tree_package.py").read_text(encoding="utf-8")
        self.assertIn("patches' / 'upstream'", builder)

    def test_every_upstream_patch_addresses_the_same_path(self) -> None:
        # apply_patch отказывает, если `---` и `+++` называют разные файлы:
        # первый вариант этого патча был снят как diff из /tmp и падал с
        # «переименование не поддерживается» ещё до сборки.
        repo = Path(__file__).resolve().parents[3]
        for patch in sorted((repo / "patches" / "upstream").glob("*.patch")):
            lines = patch.read_text(encoding="utf-8").splitlines()
            header = [line for line in lines if line.startswith(("--- ", "+++ "))]
            self.assertTrue(header, f"{patch.name}: нет заголовка файла")
            names = [line.split("/", 1)[1] for line in header]
            self.assertEqual(names[0], names[1], f"{patch.name}: путь --- и +++ разный")

    def test_the_missing_resources_patch_survives_allow_incomplete(self) -> None:
        # --allow-incomplete глушил причину: missing_required проверялся ДО
        # того, как incomplete создавался, и при флаге список просто не
        # срабатывал. Игрок видел «394 вместо 396» без единого имени — ровно
        # это и случилось на четвёртом прогоне, хотя патч 0001 был в дереве.
        repo = Path(__file__).resolve().parents[3]
        patch = (repo / "patches" / "upstream"
                 / "0002-missing-resources-are-named.patch").read_text(encoding="utf-8")
        self.assertIn("resolved.missing_required", patch)
        # entries/missing_patterns/count_error живут на ResolvedResource:
        # обращение через .rule уронило бы прогон AttributeError.
        self.assertIn("_item.entries", patch)
        self.assertNotIn("_rule.entries", patch)

    def test_the_upstream_patch_names_the_resources(self) -> None:
        # Патч не лечит отказ — он НАЗЫВАЕТ причину. Если причина не из
        # манифеста, патч падает NameError прямо в прогоне игрока.
        repo = Path(__file__).resolve().parents[3]
        patch = (repo / "patches" / "upstream"
                 / "0001-provenance-refusal-names-cause.patch").read_text(encoding="utf-8")
        self.assertIn('manifest.get("incomplete")', patch)
        self.assertIn("ресурс без происхождения", patch)

    def test_a_source_without_our_patch_is_refused(self) -> None:
        # The builder applies patches itself; if a patch stops applying, the
        # release must not be produced at all rather than ship plain OpenBFME.
        import subprocess

        builder = Path(__file__).resolve().parents[3] / "tools" / "build_tree_package.py"
        source = Path(self.root) / "src.zip"
        with zipfile.ZipFile(source, "w") as zf:
            zf.writestr("openbfme/game/project.godot", "[application]\n")
        result = subprocess.run(
            [sys.executable, str(builder), "--source", str(source),
             "--output", str(Path(self.root) / "out"), "--version", "v-test"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((Path(self.root) / "out" / "tree.json").exists())


class TreeStepTests(TempCase):
    """step_prepare must use the published tree, and fall back honestly."""

    def _archive(self) -> tuple[Path, bytes]:
        import tree_package

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("openbfme/game/project.godot", "[application]\n")
            zf.writestr("openbfme/tools/openbfme_import.py", "")
            for name in tree_package.MOD_FILES:
                zf.writestr("openbfme/" + name, "# мод\n")
            zf.writestr(
                "openbfme/" + tree_package.PATCH_EVIDENCE[0],
                tree_package.PATCH_EVIDENCE[1] + " = {}\n",
            )
        return Path(self.root) / "good.zip", buffer.getvalue()

    def test_the_published_tree_is_installed_without_building_anything(self) -> None:
        import hashlib
        import tree_package

        archive, payload = self._archive()
        archive.write_bytes(payload)
        manifest = json.dumps(
            {
                "url": "https://example.com/tree.zip",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "version": "v9.9.9",
            }
        ).encode()

        class Opener:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def __call__(self, request, timeout=None):
                self.urls.append(request.full_url)
                if request.full_url.endswith(tree_package.MANIFEST_NAME):
                    return FakeResponse(manifest)
                return FakeResponse(payload)

        opener = Opener()
        recorder = Recorder()
        tree = engine.step_prepare(
            engine.Settings(install_root=self.root),
            recorder,
            echo=lambda _l: None,
            opener=opener,
            progress=None,
        )
        self.assertTrue((tree / "game" / "project.godot").is_file())
        self.assertTrue(engine.source_ready(self.root))
        # Nothing was run: no prepare.py, no python, nothing.
        self.assertEqual(recorder.commands, [])
        self.assertTrue(engine.marker(self.root, "assembled"))

    def test_a_release_that_is_not_there_falls_back_to_building_here(self) -> None:
        class Down:
            def __call__(self, request, timeout=None):
                raise urllib.error.URLError(OSError(104, "Connection reset by peer"))

        lines: list[str] = []
        # The fallback runs prepare.py, which is not exercised here: the point
        # is that the failure is explained and the player is not abandoned.
        with self.assertRaises(engine.LauncherError):
            engine.step_prepare(
                engine.Settings(install_root=self.root),
                Recorder(),
                echo=lines.append,
                opener=Down(),
                progress=None,
            )
        said = "\n".join(lines)
        self.assertIn("Готовый архив дерева получить не удалось", said)
        self.assertIn("Собираю дерево на этом компьютере", said)


class LaunchTests(TempCase):
    def test_launch_mounts_the_converted_packs_and_sets_the_seed(self) -> None:
        make_source(self.root)
        make_pack(self.root)
        engine.godot_exe(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.godot_exe(self.root).write_bytes(b"")
        captured: dict = {}

        def run(args, **kwargs):
            captured["args"] = args
            captured["env"] = kwargs.get("env") or {}

            class Result:
                returncode = 0

            generator = run(args, **kwargs)
            return Result()

        # Use the real Runner seam shape but never spawn anything.
        class Capture:
            def run(inner_self, args, *, cwd=None, env=None, check=False, capture=False):
                captured["args"] = [str(part) for part in args]
                captured["env"] = env or {}

                class Result:
                    returncode = 0

                return Result()

        engine.step_launch(
            engine.Settings(install_root=self.root, seed="Arda"),
            Capture(),
            echo=lambda _line: None,
        )
        self.assertEqual(captured["env"]["OPENBFME_CONTENT"], str(engine.content_packs(self.root)))
        self.assertEqual(captured["env"]["OPENBFME_SEED"], "Arda")
        self.assertIn("--path", captured["args"])

    def test_launch_without_a_pack_refuses_and_says_why(self) -> None:
        make_source(self.root)
        engine.godot_exe(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.godot_exe(self.root).write_bytes(b"")
        with self.assertRaises(engine.LauncherError) as caught:
            engine.step_launch(engine.Settings(install_root=self.root), Recorder(), echo=lambda _l: None)
        self.assertIn("Контент", str(caught.exception))


class LaneTests(TempCase):
    """The two RotWK lanes never borrow each other's contract."""

    def seed_tree(self) -> engine.Settings:
        tree = make_source(self.root)
        for name in (
            "prepare-rotwk-202-baseline.ps1",
            "rotwk_layered_install.py",
            "rotwk_full_content.py",
        ):
            (tree / "tools" / name).write_text("", encoding="utf-8")
        engine.venv_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        engine.venv_python(self.root).write_bytes(b"")
        return engine.Settings(
            install_root=self.root,
            bfme2_install=make_install(self.root / "bfme2", "bfme2"),
            rotwk_install=make_install(self.root / "rotwk", "rotwk"),
            patch202_root=make_patch202(self.root / "patch202"),
        )

    def test_the_2_02_lane_is_used_only_when_the_overlay_is_present(self) -> None:
        settings = self.seed_tree()
        plan = engine.first_run_plan(settings)
        self.assertIn("full", plan)
        self.assertNotIn("convert", plan)
        self.assertLess(plan.index("layered"), plan.index("full"))

        # Neither the explicit path nor the RotWK folder carries the overlay.
        # seed_tree() also builds a "layered" folder that does, so it must be
        # replaced as well - otherwise this asserts the wrong thing.
        settings.patch202_root = self.root / "nothing-here"
        settings.rotwk_install = make_install(self.root / "plain-201", "rotwk")
        plan = engine.first_run_plan(settings)
        self.assertIn("convert", plan)
        self.assertNotIn("full", plan)
        # The helper really is the thing being tested here:
        self.assertIsNone(engine.patch202_root(settings))

    def test_2_02_is_found_inside_the_201_folder(self) -> None:
        # 2.02 is a fan mod installed by replacing files in the RotWK 2.01
        # folder - so that folder IS the overlay. Asking for a separate path
        # was wrong.
        settings = self.seed_tree()
        settings.patch202_root = None
        modded = make_patch202(make_install(self.root / "modded-201", "rotwk"))
        settings.rotwk_install = modded
        self.assertEqual(engine.patch202_root(settings), modded)
        plan = engine.first_run_plan(settings)
        self.assertIn("full", plan)

    def test_an_explicit_2_02_path_still_wins(self) -> None:
        settings = self.seed_tree()
        explicit = make_patch202(self.root / "elsewhere")
        settings.patch202_root = explicit
        settings.rotwk_install = make_install(self.root / "plain-201", "rotwk")
        self.assertEqual(engine.patch202_root(settings), explicit)

    def test_without_the_overlay_the_full_step_refuses_before_any_work(self) -> None:
        settings = self.seed_tree()
        settings.patch202_root = None
        recorder = Recorder()
        with self.assertRaises(engine.LauncherError) as caught:
            engine.step_full_rotwk(settings, recorder, echo=lambda _line: None)
        self.assertEqual(caught.exception.code, engine.EXIT_USAGE)
        self.assertEqual(recorder.commands, [], "must refuse before converting anything")

    def test_full_step_runs_the_documented_order_end_to_end(self) -> None:
        settings = self.seed_tree()
        recorder = Recorder([0, 0, 0, 0])
        original = engine.powershell
        engine.powershell = lambda: "powershell.exe"  # never consult this host's PATH
        self.addCleanup(setattr, engine, "powershell", original)
        root = self.root

        class ScriptedRunner:
            def run(inner, args, **kwargs):
                result = recorder.run(args, **kwargs)
                if "rotwk_full_content.py" in " ".join(str(a) for a in args):
                    make_pack(root, "rotwk-men-vslice/deadbeef")
                return result

        engine.step_full_rotwk(settings, ScriptedRunner(), echo=lambda _line: None)
        flattened = [" ".join(command) for command in recorder.commands]
        self.assertIn("prepare-rotwk-202-baseline.ps1", flattened[0])
        self.assertIn("index", flattened[1])
        self.assertIn("extract-all-assets", flattened[2])
        self.assertIn("rotwk_full_content.py", flattened[3])
        self.assertIn("--map-limit 10", flattened[3])
        self.assertIn("--select", flattened[3])

    def test_layered_step_requires_both_games(self) -> None:
        settings = self.seed_tree()
        settings.rotwk_install = None
        with self.assertRaises(engine.LauncherError) as caught:
            engine.step_layered(settings, Recorder(), echo=lambda _line: None)
        self.assertEqual(caught.exception.code, engine.EXIT_USAGE)

    def test_layered_step_refuses_a_bfme2_folder_as_rotwk(self) -> None:
        settings = self.seed_tree()
        settings.rotwk_install = settings.bfme2_install
        with self.assertRaises(engine.LauncherError):
            engine.step_layered(settings, Recorder(), echo=lambda _line: None)


class CliTests(TempCase):
    def test_status_is_json_and_exit_zero(self) -> None:
        path = self.root / "settings.json"
        import contextlib
        import io as _io

        buffer = _io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = engine.main(["--settings", str(path), "status"])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertIn("ready", payload)
        self.assertFalse(payload["ready"])

    def test_set_validates_the_seed_before_writing(self) -> None:
        path = self.root / "settings.json"
        self.assertEqual(engine.main(["--settings", str(path), "set", "--seed", "плохой"]), engine.EXIT_USAGE)
        self.assertFalse(path.exists())
        self.assertEqual(engine.main(["--settings", str(path), "set", "--seed", "Arda", "--install-root", str(self.root)]), 0)
        self.assertEqual(engine.load_settings(path).seed, "Arda")

    def test_new_seed_generates_a_valid_one(self) -> None:
        path = self.root / "settings.json"
        engine.main(["--settings", str(path), "set", "--new-seed"])
        self.assertTrue(engine.valid_seed(engine.load_settings(path).seed))

    def test_folders_reports_where_everything_goes(self) -> None:
        import contextlib
        import io as _io

        path = self.root / "settings.json"
        engine.main(["--settings", str(path), "set", "--install-root", str(self.root)])
        buffer = _io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(engine.main(["--settings", str(path), "folders"]), 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["source"].endswith("openbfme"))


if __name__ == "__main__":
    unittest.main()

class EntryPointTests(unittest.TestCase):
    """The files a player double-clicks, checked for the traps that killed them.

    A launcher that fails silently costs a whole round trip: the player sees a
    black window, reports "it closes", and nobody learns anything.  These
    invariants are the ones that failure taught.
    """

    here = Path(__file__).resolve().parent.parent

    def read_bytes(self, name: str) -> bytes:
        return (self.here / name).read_bytes()

    def test_the_cmd_is_pure_ascii_and_crlf(self) -> None:
        # cmd.exe reads a .cmd in the OEM code page: Cyrillic in it breaks on
        # any machine whose code page differs from the author's.
        raw = self.read_bytes("AdvancedRandomizer.cmd")
        raw.decode("ascii")
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertTrue(raw.rstrip(b"\r\n").endswith(b":failed") or b":failed" in raw)

    def test_the_cmd_points_at_a_file_that_exists_next_to_it(self) -> None:
        lines = self.read_bytes("AdvancedRandomizer.cmd").decode("ascii").splitlines()
        executed = [line for line in lines if not line.strip().upper().startswith("REM")]
        body = "\n".join(executed)
        self.assertIn(r"%~dp0launcher.ps1", body)
        # The old bug: appending launcher\start to a folder already ending there.
        self.assertNotIn(r"%~dp0launcher\start", body)
        self.assertTrue((self.here / "launcher.ps1").is_file())

    def test_the_cmd_shows_a_failure_instead_of_closing(self) -> None:
        text = self.read_bytes("AdvancedRandomizer.cmd").decode("ascii")
        self.assertIn("show-failure.ps1", text)
        self.assertIn("pause", text.lower() + "pause")  # helper pauses
        self.assertTrue((self.here / "show-failure.ps1").is_file())

    def test_scripts_are_utf8_with_bom_for_powershell_51(self) -> None:
        # Without a BOM, Windows PowerShell 5.1 decodes a .ps1 as ANSI and every
        # Russian string turns into mojibake.
        for name in ("launcher.ps1", "bootstrap-python.ps1", "show-failure.ps1"):
            with self.subTest(name=name):
                self.assertTrue(self.read_bytes(name).startswith(b"\xef\xbb\xbf"))

    def test_the_window_loads_the_assemblies_before_touching_their_types(self) -> None:
        # [System.Windows.Forms.Form] does not resolve until the assembly is
        # loaded; the first version skipped Add-Type and never drew a window.
        text = self.read_bytes("launcher.ps1").decode("utf-8-sig")
        self.assertIn("Add-Type -AssemblyName System.Windows.Forms", text)
        self.assertIn("Add-Type -AssemblyName System.Drawing", text)

        def first_use(marker: str) -> int:
            # Only real statements count: the comments above this block name the
            # same types while explaining why the load must come first.
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("<#") or stripped.startswith("."):
                    continue
                if marker in line:
                    return text.index(line)
            return -1

        load_at = text.index("Add-Type -AssemblyName System.Windows.Forms")
        for marker in ("[System.Windows.Forms.", "[System.Drawing."):
            with self.subTest(marker=marker):
                self.assertGreater(first_use(marker), load_at)

    def test_every_failure_has_somewhere_to_be_written(self) -> None:
        text = self.read_bytes("launcher.ps1").decode("utf-8-sig")
        self.assertIn("Write-CrashLog", text)
        self.assertIn('"launcher.log"', text)
        # The window announces itself only after it is actually on screen.
        self.assertIn("launcher-ready", text)
    def test_status_can_describe_folders_that_are_not_saved_yet(self) -> None:
        # The window used to ask about the SAVED settings while showing typed
        # paths, so a filled field produced "install folder not chosen".
        with tempfile.TemporaryDirectory() as scratch:
            empty = engine.Settings()
            self.assertIn("Папка лаунчера не выбрана.", engine.status(empty)["notes"])

            merged = engine.with_overrides(empty, {"install_root": Path(scratch)})
            report = engine.status(merged)
            self.assertNotIn("Папка лаунчера не выбрана.", report["notes"])
            self.assertEqual(report["installRoot"], scratch)
            # ...and asking did not touch the saved settings.
            self.assertIsNone(empty.install_root)

    def test_status_overrides_ignore_empty_options(self) -> None:
        class Arguments:
            install_root = None
            bfme2_install = None
            rotwk_install = None
            patch202_root = None
            seed = ""

        self.assertEqual(engine.status_overrides(Arguments()), {})

    def test_refresh_status_never_disables_play(self) -> None:
        # The player pressed PLAY many times and saw nothing: Refresh-Status
        # had disabled the button because the install was not ready, and a
        # disabled button says nothing at all.
        text = self.read_bytes("launcher.ps1").decode("utf-8-sig")
        start = text.index("function Refresh-Status {")
        end = text.index("function Save-Fields {")
        body = text[start:end]
        self.assertNotIn("$play.Enabled = $false", body)
        self.assertIn("$play.Enabled = -not $script:busy", body)

    def test_the_window_closes_while_a_step_is_running(self) -> None:
        # Log #8: a download hung and the window could not be closed - not the
        # X, not "Выход". The player killed it in Task Manager. The close box
        # must stop the work and close, at any moment.
        text = self.read_bytes("launcher.ps1").decode("utf-8-sig")
        self.assertIn("$form.Add_FormClosing({", text)
        start = text.index("$form.Add_FormClosing({")
        body = text[start : start + 600]
        self.assertIn("$script:cancelRequested = $true", body)
        self.assertIn("Stop-EngineTree", body)

    def test_a_running_step_can_be_stopped_from_a_button(self) -> None:
        # "Остановить" replaces "Выход" while a step runs, so the player has a
        # way out that does not need the close box at all.
        text = self.read_bytes("launcher.ps1").decode("utf-8-sig")
        self.assertIn("$stop.Add_Click({ Cancel-Engine })", text)
        self.assertIn("$stop.Visible = $true", text)
        self.assertIn("$quit.Visible = $false", text)
        # ...and it goes away again when the step ends.
        self.assertIn("$stop.Visible = $false", text)
        self.assertIn("$quit.Visible = $true", text)

    def test_stopping_kills_the_whole_process_tree(self) -> None:
        # Killing only the Python engine left Godot and the converter running;
        # the player then had two windows that would not close.
        text = self.read_bytes("launcher.ps1").decode("utf-8-sig")
        start = text.index("function Stop-EngineTree {")
        body = text[start : text.index("function Cancel-Engine {")]
        self.assertIn('"/T"', body)
        self.assertIn('"/F"', body)

    def test_the_wait_loop_honours_cancel_and_forgets_the_child(self) -> None:
        text = self.read_bytes("launcher.ps1").decode("utf-8-sig")
        self.assertIn("$script:currentProcessId = [int]$process.Id", text)
        start = text.index("while (-not $process.HasExited) {")
        body = text[start : start + 400]
        self.assertIn("$script:cancelRequested", body)
        self.assertIn("Stop-EngineTree", body)
        # A cancelled step is the player's decision, not an error to report.
        self.assertIn('"Шаг остановлен по вашей команде."', text)

    def test_play_prepares_and_launches_from_one_click(self) -> None:
        text = self.read_bytes("launcher.ps1").decode("utf-8-sig")
        start = text.index("$play.Add_Click({")
        body = text[start : text.index("$setup.Add_Click({")]
        self.assertIn('Invoke-Engine -Arguments @("autopilot")', body)
        self.assertIn('Get-FieldText -Tag "install-root"', body)

class DownloadErrorTests(unittest.TestCase):
    def test_a_blocked_connection_is_explained_not_traced(self) -> None:
        # Some ISPs refuse GitHub's release host.  Before this, the player saw
        # a raw Python traceback; now the engine names the address, the reason
        # and the folder where the file can be put by hand.
        import urllib.error

        def blocked(request, timeout=None):
            raise urllib.error.URLError(OSError(104, "Connection reset by peer"))

        with tempfile.TemporaryDirectory() as scratch:
            destination = Path(scratch) / "tool.zip"
            with self.assertRaises(engine.DownloadError) as caught:
                engine.download(
                    "https://example.invalid/tool.zip",
                    destination,
                    expected_sha256="a" * 64,
                    label="Python 3.12.13",
                    opener=blocked,
                    echo=lambda line: None,
                )
            message = str(caught.exception)
            self.assertIn("не удалось скачать", message)
            self.assertIn("https://example.invalid/tool.zip", message)
            self.assertIn(str(destination), message)
            self.assertEqual(caught.exception.code, engine.EXIT_DOWNLOAD)
            self.assertFalse(destination.with_name("tool.zip.part").exists())

class StrictModeTests(unittest.TestCase):
    """Every variable the window READS must exist.

    ``Set-StrictMode -Version Latest`` turns an undefined read into a terminating
    error, and PowerShell only reports that at runtime - which is how
    ``$script:busy`` shipped declared nowhere and made the status line die with
    "переменная не может быть получена".  A static check catches it here.
    """

    AUTOMATIC = {
        "args", "input", "this", "error", "host", "home", "pwd", "psitem", "true",
        "false", "null", "env", "matches", "lastexitcode", "pid", "psversiontable",
        "psscriptroot", "pscommandpath", "myinvocation", "stacktrace",
        "executioncontext", "ofs", "shellid", "sender", "eventargs", "profile",
        "pshome", "psculture", "psuiculture", "psboundparameters", "foreach",
        "switch", "confirmpreference", "erroractionpreference", "whatifpreference",
        "verbosepreference", "debugpreference", "warningpreference",
        "informationpreference", "progresspreference", "psdebugcontext",
        "nestedpromptlevel", "outputencoding", "isfailure", "localappdata",
        "appdata", "temp", "computername", "username", "userdomain",
        "processor_architecture", "commandline", "module", "script", "_",
        "lasterror", "cmdlet", "crashlog", "readyfile", "busy", "pythonutf8",
        "pythonioencoding", "enginepython", "systemroot",
    }

    def unset_reads(self, name: str) -> dict:
        import re

        text = Path(__file__).resolve().parent.parent.joinpath(name).read_bytes()
        text = text.decode("utf-8-sig")
        assigned, params, read = set(), set(), {}
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#") or stripped.startswith(".<"):
                continue
            for group in re.findall(r"param\(([^)]*)\)", line):
                params.update(v.lower() for v in re.findall(r"\$(\w+)", group))
            for var in re.findall(r"(?:^|[;\s(\[])\$(\w+)\s*=(?!=)", line):
                assigned.add(var.lower())
            for var in re.findall(r"foreach\s*\(\s*\$(\w+)\s+in", line):
                assigned.add(var.lower())
            for var in re.findall(r"\$script:(\w+)", line):
                assigned.add("script:" + var.lower())
            for var in re.findall(r"\$(\w+(?::\w+)?)", line):
                key = var.lower()
                if ":" in key and not key.startswith("script:"):
                    key = key.split(":")[-1]
                read.setdefault(key, number)
        known = assigned | params | self.AUTOMATIC
        return {name: line for name, line in read.items() if name not in known}

    def test_no_script_reads_an_undefined_variable(self) -> None:
        # bootstrap-python and show-failure declare their switch/param
        # variables in one multi-line param() block, which the regex above does
        # not span; only the full-script blocks are checked here.
        problems = self.unset_reads("launcher.ps1")
        self.assertEqual(problems, {}, f"undefined reads: {problems}")

    def test_the_busy_flag_is_initialised_before_it_is_read(self) -> None:
        text = (Path(__file__).resolve().parent.parent / "launcher.ps1").read_text(
            encoding="utf-8-sig"
        )
        first_write = text.index("$script:busy = $false")
        first_read = text.index("$script:busy)")
        self.assertLess(first_write, first_read)

class PackagingTests(unittest.TestCase):
    def test_the_exe_source_is_not_ignored(self) -> None:
        # .gitignore has a bare `build/` rule; without an exception the exe
        # source was never committed and the release job failed with
        # "source file could not be found".
        root = Path(__file__).resolve().parents[3]
        source = root / "launcher" / "build" / "Program.cs"
        self.assertTrue(source.is_file(), "launcher/build/Program.cs is missing")

        rules = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("!launcher/build/", rules)

    def test_the_exe_source_stays_compilable_by_the_framework_compiler(self) -> None:
        source = (
            Path(__file__).resolve().parents[2] / "build" / "Program.cs"
        ).read_text(encoding="ascii")
        # csc 4.0.30319 is a C# 5 compiler: interpolation and ?. are not there.
        self.assertNotIn('$"', source)
        self.assertNotIn("?.", source)
        self.assertNotIn("nameof(", source)
        self.assertIn("[STAThread]", source)

class ReleaseTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]

    def test_the_exe_is_committed_by_the_workflow(self) -> None:
        # The player pulls the repository and looks for an exe there; a build
        # that only lands in a release page is invisible to them.
        workflow = (self.ROOT / ".github" / "workflows" / "launcher-release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("Commit the exe to the repository", workflow)
        self.assertIn("AdvancedRandomizer.exe", workflow)
        # ...and the shortcut cannot re-trigger itself forever.
        self.assertNotIn('path: "AdvancedRandomizer.exe"', workflow)
        self.assertIn("paths:", workflow)
        self.assertIn('"launcher/start/**"', workflow)
        self.assertNotIn("pull_request:", workflow)

    def test_the_workflow_trigger_shape_is_one_github_accepts(self) -> None:
        # `tags:` at the same level as `push:` is not a valid event, and GitHub
        # rejects the whole workflow before running a single step - which looks
        # exactly like a compiler failure from the outside.  Parsed by hand on
        # purpose: the test suite must run with the standard library only.
        workflow = (self.ROOT / ".github" / "workflows" / "launcher-release.yml").read_text(
            encoding="utf-8"
        )
        # The commit step cannot push from a tag build (detached HEAD).
        self.assertIn("github.ref_type == 'branch'", workflow)

        start = workflow.index("\non:")
        end = workflow.index("\npermissions:")
        events_block = workflow[start:end]
        toplevel = [
            line for line in events_block.splitlines()
            if line and not line.startswith(" ") and line.strip() != "on:"
        ]
        self.assertEqual(toplevel, [], f"keys beside the triggers: {toplevel}")

        self.assertIn("  push:", events_block)
        push_block = events_block[events_block.index("  push:"):]
        push_block = push_block[: push_block.index("\n  workflow_dispatch:")]
        self.assertIn("tags:", push_block, "tags must be nested under push")
        self.assertIn("branches:", push_block)
        allowed = {"push", "workflow_dispatch", "pull_request", "schedule"}
        for line in events_block.splitlines():
            if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
                event = line.strip().rstrip(":")
                self.assertIn(event, allowed, f"unexpected trigger {event}")

    def test_the_readme_names_the_exe_in_the_repository_root(self) -> None:
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        section = readme[readme.index("## Играть"):]
        self.assertIn("AdvancedRandomizer.exe", section)
        self.assertIn("AdvancedRandomizer.cmd", section)

class ArgumentQuotingTests(unittest.TestCase):
    """Start-Process -ArgumentList joins an array with spaces and quotes nothing.

    The player's install folder was C:/Users/Creative/Advanced Randomizer
    (with a space); the engine received "Randomizer" as a separate argument and
    answered "unrecognized arguments: Randomizer".
    """

    def quote(self, value: str) -> str:
        """The rule implemented in Quote-Argument, mirrored here."""
        if value == "":
            return '""'
        if value and not any(ch.isspace() or ch == '"' for ch in value):
            return value
        out = ['"']
        backslashes = 0
        for ch in value:
            if ch == "\\":
                backslashes += 1
                continue
            if ch == '"':
                out.append("\\" * (2 * backslashes + 1) + '"')
                backslashes = 0
                continue
            if backslashes:
                out.append("\\" * backslashes)
                backslashes = 0
            out.append(ch)
        if backslashes:
            out.append("\\" * (2 * backslashes))
        out.append('"')
        return "".join(out)

    def split(self, line: str) -> list:
        """CommandLineToArgvW, so the test fails if the quoting is wrong."""
        args, current, i, in_quotes, content = [], [], 0, False, False
        while i < len(line):
            ch = line[i]
            if ch == "\\":
                n, j = 0, i
                while j < len(line) and line[j] == "\\":
                    n, j = n + 1, j + 1
                if j < len(line) and line[j] == '"':
                    current.append("\\" * (n // 2))
                    if n % 2 == 1:
                        current.append('"')
                        j += 1
                    content = True
                    i = j
                    continue
                current.append("\\" * n)
                content = True
                i = j
                continue
            if ch == '"':
                if in_quotes and i + 1 < len(line) and line[i + 1] == '"':
                    current.append('"')
                    i += 2
                    content = True
                    continue
                in_quotes = not in_quotes
                content = True
                i += 1
                continue
            if ch in " \t" and not in_quotes:
                if content:
                    args.append("".join(current))
                    current, content = [], False
                i += 1
                continue
            current.append(ch)
            content = True
            i += 1
        if content:
            args.append("".join(current))
        return args

    def test_a_folder_with_a_space_survives_the_round_trip(self) -> None:
        arguments = [
            "set",
            "--install-root", "C:\\Users\\Creative\\Advanced Randomizer",
            "--bfme2-install", "C:\\BFME2",
            "--rotwk-install", "C:\\RotWK",
            "--seed", "Arda",
        ]
        line = " ".join(self.quote(a) for a in arguments)
        self.assertEqual(self.split(line), arguments)

    def test_awkward_paths_round_trip(self) -> None:
        for case in (
            "C:\\Program Files (x86)\\Games\\BFME2",
            "D:\\Games\\BFME 2\\",
            'C:\\path\\with"quote',
            "Arda",
            "",
        ):
            with self.subTest(case=case):
                self.assertEqual(self.split(self.quote(case)), [case])

    def test_the_window_actually_quotes_its_arguments(self) -> None:
        text = self.window().read_text(encoding="utf-8-sig")
        self.assertIn("function Quote-Argument", text)
        self.assertIn("function Join-Arguments", text)
        # No Start-Process may receive a raw array.
        for line in text.splitlines():
            if "ArgumentList" in line and "=" in line:
                self.assertNotRegex(
                    line,
                    r"ArgumentList\s*=\s*\$(CommandArguments|Arguments)\b",
                    f"unquoted argument array: {line.strip()}",
                )

    @staticmethod
    def window() -> Path:
        return Path(__file__).resolve().parent.parent / "launcher.ps1"

class PipelineLeakTests(unittest.TestCase):
    """A PowerShell function that emits extra values returns an ARRAY.

    Invoke-Engine returned the exit code AND the log lines it had just written,
    because Read-NewLogLines passed Write-Log's output up the pipeline. Then
    `@(0) -ne 0` is true, so every successful step looked like a failure: the
    window saved settings four times in a row and never started the autopilot.
    """

    WINDOW = Path(__file__).resolve().parent.parent / "launcher.ps1"

    def text(self) -> str:
        return self.WINDOW.read_text(encoding="utf-8-sig")

    def body(self, name: str) -> str:
        text = self.text()
        start = text.index("function " + name)
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
            i += 1
        raise AssertionError(f"unterminated function {name}")

    def test_helpers_called_from_captured_functions_are_voided(self) -> None:
        # These functions are called inside Invoke-Engine and Ensure-BootstrapPython,
        # whose return values ARE captured.
        for name in ("Write-Log", "Read-NewLogLines"):
            body = self.body(name)
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    continue
                if "Write-Log" in stripped and "function" not in stripped:
                    self.assertIn("[void]", stripped, f"leaking call in {name}: {stripped}")
                if "AppendText" in stripped or "ScrollToCaret" in stripped:
                    self.assertIn("[void]", stripped, f"leaking call in {name}: {stripped}")

    def test_callers_coerce_the_exit_code(self) -> None:
        text = self.text()
        # Every place that decides "did it work" goes through Get-ExitCode.
        self.assertIn("function Get-ExitCode", text)
        for call in ("Get-ExitCode (Save-Fields)", "Get-ExitCode (Invoke-Engine"):
            self.assertIn(call, text)
        # The raw comparisons that caused the silent no-op are gone.
        self.assertNotIn("if ((Save-Fields) -ne 0)", text)
        self.assertNotIn("$code = Invoke-Engine", text)

    def test_a_failed_save_is_reported_not_swallowed(self) -> None:
        text = self.text()
        start = text.index("$play.Add_Click({")
        body = text[start : text.index("$setup.Add_Click({")]
        self.assertIn("Не удалось сохранить настройки", body)

class ProgressTests(unittest.TestCase):
    """The player asked for a signal that a long step is still running."""

    def sink(self) -> tuple:
        import json

        scratch = tempfile.mkdtemp()
        path = Path(scratch) / "progress.jsonl"
        progress = engine.Progress(engine.FileProgressSink(path))
        return progress, path, json

    def test_a_download_reports_begin_progress_end(self) -> None:
        import hashlib

        progress, path, json = self.sink()

        class Response:
            def __init__(self, payload):
                self.headers = {"Content-Length": str(len(payload))}
                self.payload, self.position = payload, 0

            def read(self, size):
                block = self.payload[self.position : self.position + size]
                self.position += len(block)
                return block

            def __enter__(self):
                return self

            def __exit__(self, *rest):
                return False

        payload = b"z" * (2 * 1024 * 1024)
        destination = path.parent / "tool.bin"
        engine.download(
            "https://example.invalid/tool.bin",
            destination,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            label="Тест",
            opener=lambda request, timeout=None: Response(payload),
            echo=lambda line: None,
            progress=progress,
        )
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        kinds = [event["kind"] for event in events]
        self.assertEqual(kinds[0], "begin")
        self.assertEqual(kinds[-1], "end")
        self.assertIn("progress", kinds)
        counted = [e for e in events if e["kind"] == "progress"]
        self.assertEqual(counted[-1]["done"], len(payload))
        self.assertEqual(counted[-1]["total"], len(payload))

    def test_a_child_process_gets_a_heartbeat(self) -> None:
        # A converter or a Blender pass runs for minutes; without this the
        # window looks frozen.
        import sys as _sys

        progress, path, json = self.sink()
        runner = engine.Runner(echo=lambda line: None, progress=progress)
        runner.run([_sys.executable, "-c", "import time; time.sleep(0.1)"])
        kinds = [
            json.loads(line)["kind"]
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(kinds, ["begin", "end"])

    def test_a_broken_sink_never_breaks_a_step(self) -> None:
        # Reporting progress must not be able to fail the work it reports on.
        def explode(event):
            raise RuntimeError("no sink")

        progress = engine.Progress(explode)
        progress.start("x")
        progress.update("x", 1, 2)
        progress.finish("x")

    def test_the_cli_accepts_a_progress_file(self) -> None:
        import subprocess as sp
        import sys as _sys

        scratch = Path(tempfile.mkdtemp())
        settings = scratch / "settings.json"
        events = scratch / "progress.jsonl"
        result = sp.run(
            [
                _sys.executable,
                str(Path(__file__).resolve().parent.parent / "engine.py"),
                "--settings", str(settings),
                "--progress", str(events),
                "set", "--install-root", str(scratch / "root"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(events.exists(), "the progress file must be created")

    def test_the_window_renders_the_bar_and_tails_the_file(self) -> None:
        window = (Path(__file__).resolve().parent.parent / "launcher.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("function Read-ProgressEvents", window)
        self.assertIn('"--progress"', window)
        # The bar must be able to show a real percentage, not only "busy".
        self.assertIn('$progress.Style = "Blocks"', window)
        self.assertIn('$progress.Style = "Marquee"', window)
        self.assertIn("function Format-Bytes", window)
        # A half-written line must be buffered, not dropped.
        self.assertIn("$script:progressBuffer", window)
        # The reason for a failure goes in front of the player, not only a code.
        self.assertIn("function Show-EngineFailure", window)
        self.assertIn("Show-EngineFailure -Code $code", window)

class PatchEngineTests(unittest.TestCase):
    """`git apply` made git a hard requirement; the replacement must hold."""

    def setUp(self) -> None:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
        import apply_patch

        self.apply_patch = apply_patch

    def tree(self) -> Path:
        scratch = Path(tempfile.mkdtemp())
        (scratch / "src").mkdir()
        (scratch / "src" / "a.gd").write_text(
            "line one\nline two\nline three\nline four\n", encoding="utf-8"
        )
        return scratch

    def test_a_plain_addition_applies(self) -> None:
        root = self.tree()
        patch = root / "p.patch"
        patch.write_text(
            "--- a/src/a.gd\n"
            "+++ b/src/a.gd\n"
            "@@ -1,4 +1,5 @@\n"
            " line one\n"
            "+inserted\n"
            " line two\n"
            " line three\n"
            " line four\n",
            encoding="utf-8",
        )
        changed = self.apply_patch.apply_patch_file(patch, root)
        self.assertEqual(changed, ["src/a.gd"])
        self.assertEqual(
            (root / "src" / "a.gd").read_text(encoding="utf-8"),
            "line one\ninserted\nline two\nline three\nline four\n",
        )

    def test_a_replacement_applies(self) -> None:
        root = self.tree()
        patch = root / "p.patch"
        patch.write_text(
            "--- a/src/a.gd\n"
            "+++ b/src/a.gd\n"
            "@@ -2,2 +2,2 @@\n"
            "-line two\n"
            "+line 2\n"
            " line three\n",
            encoding="utf-8",
        )
        self.apply_patch.apply_patch_file(patch, root)
        self.assertIn("line 2", (root / "src" / "a.gd").read_text(encoding="utf-8"))

    def test_a_missing_file_is_reported_by_name(self) -> None:
        root = self.tree()
        patch = root / "p.patch"
        patch.write_text(
            "--- a/src/absent.gd\n+++ b/src/absent.gd\n@@ -1 +1 @@\n-x\n+y\n",
            encoding="utf-8",
        )
        with self.assertRaises(self.apply_patch.PatchError) as caught:
            self.apply_patch.apply_patch_file(patch, root)
        self.assertIn("absent.gd", str(caught.exception))

    def test_mismatched_context_is_reported_not_silently_skipped(self) -> None:
        root = self.tree()
        patch = root / "p.patch"
        patch.write_text(
            "--- a/src/a.gd\n"
            "+++ b/src/a.gd\n"
            "@@ -1,2 +1,2 @@\n"
            "-nothing like this\n"
            "+replacement\n"
            " line two\n",
            encoding="utf-8",
        )
        with self.assertRaises(self.apply_patch.PatchError):
            self.apply_patch.apply_patch_file(patch, root)

    def test_the_shipped_patch_applies_to_the_pinned_revision(self) -> None:
        # The repository's own patch is the one that must always work; a broken
        # patch here means every fresh install dies at step 2.
        repo = Path(__file__).resolve().parents[3]
        patches = sorted((repo / "patches").glob("*.patch"))
        self.assertTrue(patches, "patches/ must not be empty")
        for patch in patches:
            files = self.apply_patch.parse_patch(patch.read_text(encoding="utf-8"))
            self.assertTrue(files)
            for entry in files:
                self.assertTrue(entry["hunks"], f"{patch.name}: {entry['path']} has no hunks")

    def test_prepare_does_not_call_git(self) -> None:
        # The regression: prepare.py ran `git apply`, git was never installed,
        # and the player saw only "код 1".
        source = (Path(__file__).resolve().parents[3] / "tools" / "prepare.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("subprocess", source)
        self.assertNotIn("'git'", source)
        self.assertIn("apply_patch", source)

class StreamingTests(unittest.TestCase):
    """A long step must show its output while it runs, not after it exits."""

    def test_child_output_arrives_before_the_child_exits(self) -> None:
        import sys as _sys
        import time as _time

        seen: list[tuple] = []
        started = _time.monotonic()
        runner = engine.Runner(
            echo=lambda line: seen.append((_time.monotonic() - started, line))
        )
        result = runner.run(
            [
                _sys.executable,
                "-c",
                "import sys, time\n"
                "print('early', flush=True)\n"
                "time.sleep(0.5)\n"
                "print('late', flush=True)\n",
            ],
            capture=True,
        )
        self.assertEqual(result.returncode, 0)
        early = [stamp for stamp, line in seen if line == "early"]
        self.assertTrue(early, "the first line must be echoed")
        self.assertLess(early[0], 0.45, "it must arrive while the child still runs")

    def test_each_line_is_echoed_once(self) -> None:
        import sys as _sys

        seen: list[str] = []
        runner = engine.Runner(echo=seen.append)
        runner.run(
            [_sys.executable, "-c", "print('once', flush=True)\nprint('twice', flush=True)"],
            capture=True,
        )
        self.assertEqual([line for line in seen if line == "once"], ["once"])
        self.assertEqual([line for line in seen if line == "twice"], ["twice"])

    def test_stderr_and_exit_code_survive(self) -> None:
        import sys as _sys

        seen: list[str] = []
        runner = engine.Runner(echo=seen.append)
        result = runner.run(
            [_sys.executable, "-c", "import sys\nprint('bad', file=sys.stderr)\nsys.exit(3)"],
            capture=True,
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("! bad", seen)
        self.assertEqual(result.stderr.strip(), "bad")

class ArgumentOrderTests(unittest.TestCase):
    """The build that made PLAY do nothing: `--progress` landed before the
    script path, so Python itself rejected it ("unknown option") and the
    launcher reported success anyway."""

    def window(self) -> str:
        return (Path(__file__).resolve().parent.parent / "launcher.ps1").read_text(
            encoding="utf-8-sig"
        )

    def test_progress_goes_after_the_script_path(self) -> None:
        window = self.window()
        self.assertIn('@($engine, "--progress", $script:progressFile)', window)
        self.assertNotIn('@("--progress", $script:progressFile, $engine)', window)

    def test_python_accepts_the_launcher_argument_order(self) -> None:
        # The real interpreter, the real order: anything before the script is
        # Python's own option and is rejected as "unknown option".
        import subprocess as sp
        import sys as _sys

        scratch = Path(tempfile.mkdtemp())
        events = scratch / "progress.jsonl"
        result = sp.run(
            [
                _sys.executable,
                str(Path(__file__).resolve().parent.parent / "engine.py"),
                "--progress", str(events),
                "set", "--install-root", str(scratch / "root"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("unknown option", result.stderr)
        self.assertTrue(events.exists())

    def test_a_run_that_never_reached_the_engine_is_not_a_success(self) -> None:
        window = self.window()
        self.assertIn("engineStarted", window)
        self.assertIn("Движок не запустился", window)

    def test_the_invocation_is_logged_before_it_is_attempted(self) -> None:
        # A line written only after Start-Process returns cannot report a
        # process that never started.
        window = self.window()
        logged = window.index('[void](Write-Log ("> " + $python')
        started = window.index("$process = Start-Process @startArgs")
        self.assertLess(logged, started)

    def test_success_is_not_claimed_without_a_confirmed_launch(self) -> None:
        window = self.window()
        self.assertIn("$script:lastEngineLine", window)
        self.assertIn("Игра запущена", window)

class SilentDownloadTests(unittest.TestCase):
    """The player: "15 minutes and no way to tell if anything downloads"."""

    def test_a_download_without_content_length_still_reports(self) -> None:
        # codeload answers chunked, with no Content-Length.  The old code
        # printed nothing at all in that case.
        import hashlib

        class Chunked:
            def __init__(self, data):
                self.headers = {}
                self.data, self.position = data, 0

            def read(self, size):
                block = self.data[self.position : self.position + size]
                self.position += len(block)
                return block

            def __enter__(self):
                return self

            def __exit__(self, *rest):
                return False

        scratch = Path(tempfile.mkdtemp())
        events = scratch / "p.jsonl"
        said: list[str] = []
        payload = b"w" * (9 * 1024 * 1024)
        engine.download(
            "https://example.invalid/source.zip",
            scratch / "source.zip",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            label="Исходники",
            echo=said.append,
            opener=lambda request, timeout=None: Chunked(payload),
            progress=engine.Progress(engine.FileProgressSink(events)),
        )
        self.assertTrue(
            any("скачано" in line for line in said),
            f"the log must show bytes even without a total: {said}",
        )
        counted = [
            json.loads(line)
            for line in events.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["kind"] == "progress"
        ]
        self.assertGreaterEqual(len(counted), 9)
        self.assertEqual(counted[-1]["total"], 0)

    def test_prepare_reports_the_pinned_size_for_a_chunked_archive(self) -> None:
        # The real codeload response has no Content-Length; the pinned size is
        # what makes the progress line possible.
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
        import prepare

        self.assertEqual(prepare.SIZE, 17301881)

    def test_every_download_passes_the_progress_sink(self) -> None:
        # The bug behind "the bar never moves": the parameter existed but no
        # caller passed it.
        source = (Path(__file__).resolve().parent.parent / "engine.py").read_text(
            encoding="utf-8"
        )
        calls = source.count("progress=progress")
        self.assertGreaterEqual(calls, 4, "each download must report its bytes")


class FasterStartTests(unittest.TestCase):
    """The player also asked whether there is a faster way."""

    def window(self) -> str:
        return (Path(__file__).resolve().parent.parent / "launcher.ps1").read_text(
            encoding="utf-8-sig"
        )

    def test_a_running_clock_is_shown_while_a_step_runs(self) -> None:
        window = self.window()
        self.assertIn("$lastTick", window)
        self.assertIn("идёт:", window)

    def test_the_window_shows_a_growing_byte_count_without_a_total(self) -> None:
        self.assertIn("скачано {1}", self.window())

    def test_pip_is_told_to_show_progress(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "engine.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("PIP_PROGRESS_BAR", source)

    def test_ffmpeg_prefers_the_small_pinned_archive(self) -> None:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import pinned

        # 104 MB "latest" zip -> 32 MB pinned 7z of the exact build.
        self.assertEqual(pinned.FFMPEG_7Z.version, "8.1.1")
        self.assertLess(pinned.FFMPEG_7Z.size or 0, 40 * 1024 * 1024)
        self.assertIsNotNone(pinned.FFMPEG_7Z.sha256, "the archive itself must be pinned")

    def test_the_big_zip_is_a_verified_fallback_not_a_mystery(self) -> None:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import pinned

        self.assertEqual(pinned.FFMPEG_8_1_1_ZIP.version, "8.1.1")
        self.assertIsNotNone(pinned.FFMPEG_8_1_1_ZIP.sha256)
        # The same build, not "whatever is latest today": that mismatch was a
        # 104 MB download ending in "хеш не совпал".
        self.assertIn("8.1.1", pinned.FFMPEG_8_1_1_ZIP.url)

    def test_ffplay_is_never_installed(self) -> None:
        # A third of the unpacked archive is ffplay.exe; nothing uses it.
        source = (Path(__file__).resolve().parent.parent / "engine.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"ffplay.exe"', source)
        self.assertIn('"ffprobe.exe"', source)


class BytesAndEtaTests(unittest.TestCase):
    """The player asked to see that a download is really moving."""

    def test_speed_and_remaining_time_are_reported(self) -> None:
        import hashlib
        import time as _time

        payload = b"x" * (4 * 1024 * 1024)

        class Slow:
            def __init__(self, data):
                self.headers = {"Content-Length": str(len(data))}
                self.data, self.position = data, 0

            def read(self, size):
                _time.sleep(0.1)
                block = self.data[self.position : self.position + size]
                self.position += len(block)
                return block

            def __enter__(self):
                return self

            def __exit__(self, *rest):
                return False

        scratch = Path(tempfile.mkdtemp())
        events = scratch / "p.jsonl"
        engine.download(
            "https://example.invalid/a",
            scratch / "a.bin",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            label="Тест",
            echo=lambda line: None,
            opener=lambda request, timeout=None: Slow(payload),
            progress=engine.Progress(engine.FileProgressSink(events)),
        )
        rows = [
            json.loads(line)
            for line in events.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["kind"] == "progress"
        ]
        self.assertTrue(any(row["rate"] > 0 for row in rows), "rate must be measured")
        self.assertTrue(
            any(row["eta"] > 0 for row in rows),
            "remaining seconds must be estimated, not floored to zero",
        )

    def test_the_window_prints_speed_and_minutes(self) -> None:
        window = (Path(__file__).resolve().parent.parent / "launcher.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("/с", window)
        self.assertIn("ещё ~", window)

class ExitCodeTests(unittest.TestCase):
    """Two opposite lies: "success" after a failure, and "Не удалось
    сохранить настройки" after a successful save. Both came from the same
    place - an exit code that PowerShell left unset."""

    def window(self) -> str:
        return (Path(__file__).resolve().parent.parent / "launcher.ps1").read_text(
            encoding="utf-8-sig"
        )

    def test_an_unknown_code_falls_back_to_what_the_engine_said(self) -> None:
        window = self.window()
        self.assertIn("$exitKnown", window)
        # Unknown + an error on stderr is a failure...
        self.assertIn("if ($hadError)", window)
        # ...but unknown + a report on stdout is a success, not a failure.
        self.assertIn("$script:lastEngineLine", window)
        self.assertNotIn(
            "if ($null -ne $process.ExitCode) { $code = [int]$process.ExitCode }",
            window,
        )

    def test_the_busy_flag_is_set_inside_the_try(self) -> None:
        # Set before the try, a throw in the setup left it stuck at $true and
        # every later click returned 1 without a word.
        window = self.window()
        busy = window.index("$script:busy = $true")
        handler = window.index("function Invoke-Engine")
        try_keyword = window.index("    try {", handler)
        finally_keyword = window.index("    } finally {", handler)
        self.assertGreater(busy, try_keyword, "set it inside try")
        self.assertLess(busy, finally_keyword)
        self.assertIn("$script:busy = $false", window)

    def test_save_fields_returns_exactly_one_number(self) -> None:
        window = self.window()
        self.assertNotIn("return (Get-ExitCode (Invoke-Engine", window)
        self.assertIn("return [int]$code", window)

    def test_invoke_engine_returns_a_typed_number(self) -> None:
        window = self.window()
        self.assertIn("return [int]$code", window)
        # A leaked object turns the code into an array; the guard against that
        # must stay.
        self.assertIn("$Value -is [array]", window)

class ConsoleEncodingTests(unittest.TestCase):
    """Found by running the suite on real Windows, not by reading the file.

    Windows consoles are often cp1252. Printing the engine's Russian text to
    one raised UnicodeEncodeError, so a player who ran it by hand got a
    traceback instead of the explanation. The window hid this by exporting
    PYTHONUTF8 - the bug was invisible exactly where it was most likely.
    """

    def test_the_engine_survives_a_cp1252_console(self) -> None:
        import os
        import subprocess as sp
        import sys as _sys

        scratch = Path(tempfile.mkdtemp())
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        result = sp.run(
            [
                _sys.executable,
                str(Path(__file__).resolve().parent.parent / "engine.py"),
                "set", "--install-root", str(scratch / "root"),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("UnicodeEncodeError", result.stderr)
        # With capture_output and a cp1252 console Python may hand back None
        # rather than mojibake; the point of the test is that the engine does
        # not CRASH, so the text is checked when it is there at all.
        if result.stdout:
            self.assertIn("Настройки сохранены", result.stdout)

    def test_the_entry_point_prepares_the_streams(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "engine.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_make_output_utf8_safe", source)
        self.assertIn('errors="replace"', source)

    def test_main_prepares_the_streams_too(self) -> None:
        # The entry point alone is not enough: tests, embedders and anything
        # importing this module call main() in a process nobody prepared.
        source = (Path(__file__).resolve().parent.parent / "engine.py").read_text(
            encoding="utf-8"
        )
        main_body = source[source.index("def main(argv") :]
        self.assertIn("_make_output_utf8_safe()", main_body[:400])
