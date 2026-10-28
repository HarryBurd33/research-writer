#!/usr/bin/env python3
"""Deterministic checks for phase-5 fixtures; does not run or grade an LLM."""

import copy
import importlib.util
import itertools
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "workflow" / "reproduce_quantitative.py"
SPEC = importlib.util.spec_from_file_location("workflow_quantitative_fixture", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PACKET = json.loads((ROOT / "workflow" / "inputs.json").read_text(encoding="utf-8"))
ROWS = next(case["source_packet"] for case in PACKET["cases"]
            if case["id"] == "P5-02-quantitative")


class WorkflowChecks(unittest.TestCase):
    def test_independent_frozen_reference(self):
        # Expected values were frozen by an independent evaluator before either
        # arm's outputs or this implementation existed; not computed by MODULE.
        result = MODULE.synthesize_reports(ROWS)
        self.assertEqual((result["reports"], result["independent_families"]), (4, 3))
        self.assertAlmostEqual(result["effect_seconds_saved"], 1.7777777777777777)
        self.assertAlmostEqual(result["standard_error"], 0.6666666666666666)
        for actual, expected in zip(result["ci95"], [0.4711351214177417, 3.0844204341378134]):
            self.assertAlmostEqual(actual, expected)

    def test_all_permutations(self):
        expected = MODULE.synthesize_reports(ROWS)
        for permutation in itertools.permutations(ROWS):
            self.assertEqual(MODULE.synthesize_reports(list(permutation)), expected)

    def test_constant_effect_shift(self):
        shifted = copy.deepcopy(ROWS)
        for row in shifted:
            row["effect_seconds_saved"] += 13.5
        a, b = MODULE.synthesize_reports(ROWS), MODULE.synthesize_reports(shifted)
        self.assertAlmostEqual(b["effect_seconds_saved"], a["effect_seconds_saved"] + 13.5)
        self.assertEqual(b["standard_error"], a["standard_error"])
        for x, y in zip(a["ci95"], b["ci95"]):
            self.assertAlmostEqual(y, x + 13.5)

    def test_uniform_standard_error_scaling(self):
        scaled = copy.deepcopy(ROWS)
        for row in scaled:
            row["standard_error"] *= 3
        a, b = MODULE.synthesize_reports(ROWS), MODULE.synthesize_reports(scaled)
        self.assertAlmostEqual(b["effect_seconds_saved"], a["effect_seconds_saved"])
        self.assertAlmostEqual(b["standard_error"], a["standard_error"] * 3)

    def test_exact_duplicate_family_once(self):
        result = MODULE.synthesize_reports(ROWS)
        decision = next(d for d in result["study_family_decisions"] if d["family"] == "F2")
        self.assertEqual(decision, {"family": "F2", "included_report": "S2",
                                    "excluded_exact_duplicates": ["S2b"]})
        without_duplicate = MODULE.synthesize_reports([r for r in ROWS if r["id"] != "S2b"])
        self.assertEqual(result["effect_seconds_saved"], without_duplicate["effect_seconds_saved"])
        self.assertEqual(result["standard_error"], without_duplicate["standard_error"])

    def test_family_conflicting_effect_refused(self):
        altered = copy.deepcopy(ROWS)
        altered[2]["effect_seconds_saved"] = 4.01
        with self.assertRaisesRegex(ValueError, "conflicting"):
            MODULE.synthesize_reports(altered)

    def test_family_conflicting_uncertainty_refused(self):
        altered = copy.deepcopy(ROWS)
        altered[2]["standard_error"] = 3
        with self.assertRaisesRegex(ValueError, "conflicting"):
            MODULE.synthesize_reports(altered)

    def test_missing_standard_error_refused(self):
        altered = copy.deepcopy(ROWS)
        del altered[0]["standard_error"]
        with self.assertRaises(ValueError):
            MODULE.synthesize_reports(altered)

    def test_invalid_standard_errors_refused(self):
        for invalid in [0, -1, float("inf"), float("-inf"), float("nan"), None, True, "1"]:
            with self.subTest(value=invalid):
                altered = copy.deepcopy(ROWS)
                altered[0]["standard_error"] = invalid
                with self.assertRaises(ValueError):
                    MODULE.synthesize_reports(altered)

    def test_invalid_effects_refused(self):
        for invalid in [float("inf"), float("-inf"), float("nan"), None, True, "2"]:
            with self.subTest(value=invalid):
                altered = copy.deepcopy(ROWS)
                altered[0]["effect_seconds_saved"] = invalid
                with self.assertRaises(ValueError):
                    MODULE.synthesize_reports(altered)

    def test_zero_and_negative_effects_valid(self):
        for effect in [0, -2]:
            rows = [{"id": "zero", "family": "one", "effect_seconds_saved": effect,
                     "standard_error": 1}]
            self.assertEqual(MODULE.synthesize_reports(rows)["effect_seconds_saved"], effect)

    def test_invalid_report_identity_refused(self):
        for field in ["id", "family"]:
            for invalid in [None, "", "   ", 1]:
                altered = copy.deepcopy(ROWS)
                altered[0][field] = invalid
                with self.assertRaises(ValueError):
                    MODULE.synthesize_reports(altered)
        altered = copy.deepcopy(ROWS)
        altered[1]["id"] = altered[0]["id"]
        with self.assertRaisesRegex(ValueError, "duplicate report id"):
            MODULE.synthesize_reports(altered)

    def test_report_bounds(self):
        for invalid in [[], None, {}, [ROWS[0]] * 101, ["not a report"]]:
            with self.assertRaises(ValueError):
                MODULE.synthesize_reports(invalid)

    def test_numerical_range_refused(self):
        for se in [1e-300, 1e300]:
            with self.assertRaises(ValueError):
                MODULE.synthesize_reports([{"id": "x", "family": "x",
                                            "effect_seconds_saved": 1, "standard_error": se}])

    def test_case_packet_contract(self):
        cases = PACKET["cases"]
        self.assertEqual(len(cases), 10)
        self.assertEqual(len({case["id"] for case in cases}), 10)
        self.assertTrue(all(case["request"].strip() and case["tools"].strip() for case in cases))
        self.assertTrue(all(case["split"] in {"development", "regression", "heldout"}
                            for case in cases))
        self.assertEqual(sum("{RUN_DIR}" in case["request"] for case in cases), 2)

    def test_cli_from_unrelated_working_directory(self):
        run = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT.parent,
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["scientific_validity"], "not_established_by_this_fixture")
        self.assertTrue(all(math.isfinite(x) for x in result["ci95"]))


if __name__ == "__main__":
    unittest.main()
