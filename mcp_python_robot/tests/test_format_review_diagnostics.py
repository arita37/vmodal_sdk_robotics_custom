"""Issue 12: findings and unresolved counts must not depend on assistant runs."""
import contextlib
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/vmodal-robot-format-review/scripts/format_review.py'
module_spec = importlib.util.spec_from_file_location('format_review_diagnostics', SCRIPT)
review = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(review)


def placeholders(value):
    if isinstance(value, dict):
        return sum(placeholders(v) for v in value.values())
    if isinstance(value, list):
        return sum(placeholders(v) for v in value)
    return int(value == '?')


class RepeatableReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.episode = self.root / 'episodes' / 'ep_demo1'
        self.episode.mkdir(parents=True)
        self.spec = json.loads((ROOT / 'data/robot/xarm6_gripper_100hz.format.json').read_text())
        self.rows = review.load_rows(ROOT / 'data/robot/ep_demo1/telemetry.jsonl')
        self.meta = json.loads((ROOT / 'data/robot/meta/ep_demo1.json').read_text())
        self.current = next(f for f in self.spec['fields'] if f['name'] == 'current')
        self.current['range'] = '?'
        self.spec['video_align']['on_fail'] = '?'

    def run_review(self, meta_layout='local'):
        (self.root / 'spec.json').write_text(json.dumps(self.spec))
        (self.episode / 'telemetry.jsonl').write_text('\n'.join(json.dumps(r) for r in self.rows))
        if meta_layout == 'local':
            (self.episode / 'meta.json').write_text(json.dumps(self.meta))
        elif meta_layout == 'sibling':
            path = self.episode.parent / 'meta'
            path.mkdir(exist_ok=True)
            (path / 'ep_demo1.json').write_text(json.dumps(self.meta))
        args = SimpleNamespace(spec=self.root / 'spec.json', episodes_dir=self.episode.parent,
                               out_dir=self.root / 'out')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = review.main(args)
        files = {p.name: p.read_bytes() for p in args.out_dir.iterdir()}
        report = files['format_review.md'].decode()
        draft = json.loads(next(v for k, v in files.items() if k.endswith('.json')))
        return files, stdout.getvalue(), status, report, draft

    def test_planted_fixture_is_repeatable_and_current_range_stays_open(self):
        first = self.run_review('sibling')
        second = self.run_review('sibling')
        self.assertEqual(first, second)  # report, JSON, stdout and status, byte for byte
        _, stdout, _, report, draft = first
        self.assertIn('current j2: isolated statistical outlier at rows [50]', report)
        self.assertIn('meta.start_time: differs', report)
        self.assertIn('31533195.998800 s', report)
        self.assertIn('range left unresolved; observed [0.1, 9]', report)
        self.assertIn('physical current limits have not been validated', report)
        self.assertIn('outliers must not widen the range', report)
        self.assertEqual('?', next(f for f in draft['fields'] if f['name'] == 'current')['range'])
        total = placeholders(draft)
        self.assertIn(f'{total} total', report)
        self.assertIn(f'{total - 2} unresolved data/policy values', report)
        self.assertIn('2 required human sign-off values (checked_at, checked_by)', report)
        self.assertIn('fields[1].range', report)
        self.assertIn('video_align.on_fail', stdout)

    def test_clean_episode_has_no_false_anomaly_or_metadata_discrepancy(self):
        self.current['range'] = [-2, 2]
        for row in self.rows:
            row['current'] = [.1, .3, .1, .1, .1, .1]
        self.meta['start_time'] = datetime.fromtimestamp(self.rows[0]['t_ns'] / 1e9, timezone.utc).isoformat()
        self.spec['video_align']['on_fail'] = 'warn'
        _, _, _, report, draft = self.run_review()
        self.assertNotIn('isolated statistical outlier', report)
        self.assertNotIn('meta.start_time:', report)
        self.assertIn('2 total', report)
        self.assertIn('0 unresolved data/policy values (none)', report)
        self.assertEqual(2, placeholders(draft))

    def test_ambiguous_clock_is_not_inferred_from_large_timestamps(self):
        for clock in ('?', 'relative', 'device'):
            self.spec['time']['time_base'] = clock
            report = self.run_review()[3]
            self.assertIn('comparison skipped; telemetry clock is not a declared UTC/Unix clock', report)
            self.assertNotIn('meta.start_time: differs', report)

    def test_missing_or_invalid_metadata_is_honestly_reported(self):
        self.assertIn('metadata unavailable', self.run_review('missing')[3])
        self.meta = []
        self.assertIn('metadata unreadable or not an object', self.run_review()[3])
        self.meta = {'start_time': '2026-01-01T00:00:00'}
        self.assertIn('timezone-aware ISO datetime required', self.run_review()[3])

    def test_current_is_not_a_universal_or_sample_inferred_limit(self):
        values = np.array([[.1], [.3], [.2], [9.], [.2], [.1]])
        for values in (values, values * 1000):
            self.assertIsNone(review.range_proposal(self.current, values, [])[0])
        header = {'fields': [dict(self.current, range=[-3, 3])]}
        self.assertEqual([-3, 3], review.range_proposal(self.current, values, [header])[0])

    def test_declared_limits_preserved_but_spike_still_warns(self):
        self.current['range'] = [-10, 10]
        report, draft = self.run_review()[3:]
        self.assertIn('isolated statistical outlier at rows [50]', report)
        self.assertEqual([-10, 10], next(f for f in draft['fields'] if f['name'] == 'current')['range'])

    def test_cli_copies_are_identical_across_output_directories(self):
        expected = self.run_review()[0]
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        for layout in ('skills', '.claude/skills'):
            out = self.root / layout
            result = subprocess.run([sys.executable,
                str(ROOT / layout / 'vmodal-robot-format-review/scripts/format_review.py'),
                str(self.root / 'spec.json'), str(self.episode.parent), str(out)],
                cwd=self.root, env=env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('isolated statistical outlier at rows [50]', result.stdout)
            self.assertEqual(expected, {p.name: p.read_bytes() for p in out.iterdir()})

    def test_installed_skill_matches_canonical(self):
        for name in ('SKILL.md', 'scripts/format_review.py'):
            self.assertEqual((ROOT / 'skills/vmodal-robot-format-review' / name).read_bytes(),
                             (ROOT / '.claude/skills/vmodal-robot-format-review' / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
