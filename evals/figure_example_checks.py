#!/usr/bin/env python3
"""Independent deterministic checks; these do not replace rendered visual review."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs" / "examples" / "scientific-figures"
NS = {"svg": "http://www.w3.org/2000/svg"}


class FigureExampleChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.area = Path(self.temporary.name)
        self.example = self.area / "relocated-package" / "docs" / "examples" / "scientific-figures"
        shutil.copytree(EXAMPLE, self.example)
        self.cwd = self.area / "unrelated-cwd"
        self.cwd.mkdir()

    def run_generator(self, *args, success=True):
        result = subprocess.run([sys.executable, str(self.example / "generate.py"), *map(str, args)],
                                cwd=self.cwd, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_independent_numerical_expectations(self):
        self.run_generator()
        rows = json.loads((self.example / "generated" / "statistics.json").read_text())
        self.assertEqual([row["time_min"] for row in rows], [0, 1, 2, 3])
        for row, mean, sd in zip(rows, [0, 2, 1, 3], [0, .2, .1, .3]):
            self.assertEqual(row["n"], 3)
            self.assertAlmostEqual(row["mean_mg_L"], mean, places=12)
            self.assertAlmostEqual(row["sample_sd_mg_L"], sd, places=12)
        self.assertEqual(rows[0]["values_mg_L"], [0, 0, 0])
        self.assertLess(rows[2]["mean_mg_L"], rows[1]["mean_mg_L"])

    def test_svg_labels_xml_and_planted_error(self):
        self.run_generator()
        generated = self.example / "generated"
        trees = {name: ET.parse(generated / name) for name in
                 ("measurements.svg", "protocol.svg", "erroneous-reference.svg")}
        texts = [node.text for node in trees["measurements.svg"].findall(".//svg:text", NS)]
        for required in ("0", "Time (min)", "Concentration (mg/L)"):
            self.assertIn(required, texts)
        self.assertTrue(any("Mean ± sample SD; n = 3" in text for text in texts))
        self.assertTrue(any("not a confidence interval" in text for text in texts))
        self.assertEqual(len(trees["measurements.svg"].findall(".//svg:circle", NS)), 4)
        correct = [node.text for node in trees["protocol.svg"].findall(".//svg:text", NS)]
        error = [node.text for node in trees["erroneous-reference.svg"].findall(".//svg:text", NS)]
        self.assertEqual(correct[1:5], ["collect", "fix", "stain", "image"])
        self.assertEqual(error[1:5], ["collect", "stain", "fix", "image"])
        self.assertTrue(any("ERROR FIXTURE" in text for text in error))
        self.assertTrue(any("fix and stain are reversed" in text for text in error))

    def test_pinned_sources_and_byte_determinism(self):
        self.run_generator()
        generated = self.example / "generated"
        provenance = json.loads((generated / "provenance.json").read_text())
        self.assertEqual(set(provenance["sources_sha256"]),
                         {"measurements.csv", "protocol.txt", "erroneous-diagram.json"})
        for name, digest in provenance["sources_sha256"].items():
            self.assertEqual(hashlib.sha256((self.example / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(hashlib.sha256((self.example / "generate.py").read_bytes()).hexdigest(),
                         provenance["generator_sha256"])
        for svg in generated.glob("*.svg"):
            metadata = ET.parse(svg).find("svg:metadata", NS)
            self.assertEqual(json.loads(metadata.text), provenance)
        second = self.area / "second-render"
        self.run_generator("--output-dir", second)
        for file in generated.iterdir():
            self.assertEqual(file.read_bytes(), (second / file.name).read_bytes())
            self.assertEqual(file.read_bytes(), (EXAMPLE / "generated" / file.name).read_bytes(),
                             f"Checked-in artifact is stale: {file.name}")

    def test_actual_inputs_drive_outputs(self):
        data = self.example / "measurements.csv"
        data.write_text(data.read_text().replace("1,1,1.8", "1,1,4.8"))
        self.run_generator()
        generated = self.example / "generated"
        rows = json.loads((generated / "statistics.json").read_text())
        self.assertAlmostEqual(rows[1]["mean_mg_L"], 3, places=12)
        source_hash = json.loads((generated / "provenance.json").read_text())["sources_sha256"]["measurements.csv"]
        self.assertEqual(source_hash, hashlib.sha256(data.read_bytes()).hexdigest())
        protocol = self.example / "protocol.txt"
        protocol.write_text(protocol.read_text().replace("2. fix", "2. wash"))
        self.run_generator()
        texts = [node.text for node in ET.parse(generated / "protocol.svg").findall(".//svg:text", NS)]
        self.assertEqual(texts[1:5], ["collect", "wash", "stain", "image"])

    def test_missing_duplicate_and_output_safety(self):
        data = self.example / "measurements.csv"
        original = data.read_bytes()
        self.run_generator("--output-dir", self.example, success=False)
        self.assertEqual(data.read_bytes(), original)
        data.write_text(original.decode().replace("0,1,0", "0,1,"))
        self.run_generator(success=False)
        data.write_text(original.decode().replace("0,2,0", "0,1,0"))
        self.run_generator(success=False)
        data.write_bytes(original)
        target = self.area / "symlink-output"
        target.mkdir()
        (target / "measurements.svg").symlink_to(data)
        self.run_generator("--output-dir", target, success=False)
        self.assertEqual(data.read_bytes(), original)
        (target / "measurements.svg").unlink()
        os.link(data, target / "measurements.svg")
        self.run_generator("--output-dir", target, success=False)
        self.assertEqual(data.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
