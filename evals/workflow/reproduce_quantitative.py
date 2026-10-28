#!/usr/bin/env python3
"""Reproduce one synthetic teaching fixture, not a general meta-analysis engine.

No network, optional libraries, missing-value imputation or model selection.
All included families must estimate the same quantity, as specified by P5-02.
"""

import argparse
import json
import math
from pathlib import Path


NORMAL_975 = 1.959963984540054
MAX_REPORTS = 100


def _number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{label} must be finite" + (" and positive" if positive else ""))
    return result


def synthesize_reports(rows):
    """Compute the fixture's common-effect weighted mean after family checks.

    Exact numeric duplicates within a family are retained once, choosing the
    lexicographically smallest report ID for reproducibility. Different numbers
    within one family are unresolved and refuse pooling. Family declarations
    are supplied data, not something this helper can independently authenticate.
    """
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_REPORTS:
        raise ValueError(f"reports must be a list of 1..{MAX_REPORTS} records")
    families = {}
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each report must be an object")
        report_id, family = row.get("id"), row.get("family")
        for value, label in ((report_id, "id"), (family, "family")):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a nonempty string")
        if report_id in ids:
            raise ValueError(f"duplicate report id: {report_id}")
        ids.add(report_id)
        effect = _number(row.get("effect_seconds_saved"), "effect_seconds_saved")
        se = _number(row.get("standard_error"), "standard_error", positive=True)
        families.setdefault(family, []).append((report_id, effect, se))

    included = []
    decisions = []
    for family in sorted(families):
        reports = sorted(families[family])
        selected_id, effect, se = reports[0]
        if any((other_effect, other_se) != (effect, se)
               for _, other_effect, other_se in reports[1:]):
            raise ValueError(f"unresolved conflicting reports in family: {family}")
        try:
            weight = (1.0 / se) ** 2
        except (OverflowError, ZeroDivisionError) as exc:
            raise ValueError("uncertainty outside supported numerical range") from exc
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("uncertainty outside supported numerical range")
        included.append((effect, weight))
        decisions.append({"family": family, "included_report": selected_id,
                          "excluded_exact_duplicates": [r[0] for r in reports[1:]]})

    try:
        precision = math.fsum(weight for _, weight in included)
        numerator = math.fsum(effect * weight for effect, weight in included)
        mean = numerator / precision
        standard_error = math.sqrt(1 / precision)
        interval = [mean - NORMAL_975 * standard_error,
                    mean + NORMAL_975 * standard_error]
    except (OverflowError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("calculation outside supported numerical range") from exc
    if (not all(math.isfinite(n) for n in [precision, mean, standard_error, *interval])
            or standard_error <= 0):
        raise ValueError("calculation outside supported numerical range")
    return {"method": "common-effect inverse-variance; synthetic P5-02 teaching control",
            "reports": len(rows), "independent_families": len(families),
            "effect_seconds_saved": mean, "standard_error": standard_error,
            "ci95": interval, "study_family_decisions": decisions,
            "scientific_validity": "not_established_by_this_fixture"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=Path(__file__).with_name("inputs.json"))
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 1024 * 1024:
            raise ValueError("fixture file exceeds 1 MiB")
        packet = json.loads(args.input.read_text(encoding="utf-8"))
        matches = [case for case in packet["cases"]
                   if case["id"] == "P5-02-quantitative"]
        if len(matches) != 1:
            raise ValueError("fixture requires exactly one P5-02 case")
        result = synthesize_reports(matches[0]["source_packet"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"fixture error: {exc}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
