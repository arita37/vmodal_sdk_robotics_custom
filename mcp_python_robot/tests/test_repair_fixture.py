"""Length-aware fixture and actual repair/validator regressions, no network."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/vmodal-robot-telemetry-repair"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("make_corrupt", SKILL / "tests/make_corrupt.py")
repair = load("telemetry_repair", SKILL / "scripts/telemetry_repair.py")


class RepairFixtureTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / "data/robot/xarm6_gripper_100hz.format.json").read_text())
        for field in self.spec["fields"]:
            if field["name"] == "current":
                field["range"] = [-10, 10]  # isolate mechanical repairs from the planted 9 A spike
        self.frames = json.loads((ROOT / "data/robot/ep_demo1/frame_map.json").read_text())[:2]
        self.args = SimpleNamespace(max_nan_run=5, max_interp_ms=150, clamp_tol=.02, no_quat_continuity=False)
        self.header, self.demo = fixture.read_episode(ROOT / "data/robot/ep_demo1")

    def test_lengths_and_actual_repair(self):
        for length in (80, 81, 100, 201, 520, 1000):
            with self.subTest(length=length):
                rows = [dict(copy.deepcopy(self.demo[0]), t_ns=self.demo[0]["t_ns"] + i * 10_000_000) for i in range(length)]
                original = copy.deepcopy(rows)
                for broken in (False, True):
                    damaged = fixture.corrupt(rows, broken)
                    self.assertEqual(rows, original)
                    unique = sorted({r["t_ns"] for r in damaged})
                    self.assertEqual(max(b - a for a, b in zip(unique, unique[1:])), 310_000_000 if broken else 70_000_000)
                    fixed, ops, unresolved = repair.repair(self.spec, self.header, [json.dumps(r) for r in damaged], self.args)
                    verdict, errors, _ = repair.check(self.spec, self.header, fixed, self.frames)
                    if broken:
                        self.assertEqual(verdict, "reject")
                        self.assertEqual(len(unresolved), 2)
                        self.assertTrue(any("20 consecutive" in item for item in unresolved))
                        self.assertTrue(any("310.0 ms" in item for item in unresolved))
                        self.assertEqual(ops, {})
                    else:
                        self.assertEqual(verdict, "pass", errors)
                        self.assertEqual(unresolved, [])
                        self.assertEqual(len(fixed), length)
                        self.assertEqual(ops["dropped_duplicate_timestamps"], 5)
                        self.assertTrue(any("quat" in key for key in ops))

    def test_reject_small_input_before_output(self):
        for length in (0, 1, 20, 79):
            with self.subTest(length=length), tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / "short"
                source.mkdir()
                (source / "telemetry.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [self.header] + self.demo[:length]))
                with self.assertRaisesRegex(ValueError, "at least 80"):
                    fixture.main(temp, Path(temp) / "out", "short")
                self.assertFalse((Path(temp) / "out").exists())

    def test_headerless_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp)
            (src / "telemetry.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.demo))
            header, rows = fixture.read_episode(src)
            self.assertIsNone(header)
            self.assertEqual(len(rows), 201)
            self.assertEqual(json.dumps(fixture.corrupt(rows)), json.dumps(fixture.corrupt(rows)))

    def test_reject_wrong_rate(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp)
            rows = copy.deepcopy(self.demo)
            rows[5]["t_ns"] += 1
            (src / "telemetry.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            with self.assertRaisesRegex(ValueError, "uniform 100 Hz"):
                fixture.read_episode(src)

    def test_bundled_cli_and_repair(self):
        source = ROOT / "data/robot"
        before = (source / "ep_demo1/telemetry.jsonl").read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            damaged, fixed = Path(temp) / "damaged", Path(temp) / "fixed"
            subprocess.run([sys.executable, str(SKILL / "tests/make_corrupt.py"), str(source), str(damaged), "ep_demo1", "ep_demo2"], check=True)
            records = [json.loads(line) for line in (damaged / "ep_demo1_corrupt/telemetry.jsonl").read_text().splitlines()]
            self.assertEqual(records[0]["episode_uid"], "ep_demo1_corrupt")
            self.assertEqual(len(records), 201)  # header + 201 - 6 + 5
            spec_path = Path(temp) / "fixture_spec.json"
            spec_path.write_text(json.dumps(self.spec))
            result = subprocess.run([sys.executable, str(SKILL / "scripts/telemetry_repair.py"), str(damaged), str(fixed), "--spec", str(spec_path)], check=False)
            self.assertEqual(result.returncode, 1)  # broken episode intentionally rejects
            report = json.loads((fixed / "repair_report.json").read_text())
            self.assertEqual([r["after"] for r in report], ["pass", "reject"])
            self.assertEqual([len(r["unrepaired"]) for r in report], [0, 2])
        self.assertEqual((source / "ep_demo1/telemetry.jsonl").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
