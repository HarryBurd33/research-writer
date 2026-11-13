#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inspect the bundled StoryScope taxonomy definitions offline."""

import argparse
import json
from pathlib import Path


TAXONOMY = Path(__file__).resolve().parents[1] / "references/upstream/storyscope-taxonomy.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    taxonomy = commands.add_parser(
        "taxonomy", help="Show counts or look up feature definitions", allow_abbrev=False
    )
    taxonomy.add_argument(
        "--dimension", metavar="DIM", action="append", default=[],
        help="Include all features in this dimension. Repeat to include more dimensions.",
    )
    taxonomy.add_argument(
        "--feature", metavar="ID", action="append", default=[],
        help="Include this feature ID. Repeat to include more features.",
    )
    args = parser.parse_args()

    try:
        dimensions = json.loads(TAXONOMY.read_text(encoding="utf-8"))["feature_taxonomy"]
    except (OSError, ValueError) as exc:
        taxonomy.error(f"cannot read bundled StoryScope taxonomy: {exc}")

    features_by_dimension = {
        dimension: [
            {"dimension": dimension, "aspect": aspect, **feature}
            for aspect, details in definition["aspects"].items()
            for feature in details["features"]
        ]
        for dimension, definition in dimensions.items()
    }
    counts = {dimension: len(features) for dimension, features in features_by_dimension.items()}
    features = [feature for group in features_by_dimension.values() for feature in group]
    requested_dimensions = set(args.dimension)
    requested_features = set(args.feature)
    unknown_dimensions = requested_dimensions.difference(counts)
    if unknown_dimensions:
        taxonomy.error(f"unknown dimension: {', '.join(sorted(unknown_dimensions))}")
    unknown_features = requested_features.difference(feature["id"] for feature in features)
    if unknown_features:
        taxonomy.error(f"unknown feature ID: {', '.join(sorted(unknown_features))}")

    result = {
        "scope": "Bundled StoryScope taxonomy definitions only.",
        "total_features": len(features),
        "dimensions": counts,
    }
    if requested_dimensions or requested_features:
        result["features"] = [
            feature for feature in features
            if feature["dimension"] in requested_dimensions or feature["id"] in requested_features
        ]
    print(json.dumps(result))


if __name__ == "__main__":
    main()
