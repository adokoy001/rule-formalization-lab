"""Producer and atomic publisher for immutable source packages."""
from __future__ import annotations

from datetime import datetime, timezone
import ctypes
import errno
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import sys
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .model import KernelError
from .source_model import (
    CONTEXT_CHARS,
    EXTRACTION_DEFINITION_SHA256,
    EXTRACTION_PROFILE,
    EXTRACTION_PROFILE_VERSION,
    MAX_METADATA_BYTES,
    MAX_SOURCE_BYTES,
    MAX_XML_DEPTH,
    MAX_XML_NODES,
    RETRIEVAL_FORMAT,
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

_TAG = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")
_XML_DECLARATION = re.compile(r"^\s*<\?xml\s+[^>]*encoding\s*=\s*['\"]([^'\"]+)['\"]",
                              re.IGNORECASE)
_EGOV_ARTICLE_TAGS = {
    "Article", "ArticleCaption", "ArticleTitle", "Paragraph", "ParagraphNum",
    "ParagraphSentence", "Sentence", "Ruby", "Rt",
}
_EGOV_LAYOUT_CONTAINERS = {"Article", "Paragraph", "ParagraphSentence"}
_EGOV_CHILDREN = {
    "Article": {"ArticleCaption", "ArticleTitle", "Paragraph"},
    "ArticleCaption": {"Ruby"},
    "ArticleTitle": {"Ruby"},
    "Paragraph": {"ParagraphNum", "ParagraphSentence"},
    "ParagraphNum": {"Ruby"},
    "ParagraphSentence": {"Sentence"},
    "Sentence": {"Ruby"},
}
_ERA_YEAR_BASE = {"Meiji": 1867, "Taisho": 1911, "Showa": 1925,
                  "Heisei": 1988, "Reiwa": 2018}


def _read_limited(path, limit: int, label: str) -> bytes:
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise KernelError("LIMIT_REACHED", f"{label} exceeds {limit} bytes")
    return raw


def _decode_xml(raw: bytes):
    if len(raw) > MAX_SOURCE_BYTES:
        raise KernelError("LIMIT_REACHED", "Raw source exceeds its byte limit")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise KernelError("SOURCE_INVALID", "UTF-8 BOM is outside xml-unit-text/2")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise KernelError("SOURCE_INVALID", f"Raw source is not strict UTF-8: {exc}") from exc
    declaration = _XML_DECLARATION.match(text)
    if declaration is not None and declaration.group(1).lower().replace("_", "-") != "utf-8":
        raise KernelError("SOURCE_INVALID", "XML declaration must specify UTF-8")
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise KernelError("UNSUPPORTED", "DTD and entity declarations are not supported")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        root = ElementTree.fromstring(normalized)
    except ElementTree.ParseError as exc:
        raise KernelError("SOURCE_INVALID", f"Malformed XML source: {exc}") from exc

    count = 0

    def inspect(element, depth):
        nonlocal count
        count += 1
        if count > MAX_XML_NODES:
            raise KernelError("LIMIT_REACHED", "XML exceeds the node limit")
        if depth > MAX_XML_DEPTH:
            raise KernelError("LIMIT_REACHED", "XML exceeds the depth limit")
        if type(element.tag) is not str or _TAG.fullmatch(element.tag) is None:
            raise KernelError("UNSUPPORTED", f"Unsupported XML tag {element.tag!r}")
        for child in element:
            inspect(child, depth + 1)

    inspect(root, 1)
    return root


def _path_index(root):
    paths = {}
    order = 0

    def visit(element, path):
        nonlocal order
        paths[path] = (element, order)
        order += 1
        counts = {}
        for child in element:
            tag = child.tag
            counts[tag] = counts.get(tag, 0) + 1
            visit(child, f"{path}/{tag}[{counts[tag]}]")

    visit(root, f"/{root.tag}[1]")
    return paths


def _render_unit(element, source_kind: str) -> str:
    pieces = []

    def append(value, parent_tag):
        if value is None:
            return
        if source_kind == "egov_api_v2" and parent_tag in _EGOV_LAYOUT_CONTAINERS:
            if value == "" or value.isspace():
                return
            raise KernelError(
                "UNSUPPORTED", f"Operative text directly inside e-Gov {parent_tag}")
        pieces.append(value)

    def visit(node, parent=None):
        if node.tag == "Rt":
            if parent is None or parent.tag != "Ruby" or list(node):
                raise KernelError("UNSUPPORTED", "Rt is only supported as a leaf child of Ruby")
            return
        children = list(node)
        if node.tag == "Ruby":
            if (type(node.text) is not str or not node.text or len(children) != 1
                    or children[0].tag != "Rt" or not children[0].text
                    or children[0].tail not in {None, ""}):
                raise KernelError(
                    "UNSUPPORTED",
                    "Ruby must have base text and exactly one direct nonempty Rt leaf",
                )
        elif source_kind == "egov_api_v2":
            allowed = _EGOV_CHILDREN.get(node.tag)
            if allowed is None or any(child.tag not in allowed for child in children):
                raise KernelError(
                    "UNSUPPORTED", f"Unsupported child structure in e-Gov {node.tag}")
        append(node.text, node.tag)
        for child in node:
            visit(child, node)
            append(child.tail, node.tag)

    visit(element)
    return "".join(pieces)


def _render_law_title(element) -> str:
    if element.tag != "LawTitle" or any(child.tag != "Ruby" for child in element):
        raise KernelError("UNSUPPORTED", "e-Gov LawTitle structure is unsupported")
    return _render_unit(element, "fictional_xml")


def _validate_egov_metadata(metadata: bytes, spec):
    parsed = decode_source_json(metadata, max_bytes=MAX_METADATA_BYTES,
                                label="e-Gov law_data response")
    if type(parsed) is not dict:
        raise KernelError("SOURCE_MISMATCH", "e-Gov metadata response is not an object")
    law_info, revision_info = parsed.get("law_info"), parsed.get("revision_info")
    if type(law_info) is not dict or type(revision_info) is not dict:
        raise KernelError("SOURCE_MISMATCH", "e-Gov metadata lacks law_info/revision_info")
    source = spec["source"]
    if law_info.get("law_id") != source["law_id"]:
        raise KernelError("SOURCE_MISMATCH", "e-Gov metadata law_id does not match the spec")
    if revision_info.get("law_revision_id") != source["revision_id"]:
        raise KernelError("SOURCE_MISMATCH", "e-Gov metadata revision_id does not match the spec")
    if revision_info.get("amendment_enforcement_date") != source["effective_from"]:
        raise KernelError("SOURCE_MISMATCH", "e-Gov enforcement date does not match the spec")
    return parsed


def _validate_egov_response_pair(raw: bytes, metadata) -> None:
    root = _decode_xml(raw)
    if root.tag != "Law":
        raise KernelError("SOURCE_MISMATCH", "e-Gov XML root is not Law")
    law_info = metadata["law_info"]
    attributes = {
        "LawType": law_info.get("law_type"),
        "Era": law_info.get("law_num_era"),
        "Year": (None if type(law_info.get("law_num_year")) is not int
                 else str(law_info["law_num_year"])),
        "Num": law_info.get("law_num_num"),
    }
    if any(type(value) is not str or root.get(name) != value
           for name, value in attributes.items()):
        raise KernelError("SOURCE_MISMATCH", "e-Gov XML law attributes differ from law_data")
    era_base = _ERA_YEAR_BASE.get(root.get("Era"))
    try:
        gregorian_year = era_base + int(root.get("Year")) if era_base is not None else None
    except (TypeError, ValueError):
        gregorian_year = None
    xml_date = (None if gregorian_year is None else
                f'{gregorian_year:04d}-{root.get("PromulgateMonth")}-{root.get("PromulgateDay")}')
    if law_info.get("promulgation_date") != xml_date:
        raise KernelError("SOURCE_MISMATCH", "e-Gov XML promulgation date differs from law_data")
    body = root.find("LawBody")
    title = None if body is None else body.find("LawTitle")
    if title is None or _render_law_title(title) != metadata["revision_info"].get("law_title"):
        raise KernelError("SOURCE_MISMATCH", "e-Gov XML title differs from law_data")


def _extract(spec, raw: bytes):
    root = _decode_xml(raw)
    paths = _path_index(root)
    selected = []
    previous_order = -1
    selected_paths = []
    for unit in spec["units"]:
        path = unit["structural_path"]
        found = paths.get(path)
        if found is None:
            raise KernelError("SOURCE_MISMATCH", f"Selected structural path is absent: {path}")
        element, order = found
        if order <= previous_order:
            raise KernelError("SOURCE_INVALID", "Selected units must follow XML document order")
        if any(path.startswith(parent + "/") or parent.startswith(path + "/")
               for parent in selected_paths):
            raise KernelError("SOURCE_INVALID", "Selected source units must not overlap")
        previous_order = order
        selected_paths.append(path)
        if spec["source"]["kind"] == "egov_api_v2":
            required_prefix = "/Law[1]/LawBody[1]/MainProvision[1]/"
            if not path.startswith(required_prefix) or element.tag != "Article":
                raise KernelError("UNSUPPORTED", "e-Gov v2 selects Article units in MainProvision only")
            unsupported = sorted({item.tag for item in element.iter()} - _EGOV_ARTICLE_TAGS)
            if unsupported:
                raise KernelError("UNSUPPORTED",
                                  f"Selected e-Gov Article contains unsupported tags {unsupported}")
        actual = _render_unit(element, spec["source"]["kind"])
        if actual != unit["expected_text"]:
            raise KernelError("SOURCE_MISMATCH",
                              f"Extracted text differs for unit {unit['unit_key']}")
        selected.append((unit, actual))

    extracted_text = "\n".join(text for _, text in selected)
    rows = []
    cursor = 0
    for index, (unit, exact) in enumerate(selected):
        start = cursor
        end = start + len(exact)
        cursor = end + (1 if index + 1 < len(selected) else 0)
        rows.append({
            "index": index,
            "unit_key": unit["unit_key"],
            "source_unit_id": source_unit_id(spec["source"], unit),
            "structural_kind": unit["structural_kind"],
            "structural_path": unit["structural_path"],
            "start_codepoint": start,
            "end_codepoint": end,
            "exact": exact,
            "text_sha256": sha256_bytes(exact.encode("utf-8")),
        })
    for row in rows:
        start, end = row["start_codepoint"], row["end_codepoint"]
        row["prefix"] = extracted_text[max(0, start - CONTEXT_CHARS):start]
        row["suffix"] = extracted_text[end:end + CONTEXT_CHARS]
    return extracted_text, rows


def _source_unit_manifest(spec, raw: bytes, extracted_text: str, rows):
    ids = {row["unit_key"]: row["source_unit_id"] for row in rows}
    references = []
    for item in spec["references"]:
        references.append({
            "reference_id": item["reference_id"],
            "from_source_unit_id": ids[item["from_unit_key"]],
            "literal": item["literal"],
            "status": item["status"],
            "target_source_unit_id": (
                None if item["target_unit_key"] is None else ids[item["target_unit_key"]]
            ),
        })
    return {
        "format": SOURCE_UNIT_MANIFEST_FORMAT,
        "source_spec_hash": source_digest(spec),
        "document_id": spec["source"]["document_id"],
        "revision_id": spec["source"]["revision_id"],
        "raw_sha256": sha256_bytes(raw),
        "text_sha256": sha256_bytes(extracted_text.encode("utf-8")),
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


def _request_record(url: str, *, final_url=None, status=None, content_type=None,
                    content_encoding=None, content_disposition=None, content_length=None):
    return {
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "content_encoding": content_encoding,
        "content_disposition": content_disposition,
        "content_length": content_length,
    }


def _local_retrieval(spec, retrieved_at: str):
    return {
        "format": RETRIEVAL_FORMAT,
        "mode": "local_import",
        "retrieved_at": retrieved_at,
        "raw_request": _request_record(spec["source"]["raw_url"]),
        "metadata_request": (
            None if spec["source"]["metadata_url"] is None
            else _request_record(spec["source"]["metadata_url"])
        ),
    }


def _artifact(path: str, raw: bytes, *, codepoints=None, count=None):
    result = {"path": path, "bytes": len(raw), "sha256": sha256_bytes(raw)}
    if codepoints is not None:
        result["codepoints"] = codepoints
    if count is not None:
        result["count"] = count
    return result


def _package_files(spec, raw: bytes, metadata: bytes | None, retrieval):
    validate_source_spec(spec)
    validate_retrieved_at(retrieval["retrieved_at"], "retrieval.retrieved_at")
    if sha256_bytes(raw) != spec["expected_raw_sha256"]:
        raise KernelError("SOURCE_MISMATCH", "Raw source hash differs from the capture spec")
    if spec["source"]["kind"] == "egov_api_v2":
        if metadata is None:
            raise KernelError("SOURCE_INVALID", "e-Gov source requires law_data metadata")
        if sha256_bytes(metadata) != spec["expected_metadata_sha256"]:
            raise KernelError("SOURCE_MISMATCH", "Metadata hash differs from the capture spec")
        metadata_value = _validate_egov_metadata(metadata, spec)
        _validate_egov_response_pair(raw, metadata_value)
    elif metadata is not None:
        raise KernelError("SOURCE_INVALID", "Fictional source must not have metadata")

    extracted_text, rows = _extract(spec, raw)
    text_bytes = extracted_text.encode("utf-8")
    units = _source_unit_manifest(spec, raw, extracted_text, rows)
    units_bytes = source_canonical_json(units).encode("utf-8")
    retrieval_bytes = source_canonical_json(retrieval).encode("utf-8")
    lock = {
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
            "text": _artifact(TEXT_PATH, text_bytes, codepoints=len(extracted_text)),
            "units": _artifact(UNITS_PATH, units_bytes, count=len(rows)),
            "unresolved_reference_count": sum(
                item["status"] == "unresolved" for item in spec["references"]),
        },
    }
    files = {
        RAW_PATH: raw,
        TEXT_PATH: text_bytes,
        UNITS_PATH: units_bytes,
        RETRIEVAL_PATH: retrieval_bytes,
        LOCK_PATH: source_canonical_json(lock).encode("utf-8"),
    }
    if metadata is not None:
        files[METADATA_PATH] = metadata
    return files


def _ensure_new_destination(destination) -> Path:
    path = Path(destination)
    if path.exists() or path.is_symlink():
        raise KernelError("IO_ERROR", f"Source package destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing an existing path."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise KernelError("UNSUPPORTED", "Linux renameat2 is required for atomic publication")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p,
                              ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        at_fdcwd = -100
        rename_noreplace = 1
        result = renameat2(
            at_fdcwd, os.fsencode(source.resolve()),
            at_fdcwd, os.fsencode(destination.absolute()),
            rename_noreplace,
        )
        if result != 0:
            error = ctypes.get_errno()
            if error in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
                raise KernelError(
                    "UNSUPPORTED",
                    "The destination filesystem does not support atomic no-replace "
                    "directory publication; use a local Linux filesystem",
                )
            raise OSError(error, os.strerror(error), str(destination))
        return
    if os.name == "nt":
        os.rename(source, destination)  # Windows refuses an existing destination.
        return
    raise KernelError("UNSUPPORTED", "Atomic no-replace publication is unsupported on this OS")


def _publish(spec, files, destination) -> dict:
    destination = _ensure_new_destination(destination)
    staging = Path(tempfile.mkdtemp(prefix=".source-package-", dir=destination.parent))
    try:
        for relative, content in files.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        from .source_checker import verify_source_package
        checked = verify_source_package(spec, staging)
        _rename_noreplace(staging, destination)
        return checked
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def build_source_package(spec_or_path, raw_path, destination, *, metadata_path=None,
                         retrieved_at: str) -> dict:
    spec = (load_source_json(spec_or_path, label="source capture spec")
            if not isinstance(spec_or_path, dict) else spec_or_path)
    validate_source_spec(spec)
    if Path(destination).exists() or Path(destination).is_symlink():
        raise KernelError("IO_ERROR", f"Source package destination already exists: {destination}")
    raw = _read_limited(raw_path, MAX_SOURCE_BYTES, "Raw source")
    metadata = (None if metadata_path is None
                else _read_limited(metadata_path, MAX_METADATA_BYTES, "Source metadata"))
    files = _package_files(spec, raw, metadata, _local_retrieval(spec, retrieved_at))
    return _publish(spec, files, destination)


def _header(headers, name):
    if headers is None:
        return None
    value = headers.get(name)
    return None if value is None else str(value)


def _fetch_one(url: str, accept: str, limit: int, allowed_types, *, opener, timeout: float):
    request = Request(url, headers={
        "Accept": accept,
        "Accept-Encoding": "identity",
        "User-Agent": "rule-formalization-lab-source/0.1",
    })
    response = None
    try:
        response = opener(request, timeout=timeout)
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        if status != 200:
            raise KernelError("RETRIEVAL_FAILED", f"HTTP status {status} for {url}")
        final_url = response.geturl() if hasattr(response, "geturl") else url
        if final_url != url:
            raise KernelError("RETRIEVAL_FAILED", "Redirected source URL differs from pinned URL")
        headers = getattr(response, "headers", None)
        encoding = _header(headers, "Content-Encoding")
        if encoding not in {None, "", "identity"}:
            raise KernelError("RETRIEVAL_FAILED", "Compressed HTTP representation is unsupported")
        content_type = _header(headers, "Content-Type")
        media_type = None if content_type is None else content_type.split(";", 1)[0].strip().lower()
        if media_type not in allowed_types:
            raise KernelError("RETRIEVAL_FAILED", f"Unexpected Content-Type {content_type!r}")
        body = response.read(limit + 1)
        if len(body) > limit:
            raise KernelError("LIMIT_REACHED", f"Fetched response exceeds {limit} bytes")
        content_length = _header(headers, "Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise KernelError("RETRIEVAL_FAILED", "Invalid Content-Length") from exc
            if declared_length != len(body):
                raise KernelError("RETRIEVAL_FAILED", "HTTP body length differs from Content-Length")
        record = _request_record(
            url,
            final_url=final_url,
            status=status,
            content_type=content_type,
            content_encoding=encoding,
            content_disposition=_header(headers, "Content-Disposition"),
            content_length=content_length,
        )
        return body, record
    except KernelError:
        raise
    except Exception as exc:
        raise KernelError("RETRIEVAL_FAILED", f"Failed to retrieve {url}: {exc}") from exc
    finally:
        if response is not None and hasattr(response, "close"):
            response.close()


def fetch_egov_source_package(spec_or_path, destination, *, opener=urlopen,
                              clock=None, timeout: float = 30.0) -> dict:
    spec = (load_source_json(spec_or_path, label="source capture spec")
            if not isinstance(spec_or_path, dict) else spec_or_path)
    validate_source_spec(spec)
    if spec["source"]["kind"] != "egov_api_v2":
        raise KernelError("UNSUPPORTED", "Network capture is limited to e-Gov API v2")
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        raise KernelError("SOURCE_INVALID", "Capture timeout must be a finite positive number")
    _ensure_new_destination(destination)
    raw, raw_record = _fetch_one(
        spec["source"]["raw_url"],
        "application/octet-stream, application/xml;q=0.9",
        MAX_SOURCE_BYTES,
        {"application/octet-stream", "application/xml", "text/xml"},
        opener=opener,
        timeout=timeout,
    )
    metadata, metadata_record = _fetch_one(
        spec["source"]["metadata_url"],
        "application/json",
        MAX_METADATA_BYTES,
        {"application/json"},
        opener=opener,
        timeout=timeout,
    )
    now = clock() if clock is not None else datetime.now(timezone.utc)
    if isinstance(now, datetime):
        if now.tzinfo is None:
            raise KernelError("SOURCE_INVALID", "Capture clock must be timezone-aware")
        retrieved_at = now.astimezone(timezone.utc).replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    else:
        retrieved_at = now
    validate_retrieved_at(retrieved_at)
    retrieval = {
        "format": RETRIEVAL_FORMAT,
        "mode": "https",
        "retrieved_at": retrieved_at,
        "raw_request": raw_record,
        "metadata_request": metadata_record,
    }
    files = _package_files(spec, raw, metadata, retrieval)
    return _publish(spec, files, destination)
