"""Source package extraction, capture, tamper, and retrieval tests."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import errno
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from rulekernel.model import KernelError
from rulekernel.source_checker import verify_source_package
from rulekernel.source_model import (
    EXTRACTION_DEFINITION_SHA256,
    EXTRACTION_PROFILE,
    EXTRACTION_PROFILE_VERSION,
    sha256_bytes,
    source_canonical_json,
    validate_source_spec,
)
from rulekernel.source_package import build_source_package, fetch_egov_source_package


TEXT_1 = "第1条\nA👩‍⚖️e\u0301 & 同じ文。"
TEXT_2 = "第2条\nA👩‍⚖️e\u0301 & 同じ文。"
TEXT_3 = "第3条　賭博は別に定める。"
FICTIONAL_RAW = (
    '<?xml version="1.0" encoding="UTF-8"?>\r\n'
    '<RuleSource><Unit>第1条\r\nA👩‍⚖️e\u0301 &amp; 同じ文。</Unit>'
    '<Unit>第2条\r\nA👩‍⚖️e\u0301 &amp; 同じ文。</Unit>'
    '<Unit>第3条　<Ruby>賭<Rt>と</Rt></Ruby>博は別に定める。</Unit>'
    '</RuleSource>'
).encode("utf-8")


def fictional_spec(raw=FICTIONAL_RAW, *, revision="fictional-r1", text_1=TEXT_1):
    return {
        "format": "rule-source-capture-spec/1",
        "source": {
            "kind": "fictional_xml",
            "document_id": "unicode_fixture",
            "jurisdiction": "fictional",
            "law_id": None,
            "revision_id": revision,
            "raw_url": f"urn:rule-source:unicode:{revision}",
            "metadata_url": None,
            "effective_from": "2026-09-15",
        },
        "expected_raw_sha256": sha256_bytes(raw),
        "expected_metadata_sha256": None,
        "extraction": {
            "profile": EXTRACTION_PROFILE,
            "version": EXTRACTION_PROFILE_VERSION,
            "definition_sha256": EXTRACTION_DEFINITION_SHA256,
        },
        "units": [
            {"unit_key": "U1", "structural_kind": "rule",
             "structural_path": "/RuleSource[1]/Unit[1]", "expected_text": text_1},
            {"unit_key": "U2", "structural_kind": "rule",
             "structural_path": "/RuleSource[1]/Unit[2]", "expected_text": TEXT_2},
            {"unit_key": "U3", "structural_kind": "rule",
             "structural_path": "/RuleSource[1]/Unit[3]", "expected_text": TEXT_3},
        ],
        "references": [
            {"reference_id": "REF1", "from_unit_key": "U3", "literal": "別に定める",
             "status": "unresolved", "target_unit_key": None},
        ],
    }


def egov_fixture():
    law_id = "140AC0000000045"
    revision = law_id + "_20260521_507AC0000000039"
    raw = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Law Era="Meiji" Year="40" Num="045" PromulgateMonth="04" '
        'PromulgateDay="24" LawType="Act"><LawBody><LawTitle>刑法</LawTitle>'
        '<MainProvision><Article Num="41">\n  '
        '<ArticleCaption>（責任年齢）</ArticleCaption>\n  '
        '<ArticleTitle>第四十一条</ArticleTitle>\n  '
        '<Paragraph Num="1">\n    <ParagraphNum/>\n    <ParagraphSentence>\n      '
        '<Sentence Num="1">十四歳に満たない者の行為は、罰しない。</Sentence>'
        '\n    </ParagraphSentence>\n  </Paragraph>\n</Article></MainProvision>'
        '<SupplProvision><Article Num="41"><ArticleTitle>第四十一条</ArticleTitle>'
        '<Paragraph Num="1"><ParagraphNum/><ParagraphSentence>'
        '<Sentence Num="1">附則側の同じ条番号。</Sentence>'
        '</ParagraphSentence></Paragraph></Article></SupplProvision>'
        '</LawBody></Law>'
    ).encode("utf-8")
    metadata_obj = {
        "law_info": {
            "law_id": law_id,
            "law_type": "Act",
            "law_num_era": "Meiji",
            "law_num_year": 40,
            "law_num_num": "045",
            "promulgation_date": "1907-04-24",
        },
        "revision_info": {
            "law_revision_id": revision,
            "law_title": "刑法",
            "amendment_enforcement_date": "2026-05-21",
        },
        "law_full_text": None,
    }
    metadata = source_canonical_json(metadata_obj).encode("utf-8")
    spec = {
        "format": "rule-source-capture-spec/1",
        "source": {
            "kind": "egov_api_v2",
            "document_id": "jp_penal_code",
            "jurisdiction": "JP",
            "law_id": law_id,
            "revision_id": revision,
            "raw_url": f"https://laws.e-gov.go.jp/api/2/law_file/xml/{revision}",
            "metadata_url": f"https://laws.e-gov.go.jp/api/2/law_data/{revision}",
            "effective_from": "2026-05-21",
        },
        "expected_raw_sha256": sha256_bytes(raw),
        "expected_metadata_sha256": sha256_bytes(metadata),
        "extraction": {
            "profile": EXTRACTION_PROFILE, "version": EXTRACTION_PROFILE_VERSION,
            "definition_sha256": EXTRACTION_DEFINITION_SHA256,
        },
        "units": [{
            "unit_key": "ARTICLE_41",
            "structural_kind": "article",
            "structural_path": "/Law[1]/LawBody[1]/MainProvision[1]/Article[1]",
            "expected_text": "（責任年齢）第四十一条十四歳に満たない者の行為は、罰しない。",
        }],
        "references": [],
    }
    return spec, raw, metadata


class FakeResponse:
    def __init__(self, body, content_type, url, *, length=None, status=200):
        self.body = body
        self.status = status
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body) if length is None else length),
            "Content-Encoding": "identity",
            "Content-Disposition": "attachment; filename=source.xml",
        }
        self.url = url
        self.closed = False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]

    def geturl(self):
        return self.url

    def close(self):
        self.closed = True


class SourcePackageTestCase(unittest.TestCase):
    def assert_status(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)

    def create_fictional(self, folder, *, spec=None):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        spec = fictional_spec() if spec is None else spec
        raw_path = folder / "input.xml"
        raw_path.write_bytes(FICTIONAL_RAW)
        bundle = folder / "bundle"
        result = build_source_package(
            spec, raw_path, bundle, retrieved_at="2026-09-15T10:00:00Z")
        return spec, bundle, result


class SourceRoundTripTests(SourcePackageTestCase):
    def test_saved_examples_verify_offline_against_recorded_external_hashes(self):
        project = Path(__file__).resolve().parents[1]
        cases = (
            ("fictional-unicode",
             "baeba5fb46ac6fb33aa5a31983ea58ab9d2a484cc26222dec256fb26f27bec50"),
            ("penal-code-41",
             "60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060"),
            ("criminal-procedure-55-203-206",
             "6c8510b9c9022c6d4974bd1cc00fffdcd85b1ca4547f1027c644b68c5dc9a7fe"),
        )
        with mock.patch("socket.socket", side_effect=AssertionError("network access")):
            for name, expected_hash in cases:
                with self.subTest(name=name):
                    folder = project / "examples/sources" / name
                    checked = verify_source_package(
                        folder / "source-spec.json", folder / "bundle",
                        expected_bundle_sha256=expected_hash)
                    self.assertEqual(checked["status"], "VERIFIED")
                    self.assertTrue(checked["offline"])
                    self.assertTrue(checked["bundle_hash_anchored"])

    def test_unicode_crlf_entities_ruby_repetition_and_offline_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            spec, bundle, result = self.create_fictional(temp)
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual((result["unit_count"], result["unresolved_reference_count"]),
                             (3, 1))
            self.assertTrue(result["offline"])
            units = json.loads((bundle / "derived/source-units.json").read_bytes())
            rows = units["units"]
            self.assertEqual((rows[0]["start_codepoint"], rows[0]["end_codepoint"]),
                             (0, 18))
            self.assertEqual((rows[1]["start_codepoint"], rows[1]["end_codepoint"]),
                             (19, 37))
            self.assertEqual((rows[2]["start_codepoint"], rows[2]["end_codepoint"]),
                             (38, 51))
            self.assertNotEqual(rows[0]["source_unit_id"], rows[1]["source_unit_id"])
            self.assertIn("A👩‍⚖️e\u0301 & 同じ文。", rows[0]["exact"])
            self.assertIn("賭博", rows[2]["exact"])
            self.assertNotIn("賭と博", rows[2]["exact"])
            expected = TEXT_1 + "\n" + TEXT_2 + "\n" + TEXT_3
            self.assertEqual((bundle / "derived/source.txt").read_bytes(), expected.encode("utf-8"))
            checked = verify_source_package(spec, bundle)
            self.assertEqual(checked, result)

    def test_lock_json_scalar_type_changes_are_rejected_without_external_anchor(self):
        with tempfile.TemporaryDirectory() as temp:
            spec, bundle, _ = self.create_fictional(temp)
            lock_path = bundle / "bundle.lock.json"
            lock = json.loads(lock_path.read_bytes())
            count = lock["source_unit_manifest"]["units"]["count"]
            lock["source_unit_manifest"]["units"]["count"] = float(count)
            lock_path.write_bytes(source_canonical_json(lock).encode("utf-8"))
            self.assert_status("SOURCE_INVALID", verify_source_package, spec, bundle)

    def test_checker_has_no_network_or_producer_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            spec, bundle, _ = self.create_fictional(temp)
            import inspect
            import rulekernel.source_checker as checker
            source = inspect.getsource(checker)
            self.assertNotIn("from .source_package import", source)
            self.assertEqual(verify_source_package(spec, bundle)["status"], "VERIFIED")

    def test_main_provision_path_distinguishes_same_numbered_supplement_article(self):
        spec, raw, metadata = egov_fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path, metadata_path = root / "law.xml", root / "law-data.json"
            raw_path.write_bytes(raw)
            metadata_path.write_bytes(metadata)
            result = build_source_package(
                spec, raw_path, root / "bundle", metadata_path=metadata_path,
                retrieved_at="2026-09-15T10:01:00Z")
            self.assertEqual(result["unit_count"], 1)
            text = (root / "bundle/derived/source.txt").read_text(encoding="utf-8")
            self.assertIn("責任年齢", text)
            self.assertNotIn("附則側", text)

    def test_content_whitespace_is_preserved_but_block_indentation_is_not(self):
        spec, raw, metadata = egov_fixture()
        replacement = "者の <Ruby>行<Rt>こう</Rt></Ruby>　為"
        changed = raw.replace("者の行為".encode(), replacement.encode())
        changed_spec = deepcopy(spec)
        changed_spec["expected_raw_sha256"] = sha256_bytes(changed)
        changed_spec["units"][0]["expected_text"] = (
            spec["units"][0]["expected_text"].replace("者の行為", "者の 行　為"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path, metadata_path = root / "law.xml", root / "law-data.json"
            raw_path.write_bytes(changed)
            metadata_path.write_bytes(metadata)
            build_source_package(
                changed_spec, raw_path, root / "bundle", metadata_path=metadata_path,
                retrieved_at="2026-09-15T10:01:00Z")
            actual = (root / "bundle/derived/source.txt").read_text(encoding="utf-8")
            self.assertEqual(actual, changed_spec["units"][0]["expected_text"])

    def test_fictional_mixed_content_preserves_ascii_and_ideographic_space(self):
        old = '<Unit>第1条\r\nA👩‍⚖️e\u0301 &amp; 同じ文。</Unit>'.encode("utf-8")
        new = '<Unit>A<X>B</X> <X>C</X>　</Unit>'.encode("utf-8")
        raw = FICTIONAL_RAW.replace(old, new)
        spec = fictional_spec(raw, text_1="AB C　")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path = root / "source.xml"
            raw_path.write_bytes(raw)
            build_source_package(
                spec, raw_path, root / "bundle",
                retrieved_at="2026-09-15T10:01:00Z")
            units = json.loads((root / "bundle/derived/source-units.json").read_bytes())
            self.assertEqual(units["units"][0]["exact"], "AB C　")


class SourceValidationTests(SourcePackageTestCase):
    def test_egov_xml_and_metadata_identity_must_agree(self):
        spec, raw, metadata = egov_fixture()
        changed = raw.replace("<LawTitle>刑法</LawTitle>".encode(),
                              "<LawTitle>別法</LawTitle>".encode(), 1)
        spec["expected_raw_sha256"] = sha256_bytes(changed)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path, metadata_path = root / "law.xml", root / "law-data.json"
            raw_path.write_bytes(changed)
            metadata_path.write_bytes(metadata)
            self.assert_status(
                "SOURCE_MISMATCH", build_source_package, spec, raw_path, root / "bundle",
                metadata_path=metadata_path, retrieved_at="2026-09-15T10:00:00Z")

    def test_rt_outside_ruby_malformed_ruby_and_block_text_are_rejected(self):
        ruby = "<Ruby>賭<Rt>と</Rt></Ruby>"
        fictional_variants = [
            "<Rt>OPERATIVE</Rt>",
            "<Ruby><X>賭</X><Rt>と</Rt></Ruby>",
            "<Ruby>賭<Rt>と</Rt><Rt>ばく</Rt></Ruby>",
            "<Ruby>賭<Rt><X>と</X></Rt></Ruby>",
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, replacement in enumerate(fictional_variants):
                raw = FICTIONAL_RAW.replace(ruby.encode(), replacement.encode())
                raw_path = root / f"ruby-{index}.xml"
                raw_path.write_bytes(raw)
                with self.subTest(kind="ruby", index=index):
                    self.assert_status(
                        "UNSUPPORTED", build_source_package, fictional_spec(raw), raw_path,
                        root / f"ruby-bundle-{index}",
                        retrieved_at="2026-09-15T10:00:00Z")

            spec, raw, metadata = egov_fixture()
            raw = raw.replace(b'<Article Num="41">', b'<Article Num="41">OPERATIVE', 1)
            spec["expected_raw_sha256"] = sha256_bytes(raw)
            raw_path, metadata_path = root / "block.xml", root / "metadata.json"
            raw_path.write_bytes(raw)
            metadata_path.write_bytes(metadata)
            self.assert_status(
                "UNSUPPORTED", build_source_package, spec, raw_path, root / "block-bundle",
                metadata_path=metadata_path, retrieved_at="2026-09-15T10:00:00Z")

    def test_wrong_quote_missing_path_order_overlap_and_reference_are_rejected(self):
        variants = []
        wrong_quote = fictional_spec(text_1=TEXT_1 + "欠落")
        variants.append(("SOURCE_MISMATCH", wrong_quote))
        missing = fictional_spec()
        missing["units"][0]["structural_path"] = "/RuleSource[1]/Unit[4]"
        variants.append(("SOURCE_MISMATCH", missing))
        reversed_spec = fictional_spec()
        reversed_spec["units"][0], reversed_spec["units"][1] = (
            reversed_spec["units"][1], reversed_spec["units"][0])
        variants.append(("SOURCE_INVALID", reversed_spec))
        overlapping = fictional_spec()
        overlapping["units"][1]["structural_path"] = "/RuleSource[1]"
        variants.append(("SOURCE_INVALID", overlapping))
        missing_reference = fictional_spec()
        missing_reference["references"][0]["literal"] = "存在しない引用"
        variants.append(("SOURCE_INVALID", missing_reference))
        with tempfile.TemporaryDirectory() as temp:
            raw_path = Path(temp) / "input.xml"
            raw_path.write_bytes(FICTIONAL_RAW)
            for index, (status, spec) in enumerate(variants):
                with self.subTest(index=index, status=status):
                    self.assert_status(
                        status, build_source_package, spec, raw_path, Path(temp) / f"b{index}",
                        retrieved_at="2026-09-15T10:00:00Z")

    def test_invalid_encoding_bom_doctype_and_declared_encoding_are_rejected(self):
        variants = [
            b"<RuleSource><Unit>\xff</Unit></RuleSource>",
            b"\xef\xbb\xbf<RuleSource><Unit>x</Unit></RuleSource>",
            b'<?xml version="1.0" encoding="Shift_JIS"?><RuleSource><Unit>x</Unit></RuleSource>',
            b'<!DOCTYPE x [<!ENTITY e "x">]><RuleSource><Unit>&e;</Unit></RuleSource>',
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, raw in enumerate(variants):
                path = root / f"bad{index}.xml"
                path.write_bytes(raw)
                spec = {
                    **fictional_spec(),
                    "expected_raw_sha256": sha256_bytes(raw),
                    "units": [{"unit_key": "U1", "structural_kind": "rule",
                               "structural_path": "/RuleSource[1]/Unit[1]",
                               "expected_text": "x"}],
                    "references": [],
                }
                with self.subTest(index=index):
                    with self.assertRaises(KernelError) as caught:
                        build_source_package(
                            spec, path, root / f"bundle{index}",
                            retrieved_at="2026-09-15T10:00:00Z")
                    self.assertIn(caught.exception.status, {"SOURCE_INVALID", "UNSUPPORTED"})

    def test_spec_unknown_fields_bad_profile_hash_and_revision_url_are_rejected(self):
        changes = []
        extra = fictional_spec()
        extra["unknown"] = True
        changes.append(("UNSUPPORTED", extra))
        profile = fictional_spec()
        profile["extraction"]["definition_sha256"] = "0" * 64
        changes.append(("SOURCE_MISMATCH", profile))
        egov, _, _ = egov_fixture()
        egov["source"]["raw_url"] = egov["source"]["raw_url"].replace("20260521", "20260522")
        changes.append(("SOURCE_INVALID", egov))
        missing_date, _, _ = egov_fixture()
        missing_date["source"]["effective_from"] = None
        changes.append(("SOURCE_INVALID", missing_date))
        wrong_kind, _, _ = egov_fixture()
        wrong_kind["units"][0]["structural_kind"] = "banana"
        changes.append(("SOURCE_INVALID", wrong_kind))
        wrong_jurisdiction, _, _ = egov_fixture()
        wrong_jurisdiction["source"]["jurisdiction"] = "fictional"
        changes.append(("SOURCE_INVALID", wrong_jurisdiction))
        for status, spec in changes:
            with self.subTest(status=status):
                self.assert_status(status, validate_source_spec, spec)


class SourceTamperTests(SourcePackageTestCase):
    def test_each_artifact_tamper_is_rejected(self):
        targets = [
            "raw/source.xml", "derived/source.txt", "derived/source-units.json",
            "retrieval.json", "bundle.lock.json",
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec, original, _ = self.create_fictional(root / "original")
            for index, relative in enumerate(targets):
                with self.subTest(relative=relative):
                    copy = root / f"copy{index}"
                    shutil.copytree(original, copy)
                    path = copy / relative
                    path.write_bytes(path.read_bytes() + b" ")
                    with self.assertRaises(KernelError):
                        verify_source_package(spec, copy)

    def test_unit_deletion_duplication_reorder_and_offset_tamper_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec, original, _ = self.create_fictional(root / "original")
            mutations = {
                "delete": lambda rows: rows.pop(),
                "duplicate": lambda rows: rows.append(deepcopy(rows[0])),
                "reorder": lambda rows: rows.reverse(),
                "offset": lambda rows: rows[0].__setitem__("end_codepoint", 19),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    copy = root / name
                    shutil.copytree(original, copy)
                    units_path = copy / "derived/source-units.json"
                    units = json.loads(units_path.read_bytes())
                    mutate(units["units"])
                    units_path.write_bytes(source_canonical_json(units).encode("utf-8"))
                    with self.assertRaises(KernelError):
                        verify_source_package(spec, copy)

    def test_self_consistent_internal_rehash_still_fails_external_spec_and_reconstruction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec, bundle, _ = self.create_fictional(root / "original")
            units_path = bundle / "derived/source-units.json"
            lock_path = bundle / "bundle.lock.json"
            units = json.loads(units_path.read_bytes())
            units["units"].pop()
            units["unit_count"] = 2
            units_bytes = source_canonical_json(units).encode("utf-8")
            units_path.write_bytes(units_bytes)
            lock = json.loads(lock_path.read_bytes())
            lock["source_unit_manifest"]["units"].update({
                "bytes": len(units_bytes),
                "count": 2,
                "sha256": sha256_bytes(units_bytes),
            })
            lock_path.write_bytes(source_canonical_json(lock).encode("utf-8"))
            self.assert_status("SOURCE_INVALID", verify_source_package, spec, bundle)

    def test_external_bundle_hash_anchors_the_retrieval_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec, bundle, original = self.create_fictional(root / "original")
            expected = original["bundle_hash"]
            anchored = verify_source_package(
                spec, bundle, expected_bundle_sha256=expected)
            self.assertTrue(anchored["bundle_hash_anchored"])
            self.assertFalse(original["bundle_hash_anchored"])
            for invalid in ("0" * 63, "A" * 64, 123):
                with self.subTest(invalid=invalid):
                    self.assert_status(
                        "SOURCE_INVALID", verify_source_package, spec, bundle,
                        expected_bundle_sha256=invalid)

            retrieval_path = bundle / "retrieval.json"
            lock_path = bundle / "bundle.lock.json"
            retrieval = json.loads(retrieval_path.read_bytes())
            retrieval["retrieved_at"] = "2099-01-01T00:00:00Z"
            retrieval_bytes = source_canonical_json(retrieval).encode("utf-8")
            retrieval_path.write_bytes(retrieval_bytes)
            lock = json.loads(lock_path.read_bytes())
            lock["source_document"]["retrieval"].update({
                "bytes": len(retrieval_bytes),
                "sha256": sha256_bytes(retrieval_bytes),
            })
            lock_path.write_bytes(source_canonical_json(lock).encode("utf-8"))
            self.assertEqual(verify_source_package(spec, bundle)["status"], "VERIFIED")
            self.assert_status(
                "SOURCE_MISMATCH", verify_source_package, spec, bundle,
                expected_bundle_sha256=expected)

    def test_external_bundle_hash_rejects_local_to_https_record_reclassification(self):
        spec, raw, metadata = egov_fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path, metadata_path = root / "law.xml", root / "law-data.json"
            raw_path.write_bytes(raw)
            metadata_path.write_bytes(metadata)
            bundle = root / "bundle"
            original = build_source_package(
                spec, raw_path, bundle, metadata_path=metadata_path,
                retrieved_at="2026-09-15T10:00:00Z")

            retrieval_path = bundle / "retrieval.json"
            lock_path = bundle / "bundle.lock.json"
            retrieval = json.loads(retrieval_path.read_bytes())
            retrieval["mode"] = "https"
            for key, content_type, length in (
                    ("raw_request", "application/octet-stream", len(raw)),
                    ("metadata_request", "application/json", len(metadata))):
                record = retrieval[key]
                record.update({
                    "final_url": record["requested_url"],
                    "http_status": 200,
                    "content_type": content_type,
                    "content_encoding": "identity",
                    "content_disposition": None,
                    "content_length": str(length),
                })
            retrieval_bytes = source_canonical_json(retrieval).encode("utf-8")
            retrieval_path.write_bytes(retrieval_bytes)
            lock = json.loads(lock_path.read_bytes())
            lock["source_document"]["retrieval"].update({
                "bytes": len(retrieval_bytes),
                "sha256": sha256_bytes(retrieval_bytes),
            })
            lock_path.write_bytes(source_canonical_json(lock).encode("utf-8"))
            self.assertEqual(verify_source_package(spec, bundle)["status"], "VERIFIED")
            self.assert_status(
                "SOURCE_MISMATCH", verify_source_package, spec, bundle,
                expected_bundle_sha256=original["bundle_hash"])

    def test_other_revision_package_is_rejected_by_original_spec(self):
        raw_v2 = FICTIONAL_RAW.replace("第1条".encode(), "第一条".encode(), 1)
        text_v2 = TEXT_1.replace("第1条", "第一条")
        spec_v2 = fictional_spec(raw_v2, revision="fictional-r2", text_1=text_v2)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path = root / "v2.xml"
            raw_path.write_bytes(raw_v2)
            bundle = root / "v2"
            build_source_package(
                spec_v2, raw_path, bundle, retrieved_at="2026-09-15T10:00:00Z")
            self.assert_status("SOURCE_MISMATCH", verify_source_package,
                               fictional_spec(), bundle)

    def test_extra_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec, bundle, _ = self.create_fictional(root / "original")
            (bundle / "extra.txt").write_text("untracked", encoding="utf-8")
            self.assert_status("SOURCE_INVALID", verify_source_package, spec, bundle)

    def test_file_and_directory_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, target in (
                    ("file-link", Path("raw/source.xml")),
                    ("directory-link", Path("raw"))):
                with self.subTest(name=name):
                    spec, bundle, _ = self.create_fictional(root / name)
                    (bundle / name).symlink_to(target, target_is_directory=name == "directory-link")
                    self.assert_status("SOURCE_INVALID", verify_source_package, spec, bundle)


class SourceFetchTests(SourcePackageTestCase):
    def test_injected_https_capture_publishes_only_after_both_responses_verify(self):
        spec, raw, metadata = egov_fixture()
        responses = {
            spec["source"]["raw_url"]: FakeResponse(
                raw, "application/octet-stream", spec["source"]["raw_url"]),
            spec["source"]["metadata_url"]: FakeResponse(
                metadata, "application/json", spec["source"]["metadata_url"]),
        }

        def opener(request, timeout):
            self.assertEqual(timeout, 3.0)
            return responses[request.full_url]

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "captured"
            result = fetch_egov_source_package(
                spec, destination, opener=opener,
                clock=lambda: datetime(2026, 9, 15, 10, 2, tzinfo=timezone.utc),
                timeout=3.0)
            self.assertEqual(result["retrieved_at"], "2026-09-15T10:02:00Z")
            retrieval = json.loads((destination / "retrieval.json").read_bytes())
            self.assertEqual(retrieval["mode"], "https")
            self.assertEqual(verify_source_package(spec, destination), result)

    def test_actual_egov_header_shape_without_lengths_is_recorded(self):
        spec, raw, metadata = egov_fixture()
        raw_response = FakeResponse(raw, "application/octet-stream", spec["source"]["raw_url"])
        raw_response.headers = {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{spec["source"]["revision_id"]}.xml"',
        }
        metadata_response = FakeResponse(
            metadata, "application/json", spec["source"]["metadata_url"])
        metadata_response.headers = {"Content-Type": "application/json"}
        responses = [raw_response, metadata_response]
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "captured"
            fetch_egov_source_package(
                spec, destination, opener=lambda request, timeout: responses.pop(0),
                clock=lambda: "2026-09-15T10:02:00Z")
            retrieval = json.loads((destination / "retrieval.json").read_bytes())
            self.assertIsNone(retrieval["raw_request"]["content_length"])
            self.assertIsNone(retrieval["metadata_request"]["content_length"])
            self.assertIsNone(retrieval["metadata_request"]["content_disposition"])
            self.assertIn(spec["source"]["revision_id"],
                          retrieval["raw_request"]["content_disposition"])

    def test_second_response_failure_publishes_nothing_and_does_not_touch_old_bundle(self):
        spec, raw, _ = egov_fixture()
        first = FakeResponse(raw, "application/octet-stream", spec["source"]["raw_url"])
        calls = [first]

        def opener(request, timeout):
            if calls:
                return calls.pop()
            raise TimeoutError("simulated metadata timeout")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_spec, old_bundle, old_result = self.create_fictional(root / "old")
            before = {p.relative_to(old_bundle).as_posix(): p.read_bytes()
                      for p in old_bundle.rglob("*") if p.is_file()}
            destination = root / "new"
            self.assert_status(
                "RETRIEVAL_FAILED", fetch_egov_source_package, spec, destination,
                opener=opener, clock=lambda: "2026-09-15T10:02:00Z", timeout=3.0)
            self.assertFalse(destination.exists())
            after = {p.relative_to(old_bundle).as_posix(): p.read_bytes()
                     for p in old_bundle.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(verify_source_package(old_spec, old_bundle), old_result)

    def test_truncated_content_length_and_existing_destination_are_rejected(self):
        spec, raw, _ = egov_fixture()
        response = FakeResponse(raw, "application/octet-stream", spec["source"]["raw_url"],
                                length=len(raw) + 1)
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "new"
            self.assert_status(
                "RETRIEVAL_FAILED", fetch_egov_source_package, spec, destination,
                opener=lambda request, timeout: response,
                clock=lambda: "2026-09-15T10:02:00Z")
            self.assertFalse(destination.exists())
            destination.mkdir()
            marker = destination / "keep"
            marker.write_text("old", encoding="utf-8")
            self.assert_status(
                "IO_ERROR", fetch_egov_source_package, spec, destination,
                opener=lambda request, timeout: response,
                clock=lambda: "2026-09-15T10:02:00Z")
            self.assertEqual(marker.read_text(encoding="utf-8"), "old")

    def test_nonfinite_timeout_is_rejected_by_public_api(self):
        spec, _, _ = egov_fixture()
        for timeout in (float("nan"), float("inf"), 0, -1, True):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as temp:
                self.assert_status(
                    "SOURCE_INVALID", fetch_egov_source_package, spec,
                    Path(temp) / "bundle", opener=lambda *args, **kwargs: self.fail("network"),
                    clock=lambda: "2026-09-15T10:02:00Z", timeout=timeout)


class SourceBoundaryAndTransactionTests(SourcePackageTestCase):
    def test_raw_and_metadata_limits_accept_boundary_and_reject_next_byte(self):
        spec, raw, metadata = egov_fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path, metadata_path = root / "law.xml", root / "law-data.json"
            raw_path.write_bytes(raw)
            metadata_path.write_bytes(metadata)
            with mock.patch("rulekernel.source_package.MAX_SOURCE_BYTES", len(raw)), \
                    mock.patch("rulekernel.source_package.MAX_METADATA_BYTES", len(metadata)):
                result = build_source_package(
                    spec, raw_path, root / "ok", metadata_path=metadata_path,
                    retrieved_at="2026-09-15T10:00:00Z")
                self.assertEqual(result["status"], "VERIFIED")

            raw_path.write_bytes(raw + b" ")
            larger_raw_spec = deepcopy(spec)
            larger_raw_spec["expected_raw_sha256"] = sha256_bytes(raw + b" ")
            with mock.patch("rulekernel.source_package.MAX_SOURCE_BYTES", len(raw)):
                self.assert_status(
                    "LIMIT_REACHED", build_source_package, larger_raw_spec, raw_path,
                    root / "raw-too-large", metadata_path=metadata_path,
                    retrieved_at="2026-09-15T10:00:00Z")

            raw_path.write_bytes(raw)
            metadata_path.write_bytes(metadata + b" ")
            larger_metadata_spec = deepcopy(spec)
            larger_metadata_spec["expected_metadata_sha256"] = sha256_bytes(metadata + b" ")
            with mock.patch("rulekernel.source_package.MAX_METADATA_BYTES", len(metadata)):
                self.assert_status(
                    "LIMIT_REACHED", build_source_package, larger_metadata_spec, raw_path,
                    root / "metadata-too-large", metadata_path=metadata_path,
                    retrieved_at="2026-09-15T10:00:00Z")

    def test_checker_or_rename_failure_removes_staging_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path = root / "source.xml"
            raw_path.write_bytes(FICTIONAL_RAW)
            cases = [
                mock.patch(
                    "rulekernel.source_checker.verify_source_package",
                    side_effect=KernelError("SOURCE_INVALID", "simulated checker failure")),
                mock.patch("rulekernel.source_package._rename_noreplace",
                           side_effect=OSError("simulated rename failure")),
            ]
            for index, failure in enumerate(cases):
                with self.subTest(index=index), failure:
                    destination = root / f"bundle{index}"
                    with self.assertRaises((KernelError, OSError)):
                        build_source_package(
                            fictional_spec(), raw_path, destination,
                            retrieved_at="2026-09-15T10:00:00Z")
                    self.assertFalse(destination.exists())
                    self.assertEqual(list(root.glob(".source-package-*")), [])

    def test_destination_created_after_check_is_not_replaced(self):
        from rulekernel.source_checker import verify_source_package as actual_verify

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_path = root / "source.xml"
            raw_path.write_bytes(FICTIONAL_RAW)
            destination = root / "bundle"

            def verify_then_compete(spec, staging):
                result = actual_verify(spec, staging)
                destination.mkdir()
                return result

            with mock.patch("rulekernel.source_checker.verify_source_package",
                            side_effect=verify_then_compete):
                with self.assertRaises(OSError):
                    build_source_package(
                        fictional_spec(), raw_path, destination,
                        retrieved_at="2026-09-15T10:00:00Z")
            self.assertTrue(destination.is_dir())
            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual(list(root.glob(".source-package-*")), [])

    def test_filesystem_without_rename_noreplace_is_rejected_safely(self):
        from rulekernel.source_package import _rename_noreplace

        class UnsupportedRename:
            def __call__(self, *args):
                return -1

        library = type("Library", (), {"renameat2": UnsupportedRename()})()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            destination = root / "destination"
            with mock.patch("rulekernel.source_package.ctypes.CDLL", return_value=library), \
                    mock.patch("rulekernel.source_package.ctypes.get_errno",
                               return_value=errno.EINVAL), \
                    mock.patch("rulekernel.source_package.sys.platform", "linux"):
                self.assert_status("UNSUPPORTED", _rename_noreplace, source, destination)
            self.assertTrue(source.is_dir())
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
