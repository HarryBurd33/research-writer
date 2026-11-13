#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline checks for the taxonomy CLI and bundled writing sources."""

import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1] / "skills/research-writer"
SCRIPT = Path("scripts/writing_tools.py")
TAXONOMY = Path("references/upstream/storyscope-taxonomy.json")
UPSTREAM = TAXONOMY.parent


class WritingChecks(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-I", "-S", str(SKILL / SCRIPT), "taxonomy", *args],
            capture_output=True, text=True, timeout=10,
        )

    def read_result(self, process):
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        return json.loads(process.stdout)

    def test_overview_counts(self):
        result = self.read_result(self.cli())
        self.assertEqual(result["scope"], "Bundled StoryScope taxonomy definitions only.")
        self.assertEqual(result["total_features"], 304)
        self.assertEqual(len(result["dimensions"]), 10)
        self.assertEqual(sum(result["dimensions"].values()), 304)
        self.assertEqual(result["dimensions"], {
            "revelation": 25, "events": 26, "perspective": 17, "plot": 28,
            "setting": 27, "style": 39, "situatedness": 25, "temporal_structure": 24,
            "agents": 54, "social_networks": 39,
        })
        self.assertNotIn("features", result)

    def test_dimension_selection_preserves_features(self):
        result = self.read_result(self.cli("--dimension", "revelation", "--dimension", "perspective"))
        upstream = json.loads((SKILL / TAXONOMY).read_text(encoding="utf-8"))["feature_taxonomy"]
        expected = [
            {"dimension": dimension, "aspect": aspect, **feature}
            for dimension in ("revelation", "perspective")
            for aspect, details in upstream[dimension]["aspects"].items()
            for feature in details["features"]
        ]
        self.assertEqual(len(result["features"]), 42)
        self.assertEqual(result["features"], expected)

    def test_exact_feature_ids_and_repeated_selectors(self):
        result = self.read_result(self.cli(
            "--feature", "REV_SUS_002", "--feature", "REV_SUS_001", "--feature", "REV_SUS_002",
        ))
        self.assertEqual([feature["id"] for feature in result["features"]], ["REV_SUS_001", "REV_SUS_002"])
        self.assertEqual(result["features"][1]["merged_from"], ["REV_DIS_011"])
        result = self.read_result(self.cli(
            "--feature", "REV_SUS_002", "--feature", "PER_POV_001",
            "--dimension", "revelation", "--dimension", "revelation",
        ))
        self.assertEqual(len(result["features"]), 26)
        self.assertEqual(sum(feature["id"] == "REV_SUS_002" for feature in result["features"]), 1)
        self.assertEqual(result["features"][-1]["id"], "PER_POV_001")

    def test_invalid_arguments_exit_without_json(self):
        for args, message in (
            (("--dimension", "revelation", "--dimension", "unknown"), "unknown dimension: unknown"),
            (("--feature", "REV_SUS_999"), "unknown feature ID: REV_SUS_999"),
            (("--feat", "REV_SUS_001"), "unrecognized arguments"),
            (("--input", "draft.md"), "unrecognized arguments"),
        ):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)

    def test_copied_package_works_offline_from_unrelated_directory(self):
        runner = """
import os
import runpy
import sys

def guard(event, args):
    if event.startswith(("socket.", "subprocess.")) or event in (
        "os.system", "os.exec", "os.posix_spawn", "os.mkdir", "os.remove", "os.rename", "os.rmdir",
    ):
        raise AssertionError(f"Unexpected side effect: {event}")
    if event == "open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
        raise AssertionError(f"Unexpected file write: {args[0]}")

script = sys.argv.pop(1)
sys.addaudithook(guard)
runpy.run_path(script, run_name="__main__")
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "installed skill"
            unrelated = root / "unrelated"
            unrelated.mkdir()
            for relative in (SCRIPT, TAXONOMY):
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SKILL / relative, target)
            process = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", runner, str(package / SCRIPT),
                 "taxonomy", "--feature", "REV_SUS_001"],
                cwd=unrelated, capture_output=True, text=True, timeout=10,
            )
            result = self.read_result(process)
            self.assertEqual([feature["id"] for feature in result["features"]], ["REV_SUS_001"])


class WritingSourceChecks(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        package = Path(directory.name) / "installed skill"
        shutil.copytree(SKILL, package)
        self.upstream = package / UPSTREAM
        self.manifest_path = self.upstream / "manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.package_check = runpy.run_path(str(package / "scripts/self_check.py"))["package_check"]

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_unchanged_copied_package_passes(self):
        self.package_check()

    def test_changed_bytes_fail_sha256_for_each_source(self):
        for name in ("humanizer.md", "humanizer-license.md", "storyscope-taxonomy.json", "storyscope-license.md"):
            with self.subTest(source=name):
                path = self.upstream / name
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                try:
                    with self.assertRaises(ValueError) as caught:
                        self.package_check()
                    self.assertEqual(str(caught.exception), f"Writing-source hash mismatch: {name}")
                finally:
                    path.write_bytes(original)

    def test_changed_bytes_with_matching_sha256_fail_git_identity(self):
        name = "storyscope-taxonomy.json"
        path = self.upstream / name
        changed = path.read_bytes() + b"\n"
        path.write_bytes(changed)
        entry = next(resource for resource in self.manifest["resources"] if resource["path"] == name)
        entry["sha256"] = hashlib.sha256(changed).hexdigest()
        self.save_manifest()
        with self.assertRaises(ValueError) as caught:
            self.package_check()
        self.assertEqual(str(caught.exception), f"Writing-source Git identity mismatch: {name}")

    def test_missing_resource_is_rejected(self):
        name = "humanizer-license.md"
        (self.upstream / name).unlink()
        with self.assertRaises(ValueError) as caught:
            self.package_check()
        self.assertEqual(str(caught.exception), f"Missing/escaping resource: {(UPSTREAM / name).as_posix()}")

    def test_missing_manifest_entry_is_rejected(self):
        self.manifest["resources"].pop()
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Incomplete writing-source manifest"):
            self.package_check()


if __name__ == "__main__":
    unittest.main()
