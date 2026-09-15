"""CLI: create evidence and independently verify it before reporting a result."""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
import tempfile

from .checker import verify
from .diff import analyze_diff
from .diff_checker import verify_diff
from .engine import analyze
from .interpretation import compile_interpretation
from .interpretation_checker import verify_interpretation_package
from .model import (KernelError, MAX_CERTIFICATE_BYTES, MAX_CONTEXTS,
                    canonical_json, load_json)
from .reachability import analyze_reachability
from .reachability_checker import verify_reachability
from .source_checker import verify_source_package
from .source_package import build_source_package, fetch_egov_source_package
from .staged_reachability import analyze_staged_reachability
from .staged_reachability_checker import verify_staged_reachability
from .staged_reachability_model import load_staged_scope_expectations


def _save_certificate(path, certificate):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=destination.parent, delete=False) as stream:
            temp_name = stream.name
            stream.write(canonical_json(certificate))
        os.replace(temp_name, destination)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)


def _save_new_package(path, package):
    """Atomically publish a new JSON artifact without replacing an existing path."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=destination.parent, delete=False) as stream:
            temp_name = stream.name
            stream.write(canonical_json(package))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_name, destination)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)


def _load_certificate(path):
    try:
        return load_json(path, max_bytes=MAX_CERTIFICATE_BYTES)
    except KernelError as exc:
        if exc.status == "MODEL_INVALID":
            raise KernelError("CERTIFICATE_INVALID", exc.message) from exc
        raise


def _ensure_distinct(output, *inputs):
    if output is None:
        return
    destination = Path(output).resolve()
    if any(destination == Path(source).resolve() for source in inputs):
        raise KernelError("IO_ERROR", "Certificate output must differ from every model input")


def _ensure_outside_tree(output, directory):
    destination = Path(output).resolve()
    root = Path(directory).resolve()
    if destination == root or destination.is_relative_to(root):
        raise KernelError("IO_ERROR", "Output must be outside the immutable source package")


def _show(model, result):
    print(model["title"])
    print(f'証拠検査: {result["status"]}')
    print(f'宣言範囲 {result["total_contexts"]} 状況 / '
          f'入力・背景条件に合う範囲 {result["admitted_contexts"]} 状況')
    source = {rule["id"]: rule["source"] for rule in model["rules"]}
    for query in result["queries"]:
        label = "結論の衝突" if query["kind"] == "conflict" else "扱いの抜け"
        print(f'- {query["output"]} / {label}: {query["count"]} 状況 '
              f'[{query["status"]}]')
        witness = query["witness"]
        if witness is not None:
            print("  具体例: " + canonical_json(witness["input"]))
            if witness["rule_ids"]:
                print("  結論: " + canonical_json(witness["values"]))
                for rule_id in witness["rule_ids"]:
                    print(f"  {rule_id}: {source[rule_id]}")
            else:
                print("  この出力を与える有効な規則がありません。")
    if not result["queries"]:
        print("検査対象の出力が宣言されていないため、照会は0件です。")
    print("結果は宣言した有限範囲と手書きモデルに限ります。原文との意味対応は未検証です。")


def _show_diff(left, right, result):
    labels = {
        "scope_change": "適用範囲の変化",
        "semantic_change": "結論状態・値の変化",
        "explanation_only": "有効な規則IDだけの変化",
        "conflict_introduced": "衝突の発生",
        "conflict_resolved": "衝突の解消",
        "gap_introduced": "扱いの抜けの発生",
        "gap_resolved": "扱いの抜けの解消",
    }
    print(f'{left["title"]} → {right["title"]}')
    print(f'差分証拠検査: {result["status"]}')
    print(f'宣言範囲 {result["total_contexts"]} 状況 / '
          f'左 {result["left_admitted_contexts"]} / '
          f'右 {result["right_admitted_contexts"]} / '
          f'共通 {result["common_admitted_contexts"]}')
    findings = [query for query in result["queries"] if query["count"]]
    if not findings:
        print("- 照会対象の差分: 0状況 [NO_WITNESS_IN_SCOPE_VERIFIED]")
    for query in findings:
        output = "適用範囲" if query["output"] is None else query["output"]
        print(f'- {output} / {labels[query["kind"]]}: {query["count"]} 状況 '
              f'[{query["status"]}]')
        print("  具体例: " + canonical_json(query["witness"]["input"]))
        print("  左: " + canonical_json(query["witness"]["left"]))
        print("  右: " + canonical_json(query["witness"]["right"]))
    print("差分は両モデルが宣言した有限範囲に限ります。原文改定の正しさは未検証です。")


def _show_reachability(model, result):
    labels = {
        "unreachable": "条件が成立しない",
        "always_suppressed": "成立するが常に抑止",
        "partially_suppressed": "一部の状況で抑止",
        "always_effective_when_enabled": "成立時は常に有効",
    }
    print(model["title"])
    print(f'到達可能性証拠検査: {result["status"]}')
    print(f'宣言範囲 {result["total_contexts"]} 状況 / '
          f'入力・背景条件に合う範囲 {result["admitted_contexts"]} 状況 / '
          f'{result["total_rules"]} 規則')
    for rule in result["rules"]:
        print(f'- {rule["rule_id"]}: {labels[rule["classification"]]} / '
              f'enabled {rule["enabled_count"]} / effective {rule["effective_count"]}')
        witness = rule["enabled_witness"]
        if witness is not None and rule["classification"] == "always_suppressed":
            print("  常時抑止される条件成立例: " + canonical_json(witness["input"]))
    print("診断は宣言範囲内の到達性です。規則の削除可否や原文との意味対応は判定しません。")


def _show_staged_reachability(model, result):
    print(model["title"])
    print(f'段階別到達可能性証拠検査: {result["status"]}')
    print(f'宣言範囲 {result["total_contexts"]} / facts適合 '
          f'{result["facts_matching_contexts"]} / constraints適合 '
          f'{result["constraints_matching_contexts"]} / 両方適合 '
          f'{result["admitted_contexts"]}')
    binding = result["scope_expectations_binding"]
    if binding is None:
        print("scope expectations: なし")
    else:
        print("scope expectations: 外部hash照合あり / " +
              binding["scope_expectations_sha256"])
    for rule in result["rules"]:
        print(f'- {rule["rule_id"]}: guard {rule["guard_count"]} / '
              f'guard+facts {rule["guard_and_facts_count"]} / '
              f'guard+constraints {rule["guard_and_constraints_count"]} / '
              f'enabled {rule["enabled_count"]} / effective {rule["effective_count"]}')
        print(f'  段階: {rule["activation_stage"]} / '
              f'filter: {rule["filter_diagnosis"]} / '
              f'期待: {rule["expectation_result"]}')
        if rule["range_hint"] is not None:
            hint = rule["range_hint"]
            print(f'  有限範囲hint: {hint["variable"]} {hint["operator"]} '
                  f'{hint["constant"]} は宣言整数範囲 '
                  f'{hint["declared_min"]}..{hint["declared_max"]} と非交差')
        if rule["attention_codes"]:
            print("  注意: " + ",".join(rule["attention_codes"]))
    print(f'注意件数: {result["attention_count"]}')
    print("段階件数とhintは宣言した有限範囲での結果です。一般の論理矛盾、"
          "意図的な対象外、原文解釈の正しさを自動認定しません。")


def _show_source(result, bundle, *, published):
    label = "原文package生成・独立検査" if published else "原文package独立再検査"
    print(f'{label}: {result["status"]}')
    print(f'文書 {result["document_id"]} / 版 {result["revision_id"]}')
    print(f'原文単位 {result["unit_count"]} / 未解決参照 '
          f'{result["unresolved_reference_count"]}')
    print(f'取得記録値 {result["retrieved_at"]} / 施行日 '
          f'{result["effective_from"] or "未指定"}')
    print("外部bundle hash照合: " +
          ("あり" if result["bundle_hash_anchored"] else "なし"))
    print(f'raw SHA-256: {result["raw_sha256"]}')
    print(f'source unit manifest SHA-256: {result["source_unit_manifest_sha256"]}')
    print(f'bundle.lock SHA-256: {result["bundle_hash"]}')
    print(f'package: {bundle}')
    print("検査済みなのは保存bytes・抽出・位置・版指定との対応です。"
          "最新版性、発行者の真正性、法的意味の正しさは判定しません。")


def _show_interpretation(result, package, *, published):
    label = "解釈IR変換・独立検査" if published else "解釈IR package独立再検査"
    print(f'{label}: {result["status"]}')
    print(f'Core規則 {result["selected_rule_count"]} / '
          f'ホスト境界例 {result["semantic_test_count"]}')
    counts = result["coverage_counts"]
    print(f'原文coverage selected {counts["selected"]} / '
          f'unresolved {counts["unresolved"]} / excluded {counts["excluded"]}')
    print(f'意味対応状態: {result["semantic_correspondence"]}')
    print(f'Core model hash: {result["core_model_hash"]}')
    print(f'package hash: {result["package_hash"]}')
    print("外部package hash照合: " +
          ("あり" if result["package_hash_anchored"] else "なし（生成直後）"))
    print(f'package: {package}')
    print("LOWERING_VERIFIEDは固定入力からCoreと来歴を再構成できたという意味です。"
          "HOST_REVIEW_RECORDEDはレビュー記録とのhash整合であり、原文解釈の正しさや"
          "レビュアー本人性を機械証明しません。")


def _add_runtime_options(parser, certificate=False):
    if certificate:
        parser.add_argument("--certificate", help="独立検査済みの全列挙証拠を保存するJSONパス")
    parser.add_argument("--max-contexts", type=int, default=MAX_CONTEXTS)
    parser.add_argument("--json", action="store_true", help="機械用JSON結果")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="自前の有限ルール検証カーネル (finite-decisions/1)")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="全列挙し、独立検査後に結果を表示")
    check.add_argument("model")
    _add_runtime_options(check, certificate=True)
    recheck = commands.add_parser("verify", help="保存済み証拠を期待モデルと照合")
    recheck.add_argument("model")
    recheck.add_argument("certificate")
    _add_runtime_options(recheck)
    diff = commands.add_parser("diff", help="二つの有限モデルを全入力で比較し、独立検査")
    diff.add_argument("left_model")
    diff.add_argument("right_model")
    _add_runtime_options(diff, certificate=True)
    rediff = commands.add_parser("verify-diff", help="保存済みの改定差分証拠を再検査")
    rediff.add_argument("left_model")
    rediff.add_argument("right_model")
    rediff.add_argument("certificate")
    _add_runtime_options(rediff)
    reach = commands.add_parser("reachability", help="各規則の条件成立・抑止状況を全列挙し、独立検査")
    reach.add_argument("model")
    _add_runtime_options(reach, certificate=True)
    rereach = commands.add_parser("verify-reachability", help="保存済みの到達可能性証拠を再検査")
    rereach.add_argument("model")
    rereach.add_argument("certificate")
    _add_runtime_options(rereach)
    staged = commands.add_parser(
        "reachability-staged", help="guard/facts/constraints/overrideの段階別到達性を独立検査")
    staged.add_argument("model")
    staged.add_argument("--scope-expectations",
                        help="T05 rule-scope-expectations/1 JSON")
    staged.add_argument("--expected-scope-expectations-sha256",
                        help="package外に控えたscope expectations SHA-256")
    _add_runtime_options(staged, certificate=True)
    restaged = commands.add_parser(
        "verify-reachability-staged", help="保存済み段階別到達可能性証拠を再検査")
    restaged.add_argument("model")
    restaged.add_argument("certificate")
    restaged.add_argument("--scope-expectations",
                          help="生成時と同じT05 scope expectations JSON")
    restaged.add_argument("--expected-scope-expectations-sha256",
                          help="生成時と同じ外部scope expectations SHA-256")
    _add_runtime_options(restaged)
    source_build = commands.add_parser(
        "source-build", help="固定済みrawとcapture specから原文packageを生成・独立検査")
    source_build.add_argument("spec")
    source_build.add_argument("raw")
    source_build.add_argument("--metadata", help="e-Gov law_data JSONの保存応答")
    source_build.add_argument("--retrieved-at", required=True,
                              help="取得観測時刻 (YYYY-MM-DDTHH:MM:SSZ)")
    source_build.add_argument("--bundle", required=True, help="新規packageディレクトリ")
    source_build.add_argument("--json", action="store_true", help="機械用JSON結果")
    source_fetch = commands.add_parser(
        "source-fetch-egov", help="版固定e-Gov URLから原文packageを取得・独立検査")
    source_fetch.add_argument("spec")
    source_fetch.add_argument("--bundle", required=True, help="新規packageディレクトリ")
    source_fetch.add_argument("--timeout", type=float, default=30.0)
    source_fetch.add_argument("--json", action="store_true", help="機械用JSON結果")
    source_verify = commands.add_parser(
        "verify-source", help="原文packageをcapture specとoffline照合")
    source_verify.add_argument("spec")
    source_verify.add_argument("bundle")
    source_verify.add_argument(
        "--expected-bundle-sha256",
        help="別に記録したbundle.lock.jsonのlowercase SHA-256")
    source_verify.add_argument("--json", action="store_true", help="機械用JSON結果")
    interpretation_build = commands.add_parser(
        "compile-interpretation",
        help="ホストレビュー済み候補をCoreへ変換し、独立検査後に保存")
    interpretation_build.add_argument("task")
    interpretation_build.add_argument("candidate")
    interpretation_build.add_argument("review")
    interpretation_build.add_argument("scope_expectations")
    interpretation_build.add_argument("--source-spec", required=True)
    interpretation_build.add_argument("--source-bundle", required=True)
    interpretation_build.add_argument("--expected-source-bundle-sha256", required=True)
    interpretation_build.add_argument("--expected-review-sha256", required=True)
    interpretation_build.add_argument("--expected-scope-expectations-sha256", required=True)
    interpretation_build.add_argument("--package", required=True,
                                      help="独立検査後に保存する新しいcompiled package JSON")
    interpretation_build.add_argument("--json", action="store_true", help="機械用JSON結果")
    interpretation_verify = commands.add_parser(
        "verify-interpretation", help="保存済み解釈IR packageを原文からoffline再構成")
    interpretation_verify.add_argument("task")
    interpretation_verify.add_argument("candidate")
    interpretation_verify.add_argument("review")
    interpretation_verify.add_argument("scope_expectations")
    interpretation_verify.add_argument("package")
    interpretation_verify.add_argument("--source-spec", required=True)
    interpretation_verify.add_argument("--source-bundle", required=True)
    interpretation_verify.add_argument("--expected-source-bundle-sha256", required=True)
    interpretation_verify.add_argument("--expected-review-sha256", required=True)
    interpretation_verify.add_argument("--expected-scope-expectations-sha256", required=True)
    interpretation_verify.add_argument("--expected-package-sha256")
    interpretation_verify.add_argument("--json", action="store_true", help="機械用JSON結果")
    args = parser.parse_args(argv)
    try:
        if args.command == "compile-interpretation":
            _ensure_distinct(args.package, args.task, args.candidate, args.review,
                             args.scope_expectations, args.source_spec)
            _ensure_outside_tree(args.package, args.source_bundle)
            package = compile_interpretation(
                args.task, args.candidate, args.review, args.scope_expectations,
                args.source_spec, args.source_bundle,
                expected_source_bundle_sha256=args.expected_source_bundle_sha256,
                expected_review_sha256=args.expected_review_sha256,
                expected_scope_expectations_sha256=(
                    args.expected_scope_expectations_sha256),
            )
            checked = verify_interpretation_package(
                args.task, args.candidate, args.review, args.scope_expectations,
                args.source_spec, args.source_bundle, package,
                expected_source_bundle_sha256=args.expected_source_bundle_sha256,
                expected_review_sha256=args.expected_review_sha256,
                expected_scope_expectations_sha256=(
                    args.expected_scope_expectations_sha256),
            )
            _save_new_package(args.package, package)
            result = {**checked, "published_package": str(args.package)}
            if args.json:
                print(canonical_json(result))
            else:
                _show_interpretation(result, args.package, published=True)
            return 1 if result["coverage_counts"]["unresolved"] else 0
        if args.command == "verify-interpretation":
            checked = verify_interpretation_package(
                args.task, args.candidate, args.review, args.scope_expectations,
                args.source_spec, args.source_bundle, args.package,
                expected_source_bundle_sha256=args.expected_source_bundle_sha256,
                expected_review_sha256=args.expected_review_sha256,
                expected_scope_expectations_sha256=(
                    args.expected_scope_expectations_sha256),
                expected_package_sha256=args.expected_package_sha256,
            )
            result = {**checked, "package": str(args.package)}
            if args.json:
                print(canonical_json(result))
            else:
                _show_interpretation(result, args.package, published=False)
            return 1 if result["coverage_counts"]["unresolved"] else 0
        if args.command == "source-build":
            checked = build_source_package(
                args.spec, args.raw, args.bundle, metadata_path=args.metadata,
                retrieved_at=args.retrieved_at)
            result = {**checked, "published_bundle": str(args.bundle)}
            if args.json:
                print(canonical_json(result))
            else:
                _show_source(result, args.bundle, published=True)
            return 1 if result["unresolved_reference_count"] else 0
        if args.command == "source-fetch-egov":
            if not math.isfinite(args.timeout) or args.timeout <= 0:
                raise KernelError("SOURCE_INVALID", "--timeout must be a finite positive number")
            checked = fetch_egov_source_package(
                args.spec, args.bundle, timeout=args.timeout)
            result = {**checked, "published_bundle": str(args.bundle)}
            if args.json:
                print(canonical_json(result))
            else:
                _show_source(result, args.bundle, published=True)
            return 1 if result["unresolved_reference_count"] else 0
        if args.command == "verify-source":
            checked = verify_source_package(
                args.spec, args.bundle,
                expected_bundle_sha256=args.expected_bundle_sha256)
            result = {**checked, "bundle": str(args.bundle)}
            if args.json:
                print(canonical_json(result))
            else:
                _show_source(result, args.bundle, published=False)
            return 1 if result["unresolved_reference_count"] else 0

        if args.command in {"check", "verify", "reachability", "verify-reachability",
                            "reachability-staged", "verify-reachability-staged"}:
            model = load_json(args.model)
        else:
            left = load_json(args.left_model)
            right = load_json(args.right_model)

        if args.command == "check":
            _ensure_distinct(args.certificate, args.model)
            certificate = analyze(model, max_contexts=args.max_contexts)
            checked = verify(model, certificate, max_contexts=args.max_contexts)
        elif args.command == "verify":
            certificate = _load_certificate(args.certificate)
            checked = verify(model, certificate, max_contexts=args.max_contexts)
        elif args.command == "diff":
            _ensure_distinct(args.certificate, args.left_model, args.right_model)
            certificate = analyze_diff(left, right, max_contexts=args.max_contexts)
            checked = verify_diff(left, right, certificate, max_contexts=args.max_contexts)
        elif args.command == "verify-diff":
            certificate = _load_certificate(args.certificate)
            checked = verify_diff(left, right, certificate, max_contexts=args.max_contexts)
        elif args.command == "reachability":
            _ensure_distinct(args.certificate, args.model)
            certificate = analyze_reachability(model, max_contexts=args.max_contexts)
            checked = verify_reachability(model, certificate, max_contexts=args.max_contexts)
        elif args.command == "reachability-staged":
            distinct_inputs = [args.model]
            if args.scope_expectations is not None:
                distinct_inputs.append(args.scope_expectations)
            _ensure_distinct(args.certificate, *distinct_inputs)
            expectations = (None if args.scope_expectations is None else
                            load_staged_scope_expectations(args.scope_expectations))
            certificate = analyze_staged_reachability(
                model, expectations,
                expected_scope_expectations_sha256=(
                    args.expected_scope_expectations_sha256),
                max_contexts=args.max_contexts,
            )
            checked = verify_staged_reachability(
                model, certificate, expectations,
                expected_scope_expectations_sha256=(
                    args.expected_scope_expectations_sha256),
                max_contexts=args.max_contexts,
            )
        elif args.command == "verify-reachability-staged":
            certificate = _load_certificate(args.certificate)
            expectations = (None if args.scope_expectations is None else
                            load_staged_scope_expectations(args.scope_expectations))
            checked = verify_staged_reachability(
                model, certificate, expectations,
                expected_scope_expectations_sha256=(
                    args.expected_scope_expectations_sha256),
                max_contexts=args.max_contexts,
            )
        else:
            certificate = _load_certificate(args.certificate)
            checked = verify_reachability(model, certificate, max_contexts=args.max_contexts)

        if args.command in {"check", "diff", "reachability", "reachability-staged"} and args.certificate:
            _save_certificate(args.certificate, certificate)
        limits = {"max_contexts": args.max_contexts,
                  "max_certificate_bytes": MAX_CERTIFICATE_BYTES}
        if args.command in {"diff", "verify-diff"}:
            result = {"title": f'{left["title"]} → {right["title"]}',
                      "left_title": left["title"], "right_title": right["title"],
                      **checked, "limits": limits}
        else:
            result = {"title": model["title"], "origin_kind": model["origin_kind"],
                      **checked, "limits": limits}
        if args.json:
            print(canonical_json(result))
        elif args.command in {"diff", "verify-diff"}:
            _show_diff(left, right, result)
            if args.command == "diff" and args.certificate:
                print(f"証拠保存: {args.certificate}")
        elif args.command in {"reachability-staged", "verify-reachability-staged"}:
            _show_staged_reachability(model, result)
            if args.command == "reachability-staged" and args.certificate:
                print(f"証拠保存: {args.certificate}")
        elif args.command in {"reachability", "verify-reachability"}:
            _show_reachability(model, result)
            if args.command == "reachability" and args.certificate:
                print(f"証拠保存: {args.certificate}")
        else:
            _show(model, result)
            if args.command == "check" and args.certificate:
                print(f"証拠保存: {args.certificate}")
        if args.command in {"diff", "verify-diff", "check", "verify"}:
            return 1 if any(query["count"] for query in result["queries"]) else 0
        if args.command in {"reachability-staged", "verify-reachability-staged"}:
            return 1 if result["attention_count"] else 0
        actionable = {"unreachable", "always_suppressed"}
        return 1 if any(rule["classification"] in actionable for rule in result["rules"]) else 0
    except (KernelError, OSError) as exc:
        status = exc.status if isinstance(exc, KernelError) else "IO_ERROR"
        message = exc.message if isinstance(exc, KernelError) else str(exc)
        attention = status in {
            "REVIEW_REQUIRED", "REVIEW_REJECTED", "MODEL_INCOMPLETE", "SEMANTIC_MISMATCH"
        }
        if args.json:
            failure = {"status": status, "message": message,
                       "finding": "attention" if attention else "undetermined"}
            if args.command in {"source-build", "source-fetch-egov"}:
                failure["published_bundle"] = None
            if args.command == "compile-interpretation":
                failure["published_package"] = None
            print(canonical_json(failure))
        else:
            print(f"{status}: {message}\n検査は確定していません。", file=sys.stderr)
        return 1 if attention else 2


if __name__ == "__main__":
    sys.exit(main())
