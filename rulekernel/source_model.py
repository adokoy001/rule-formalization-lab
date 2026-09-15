"""Strict data boundary for immutable source capture specifications."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from .model import KernelError


SOURCE_SPEC_FORMAT = "rule-source-capture-spec/1"
SOURCE_PACKAGE_FORMAT = "rule-source-package/1"
SOURCE_UNIT_MANIFEST_FORMAT = "rule-source-unit-manifest/1"
RETRIEVAL_FORMAT = "rule-source-retrieval/1"
EXTRACTION_PROFILE = "xml-unit-text/2"
EXTRACTION_PROFILE_VERSION = "2"
SOURCE_CHECKER_VERSION = "0.1.0"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_SOURCE_SPEC_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_SOURCE_UNITS = 4096
MAX_REFERENCES = 4096
MAX_XML_NODES = 100_000
MAX_XML_DEPTH = 128
CONTEXT_CHARS = 16

EXTRACTION_DEFINITION = {
    "profile": EXTRACTION_PROFILE,
    "version": EXTRACTION_PROFILE_VERSION,
    "encoding": "UTF-8 without BOM; decoding errors are fatal",
    "raw_bytes": "preserved exactly before decoding and XML processing",
    "newlines": "XML 1.0 CRLF and CR are normalized to LF for derived text",
    "character_references": "XML predefined and numeric references are decoded",
    "unicode_normalization": "none",
    "text_nodes": (
        "document order; text is preserved exactly except whitespace-only direct nodes "
        "of e-Gov Article, Paragraph, and ParagraphSentence layout containers"
    ),
    "ruby": (
        "Ruby must contain base text and exactly one direct leaf Rt child; only that Rt "
        "reading is omitted; Rt anywhere else is unsupported"
    ),
    "fictional_mixed_content": "all text and whitespace inside selected units is preserved",
    "egov_layout_containers": ["Article", "Paragraph", "ParagraphSentence"],
    "egov_content_elements": ["ArticleCaption", "ArticleTitle", "ParagraphNum", "Sentence"],
    "egov_child_grammar": {
        "Article": ["ArticleCaption", "ArticleTitle", "Paragraph"],
        "ArticleCaption": ["Ruby"],
        "ArticleTitle": ["Ruby"],
        "Paragraph": ["ParagraphNum", "ParagraphSentence"],
        "ParagraphNum": ["Ruby"],
        "ParagraphSentence": ["Sentence"],
        "Sentence": ["Ruby"],
    },
    "unit_separator": "one LF between selected units",
    "coordinate_system": "unicode-codepoint-0-based-half-open/1",
}

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"(?:/[A-Za-z][A-Za-z0-9]*(?:\[[0-9]+\]))+\Z")
_LAW_ID = re.compile(r"[0-9A-Za-z]{8,32}\Z")


def _invalid(message: str, status: str = "SOURCE_INVALID") -> None:
    raise KernelError(status, message)


def source_canonical_json(value) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False)
        rendered.encode("utf-8")
        return rendered
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise KernelError("SOURCE_INVALID", f"Not canonical source JSON: {exc}") from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_digest(value) -> str:
    return sha256_bytes(source_canonical_json(value).encode("utf-8"))


EXTRACTION_DEFINITION_SHA256 = source_digest(EXTRACTION_DEFINITION)


def decode_source_json(raw: bytes, *, max_bytes: int, label: str):
    if len(raw) > max_bytes:
        raise KernelError("LIMIT_REACHED", f"{label} exceeds {max_bytes} bytes")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _invalid(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_number(value):
        _invalid(f"{label}: unsupported JSON number {value}")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_float=reject_number, parse_constant=reject_number)
        source_canonical_json(result)
        return result
    except KernelError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise KernelError("SOURCE_INVALID", f"{label}: invalid JSON: {exc}") from exc


def load_source_json(path, *, max_bytes: int = MAX_SOURCE_SPEC_BYTES,
                     label: str = "source JSON"):
    with Path(path).open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    return decode_source_json(raw, max_bytes=max_bytes, label=label)


def _shape(value, fields, path: str) -> None:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _invalid(f"{path}: expected object with string keys")
    missing = set(fields) - value.keys()
    extra = value.keys() - set(fields)
    if missing:
        _invalid(f"{path}: missing fields {sorted(missing)}")
    if extra:
        _invalid(f"{path}: unknown fields {sorted(extra)}", "UNSUPPORTED")


def _text(value, path: str, *, maximum: int = 8192, allow_empty: bool = False) -> None:
    if type(value) is not str or (not allow_empty and not value) or len(value) > maximum:
        qualifier = "string" if allow_empty else "nonempty string"
        _invalid(f"{path}: expected {qualifier} of at most {maximum} codepoints")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _invalid(f"{path}: invalid Unicode")


def _nullable_text(value, path: str, *, maximum: int = 8192) -> None:
    if value is not None:
        _text(value, path, maximum=maximum)


def _identifier(value, path: str) -> None:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _invalid(f"{path}: invalid identifier")


def _sha(value, path: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid(f"{path}: expected lowercase SHA-256 hex")


def _date(value, path: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str:
        _invalid(f"{path}: expected ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        _invalid(f"{path}: invalid ISO date: {exc}")
    if parsed.isoformat() != value:
        _invalid(f"{path}: date must use YYYY-MM-DD")


def validate_retrieved_at(value, path: str = "retrieved_at") -> None:
    if type(value) is not str:
        _invalid(f"{path}: expected RFC3339 UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        _invalid(f"{path}: expected YYYY-MM-DDTHH:MM:SSZ: {exc}")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        _invalid(f"{path}: timestamp is not canonical")


def _url(value, path: str, *, schemes=("https", "urn")) -> None:
    _text(value, path, maximum=2048)
    parsed = urlparse(value)
    if parsed.scheme not in schemes:
        _invalid(f"{path}: unsupported URL scheme")
    if parsed.scheme == "https" and (not parsed.netloc or parsed.username or parsed.password):
        _invalid(f"{path}: invalid HTTPS URL")


def _structural_path(value, path: str) -> None:
    if type(value) is not str or len(value) > 4096 or _PATH.fullmatch(value) is None:
        _invalid(f"{path}: expected canonical /Tag[1]/Child[1] path")
    for index in re.findall(r"\[([0-9]+)\]", value):
        if int(index) < 1:
            _invalid(f"{path}: structural indices are one-based")


def validate_source_spec(spec) -> None:
    _shape(spec, {"format", "source", "expected_raw_sha256",
                  "expected_metadata_sha256", "extraction", "units", "references"},
           "spec")
    if spec["format"] != SOURCE_SPEC_FORMAT:
        _invalid("spec.format: unsupported source specification", "UNSUPPORTED")

    source = spec["source"]
    _shape(source, {"kind", "document_id", "jurisdiction", "law_id", "revision_id",
                    "raw_url", "metadata_url", "effective_from"}, "spec.source")
    kind = source["kind"]
    if kind not in {"fictional_xml", "egov_api_v2"}:
        _invalid(f"spec.source.kind: unsupported kind {kind!r}", "UNSUPPORTED")
    _identifier(source["document_id"], "spec.source.document_id")
    _text(source["jurisdiction"], "spec.source.jurisdiction", maximum=64)
    _nullable_text(source["law_id"], "spec.source.law_id", maximum=64)
    _text(source["revision_id"], "spec.source.revision_id", maximum=128)
    _url(source["raw_url"], "spec.source.raw_url")
    if source["metadata_url"] is not None:
        _url(source["metadata_url"], "spec.source.metadata_url", schemes=("https",))
    _date(source["effective_from"], "spec.source.effective_from", nullable=True)
    _sha(spec["expected_raw_sha256"], "spec.expected_raw_sha256")
    _sha(spec["expected_metadata_sha256"], "spec.expected_metadata_sha256", nullable=True)

    if kind == "fictional_xml":
        if source["law_id"] is not None or source["metadata_url"] is not None:
            _invalid("fictional source must not declare law_id or metadata_url")
        if spec["expected_metadata_sha256"] is not None:
            _invalid("fictional source must not declare a metadata hash")
    else:
        law_id, revision_id = source["law_id"], source["revision_id"]
        if source["jurisdiction"] != "JP":
            _invalid("e-Gov source jurisdiction must be 'JP'")
        if type(law_id) is not str or _LAW_ID.fullmatch(law_id) is None:
            _invalid("e-Gov source requires a valid law_id")
        if not revision_id.startswith(law_id + "_"):
            _invalid("e-Gov revision_id must be anchored to law_id")
        expected_raw_url = f"https://laws.e-gov.go.jp/api/2/law_file/xml/{revision_id}"
        expected_metadata_url = f"https://laws.e-gov.go.jp/api/2/law_data/{revision_id}"
        if source["raw_url"] != expected_raw_url or source["metadata_url"] != expected_metadata_url:
            _invalid("e-Gov URLs must pin the declared revision_id")
        if spec["expected_metadata_sha256"] is None:
            _invalid("e-Gov source requires expected_metadata_sha256")
        if source["effective_from"] is None:
            _invalid("e-Gov source requires an explicit effective_from date")

    extraction = spec["extraction"]
    _shape(extraction, {"profile", "version", "definition_sha256"}, "spec.extraction")
    if (extraction["profile"], extraction["version"]) != (
            EXTRACTION_PROFILE, EXTRACTION_PROFILE_VERSION):
        _invalid("spec.extraction: unsupported extraction profile", "UNSUPPORTED")
    if extraction["definition_sha256"] != EXTRACTION_DEFINITION_SHA256:
        _invalid("spec.extraction.definition_sha256 does not match this implementation",
                 "SOURCE_MISMATCH")

    units = spec["units"]
    if type(units) is not list or not 1 <= len(units) <= MAX_SOURCE_UNITS:
        _invalid(f"spec.units: expected 1..{MAX_SOURCE_UNITS} entries")
    keys, paths = set(), set()
    by_key = {}
    for index, unit in enumerate(units):
        path = f"spec.units[{index}]"
        _shape(unit, {"unit_key", "structural_kind", "structural_path", "expected_text"}, path)
        _identifier(unit["unit_key"], path + ".unit_key")
        _identifier(unit["structural_kind"], path + ".structural_kind")
        if kind == "egov_api_v2" and unit["structural_kind"] != "article":
            _invalid(f"{path}.structural_kind: e-Gov units must use 'article'")
        _structural_path(unit["structural_path"], path + ".structural_path")
        _text(unit["expected_text"], path + ".expected_text", maximum=262_144)
        if unit["unit_key"] in keys or unit["structural_path"] in paths:
            _invalid(f"{path}: duplicate unit_key or structural_path")
        keys.add(unit["unit_key"])
        paths.add(unit["structural_path"])
        by_key[unit["unit_key"]] = unit

    references = spec["references"]
    if type(references) is not list or len(references) > MAX_REFERENCES:
        _invalid(f"spec.references: expected at most {MAX_REFERENCES} entries")
    reference_ids = set()
    for index, reference in enumerate(references):
        path = f"spec.references[{index}]"
        _shape(reference, {"reference_id", "from_unit_key", "literal", "status",
                           "target_unit_key"}, path)
        _identifier(reference["reference_id"], path + ".reference_id")
        _identifier(reference["from_unit_key"], path + ".from_unit_key")
        _text(reference["literal"], path + ".literal", maximum=2048)
        if reference["reference_id"] in reference_ids:
            _invalid(f"{path}: duplicate reference_id")
        reference_ids.add(reference["reference_id"])
        if reference["from_unit_key"] not in by_key:
            _invalid(f"{path}: unknown from_unit_key")
        if reference["literal"] not in by_key[reference["from_unit_key"]]["expected_text"]:
            _invalid(f"{path}: literal is absent from the declared source unit")
        status = reference["status"]
        target = reference["target_unit_key"]
        if status == "unresolved":
            if target is not None:
                _invalid(f"{path}: unresolved reference must have null target_unit_key")
        elif status == "resolved":
            if type(target) is not str or target not in by_key:
                _invalid(f"{path}: resolved reference requires a selected target unit")
        else:
            _invalid(f"{path}: unsupported reference status {status!r}", "UNSUPPORTED")

    if len(source_canonical_json(spec).encode("utf-8")) > MAX_SOURCE_SPEC_BYTES:
        raise KernelError("LIMIT_REACHED", "Source specification exceeds its byte limit")


def source_unit_id(source, unit) -> str:
    return source_digest({
        "id_profile": "source-unit-id/1",
        "document_id": source["document_id"],
        "revision_id": source["revision_id"],
        "structural_kind": unit["structural_kind"],
        "structural_path": unit["structural_path"],
    })
