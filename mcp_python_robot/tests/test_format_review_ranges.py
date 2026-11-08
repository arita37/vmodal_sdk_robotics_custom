"""Offline regressions for issue 3: sample extrema are not physical limits."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/vmodal-robot-format-review/scripts/format_review.py'
spec = importlib.util.spec_from_file_location('format_review_ranges', SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class RangeReviewTests(unittest.TestCase):
    def test_constant_joint_needs_physical_limits(self):
        for values in (np.full((20, 6), .1), np.tile(np.arange(6), (20, 1)),
                       np.array([[.1], [.10000001]])):
            proposal, reason = review.range_proposal({'name': 'q', 'unit': 'rad'}, values, [])
            self.assertIsNone(proposal)
            self.assertIn('constant', reason)

    def test_declared_header_limits_preferred_over_samples(self):
        field = {'name': 'q', 'unit': 'rad', 'shape': [6]}
        header = {'fields': [dict(field, range=[-2, 3])]}
        proposal, reason = review.range_proposal(field, np.full((20, 6), .1), [header])
        self.assertEqual(proposal, [-2, 3])
        self.assertIn('human review', reason)

    def test_conflicting_or_incompatible_headers_left_open(self):
        field = {'name': 'q', 'unit': 'rad', 'shape': [6]}
        good = {'fields': [dict(field, range=[-2, 3])]}
        for overrides in ({'range': [-3, 3]}, {'unit': 'deg'}, {'shape': [7]},
                          {'range': [.1, .1]}, {'range': [float('-inf'), 3]}):
            bad = {'fields': [dict(field, range=[-2, 3]) | overrides]}
            self.assertIsNone(review.range_proposal(field, np.full((20, 6), .1), [good, bad])[0])

    def test_normalized_gripper_has_no_margin(self):
        for name in ('gripper', 'cmd_gripper'):
            for unit in ('0_open_1_closed', '0_closed_1_open', 'normalized_grip_pos_0_open'):
                field = {'name': name, 'unit': unit}
                for values in (np.array([[0.], [1.]]), np.array([[.1], [.1]])):
                    self.assertEqual(review.range_proposal(field, values, [])[0], [0, 1])
        self.assertIsNone(review.range_proposal({'name': 'gripper', 'unit': '?'}, np.ones((2, 1)), [])[0])

    def test_narrow_sample_ranges_never_collapse_or_exclude_observations(self):
        for lo, hi in ((.1, .100002), (.100002, .2), (-.100002, -.1),
                       (-.000002, .000002), (1.234567, 1.234569)):
            with self.subTest(lo=lo, hi=hi):
                proposal, _ = review.range_proposal(
                    {'name': 'q', 'unit': 'rad'}, np.array([[lo], [hi]]), [])
                self.assertIsNotNone(proposal)
                self.assertLess(proposal[0], proposal[1])
                self.assertLessEqual(proposal[0], lo)
                self.assertGreaterEqual(proposal[1], hi)
        # Overflow in the margin calculation must not create non-finite limits.
        bounds = review.nice_range(-1e308, 1e308)
        self.assertEqual(bounds, [-1e308, 1e308])

    def test_moving_unbounded_field_stays_sample_based(self):
        proposal, reason = review.range_proposal({'name': 'q', 'unit': 'rad'}, np.array([[0.], [1.]]), [])
        self.assertEqual(proposal, [-.1, 1.1])
        self.assertIn('not verified', reason)

    def test_draft_and_report_are_deterministic_and_preserve_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            episode = root / 'episodes' / 'still'
            episode.mkdir(parents=True)
            fields = [
                {'name': 'q', 'unit': 'rad', 'shape': [2], 'range': '?'},
                {'name': 'cmd_q', 'unit': 'rad', 'shape': [2], 'range': '?', 'role': 'command'},
                {'name': 'gripper', 'unit': '0_open_1_closed', 'shape': [], 'range': '?'},
                {'name': 'current', 'unit': 'A', 'shape': [], 'range': [-5, 5]},
            ]
            header = {'fields': [dict(fields[0], range=[-2, 2])]}
            rows = [dict(t_ns=i * 10_000_000, q=[.1, .1], cmd_q=[.1, .1], gripper=1.1, current=.3) for i in range(20)]
            (episode / 'telemetry.jsonl').write_text('\n'.join(json.dumps(r) for r in [header] + rows))
            source = {'format_id': 'test', 'format_version': 1, 'checked_by': 'reviewer',
                      'fields': fields, 'sampling': {'rate_hz': 100, 'rate_tol_pct': 3, 'max_gap_ms': 20}}
            (root / 'spec.json').write_text(json.dumps(source))
            args = SimpleNamespace(spec=root / 'spec.json', episodes_dir=root / 'episodes', out_dir=root / 'out')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(review.main(args), 1)  # gripper is outside physical bounds
                before = {p.name: p.read_bytes() for p in args.out_dir.iterdir()}
                review.main(args)
            self.assertEqual(before, {p.name: p.read_bytes() for p in args.out_dir.iterdir()})
            draft = json.loads((args.out_dir / 'test.v2.draft.json').read_text())
            result = {f['name']: f for f in draft['fields']}
            self.assertEqual(result['q']['range'], [-2, 2])
            self.assertEqual(result['cmd_q']['range'], '?')
            self.assertEqual(result['gripper']['range'], [0, 1])
            self.assertEqual(result['current']['range'], [-5, 5])
            self.assertEqual(draft['checked_by'], '?')
            self.assertIn('outside proposed declared limits', (args.out_dir / 'format_review.md').read_text())

    def test_skill_copies_match(self):
        self.assertEqual(SCRIPT.read_bytes(), (ROOT / '.claude/skills/vmodal-robot-format-review/scripts/format_review.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
