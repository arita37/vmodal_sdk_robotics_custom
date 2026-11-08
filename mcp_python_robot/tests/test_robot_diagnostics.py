"""Deterministic diagnostics for the intentionally defective bundled episodes."""
import asyncio
import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.mcp_server.robot import robot_episode_upload
from src.mcp_server.robot_diagnostics import current_warnings, metadata_start_time_warnings
from src.mcp_server.robot_format import update_json_format_specs_from_file
from src.mcp_server.utils import os_json_read, os_json_write, os_rows_read

DATA = Path(__file__).resolve().parents[1] / "data" / "robot"


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.spec = os_json_read(DATA / "xarm6_gripper_100hz.format.json")
        _, self.rows = os_rows_read(DATA / "ep_demo1" / "telemetry.jsonl")
        self.meta = os_json_read(DATA / "meta" / "ep_demo1.json")

    def test_original_sample_and_old_registry(self):
        for old in (False, True):
            with self.subTest(old_registry=old), tempfile.TemporaryDirectory() as tmp:
                spec = copy.deepcopy(self.spec)
                if old:
                    next(f for f in spec['fields'] if f['name'] == 'current').pop('range')
                path = os_json_write(Path(tmp) / 'format.json', spec)
                cfg = SimpleNamespace(robot_dir=str(Path(tmp) / 'store'), upload_max_mb=5120)
                update_json_format_specs_from_file(cfg, path, 'demo')
                client = SimpleNamespace(collections=SimpleNamespace(video_upload=AsyncMock(), upload_metadata_jsonl=AsyncMock()))
                out = asyncio.run(robot_episode_upload(cfg, 'demo', 'ep_demo1',
                    str(DATA / 'ep_demo1' / 'cam_scene.mp4'), str(DATA / 'ep_demo1' / 'telemetry.jsonl'),
                    str(DATA / 'ep_demo1' / 'frame_map.json'), str(DATA / 'meta' / 'ep_demo1.json'),
                    'r1', dry_run=True, client=client))
                report = out['check_report']
                self.assertTrue(any('meta.start_time: differs' in w for w in report['warnings']))
                self.assertTrue(any('current j2' in w and '[50]' in w for w in report['warnings']))
                if old:
                    self.assertTrue(any('no configured range' in w for w in report['warnings']))
                else:
                    self.assertEqual('rejected', out['status'])
                    self.assertIn('row 50 current: outside range', report['errors'])
                client.collections.video_upload.assert_not_awaited()
                client.collections.upload_metadata_jsonl.assert_not_awaited()

    def test_start_time_semantics(self):
        rows = [{'t_ns': 1735689600000000000}]
        check = lambda value: metadata_start_time_warnings(self.spec, rows, {'start_time': value})
        for value in ('2025-01-01T00:00:00Z', '2025-01-01T01:00:00+01:00', '2024-12-31T19:00:00-05:00', '2025-01-01T00:00:01Z'):
            self.assertEqual([], check(value))
        for value in ('2026-01-01T00:00:00Z', '2024-01-01T00:00:00Z', '2025-01-01T00:00:01.001Z'):
            self.assertIn('differs', check(value)[0])
        for value in ('2025-01-01', '2025-01-01T00:00:00', 'not a date', 123, None):
            self.assertTrue(check(value))
        for base in ('relative', 'monotonic', 'device', 'unknown'):
            spec = copy.deepcopy(self.spec)
            spec['time']['time_base'] = base
            warning = metadata_start_time_warnings(spec, rows, {'start_time': '2025-01-01T00:00:00Z'})
            self.assertIn('comparison skipped', warning[0])
        self.assertTrue(metadata_start_time_warnings(self.spec, [], self.meta))
        self.assertTrue(metadata_start_time_warnings(self.spec, [{'t_ns': True}], self.meta))

    def test_current_no_universal_limit(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row['current'] = [100.0] * 6
        self.assertEqual([], current_warnings(self.spec, rows))
        rows[50]['current'][1] = 3000.0
        self.assertTrue(any('current j2' in w for w in current_warnings(self.spec, rows)))
        rows[50]['current'][1] = float('nan')
        self.assertEqual([], current_warnings(self.spec, rows))
        self.assertEqual([], current_warnings(self.spec, rows[:3]))


if __name__ == '__main__':
    unittest.main()
