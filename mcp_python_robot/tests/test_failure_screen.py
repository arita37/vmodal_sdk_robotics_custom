"""Offline regressions for the outcome screen and bundled failure fixtures."""
import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/vmodal-robot-failure-screen/scripts/failure_screen.py'
spec = importlib.util.spec_from_file_location('failure_screen', SCRIPT)
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)


class FailureScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.episodes = self.root / 'episodes'
        self.episodes.mkdir()

    def episode(self, uid, state, cmd=None, invert=False):
        ep = self.episodes / uid
        ep.mkdir()
        if cmd is None:
            cmd = [0.] * 10 + [1.] * (len(state) - 10)
        rows = [{'t_ns': i * 10_000_000, 'gripper': 1 - s if invert else s,
                 'cmd_gripper': c, 'ee_pos': [i * .001, 0, 0]}
                for i, (s, c) in enumerate(zip(state, cmd))]
        (ep / 'telemetry.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        (ep / 'meta.json').write_text('{"success": true}')
        (ep / 'frame_map.json').write_text(json.dumps(list(range(60))))
        return ep

    def run_screen(self, **thresholds):
        cfg = self.root / 'thresholds.json'
        cfg.write_text(json.dumps(thresholds))
        out = self.root / 'out'
        with contextlib.redirect_stdout(io.StringIO()):
            screen.cmd_screen(SimpleNamespace(episodes_dir=self.episodes, out_dir=out,
                                             thresholds=cfg, no_sheets=True))
        return json.loads((out / 'candidates.json').read_text())

    @staticmethod
    def rules(result, uid):
        return {c['rule'] for c in result['candidates'] if c['episode_uid'] == uid}

    def test_demo_defects_and_review_safety(self):
        for uid in ('ep_demo1', 'ep_demo2'):
            shutil.copytree(ROOT / 'data/robot' / uid, self.episodes / uid)
            self.assertEqual(json.loads((self.episodes / uid / 'meta.json').read_text()),
                             json.loads((ROOT / 'data/robot/meta' / (uid + '.json')).read_text()))
        result = self.run_screen()
        self.assertTrue({'closed_further_than_peers', 'opens_while_commanded_closed'} <= self.rules(result, 'ep_demo1'))
        self.assertNotIn('gripper_did_not_close', self.rules(result, 'ep_demo2'))
        for candidate in result['candidates']:
            self.assertEqual(candidate['source'], 'auto')
            self.assertEqual(candidate['review_status'], 'unreviewed')
        with (self.root / 'out/review_sheet.csv').open() as fh:
            self.assertTrue(all(not row['decision'] for row in csv.DictReader(fh)))
        # Deliberate date mismatch and current spike must not be sanitized.
        self.assertEqual(json.loads((self.episodes / 'ep_demo1/meta.json').read_text())['start_time'], '2026-10-22T10:00:00Z')

    def test_peer_counts_and_zero_mad(self):
        for count in (1, 2, 3, 5):
            with self.subTest(episodes=count):
                for p in self.episodes.iterdir():
                    shutil.rmtree(p)
                self.episode('miss', [0.] * 15 + [.99] * 186)
                for i in range(count - 1):
                    self.episode(f'peer{i}', [.5] * 201, [1.] * 201)
                result = self.run_screen()
                self.assertEqual('closed_further_than_peers' in self.rules(result, 'miss'), count >= 2)
                for i in range(count - 1):
                    self.assertNotIn('closed_further_than_peers', self.rules(result, f'peer{i}'))

    def test_both_polarities_and_initial_holding(self):
        for invert in (False, True):
            with self.subTest(invert=invert):
                for p in self.episodes.iterdir():
                    shutil.rmtree(p)
                self.episode('drop', [0.] * 15 + [.99] * 65 + [.7] * 121, invert=invert)
                self.episode('holding', [.5] * 201, [1.] * 201, invert=invert)
                self.episode('stuck', [0.] * 201, invert=invert)
                result = self.run_screen()
                self.assertIn('opens_while_commanded_closed', self.rules(result, 'drop'))
                self.assertIn('closed_further_than_peers', self.rules(result, 'drop'))
                self.assertNotIn('gripper_did_not_close', self.rules(result, 'holding'))
                self.assertIn('gripper_did_not_close', self.rules(result, 'stuck'))

    def test_unknown_polarity_and_explicit_override(self):
        self.episode('holding', [.5] * 201, [1.] * 201)
        self.episode('stuck', [.0] * 201)
        result = self.run_screen()
        self.assertIn('unknown', result['gripper_polarity'])
        self.assertNotIn('gripper_did_not_close', self.rules(result, 'stuck'))
        result = self.run_screen(state_polarity=1)
        self.assertIn('gripper_did_not_close', self.rules(result, 'stuck'))
        self.assertNotIn('gripper_did_not_close', self.rules(result, 'holding'))
        with self.assertRaises(SystemExit):
            self.run_screen(state_polarity=2)

    def test_no_close_command_and_empty_directory(self):
        with self.assertRaisesRegex(SystemExit, 'no episodes'):
            self.run_screen()
        self.episode('open', [0.] * 201, [0.] * 201)
        self.assertIn('no_close_command', self.rules(self.run_screen(), 'open'))

    def test_normal_release_noise_and_regrasp_do_not_flag_drop(self):
        self.episode('release', [0.] * 15 + [.6] * 85 + [0.] * 101,
                     [0.] * 10 + [1.] * 90 + [0.] * 101)
        self.episode('noise', [0.] * 15 + [.6] * 65 + [.2] + [.6] * 120)
        self.episode('spike', [0.] * 15 + [.6] * 65 + [.99] + [.6] * 120)
        self.episode('regrasp', [0.] * 15 + [.8] * 65 + [0.] * 30 + [.5] * 91,
                     [0.] * 10 + [1.] * 70 + [0.] * 25 + [1.] * 96)
        result = self.run_screen()
        for uid in ('release', 'noise', 'spike', 'regrasp'):
            self.assertNotIn('opens_while_commanded_closed', self.rules(result, uid))

    def test_initial_hold_drop_requires_known_polarity(self):
        self.episode('drop', [.8] * 80 + [.5] * 121, [1.] * 201)
        self.assertNotIn('opens_while_commanded_closed', self.rules(self.run_screen(), 'drop'))
        result = self.run_screen(state_polarity=1)
        self.assertIn('opens_while_commanded_closed', self.rules(result, 'drop'))
        self.assertNotIn('gripper_did_not_close', self.rules(result, 'drop'))
        opening = next(c for c in result['candidates'] if c['rule'] == 'opens_while_commanded_closed')
        self.assertLessEqual(opening['t_start_ns'], 800_000_000)
        self.assertGreaterEqual(opening['t_end_ns'], 900_000_000)

    def test_peer_spread_limits_comparisons(self):
        for i, width in enumerate((.3, .5, .7, .9)):
            self.episode(f'peer{i}', [0.] * 15 + [width] * 186)
        self.assertFalse(any(c['rule'] == 'closed_further_than_peers' for c in self.run_screen()['candidates']))

    def test_equal_peers_do_not_flag_empty_grasp(self):
        for i in range(5):
            self.episode(f'peer{i}', [0.] * 15 + [.6] * 186)
        self.assertFalse(any(c['rule'] == 'closed_further_than_peers' for c in self.run_screen()['candidates']))

    def test_skill_script_copies_match(self):
        self.assertEqual(SCRIPT.read_bytes(), (ROOT / '.claude/skills/vmodal-robot-failure-screen/scripts/failure_screen.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
