#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Original MIT-licensed research record tools; Python standard library only.

Integrity checks establish recorded identity and consistency, never semantic
entailment or scientific correctness. Network access occurs only in explicit
search and lookup-doi commands. Input files and HTTP bodies are capped at 10 MiB.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

MAX_BYTES = 10 * 1024 * 1024
CONTEXT = ("run", "condition", "dataset", "metric", "unit", "seed", "statistic", "value")
ACCESS = {"metadata": 0, "abstract": 1, "full_text": 2}


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ToolArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"status": "failed", "error": {"code": "invalid_arguments",
                                                       "message": message}}, sort_keys=True), file=sys.stderr)
        raise SystemExit(2)


def _error(code: str, record: str, detail: str) -> dict:
    return {"code": code, "record": record, "detail": detail}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ToolError("duplicate_json_key", f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ToolError("input_too_large", "Input exceeds 10 MiB")
    return data


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(_read_bytes(Path(path)).decode("utf-8"),
                          object_pairs_hook=_unique_object, parse_float=Decimal,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ToolError("nonfinite_json", f"Invalid JSON number: {value}")))
    except (ValueError, UnicodeError) as exc:
        raise ToolError("invalid_json", str(exc)) from exc


def write_json(path: str | Path, value: Any, force: bool = False) -> None:
    target = Path(path)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                         allow_nan=False, default=str) + "\n"
    if not force:
        # Exclusive creation also protects against a competing writer.
        with target.open("x", encoding="utf-8") as stream:
            stream.write(payload)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".research-record-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def init_project(directory: str | Path) -> dict:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "research-project.json"
    if manifest.exists():
        return {"status": "preserved", "path": str(manifest)}
    try:
        write_json(manifest, {"schema_version": 1, "target": None, "destination": None,
                              "scope": None, "decisions": [], "budgets": {}, "records": {}})
    except FileExistsError:
        return {"status": "preserved", "path": str(manifest)}
    return {"status": "created", "path": str(manifest)}


def normalize_identifier(value: Any, kind: str | None = None) -> dict:
    """Normalize DOI/arXiv/PMID identity, retaining arXiv version separately."""
    original = value
    result = {"original": original, "kind": kind, "normalized": None, "valid": False}
    if not isinstance(value, str) or not value.strip():
        return {**result, "error": "Identifier must be a nonempty string"}
    text = value.strip()
    if kind:
        kind = kind.lower()
    if not kind:
        if re.match(r"(?i)^(?:doi:|https?://(?:dx\.)?doi\.org/|10\.)", text):
            kind = "doi"
        elif re.match(r"(?i)^(?:arxiv:|https?://(?:www\.)?arxiv\.org/|\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})", text):
            kind = "arxiv"
        elif re.match(r"(?i)^(?:pmid:|https?://pubmed\.ncbi\.nlm\.nih\.gov/|\d+$)", text):
            kind = "pmid"
    result["kind"] = kind
    if kind == "doi":
        text = re.sub(r"(?i)^doi:\s*", "", text)
        if re.match(r"(?i)^https?://(?:dx\.)?doi\.org/", text):
            text = urllib.parse.unquote(urllib.parse.urlsplit(text).path.lstrip("/"))
        text = text.lower()
        if re.fullmatch(r'10\.\d{4,9}/[^\s<>"{}]+', text):
            return {**result, "normalized": text, "valid": True}
    elif kind == "arxiv":
        text = re.sub(r"(?i)^arxiv:\s*", "", text)
        if re.match(r"(?i)^https?://(?:www\.)?arxiv\.org/", text):
            text = urllib.parse.urlsplit(text).path
            text = re.sub(r"^/(?:abs|pdf|html)/", "", text)
        text = re.sub(r"(?i)\.pdf$", "", text).lower()
        match = re.fullmatch(r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})(v[1-9]\d*)?", text)
        if match:
            core = match.group(1)
            # Modern IDs contain a valid calendar month.
            if "." not in core[:5] or 1 <= int(core[2:4]) <= 12:
                return {**result, "normalized": core, "version": match.group(2), "valid": True}
    elif kind == "pmid":
        text = re.sub(r"(?i)^pmid:\s*", "", text)
        if re.match(r"(?i)^https?://pubmed\.ncbi\.nlm\.nih\.gov/", text):
            text = urllib.parse.urlsplit(text).path.strip("/")
        if re.fullmatch(r"\d{1,12}", text) and int(text) > 0:
            return {**result, "normalized": str(int(text)), "valid": True}
    return {**result, "error": "Invalid or unsupported identifier"}


def normalize_records(records: Any) -> dict:
    """Deduplicate by shared canonical identity, retaining every original record."""
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ToolError("invalid_bibliography", "Bibliography input must be a list of objects")
    groups, errors = [], []
    for index, record in enumerate(records):
        identifiers = []
        for kind in ("doi", "arxiv", "pmid"):
            if kind not in record:
                continue
            values = record[kind] if isinstance(record[kind], list) else [record[kind]]
            for value in values:
                normalized = normalize_identifier(value, kind)
                identifiers.append(normalized)
                if not normalized["valid"]:
                    errors.append(_error("invalid_identifier", str(index), f"Invalid {kind} identifier"))
        if not identifiers:
            errors.append(_error("missing_identifier", str(index), "No DOI, arXiv ID or PMID supplied"))
        keys = {(i["kind"], i["normalized"]) for i in identifiers if i["valid"]}
        matches = [g for g in groups if g["keys"] & keys]
        if matches:
            group = matches[0]
            for other in matches[1:]:
                group["keys"] |= other["keys"]
                group["identifiers"] += other["identifiers"]
                group["provenance"] += other["provenance"]
                groups.remove(other)
        else:
            group = {"keys": set(), "identifiers": [], "provenance": []}
            groups.append(group)
        group["keys"] |= keys
        group["identifiers"] += identifiers
        group["provenance"].append({"input_index": index, "record": record})
    output, conflicts = [], []
    for index, group in enumerate(groups):
        canonical = {kind: sorted(value for k, value in group["keys"] if k == kind)
                     for kind in ("doi", "arxiv", "pmid")}
        for kind, values in canonical.items():
            if len(values) > 1:
                conflicts.append(_error("identity_conflict", str(index), f"Conflicting {kind} identities: {values}"))
        for field in ("title", "year", "authors"):
            variants = {json.dumps(p["record"][field], sort_keys=True, default=str)
                        for p in group["provenance"] if field in p["record"]}
            if len(variants) > 1:
                conflicts.append(_error("metadata_conflict", str(index), f"Different {field} values retained"))
        output.append({"canonical": canonical, "identifier_variants": group["identifiers"],
                       "provenance": sorted(group["provenance"], key=lambda p: p["input_index"])})
    return {"status": "failed" if errors or conflicts else "success", "records": output,
            "errors": errors, "conflicts": conflicts, "semantic_verification": "not_performed"}


def _public_crossref(url: str) -> dict:
    retrieved = datetime.now(timezone.utc).isoformat()
    base = {"request_url": url, "retrieved_at": retrieved, "access": "metadata_only",
            "identity_only": True, "semantic_verification": "not_performed", "results": []}
    request = urllib.request.Request(url, headers={"User-Agent": "research-writer-evidence-tools/1.0",
                                                   "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return {**base, "status": "failed", "error": "response_too_large"}
        payload = json.loads(data)
        if not isinstance(payload, dict) or not isinstance(payload.get("message"), dict):
            return {**base, "status": "failed", "error": "invalid_provider_response"}
        message = payload["message"]
        items = message.get("items") if "items" in message else [message]
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            return {**base, "status": "failed", "error": "invalid_provider_results"}
        results = []
        for item in items:
            normalized = normalize_identifier(item.get("DOI"), "doi")
            if not normalized["valid"]:
                return {**base, "status": "failed", "error": "invalid_provider_record"}
            results.append({"doi": normalized["normalized"], "title": item.get("title", []),
                            "authors": item.get("author", []), "published": item.get("published"),
                            "publisher": item.get("publisher"), "type": item.get("type"),
                            "url": item.get("URL"), "metadata_url": "https://api.crossref.org/works/" +
                            urllib.parse.quote(normalized["normalized"] or "", safe=""),
                            "access": "metadata_only", "retrieved_at": retrieved})
        return {**base, "status": "success" if results else "empty", "results": results}
    except urllib.error.HTTPError as exc:
        status = "empty" if exc.code == 404 else "unavailable" if exc.code == 429 or exc.code >= 500 else "failed"
        return {**base, "status": status, "error": "http_error", "http_status": exc.code}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {**base, "status": "unavailable", "error": "network_unavailable"}
    except (ValueError, UnicodeError, TypeError):
        return {**base, "status": "failed", "error": "invalid_provider_response"}


def search_crossref(query: str, limit: int = 5) -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ToolError("invalid_query", "Query must contain 1–1000 characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ToolError("invalid_limit", "Limit must be between 1 and 20")
    parameters = urllib.parse.urlencode({"query": query.strip(), "rows": limit})
    return _public_crossref("https://api.crossref.org/works?" + parameters)


def lookup_doi(doi: str) -> dict:
    normalized = normalize_identifier(doi, "doi")
    if not normalized["valid"]:
        raise ToolError("invalid_doi", "DOI is invalid")
    result = _public_crossref("https://api.crossref.org/works/" + urllib.parse.quote(normalized["normalized"], safe=""))
    result["requested_doi"] = normalized["normalized"]
    if result["status"] == "success":
        matches = [r for r in result["results"] if r["doi"] == normalized["normalized"]]
        result["identity_status"] = "identity_verified" if matches else "mismatch"
        if not matches:
            result["status"] = "failed"
            result["error"] = "doi_identity_mismatch"
    else:
        result["identity_status"] = "unresolved"
    return result


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        raise ValueError("Value must be a finite decimal number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Value must be a finite decimal number") from exc
    if not number.is_finite():
        raise ValueError("Value must be finite")
    return number


def verify_evidence(manifest: Any, base_directory: str | Path = ".") -> dict:
    """Verify hashes and exact context-linked CSV values; no network or writes."""
    errors = []
    report = {"status": "fail", "passed": False, "errors": errors,
              "semantic_entailment": "not_checked", "scientific_validity": "not_checked",
              "scope": "artifact hashes, CSV row/context identity, source access and locators"}
    if not isinstance(manifest, dict):
        errors.append(_error("invalid_manifest", "manifest", "Manifest must be an object"))
        return report
    root = Path(base_directory).resolve()
    indexes = {}
    for category in ("artifacts", "measurements", "claims", "sources", "source_claims"):
        records = manifest.get(category, [])
        if not isinstance(records, list):
            errors.append(_error("invalid_records", category, "Expected list"))
            records = []
        index = {}
        for position, record in enumerate(records):
            label = f"{category}[{position}]"
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"].strip():
                errors.append(_error("missing_id", label, "Nonempty string ID required"))
                continue
            if record["id"] in index:
                errors.append(_error("duplicate_id", label, record["id"]))
                continue
            index[record["id"]] = record
        indexes[category] = index
    if not indexes["claims"] and not indexes["source_claims"]:
        report["status"] = "not_checked"
        report["reason"] = "no_claims_to_check"
        report["counts"] = {key: len(value) for key, value in indexes.items()}
        return report
    tables = {}
    for identity, artifact in indexes["artifacts"].items():
        label = f"artifact:{identity}"
        try:
            relative = artifact.get("path")
            if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise ToolError("unsafe_artifact_path", "Relative artifact path without traversal required")
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ToolError("unsafe_artifact_path", "Artifact resolves outside manifest directory")
            expected = artifact.get("sha256")
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                raise ToolError("invalid_hash", "SHA-256 hex digest required")
            raw = _read_bytes(path)
            if hashlib.sha256(raw).hexdigest() != expected.lower():
                raise ToolError("hash_mismatch", "Artifact content differs from recorded SHA-256")
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
            header = reader.fieldnames or []
            if len(header) != len(set(header)) or any(k not in header for k in CONTEXT):
                raise ToolError("invalid_csv_header", "CSV needs unique headers including all context fields")
            rows = list(reader)
            if any(None in row or any(row[k] is None for k in CONTEXT) for row in rows):
                raise ToolError("invalid_csv_row", "CSV has missing or excess cells")
            tables[identity] = rows
        except (OSError, UnicodeError, csv.Error, ToolError) as exc:
            errors.append(_error(getattr(exc, "code", "artifact_unreadable"), label, str(exc)))
    valid_measurements = set()
    def valid_context(record, label):
        good = True
        for key in CONTEXT:
            if key == "value":
                try:
                    _decimal(record.get(key))
                except ValueError as exc:
                    errors.append(_error("invalid_value", label, str(exc)))
                    good = False
            elif not isinstance(record.get(key), str) or not record[key].strip():
                errors.append(_error("missing_context", label, f"Nonempty string required: {key}"))
                good = False
        return good
    def compare(left, right, label):
        good = True
        for key in CONTEXT:
            try:
                same = _decimal(left.get(key)) == _decimal(right.get(key)) if key == "value" else left.get(key) == right.get(key)
            except ValueError:
                same = False
            if not same:
                errors.append(_error("context_mismatch", label, f"Mismatch in {key}"))
                good = False
        return good
    for identity, measurement in indexes["measurements"].items():
        label = f"measurement:{identity}"
        good = valid_context(measurement, label)
        aid = measurement.get("artifact_id")
        if not isinstance(aid, str) or aid not in indexes["artifacts"]:
            errors.append(_error("missing_artifact", label, "Artifact ID does not resolve"))
            continue
        if aid not in tables:
            errors.append(_error("unverified_artifact", label, "Artifact failed hash or CSV checks"))
            continue
        row = measurement.get("row")
        if isinstance(row, bool) or not isinstance(row, int) or not 1 <= row <= len(tables[aid]):
            errors.append(_error("invalid_row", label, "Row must be a 1-based CSV data-row index"))
            continue
        if compare(measurement, tables[aid][row - 1], label) and good:
            valid_measurements.add(identity)
    for identity, claim in indexes["claims"].items():
        label = f"claim:{identity}"
        valid_context(claim, label)
        eid = claim.get("evidence_id")
        if not isinstance(eid, str) or eid not in indexes["measurements"]:
            errors.append(_error("missing_evidence", label, "Evidence ID does not resolve"))
        else:
            compare(claim, indexes["measurements"][eid], label)
            if eid not in valid_measurements:
                errors.append(_error("unverified_evidence", label, "Linked measurement failed verification"))
    for identity, source in indexes["sources"].items():
        if not isinstance(source.get("access"), str) or source["access"] not in ACCESS:
            errors.append(_error("invalid_access", f"source:{identity}", "Access must be metadata, abstract or full_text"))
        if not isinstance(source.get("identity_status"), str) or not source["identity_status"].strip():
            errors.append(_error("missing_identity_status", f"source:{identity}", "Identity status required"))
        if not isinstance(source.get("locator"), str) or not source["locator"].strip():
            errors.append(_error("missing_locator", f"source:{identity}", "Source locator required"))
    for identity, claim in indexes["source_claims"].items():
        label = f"source_claim:{identity}"
        sid = claim.get("source_id")
        source = indexes["sources"].get(sid) if isinstance(sid, str) else None
        if source is None:
            errors.append(_error("missing_source", label, "Source ID does not resolve"))
            continue
        required = claim.get("required_access")
        if not isinstance(required, str) or required not in ACCESS:
            errors.append(_error("invalid_required_access", label, "Required access must be metadata, abstract or full_text"))
        elif not isinstance(source.get("access"), str) or ACCESS.get(source["access"], -1) < ACCESS[required]:
            errors.append(_error("insufficient_source_access", label, "Recorded source access is below claim requirement"))
        if source.get("identity_status") not in ("verified", "identity_verified"):
            errors.append(_error("unverified_source_identity", label, "Source identity has not been verified"))
        for record, name in ((source, "source"), (claim, "claim")):
            if not isinstance(record.get("locator"), str) or not record["locator"].strip():
                errors.append(_error("missing_locator", label, f"{name} requires a source locator"))
    report["counts"] = {key: len(value) for key, value in indexes.items()}
    report["passed"] = not errors
    report["status"] = "pass" if not errors else "fail"
    return report


def main(argv=None) -> int:
    parser = ToolArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init-project")
    initialize.add_argument("--directory", required=True)
    for command in ("bibliography", "verify-evidence", "search", "lookup-doi"):
        sub = commands.add_parser(command)
        sub.add_argument("--output", required=True)
        sub.add_argument("--force", action="store_true")
        if command in ("bibliography", "verify-evidence"):
            sub.add_argument("--input", required=True)
        if command == "search":
            sub.add_argument("--query", required=True)
            sub.add_argument("--limit", type=int, default=5)
        if command == "lookup-doi":
            sub.add_argument("--doi", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init-project":
            print(json.dumps(init_project(args.directory), sort_keys=True))
            return 0
        if Path(args.output).exists() and not args.force:
            raise ToolError("output_exists", "Output already exists; use --force to replace it")
        if args.command == "bibliography":
            result = normalize_records(read_json(args.input))
        elif args.command == "verify-evidence":
            result = verify_evidence(read_json(args.input), Path(args.input).resolve().parent)
        elif args.command == "search":
            result = search_crossref(args.query, args.limit)
        else:
            result = lookup_doi(args.doi)
        write_json(args.output, result, args.force)
        return 0 if result["status"] in ("success", "empty", "pass") else 2
    except (ToolError, OSError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps({"status": "failed", "error": {"code": getattr(exc, "code", "io_or_input_error"),
                                                       "message": str(exc)}}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
