#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable, offline regressions promoted from known v0.6.0 edge cases.

These are public developer regressions, not fresh held-out scientific validation.
Run --molecular only in an environment containing RDKit and OpenMM.
"""
import argparse
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.dont_write_bytecode = True
SKILL = Path(__file__).resolve().parents[1] / "skills" / "research-writer"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--molecular", action="store_true")
ARGS, REMAINING = parser.parse_known_args()


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


E = module("regression_evidence", "evidence_tools.py")
R = module("regression_research", "research_tools.py")


class Response:
    def __init__(self, payload, raw=False):
        self.payload = payload if raw else json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return self.payload


class RegressionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, value="12.0"):
        context = dict(run="run-A", condition="298 K", dataset="sample-A",
                       metric="concentration", unit="mg/mL", seed="not_applicable",
                       statistic="single_measurement", value=value)
        path = self.root / "measurement.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=E.CONTEXT, lineterminator="\n")
            writer.writeheader()
            writer.writerow(context)
        return dict(artifacts=[dict(id="a", path=path.name,
                                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())],
                    measurements=[dict(id="m", artifact_id="a", row=1, **context)],
                    claims=[dict(id="c", evidence_id="m", **context)])

    def assert_rejected(self, manifest, code=None):
        report = E.verify_evidence(manifest, self.root)
        self.assertFalse(report["passed"], report)
        if code:
            self.assertIn(code, {e["code"] for e in report["errors"]}, report)
        return report

    def cli(self, filename, *args):
        return subprocess.run([sys.executable, str(SKILL / "scripts" / filename), *args],
                              cwd=self.root, capture_output=True, text=True, timeout=45)

    def test_identifier_forms_versions_and_idempotence(self):
        examples = [("DOI:10.5432/AbC.007", "doi", "10.5432/abc.007"),
                    ("https://doi.org/10.5432/abc.007", "doi", "10.5432/abc.007"),
                    ("PMID:24681012", "pmid", "24681012"),
                    ("https://pubmed.ncbi.nlm.nih.gov/24681012/", "pmid", "24681012"),
                    ("arXiv:2402.13579v2", "arxiv", "2402.13579"),
                    ("https://arxiv.org/abs/2402.13579v1", "arxiv", "2402.13579")]
        for original, kind, expected in examples:
            with self.subTest(original=original):
                result = E.normalize_identifier(original)
                self.assertTrue(result["valid"])
                self.assertEqual(result["normalized"], expected)
                self.assertEqual(E.normalize_identifier(expected, kind)["normalized"], expected)
        self.assertEqual(E.normalize_identifier(examples[-1][0])["version"], "v1")
        for value in ("10.not-a-doi/example", "pmid:not-numeric", "arXiv:2413.12345", "", None):
            with self.subTest(invalid=value):
                self.assertFalse(E.normalize_identifier(value)["valid"])

    def test_bibliography_retains_provenance_versions_and_conflicts(self):
        records = [{"doi": "10.5432/abc.007", "arxiv": "2402.13579v1", "title": "First title"},
                   {"doi": "DOI:10.5432/AbC.007", "arxiv": "2402.13579v2", "title": "Revised title"},
                   {"doi": "10.5432/abc.008", "arxiv": "2402.13579v2"},
                   {"doi": "invalid", "note": "Retain this rejected source"}]
        result = E.normalize_records(records)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["records"][0]["provenance"],
                         [dict(input_index=i, record=records[i]) for i in range(3)])
        self.assertEqual(result["records"][1]["provenance"][0]["record"], records[3])
        self.assertEqual({x.get("version") for x in result["records"][0]["identifier_variants"]
                          if x["kind"] == "arxiv"}, {"v1", "v2"})
        self.assertEqual({x["code"] for x in result["conflicts"]},
                         {"identity_conflict", "metadata_conflict"})
        self.assertEqual(E.normalize_records(records), result)
        for invalid in ({"doi": "10.5432/a"}, ["not an object"]):
            with self.subTest(invalid=invalid), self.assertRaises(E.ToolError):
                E.normalize_records(invalid)

    def test_provider_failures_are_not_verified_identities(self):
        url = "https://api.crossref.org/works/example"
        examples = [(urllib.error.URLError("offline"), "unavailable"),
                    (TimeoutError(), "unavailable")]
        examples += [(urllib.error.HTTPError(url, code, "fixture", None, None), status)
                     for code, status in [(503, "unavailable"), (429, "unavailable"),
                                          (403, "failed"), (404, "empty")]]
        for failure, status in examples:
            with self.subTest(failure=str(failure)), patch.object(E.urllib.request, "urlopen", side_effect=failure):
                result = E.lookup_doi("10.5432/abc.007")
                self.assertEqual(result["status"], status)
                self.assertEqual(result["identity_status"], "unresolved")
                self.assertEqual(result["results"], [])
                self.assertEqual(result["semantic_verification"], "not_performed")
            if isinstance(failure, urllib.error.HTTPError):
                failure.close()

    def test_provider_success_empty_mismatch_and_invalid_schema(self):
        examples = [({"message": {"items": []}}, "empty", "unresolved"),
                    ({"message": {"DOI": "10.5432/abc.007", "title": ["Fixture"]}}, "success", "identity_verified"),
                    ({"message": {"DOI": "10.5432/abc.008"}}, "failed", "mismatch"),
                    ({"message": {"DOI": "invalid"}}, "failed", "unresolved"),
                    ({"message": []}, "failed", "unresolved"),
                    ({"message": {"items": ["not a record"]}}, "failed", "unresolved")]
        for payload, status, identity in examples:
            with self.subTest(payload=payload), patch.object(E.urllib.request, "urlopen", return_value=Response(payload)):
                result = E.lookup_doi("10.5432/abc.007")
                self.assertEqual(result["status"], status)
                self.assertEqual(result["identity_status"], identity)
                self.assertEqual(result["access"], "metadata_only")
                self.assertEqual(result["semantic_verification"], "not_performed")
        for payload in (b"{", b"\xff", b"x" * (E.MAX_BYTES + 1)):
            with self.subTest(raw_length=len(payload)), patch.object(E.urllib.request, "urlopen", return_value=Response(payload, raw=True)):
                self.assertEqual(E.lookup_doi("10.5432/abc.007")["status"], "failed")

    def test_invalid_search_inputs_never_network(self):
        with patch.object(E.urllib.request, "urlopen", side_effect=AssertionError("Unexpected network")):
            with self.assertRaises(E.ToolError):
                E.lookup_doi("invalid-doi")
            for query, limit in [("", 1), ("x" * 1001, 1), ("fixture", 0),
                                 ("fixture", 21), ("fixture", True)]:
                with self.subTest(query_length=len(query), limit=limit), self.assertRaises(E.ToolError):
                    E.search_crossref(query, limit)

    def test_all_context_fields_are_bound_to_claim_and_csv(self):
        manifest = self.fixture()
        self.assertTrue(E.verify_evidence(manifest, self.root)["passed"])
        for category in ("claims", "measurements"):
            for field in E.CONTEXT:
                with self.subTest(category=category, field=field):
                    changed = copy.deepcopy(manifest)
                    changed[category][0][field] = "12.0001" if field == "value" else "different"
                    self.assert_rejected(changed, "context_mismatch")

    def test_missing_blank_and_nonfinite_are_rejected_but_zero_is_valid(self):
        manifest = self.fixture("0")
        manifest["claims"][0]["value"] = "0.000"
        self.assertTrue(E.verify_evidence(manifest, self.root)["passed"])
        for category in ("claims", "measurements"):
            for field in E.CONTEXT:
                with self.subTest(category=category, missing=field):
                    changed = copy.deepcopy(manifest)
                    changed[category][0].pop(field)
                    self.assert_rejected(changed)
            for value in (None, True, False, "NaN", "Infinity", "-Infinity", "", [], {}):
                with self.subTest(category=category, invalid_value=value):
                    changed = copy.deepcopy(manifest)
                    changed[category][0]["value"] = value
                    self.assert_rejected(changed, "invalid_value")
            changed = copy.deepcopy(manifest)
            changed[category][0]["condition"] = " "
            self.assert_rejected(changed, "missing_context")

    def test_hash_row_links_and_duplicate_ids(self):
        base = self.fixture()
        mutations = [("hash_mismatch", "artifacts", "sha256", "0" * 64),
                     ("invalid_hash", "artifacts", "sha256", "bad"),
                     ("missing_artifact", "measurements", "artifact_id", "missing"),
                     ("missing_evidence", "claims", "evidence_id", "missing")]
        mutations += [("invalid_row", "measurements", "row", value) for value in (0, 2, True, "1", None)]
        for code, category, field, value in mutations:
            with self.subTest(category=category, field=field, value=value):
                changed = copy.deepcopy(base)
                changed[category][0][field] = value
                self.assert_rejected(changed, code)
        for category in ("artifacts", "measurements", "claims"):
            with self.subTest(duplicate_category=category):
                changed = copy.deepcopy(base)
                changed[category].append(copy.deepcopy(changed[category][0]))
                self.assert_rejected(changed, "duplicate_id")
        (self.root / "measurement.csv").write_bytes(b"corrupted")
        self.assert_rejected(base, "hash_mismatch")

    def test_traversal_and_absolute_artifacts_rejected(self):
        base = self.fixture()
        for path in ("../measurement.csv", str((self.root / "measurement.csv").resolve())):
            with self.subTest(path=path):
                changed = copy.deepcopy(base)
                changed["artifacts"][0]["path"] = path
                self.assert_rejected(changed, "unsafe_artifact_path")

    def test_symlink_escaping_manifest_directory_rejected(self):
        manifest = self.fixture()
        nested = self.root / "nested"
        nested.mkdir()
        link = nested / "linked.csv"
        try:
            link.symlink_to(self.root / "measurement.csv")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("OS does not permit this symlink control: " + type(exc).__name__)
        manifest["artifacts"][0]["path"] = "linked.csv"
        report = E.verify_evidence(manifest, nested)
        self.assertFalse(report["passed"])
        self.assertIn("unsafe_artifact_path", {e["code"] for e in report["errors"]})

    def test_malformed_csv_headers_and_cells(self):
        base = self.fixture()
        examples = ["run,run\na,b\n", ",".join(E.CONTEXT) + "\nonly-one-cell\n",
                    ",".join(E.CONTEXT) + "\n" + ",".join(["a"] * 9) + "\n"]
        for data in examples:
            with self.subTest(data=data):
                changed = copy.deepcopy(base)
                (self.root / "measurement.csv").write_bytes(data.encode())
                changed["artifacts"][0]["sha256"] = hashlib.sha256(data.encode()).hexdigest()
                self.assert_rejected(changed)

    def test_empty_claims_never_pass(self):
        for data in ({}, {"artifacts": []}, {"claims": []}):
            with self.subTest(manifest=data):
                result = E.verify_evidence(data, self.root)
                self.assertEqual(result["status"], "not_checked")
                self.assertFalse(result["passed"])

    def test_source_access_identity_and_locators(self):
        manifest = dict(sources=[dict(id="s", access="full_text", identity_status="verified", locator="fixture:source")],
                        source_claims=[dict(id="sc", source_id="s", required_access="full_text", locator="section 4")])
        passed = E.verify_evidence(manifest, self.root)
        self.assertTrue(passed["passed"])
        self.assertEqual(passed["semantic_entailment"], "not_checked")
        self.assertEqual(passed["scientific_validity"], "not_checked")
        for access in ("metadata", "abstract"):
            changed = copy.deepcopy(manifest)
            changed["sources"][0]["access"] = access
            self.assert_rejected(changed, "insufficient_source_access")
        for category, field, value, code in [("sources", "identity_status", "unresolved", "unverified_source_identity"),
                                             ("sources", "locator", "", "missing_locator"),
                                             ("source_claims", "locator", "", "missing_locator"),
                                             ("source_claims", "source_id", "missing", "missing_source")]:
            changed = copy.deepcopy(manifest)
            changed[category][0][field] = value
            self.assert_rejected(changed, code)

    def test_json_duplicate_keys_and_nonfinite_input_rejected(self):
        for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{'):
            with self.subTest(data=data):
                path = self.root / "invalid.json"
                path.write_text(data, encoding="utf-8")
                with self.assertRaises(E.ToolError):
                    E.read_json(path)

    def test_remote_declarations_and_plans_cannot_execute(self):
        profile = self.root / "remote.json"
        profile.write_text(json.dumps(dict(mode="remote", remote_host="unconfigured.invalid; $(never)",
                                          accelerator="cuda", python="unprobed-python")), encoding="utf-8")
        source = self.root / "request.json"
        source.write_text("{}", encoding="utf-8")
        with patch.object(R.subprocess, "run", side_effect=AssertionError("Must not execute")):
            doctor = R.doctor(argparse.Namespace(profile=str(profile), probe_gpu=True))
            plan = R.plan(argparse.Namespace(profile=str(profile), input=str(source), tool="boltz"))
        self.assertEqual(doctor["gpu"]["status"], "not_probed")
        self.assertTrue(all(e["status"] == "remote_unprobed" and not e["execution_tested"] and
                            not e["weights_verified"] for e in doctor["engines"]))
        self.assertEqual(plan["status"], "planned_not_executed")
        self.assertFalse(plan["argv_is_execution_ready"])
        self.assertFalse(plan["remote_contacted"])
        self.assertEqual(plan["input"]["sha256"], hashlib.sha256(b"{}").hexdigest())

    def test_local_inventory_and_profile_validation(self):
        with patch.object(R.subprocess, "run", side_effect=AssertionError("No probe requested")):
            result = R.doctor(argparse.Namespace(profile=None, probe_gpu=False))
        self.assertEqual(result["gpu"]["status"], "not_probed")
        self.assertTrue(all(not e["execution_tested"] for e in result["engines"]))
        for data in ({"readiness": "ready"}, {"mode": "bad"}, {"accelerator": "magic"},
                     {"executables": ["not-a-map"]}):
            path = self.root / "invalid-profile.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(data=data), self.assertRaises(ValueError):
                R.profile(path)

    def test_cli_preserves_existing_output_unless_force(self):
        source = self.root / "bibliography.json"
        source.write_text('[{"doi":"10.5432/abc.007"}]', encoding="utf-8")
        output = self.root / "report.json"
        output.write_text("user-edited", encoding="utf-8")
        result = self.cli("evidence_tools.py", "bibliography", "--input", str(source), "--output", str(output))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(output.read_text(encoding="utf-8"), "user-edited")
        result = self.cli("evidence_tools.py", "bibliography", "--input", str(source), "--output", str(output), "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "success")
        profile = self.root / "profile.json"
        profile.write_text("user-edited", encoding="utf-8")
        result = self.cli("research_tools.py", "profile", "--output", str(profile))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(profile.read_text(encoding="utf-8"), "user-edited")

    @unittest.skipUnless(ARGS.molecular, "Optional molecular environment not requested")
    def test_molecular_conformer_structure_and_hash(self):
        from rdkit import Chem
        output = self.root / "conformer.json"
        sdf = self.root / "ethanol.sdf"
        result = self.cli("research_tools.py", "rdkit-conformer", "--smiles", "CCO", "--seed", "481516",
                          "--sdf", str(sdf), "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(report["converged"])
        self.assertEqual(report["optimizer_status"], 0)
        self.assertEqual(report["artifact"]["sha256"], hashlib.sha256(sdf.read_bytes()).hexdigest())
        mol = Chem.SDMolSupplier(str(sdf), removeHs=False)[0]
        self.assertIsNotNone(mol)
        self.assertEqual(mol.GetNumAtoms(), 9)
        self.assertTrue(mol.GetConformer().Is3D())
        self.assertEqual(Chem.MolToSmiles(Chem.RemoveHs(mol)), "CCO")

    @unittest.skipUnless(ARGS.molecular, "Optional molecular environment not requested")
    def test_real_energy_measurement_provenance_and_wrong_unit(self):
        output = self.root / "energy.json"
        result = self.cli("research_tools.py", "openmm-smoke", "--output", str(output), "--run-id", "regression")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertAlmostEqual(report["energy"], 0.5, delta=1e-8)
        self.assertEqual(report["unit"], "kJ/mol")
        self.assertEqual(report["platform"], "Reference")
        artifact = report["measurement_artifact"]
        path = Path(artifact["path"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"])
        with path.open(newline="", encoding="utf-8") as stream:
            row = next(csv.DictReader(stream))
        manifest = dict(artifacts=[dict(id="a", path=path.name, sha256=artifact["sha256"])],
                        measurements=[dict(id="m", artifact_id="a", row=1, **row)],
                        claims=[dict(id="c", evidence_id="m", **row)])
        self.assertTrue(E.verify_evidence(manifest, self.root)["passed"])
        manifest["claims"][0]["unit"] = "kcal/mol"
        self.assert_rejected(manifest, "context_mismatch")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + REMAINING)
