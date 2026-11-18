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
from pathlib import Path
import sys
import tempfile
import unittest
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


def make_source(root: Path) -> Path:
    tree = engine.source_tree(root)
    (tree / "game").mkdir(parents=True, exist_ok=True)
    (tree / "game" / "project.godot").write_text("[application]\n", encoding="utf-8")
    (tree / "tools").mkdir(parents=True, exist_ok=True)
    (tree / "tools" / "openbfme_import.py").write_text("", encoding="utf-8")
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
        self.assertEqual((self.root / "out" / "dir" / "tool.exe").read_text(), "binary")


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
            engine.step_prepare(engine.Settings(install_root=self.root), Recorder(), echo=lambda _l: None)
        self.assertEqual(caught.exception.code, engine.EXIT_STATE)
        self.assertTrue(tree.is_dir())

    def test_assembled_tree_is_reused_without_running_anything(self) -> None:
        make_source(self.root)
        recorder = Recorder()
        engine.step_prepare(engine.Settings(install_root=self.root), recorder, echo=lambda _l: None)
        self.assertEqual(recorder.commands, [])


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

        settings.patch202_root = self.root / "nothing-here"
        plan = engine.first_run_plan(settings)
        self.assertIn("convert", plan)
        self.assertNotIn("full", plan)

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
