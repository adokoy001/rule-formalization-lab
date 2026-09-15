"""Offline checker for source packages, independent of the producer module."""
from __future__ import annotations

from pathlib import Path
import re
from xml.etree import ElementTree

from .model import KernelError
from .source_model import (
    CONTEXT_CHARS,
    EXTRACTION_DEFINITION_SHA256,
    EXTRACTION_PROFILE,
    EXTRACTION_PROFILE_VERSION,
    MAX_MANIFEST_BYTES,
    MAX_METADATA_BYTES,
    MAX_SOURCE_BYTES,
    MAX_XML_DEPTH,
    MAX_XML_NODES,
    RETRIEVAL_FORMAT,
    SOURCE_CHECKER_VERSION,
    SOURCE_PACKAGE_FORMAT,
    SOURCE_UNIT_MANIFEST_FORMAT,
    decode_source_json,
    load_source_json,
    sha256_bytes,
    source_canonical_json,
    source_digest,
    source_unit_id,
    validate_retrieved_at,
    validate_source_spec,
)


RAW_PATH = "raw/source.xml"
METADATA_PATH = "raw/law-data.json"
TEXT_PATH = "derived/source.txt"
UNITS_PATH = "derived/source-units.json"
RETRIEVAL_PATH = "retrieval.json"
LOCK_PATH = "bundle.lock.json"

_TAG_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")
_ENCODING = re.compile(r"^\s*<\?xml\s+[^>]*encoding\s*=\s*['\"]([^'\"]+)['\"]",
                       re.IGNORECASE)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SUPPORTED_EGOV_TAGS = {
    "Article", "ArticleCaption", "ArticleTitle", "Paragraph", "ParagraphNum",
    "ParagraphSentence", "Sentence", "Ruby", "Rt",
}
_LAYOUT_TAGS = {"Article", "Paragraph", "ParagraphSentence"}
_CHILD_GRAMMAR = {
    "Article": {"ArticleCaption", "ArticleTitle", "Paragraph"},
    "ArticleCaption": {"Ruby"},
    "ArticleTitle": {"Ruby"},
    "Paragraph": {"ParagraphNum", "ParagraphSentence"},
    "ParagraphNum": {"Ruby"},
    "ParagraphSentence": {"Sentence"},
    "Sentence": {"Ruby"},
}
_JAPANESE_ERA_STARTS = {
    "Meiji": 1868, "Taisho": 1912, "Showa": 1926, "Heisei": 1989, "Reiwa": 2019,
}


def _fail(message: str, status: str = "SOURCE_INVALID") -> None:
    raise KernelError(status, message)


def _shape(value, fields, path: str) -> None:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _fail(f"{path}: expected object")
    missing = set(fields) - value.keys()
    extra = value.keys() - set(fields)
    if missing or extra:
        _fail(f"{path}: fields differ; missing={sorted(missing)}, extra={sorted(extra)}")


def _read(bundle: Path, relative: str, limit: int) -> bytes:
    target = bundle / relative
    if target.is_symlink() or not target.is_file():
        _fail(f"Missing or unsafe package artifact: {relative}")
    with target.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise KernelError("LIMIT_REACHED", f"Package artifact exceeds limit: {relative}")
    return value


def _canonical_artifact(raw: bytes, *, maximum: int, label: str):
    parsed = decode_source_json(raw, max_bytes=maximum, label=label)
    if source_canonical_json(parsed).encode("utf-8") != raw:
        _fail(f"{label} is not canonical UTF-8 JSON")
    return parsed


def _parse_xml_again(raw: bytes):
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail("UTF-8 BOM is outside the pinned extraction profile")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeError as exc:
        raise KernelError("SOURCE_INVALID", f"Raw source is not strict UTF-8: {exc}") from exc
    declaration = _ENCODING.match(decoded)
    if declaration and declaration.group(1).casefold().replace("_", "-") != "utf-8":
        _fail("XML encoding declaration is not UTF-8")
    folded = decoded.upper()
    if "<!DOCTYPE" in folded or "<!ENTITY" in folded:
        raise KernelError("UNSUPPORTED", "DTD/entity declarations are outside the profile")
    xml_text = decoded.replace("\r\n", "\n").replace("\r", "\n")
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise KernelError("SOURCE_INVALID", f"Malformed XML source: {exc}") from exc

    stack = [(root, 1)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_XML_NODES:
            raise KernelError("LIMIT_REACHED", "XML node limit exceeded")
        if depth > MAX_XML_DEPTH:
            raise KernelError("LIMIT_REACHED", "XML depth limit exceeded")
        if type(node.tag) is not str or _TAG_NAME.fullmatch(node.tag) is None:
            raise KernelError("UNSUPPORTED", f"Unsupported XML tag {node.tag!r}")
        stack.extend((child, depth + 1) for child in reversed(list(node)))
    return root


def _all_structural_paths(root):
    indexed = {}
    preorder = 0

    def descend(node, parent_path):
        nonlocal preorder
        indexed[parent_path] = {"node": node, "preorder": preorder}
        preorder += 1
        seen = {}
        for child in list(node):
            seen[child.tag] = seen.get(child.tag, 0) + 1
            descend(child, parent_path + f"/{child.tag}[{seen[child.tag]}]")

    descend(root, f"/{root.tag}[1]")
    return indexed


def _independent_text(node, source_kind: str) -> str:
    inspection = [(node, None)]
    while inspection:
        current, parent = inspection.pop()
        children = list(current)
        if current.tag == "Rt":
            if parent is None or parent.tag != "Ruby" or children:
                raise KernelError("UNSUPPORTED", "Rt is not a Ruby reading leaf")
            continue
        if current.tag == "Ruby":
            if (type(current.text) is not str or not current.text or len(children) != 1
                    or children[0].tag != "Rt" or not children[0].text
                    or children[0].tail not in {None, ""}):
                raise KernelError("UNSUPPORTED", "Ruby structure is outside xml-unit-text/2")
        elif source_kind == "egov_api_v2":
            allowed = _CHILD_GRAMMAR.get(current.tag)
            if allowed is None or any(child.tag not in allowed for child in children):
                raise KernelError("UNSUPPORTED", "Selected e-Gov structure is outside profile")
        inspection.extend((child, current) for child in children)

    output = []
    events = [("element", node, None)]
    while events:
        kind, value, owner = events.pop()
        if kind == "text":
            if value is None:
                continue
            if source_kind == "egov_api_v2" and owner in _LAYOUT_TAGS:
                if value == "" or value.isspace():
                    continue
                raise KernelError("UNSUPPORTED", "Operative text occurs in an e-Gov layout node")
            output.append(value)
            continue
        if value.tag == "Rt":
            continue
        children = list(value)
        for child in reversed(children):
            events.append(("text", child.tail, value.tag))
            events.append(("element", child, None))
        events.append(("text", value.text, value.tag))
    return "".join(output)


def _law_title_text(node) -> str:
    if node.tag != "LawTitle" or any(child.tag != "Ruby" for child in list(node)):
        raise KernelError("UNSUPPORTED", "Saved LawTitle structure is unsupported")
    return _independent_text(node, "fictional_xml")


def _verify_metadata_again(raw: bytes, spec):
    value = decode_source_json(raw, max_bytes=MAX_METADATA_BYTES, label="saved e-Gov metadata")
    if type(value) is not dict:
        _fail("Saved e-Gov metadata is not an object", "SOURCE_MISMATCH")
    law = value.get("law_info")
    revision = value.get("revision_info")
    if type(law) is not dict or law.get("law_id") != spec["source"]["law_id"]:
        _fail("Saved e-Gov metadata has another law_id", "SOURCE_MISMATCH")
    if (type(revision) is not dict or
            revision.get("law_revision_id") != spec["source"]["revision_id"]):
        _fail("Saved e-Gov metadata has another revision_id", "SOURCE_MISMATCH")
    effective = spec["source"]["effective_from"]
    if revision.get("amendment_enforcement_date") != effective:
        _fail("Saved e-Gov metadata has another enforcement date", "SOURCE_MISMATCH")
    return value


def _cross_check_egov_pair(raw_xml: bytes, metadata) -> None:
    root = _parse_xml_again(raw_xml)
    info = metadata["law_info"]
    comparisons = (
        (root.tag, "Law"),
        (root.get("LawType"), info.get("law_type")),
        (root.get("Era"), info.get("law_num_era")),
        (root.get("Year"), str(info.get("law_num_year"))),
        (root.get("Num"), info.get("law_num_num")),
    )
    if any(type(actual) is not str or actual != expected for actual, expected in comparisons):
        _fail("Saved XML identity differs from saved law_data", "SOURCE_MISMATCH")
    try:
        western_year = _JAPANESE_ERA_STARTS[root.get("Era")] + int(root.get("Year")) - 1
        reconstructed_date = (
            f'{western_year:04d}-{root.get("PromulgateMonth")}-{root.get("PromulgateDay")}')
    except (KeyError, TypeError, ValueError):
        reconstructed_date = None
    if info.get("promulgation_date") != reconstructed_date:
        _fail("Saved XML promulgation fields differ from saved law_data", "SOURCE_MISMATCH")
    bodies = [child for child in list(root) if child.tag == "LawBody"]
    titles = ([] if len(bodies) != 1 else
              [child for child in list(bodies[0]) if child.tag == "LawTitle"])
    if (len(titles) != 1 or
            _law_title_text(titles[0]) !=
            metadata["revision_info"].get("law_title")):
        _fail("Saved XML law title differs from saved law_data", "SOURCE_MISMATCH")


def _expected_units(spec, raw: bytes):
    root = _parse_xml_again(raw)
    indexed = _all_structural_paths(root)
    chosen = []
    last_preorder = -1
    path_history = []
    for unit in spec["units"]:
        path = unit["structural_path"]
        entry = indexed.get(path)
        if entry is None:
            _fail(f"Pinned structural path is absent: {path}", "SOURCE_MISMATCH")
        if entry["preorder"] <= last_preorder:
            _fail("Pinned units are not in source order")
        if any(path.startswith(old + "/") or old.startswith(path + "/")
               for old in path_history):
            _fail("Pinned units overlap")
        last_preorder = entry["preorder"]
        path_history.append(path)
        node = entry["node"]
        if spec["source"]["kind"] == "egov_api_v2":
            if (not path.startswith("/Law[1]/LawBody[1]/MainProvision[1]/") or
                    node.tag != "Article"):
                raise KernelError("UNSUPPORTED", "e-Gov profile accepts MainProvision Article units")
            unfamiliar = sorted({part.tag for part in node.iter()} - _SUPPORTED_EGOV_TAGS)
            if unfamiliar:
                raise KernelError("UNSUPPORTED",
                                  f"Unsupported e-Gov tags in selected Article: {unfamiliar}")
        exact = _independent_text(node, spec["source"]["kind"])
        if exact != unit["expected_text"]:
            _fail(f"Pinned quote differs at {path}", "SOURCE_MISMATCH")
        chosen.append((unit, exact))

    combined = "\n".join(text for _, text in chosen)
    rows = []
    offset = 0
    for ordinal, (unit, exact) in enumerate(chosen):
        start = offset
        stop = start + len(exact)
        offset = stop
        if ordinal != len(chosen) - 1:
            offset += 1
        rows.append({
            "index": ordinal,
            "unit_key": unit["unit_key"],
            "source_unit_id": source_unit_id(spec["source"], unit),
            "structural_kind": unit["structural_kind"],
            "structural_path": unit["structural_path"],
            "start_codepoint": start,
            "end_codepoint": stop,
            "exact": exact,
            "text_sha256": sha256_bytes(exact.encode("utf-8")),
            "prefix": combined[max(0, start - CONTEXT_CHARS):start],
            "suffix": combined[stop:stop + CONTEXT_CHARS],
        })
    return combined, rows


def _unit_document(spec, raw, text, rows):
    unit_ids = {row["unit_key"]: row["source_unit_id"] for row in rows}
    references = [{
        "reference_id": ref["reference_id"],
        "from_source_unit_id": unit_ids[ref["from_unit_key"]],
        "literal": ref["literal"],
        "status": ref["status"],
        "target_source_unit_id": (
            None if ref["target_unit_key"] is None else unit_ids[ref["target_unit_key"]]
        ),
    } for ref in spec["references"]]
    return {
        "format": SOURCE_UNIT_MANIFEST_FORMAT,
        "source_spec_hash": source_digest(spec),
        "document_id": spec["source"]["document_id"],
        "revision_id": spec["source"]["revision_id"],
        "raw_sha256": sha256_bytes(raw),
        "text_sha256": sha256_bytes(text.encode("utf-8")),
        "extraction": {
            "profile": EXTRACTION_PROFILE,
            "version": EXTRACTION_PROFILE_VERSION,
            "definition_sha256": EXTRACTION_DEFINITION_SHA256,
            "coordinate_system": "unicode-codepoint-0-based-half-open/1",
        },
        "unit_count": len(rows),
        "units": rows,
        "references": references,
    }


def _validate_request(record, expected_url: str, mode: str, *, artifact_bytes: int,
                      allowed_types) -> None:
    fields = {"requested_url", "final_url", "http_status", "content_type",
              "content_encoding", "content_disposition", "content_length"}
    _shape(record, fields, "retrieval request")
    if record["requested_url"] != expected_url:
        _fail("Retrieval URL differs from the capture spec", "SOURCE_MISMATCH")
    if mode == "local_import":
        if any(record[name] is not None for name in fields - {"requested_url"}):
            _fail("Local import must not claim HTTP response metadata")
        return
    if record["final_url"] != expected_url or type(record["http_status"]) is not int:
        _fail("HTTPS retrieval did not preserve the pinned URL/status")
    if record["http_status"] != 200:
        _fail("Saved HTTPS retrieval is not a successful response")
    content_type = record["content_type"]
    if type(content_type) is not str:
        _fail("HTTPS retrieval lacks Content-Type")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in allowed_types:
        _fail("HTTPS retrieval Content-Type is outside the capture profile")
    if record["content_encoding"] not in {None, "", "identity"}:
        _fail("HTTPS retrieval used a compressed representation")
    for name in ("content_disposition", "content_length"):
        if record[name] is not None and type(record[name]) is not str:
            _fail(f"retrieval request.{name}: expected string or null")
    if record["content_length"] is not None:
        try:
            declared = int(record["content_length"])
        except ValueError as exc:
            raise KernelError("SOURCE_INVALID", "Invalid saved Content-Length") from exc
        if declared != artifact_bytes:
            _fail("Saved Content-Length differs from artifact bytes")


def _validate_retrieval(value, spec, *, raw_bytes: int, metadata_bytes=None) -> None:
    _shape(value, {"format", "mode", "retrieved_at", "raw_request", "metadata_request"},
           "retrieval")
    if value["format"] != RETRIEVAL_FORMAT:
        _fail("Unsupported retrieval record format", "UNSUPPORTED")
    if value["mode"] not in {"local_import", "https"}:
        _fail("Unsupported retrieval mode", "UNSUPPORTED")
    if value["mode"] == "https" and spec["source"]["kind"] != "egov_api_v2":
        _fail("HTTPS capture is only defined for e-Gov v2", "UNSUPPORTED")
    validate_retrieved_at(value["retrieved_at"], "retrieval.retrieved_at")
    _validate_request(value["raw_request"], spec["source"]["raw_url"], value["mode"],
                      artifact_bytes=raw_bytes,
                      allowed_types={"application/octet-stream", "application/xml", "text/xml"})
    expected_metadata_url = spec["source"]["metadata_url"]
    if expected_metadata_url is None:
        if value["metadata_request"] is not None:
            _fail("Unexpected metadata retrieval record")
    else:
        if type(value["metadata_request"]) is not dict or metadata_bytes is None:
            _fail("Missing metadata retrieval record")
        _validate_request(value["metadata_request"], expected_metadata_url, value["mode"],
                          artifact_bytes=metadata_bytes,
                          allowed_types={"application/json"})


def _artifact(path, raw, *, codepoints=None, count=None):
    result = {"path": path, "bytes": len(raw), "sha256": sha256_bytes(raw)}
    if codepoints is not None:
        result["codepoints"] = codepoints
    if count is not None:
        result["count"] = count
    return result


def verify_source_package(spec_or_path, bundle_path, *, expected_bundle_sha256=None) -> dict:
    if (expected_bundle_sha256 is not None and
            (type(expected_bundle_sha256) is not str or
             _SHA256.fullmatch(expected_bundle_sha256) is None)):
        _fail("expected_bundle_sha256 must be 64 lowercase hexadecimal characters")
    spec = (load_source_json(spec_or_path, label="source capture spec")
            if not isinstance(spec_or_path, dict) else spec_or_path)
    validate_source_spec(spec)
    bundle = Path(bundle_path)
    if bundle.is_symlink() or not bundle.is_dir():
        _fail("Source package must be a non-symlink directory")

    expected_files = {RAW_PATH, TEXT_PATH, UNITS_PATH, RETRIEVAL_PATH, LOCK_PATH}
    if spec["source"]["kind"] == "egov_api_v2":
        expected_files.add(METADATA_PATH)
    actual_files = set()
    for item in bundle.rglob("*"):
        if item.is_symlink():
            _fail(f"Symlink is forbidden in source package: {item.relative_to(bundle)}")
        if item.is_file():
            actual_files.add(item.relative_to(bundle).as_posix())
    if actual_files != expected_files:
        _fail(f"Package file inventory differs: {sorted(actual_files ^ expected_files)}")

    raw = _read(bundle, RAW_PATH, MAX_SOURCE_BYTES)
    if sha256_bytes(raw) != spec["expected_raw_sha256"]:
        _fail("Raw source differs from the capture spec", "SOURCE_MISMATCH")
    metadata = None
    if METADATA_PATH in expected_files:
        metadata = _read(bundle, METADATA_PATH, MAX_METADATA_BYTES)
        if sha256_bytes(metadata) != spec["expected_metadata_sha256"]:
            _fail("Saved metadata differs from the capture spec", "SOURCE_MISMATCH")
        metadata_value = _verify_metadata_again(metadata, spec)
        _cross_check_egov_pair(raw, metadata_value)

    text_bytes = _read(bundle, TEXT_PATH, MAX_SOURCE_BYTES)
    units_bytes = _read(bundle, UNITS_PATH, MAX_MANIFEST_BYTES)
    retrieval_bytes = _read(bundle, RETRIEVAL_PATH, 256 * 1024)
    lock_bytes = _read(bundle, LOCK_PATH, MAX_MANIFEST_BYTES)
    actual_bundle_hash = sha256_bytes(lock_bytes)
    if (expected_bundle_sha256 is not None and
            actual_bundle_hash != expected_bundle_sha256):
        _fail("Package lock differs from the external bundle hash", "SOURCE_MISMATCH")
    retrieval = _canonical_artifact(retrieval_bytes, maximum=256 * 1024,
                                    label="retrieval.json")
    _validate_retrieval(retrieval, spec, raw_bytes=len(raw),
                        metadata_bytes=None if metadata is None else len(metadata))
    _canonical_artifact(units_bytes, maximum=MAX_MANIFEST_BYTES,
                        label="derived/source-units.json")
    lock = _canonical_artifact(lock_bytes, maximum=MAX_MANIFEST_BYTES,
                               label="bundle.lock.json")

    derived_text, rows = _expected_units(spec, raw)
    expected_text_bytes = derived_text.encode("utf-8")
    if text_bytes != expected_text_bytes:
        _fail("Stored extracted text differs from independent extraction")
    expected_units = _unit_document(spec, raw, derived_text, rows)
    expected_units_bytes = source_canonical_json(expected_units).encode("utf-8")
    if units_bytes != expected_units_bytes:
        _fail("Stored source unit manifest differs from independent reconstruction")

    expected_lock = {
        "format": SOURCE_PACKAGE_FORMAT,
        "source_spec_hash": source_digest(spec),
        "source_document": {
            "document_id": spec["source"]["document_id"],
            "jurisdiction": spec["source"]["jurisdiction"],
            "law_id": spec["source"]["law_id"],
            "revision_id": spec["source"]["revision_id"],
            "effective_from": spec["source"]["effective_from"],
            "raw": _artifact(RAW_PATH, raw),
            "metadata": None if metadata is None else _artifact(METADATA_PATH, metadata),
            "retrieval": _artifact(RETRIEVAL_PATH, retrieval_bytes),
        },
        "source_unit_manifest": {
            "extraction_profile": EXTRACTION_PROFILE,
            "extraction_version": EXTRACTION_PROFILE_VERSION,
            "extraction_definition_sha256": EXTRACTION_DEFINITION_SHA256,
            "text": _artifact(TEXT_PATH, expected_text_bytes, codepoints=len(derived_text)),
            "units": _artifact(UNITS_PATH, expected_units_bytes, count=len(rows)),
            "unresolved_reference_count": sum(
                ref["status"] == "unresolved" for ref in spec["references"]),
        },
    }
    if lock != expected_lock:
        _fail("Package lock differs from independently reconstructed artifacts")

    return {
        "status": "VERIFIED",
        "source_package_format": SOURCE_PACKAGE_FORMAT,
        "source_spec_hash": source_digest(spec),
        "bundle_hash": actual_bundle_hash,
        "bundle_hash_anchored": expected_bundle_sha256 is not None,
        "raw_sha256": sha256_bytes(raw),
        "text_sha256": sha256_bytes(expected_text_bytes),
        "source_unit_manifest_sha256": sha256_bytes(expected_units_bytes),
        "unit_count": len(rows),
        "unresolved_reference_count": sum(
            ref["status"] == "unresolved" for ref in spec["references"]),
        "document_id": spec["source"]["document_id"],
        "revision_id": spec["source"]["revision_id"],
        "retrieved_at": retrieval["retrieved_at"],
        "effective_from": spec["source"]["effective_from"],
        "offline": True,
        "checker_version": SOURCE_CHECKER_VERSION,
    }
