"""Fast independent verification for saved T06 measurement reports.

This checker never reruns timed benchmark operations. It requires an external
report SHA-256, rebinds the report to the current sources and generated models,
and independently checks characterization, worker summaries, boundaries,
endpoint models, and failed-publish observations.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
from math import isfinite, prod
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rulekernel.model import (  # noqa: E402
    KernelError,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    canonical_json,
    digest,
    load_json,
    validate_model,
)


REPORT_FORMAT = "t06-benchmark-report/1"
MEASUREMENT_VERSION = "0.1.0"
PROVENANCE = "synthetic_not_t05_derived"
CONFIG_FORMAT = "t06-benchmark-config/1"
MANIFEST_FORMAT = "t06-generated-model-manifest/1"
MAX_REPORT_BYTES = 64 * 1024 * 1024
OPERATIONS = ("check", "diff", "reachability", "staged")
DEFAULT_CONFIG = HERE / "config.json"
DEFAULT_GENERATED = HERE / "generated"
KERNEL_SOURCES = (
    "rulekernel/__main__.py",
    "rulekernel/model.py",
    "rulekernel/engine.py",
    "rulekernel/checker.py",
    "rulekernel/diff.py",
    "rulekernel/diff_checker.py",
    "rulekernel/reachability.py",
    "rulekernel/reachability_checker.py",
    "rulekernel/staged_reachability.py",
    "rulekernel/staged_reachability_checker.py",
    "rulekernel/staged_reachability_model.py",
    "rulekernel/interpretation_model.py",
)
CERTIFICATE_FORMATS = {
    "check": "finite-decisions-certificate/1",
    "diff": "finite-decisions-diff-certificate/1",
    "reachability": "finite-decisions-reachability-certificate/1",
    "staged": "finite-decisions-staged-reachability-certificate/1",
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ReportVerificationError(Exception):
    """A saved report failed an independent structural or binding check."""

    def __init__(self, path, message):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def _fail(path, message):
    raise ReportVerificationError(path, message)


def _exact(value, fields, path):
    if type(value) is not dict:
        _fail(path, "expected object")
    missing = set(fields) - value.keys()
    extra = value.keys() - set(fields)
    if missing or extra:
        _fail(
            path,
            f"fields differ; missing={sorted(missing)}, extra={sorted(extra)}",
        )


def _integer(value, path, *, minimum=0):
    if type(value) is not int or value < minimum:
        _fail(path, f"expected integer >= {minimum}")


def _text(value, path, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not str or not value:
        _fail(path, "expected non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _fail(path, "invalid Unicode")


def _hash(value, path, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not str or SHA256.fullmatch(value) is None:
        _fail(path, "expected lowercase SHA-256")


def _raw_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _display_path(path):
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _reported_path(value, path):
    _text(value, path)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.resolve()


def _validate_config(config):
    _exact(
        config,
        {
            "format",
            "generator_profile",
            "provenance",
            "variables",
            "outputs",
            "matrix",
            "boundary_family",
        },
        "config",
    )
    expected = {
        "format": CONFIG_FORMAT,
        "generator_profile": "t06-deterministic-matrix/1",
        "provenance": PROVENANCE,
        "variables": [f"b{i:02d}" for i in range(13)],
        "outputs": [f"o{i:02d}" for i in range(10)],
        "matrix": {
            "rule_counts": [50, 100],
            "guard_profiles": ["sparse", "dense"],
            "background_profiles": ["full", "eighth"],
        },
        "boundary_family": {
            "context_max": 10000,
            "input": "case_id",
            "output_count": 10,
            "override_edges": 0,
            "rule_count": 100,
        },
    }
    if config != expected:
        _fail("config", "does not match the fixed T06 config contract")


def _matrix_scenarios(config):
    return [
        f"matrix-{count}-{guard}-{background}"
        for count in config["matrix"]["rule_counts"]
        for guard in config["matrix"]["guard_profiles"]
        for background in config["matrix"]["background_profiles"]
    ]


def _safe_child(directory, filename, path):
    if type(filename) is not str or not filename:
        _fail(path, "invalid filename")
    root = Path(directory).resolve()
    candidate = (root / filename).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        _fail(path, "path escapes generated directory")
    return candidate


def _assert_pair_delta(base, revision, path):
    if base["title"] != revision["title"]:
        _fail(path, "revision title differs")
    if base["rules"][0]["then"]["value"] is not False:
        _fail(path, "base R000 value is not false")
    if revision["rules"][0]["then"]["value"] is not True:
        _fail(path, "revision R000 value is not true")
    restored = json.loads(canonical_json(revision))
    restored["rules"][0]["then"]["value"] = False
    if restored != base:
        _fail(path, "base/revision differ outside R000.then.value")


def _load_manifest(config_path, generated_dir):
    config = load_json(config_path)
    _validate_config(config)
    manifest_path = Path(generated_dir) / "manifest.json"
    manifest = load_json(manifest_path, max_bytes=MAX_REPORT_BYTES)
    _exact(
        manifest,
        {
            "format",
            "provenance",
            "config_canonical_sha256",
            "config_file_sha256",
            "generator_file_sha256",
            "models",
        },
        "manifest",
    )
    if (
        manifest["format"] != MANIFEST_FORMAT
        or manifest["provenance"] != PROVENANCE
    ):
        _fail("manifest", "format or provenance mismatch")
    if manifest["config_canonical_sha256"] != digest(config):
        _fail("manifest.config_canonical_sha256", "config mismatch")
    if manifest["config_file_sha256"] != _raw_sha256(config_path):
        _fail("manifest.config_file_sha256", "config byte hash mismatch")
    generator_path = HERE / "generate.py"
    if manifest["generator_file_sha256"] != _raw_sha256(generator_path):
        _fail("manifest.generator_file_sha256", "generator byte hash mismatch")
    if type(manifest["models"]) is not list:
        _fail("manifest.models", "expected array")

    scenarios = _matrix_scenarios(config)
    expected_files = []
    for scenario in scenarios:
        expected_files.extend(
            [scenario + ".json", scenario + "-revision.json"]
        )
    expected_files.extend(
        [
            "sentinel-local-a.json",
            "sentinel-local-b.json",
            "sentinel-union-conflict.json",
            "sentinel-override-revival.json",
        ]
    )
    actual_files = [
        entry.get("file") if type(entry) is dict else None
        for entry in manifest["models"]
    ]
    if actual_files != expected_files:
        _fail("manifest.models", "model order or fixed file set mismatch")

    records = {}
    entry_fields = {
        "file",
        "scenario",
        "revision",
        "provenance",
        "source_unit_count",
        "source_unit_count_reason",
        "model_sha256",
        "bytes",
        "inputs",
        "outputs",
        "rules",
    }
    for index, entry in enumerate(manifest["models"]):
        base_path = f"manifest.models[{index}]"
        _exact(entry, entry_fields, base_path)
        if (
            entry["provenance"] != PROVENANCE
            or entry["source_unit_count"] is not None
        ):
            _fail(base_path, "synthetic provenance boundary mismatch")
        if (
            entry["source_unit_count_reason"]
            != "synthetic workload has no T04 source package"
        ):
            _fail(
                base_path + ".source_unit_count_reason", "unexpected reason"
            )
        model_path = _safe_child(
            generated_dir, entry["file"], base_path + ".file"
        )
        model = load_json(model_path)
        validate_model(model)
        checks = {
            "model_sha256": digest(model),
            "bytes": len(canonical_json(model).encode("utf-8")),
            "inputs": len(model["inputs"]),
            "outputs": len(model["outputs"]),
            "rules": len(model["rules"]),
        }
        for field, expected in checks.items():
            if entry[field] != expected:
                _fail(base_path + "." + field, "generated model mismatch")
        if model_path.read_bytes() != canonical_json(model).encode("utf-8"):
            _fail(base_path + ".file", "generated model is not canonical bytes")
        records[entry["file"]] = {
            "entry": entry,
            "path": model_path,
            "model": model,
            "file_sha256": _raw_sha256(model_path),
            "file_bytes": model_path.stat().st_size,
        }

    for scenario in scenarios:
        _assert_pair_delta(
            records[scenario + ".json"]["model"],
            records[scenario + "-revision.json"]["model"],
            f"generated pair {scenario}",
        )
    return config, manifest, manifest_path, records


def _verify_file_binding(actual, expected_path, path):
    _exact(actual, {"path", "sha256", "bytes"}, path)
    if actual["path"] != _display_path(expected_path):
        _fail(path + ".path", "bound path mismatch")
    if actual["sha256"] != _raw_sha256(expected_path):
        _fail(path + ".sha256", "bound file hash mismatch")
    if actual["bytes"] != Path(expected_path).stat().st_size:
        _fail(path + ".bytes", "bound file size mismatch")


def _verify_bindings(bindings, config_path, manifest_path, config, manifest):
    _exact(
        bindings,
        {
            "measurement_version",
            "files",
            "config_canonical_sha256",
            "manifest_canonical_sha256",
        },
        "body.bindings",
    )
    if bindings["measurement_version"] != MEASUREMENT_VERSION:
        _fail("body.bindings.measurement_version", "unsupported version")
    paths = {
        "measure": HERE / "measure.py",
        "generator": HERE / "generate.py",
        "config": Path(config_path),
        "manifest": Path(manifest_path),
    }
    paths.update({relative: ROOT / relative for relative in KERNEL_SOURCES})
    _exact(bindings["files"], set(paths), "body.bindings.files")
    for label, expected_path in paths.items():
        _verify_file_binding(
            bindings["files"][label],
            expected_path,
            f"body.bindings.files[{label!r}]",
        )
    if bindings["config_canonical_sha256"] != digest(config):
        _fail("body.bindings.config_canonical_sha256", "config mismatch")
    if bindings["manifest_canonical_sha256"] != digest(manifest):
        _fail("body.bindings.manifest_canonical_sha256", "manifest mismatch")


def _domain_values(domain):
    if domain["kind"] == "bool":
        return (False, True)
    if domain["kind"] == "int":
        return range(domain["min"], domain["max"] + 1)
    return domain["values"]


def _evaluate(expression, assignment):
    if "var" in expression:
        return assignment[expression["var"]]
    if "const" in expression:
        return expression["const"]
    operation = expression["op"]
    arguments = expression["args"]
    if operation == "not":
        return not _evaluate(arguments[0], assignment)
    if operation == "and":
        return all(_evaluate(item, assignment) for item in arguments)
    if operation == "or":
        return any(_evaluate(item, assignment) for item in arguments)
    left, right = (_evaluate(item, assignment) for item in arguments)
    if operation == "eq":
        return left == right
    if operation == "ne":
        return left != right
    if operation == "lt":
        return left < right
    if operation == "le":
        return left <= right
    if operation == "gt":
        return left > right
    if operation == "ge":
        return left >= right
    _fail("static_matrix.characterization", "unknown operator")


def _fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator}


def _characterize(model):
    """Independently replay deterministic characterization fields."""
    validate_model(model)
    if any(rule["overrides"] for rule in model["rules"]):
        _fail(
            "static_matrix.characterization",
            "fixed matrix unexpectedly has overrides",
        )
    names = sorted(model["inputs"])
    domains = [_domain_values(model["inputs"][name]) for name in names]
    total = prod(len(values) for values in domains)
    rule_ids = sorted(rule["id"] for rule in model["rules"])
    rules = {rule["id"]: rule for rule in model["rules"]}
    facts_total = constraints_total = admitted_total = 0
    guard_total = enabled_total = 0
    guard_counts = dict.fromkeys(rule_ids, 0)
    enabled_counts = dict.fromkeys(rule_ids, 0)
    max_guard = max_enabled = 0
    facts = {fact["var"]: fact["value"] for fact in model["facts"]}
    for values in product(*domains):
        assignment = dict(zip(names, values))
        facts_match = all(
            assignment[name] == value for name, value in facts.items()
        )
        constraints_match = all(
            _evaluate(expr, assignment) for expr in model["constraints"]
        )
        admitted = facts_match and constraints_match
        facts_total += int(facts_match)
        constraints_total += int(constraints_match)
        admitted_total += int(admitted)
        active = [
            rule_id
            for rule_id in rule_ids
            if _evaluate(rules[rule_id]["when"], assignment)
        ]
        enabled = active if admitted else []
        guard_total += len(active)
        enabled_total += len(enabled)
        max_guard = max(max_guard, len(active))
        max_enabled = max(max_enabled, len(enabled))
        for rule_id in active:
            guard_counts[rule_id] += 1
        for rule_id in enabled:
            enabled_counts[rule_id] += 1
    denominator = total * len(rule_ids)
    return {
        "algorithm": "measure-streaming-characterization/1",
        "total_contexts": total,
        "facts_matching_contexts": facts_total,
        "constraints_matching_contexts": constraints_total,
        "admitted_contexts": admitted_total,
        "background_fit": _fraction(admitted_total, total),
        "guard_activations": guard_total,
        "enabled_activations": enabled_total,
        "effective_activations": enabled_total,
        "guard_density": _fraction(guard_total, denominator),
        "enabled_density_declared_scope": _fraction(
            enabled_total, denominator
        ),
        "effective_density_declared_scope": _fraction(
            enabled_total, denominator
        ),
        "average_guard_ids_per_context": _fraction(guard_total, total),
        "average_enabled_ids_per_context": _fraction(enabled_total, total),
        "average_effective_ids_per_context": _fraction(
            enabled_total, total
        ),
        "max_guard_ids_per_context": max_guard,
        "max_enabled_ids_per_context": max_enabled,
        "max_effective_ids_per_context": max_enabled,
        "rules_with_no_guard_witness": sum(
            count == 0 for count in guard_counts.values()
        ),
        "rules_with_no_enabled_witness": sum(
            count == 0 for count in enabled_counts.values()
        ),
        "rules_with_no_effective_witness": sum(
            count == 0 for count in enabled_counts.values()
        ),
        "per_rule_guard_min_max": [
            min(guard_counts.values()),
            max(guard_counts.values()),
        ],
        "per_rule_enabled_min_max": [
            min(enabled_counts.values()),
            max(enabled_counts.values()),
        ],
        "per_rule_effective_min_max": [
            min(enabled_counts.values()),
            max(enabled_counts.values()),
        ],
    }


def _verify_characterization(actual, model, path):
    expected = _characterize(model)
    _exact(
        actual,
        set(expected) | {"elapsed_ns_not_a_kernel_benchmark"},
        path,
    )
    _integer(
        actual["elapsed_ns_not_a_kernel_benchmark"],
        path + ".elapsed_ns_not_a_kernel_benchmark",
    )
    deterministic = dict(actual)
    deterministic.pop("elapsed_ns_not_a_kernel_benchmark")
    if deterministic != expected:
        _fail(path, "independent characterization replay differs")


def _verify_model_binding(actual, record, path):
    fields = {
        "path",
        "model_sha256",
        "canonical_bytes",
        "file_sha256",
        "file_bytes",
        "inputs",
        "outputs",
        "rules",
        "provenance",
        "source_unit_count",
        "source_unit_count_reason",
    }
    _exact(actual, fields, path)
    entry = record["entry"]
    expected = {
        "path": _display_path(record["path"]),
        "model_sha256": entry["model_sha256"],
        "canonical_bytes": entry["bytes"],
        "file_sha256": record["file_sha256"],
        "file_bytes": record["file_bytes"],
        "inputs": entry["inputs"],
        "outputs": entry["outputs"],
        "rules": entry["rules"],
        "provenance": PROVENANCE,
        "source_unit_count": None,
        "source_unit_count_reason": (
            "synthetic workload has no T04 source package"
        ),
    }
    if actual != expected:
        _fail(path, "generated model binding mismatch")



def _verify_worker_meta(value, path, fields):
    if type(value) is not dict:
        _fail(path, "expected worker result")
    if set(value) not in (set(fields), set(fields) | {"worker_stderr"}):
        _fail(path, "worker result fields differ")
    if value["worker_returncode"] != 0:
        _fail(path + ".worker_returncode", "measurement worker did not exit 0")
    _integer(
        value["worker_wall_elapsed_ns"],
        path + ".worker_wall_elapsed_ns",
    )
    if "worker_stderr" in value:
        _text(value["worker_stderr"], path + ".worker_stderr")


def _verify_memory(value, path):
    fields = {
        "baseline_current_bytes",
        "final_current_bytes",
        "peak_bytes",
        "incremental_peak_above_loaded_inputs_bytes",
        "traceback_frames",
    }
    _exact(value, fields, path)
    for field in fields:
        _integer(value[field], path + "." + field)
    if value["traceback_frames"] != 1:
        _fail(path + ".traceback_frames", "unexpected tracemalloc depth")
    expected = max(
        0, value["peak_bytes"] - value["baseline_current_bytes"]
    )
    if value["incremental_peak_above_loaded_inputs_bytes"] != expected:
        _fail(path, "incremental peak arithmetic mismatch")
    if value["peak_bytes"] < value["final_current_bytes"]:
        _fail(path, "peak is below final current allocation")


def _verify_certificate_summary(
    value,
    path,
    *,
    checked,
    operation,
    total_contexts,
    admitted_contexts,
):
    fields = {
        "sha256",
        "canonical_bytes",
        "remaining_to_8_mib_bytes",
        "format",
        "total_contexts",
        "admitted_contexts",
        "finding_total",
        "attention_count",
    }
    if checked:
        fields |= {"checker_status", "checker_certificate_hash"}
    _exact(value, fields, path)
    _hash(value["sha256"], path + ".sha256")
    _integer(value["canonical_bytes"], path + ".canonical_bytes", minimum=1)
    if value["canonical_bytes"] > MAX_CERTIFICATE_BYTES:
        _fail(path + ".canonical_bytes", "certificate exceeds kernel limit")
    if (
        value["remaining_to_8_mib_bytes"]
        != MAX_CERTIFICATE_BYTES - value["canonical_bytes"]
    ):
        _fail(
            path + ".remaining_to_8_mib_bytes",
            "byte-limit arithmetic mismatch",
        )
    if value["format"] != CERTIFICATE_FORMATS[operation]:
        _fail(path + ".format", "operation/certificate format mismatch")
    if value["total_contexts"] != total_contexts:
        _fail(path + ".total_contexts", "model scope mismatch")
    if value["admitted_contexts"] != admitted_contexts:
        _fail(path + ".admitted_contexts", "admitted scope mismatch")
    if operation in {"check", "diff"}:
        _integer(value["finding_total"], path + ".finding_total")
    elif value["finding_total"] is not None:
        _fail(path + ".finding_total", "unexpected finding total")
    if operation == "staged":
        _integer(value["attention_count"], path + ".attention_count")
    elif value["attention_count"] is not None:
        _fail(path + ".attention_count", "unexpected attention total")
    if checked:
        if value["checker_status"] != "VERIFIED":
            _fail(path + ".checker_status", "checker did not verify")
        if value["checker_certificate_hash"] != value["sha256"]:
            _fail(path + ".checker_certificate_hash", "checker hash mismatch")


def _verify_kernel_error(value, path, *, memory=False):
    fields = {
        "status",
        "failure_phase",
        "kernel_status",
        "message",
        "worker_returncode",
        "worker_wall_elapsed_ns",
        "tracemalloc" if memory else "elapsed_ns",
    }
    _verify_worker_meta(value, path, fields)
    if (
        value["status"] != "kernel_error"
        or value["kernel_status"] != "LIMIT_REACHED"
    ):
        _fail(
            path,
            "formal report may contain only verified or LIMIT_REACHED workers",
        )
    _text(value["failure_phase"], path + ".failure_phase")
    if value["failure_phase"] not in {
        "producer",
        "checker",
        "post_time_checker",
        "post_memory_checker",
    }:
        _fail(path + ".failure_phase", "unexpected failure phase")
    _text(value["message"], path + ".message")
    if memory:
        _verify_memory(value["tracemalloc"], path + ".tracemalloc")
    else:
        _integer(value["elapsed_ns"], path + ".elapsed_ns")


def _verify_time_summary(value, path, repetitions, detail_verifier):
    fields = {
        "raw_ns",
        "timed_samples",
        "verified_samples",
        "min_ns",
        "median_ns",
        "max_ns",
        "statuses",
        "details",
    }
    _exact(value, fields, path)
    if (
        type(value["details"]) is not list
        or len(value["details"]) != repetitions
    ):
        _fail(path + ".details", "raw sample count differs from repetitions")
    for index, detail in enumerate(value["details"]):
        detail_verifier(detail, f"{path}.details[{index}]")
    raw = [detail.get("elapsed_ns") for detail in value["details"]]
    timed = [
        item for item in raw if type(item) is int and item >= 0
    ]
    ordered = sorted(timed)
    expected = {
        "raw_ns": raw,
        "timed_samples": len(timed),
        "verified_samples": sum(
            detail.get("status") == "verified"
            for detail in value["details"]
        ),
        "min_ns": min(timed) if timed else None,
        "median_ns": ordered[len(ordered) // 2] if ordered else None,
        "max_ns": max(timed) if timed else None,
        "statuses": [
            detail.get("status") for detail in value["details"]
        ],
        "details": value["details"],
    }
    if value != expected:
        _fail(path, "time summary does not match raw samples")


def _verify_workflow(
    value,
    path,
    operation,
    left_hash,
    right_hash,
    repetitions,
    total_contexts,
    admitted_contexts,
    *,
    expected_outcome=None,
):
    common = {
        "operation",
        "left_model_sha256",
        "right_model_sha256",
        "prepare",
        "producer_time",
        "producer_memory",
        "checker_time",
        "checker_memory",
        "measurement_complete",
    }
    if type(value) is not dict:
        _fail(path, "expected workflow object")
    success = (
        type(value.get("prepare")) is dict
        and value["prepare"].get("status") == "verified"
    )
    _exact(
        value,
        common | ({"certificate"} if success else set()),
        path,
    )
    if value["operation"] != operation:
        _fail(path + ".operation", "operation mismatch")
    if (
        value["left_model_sha256"] != left_hash
        or value["right_model_sha256"] != right_hash
    ):
        _fail(path, "workflow model hash mismatch")

    summary_args = {
        "operation": operation,
        "total_contexts": total_contexts,
        "admitted_contexts": admitted_contexts,
    }
    if success:
        if expected_outcome == "limit_reached":
            _fail(path, "expected LIMIT_REACHED workflow")
        prepare_fields = {
            "status",
            "producer_elapsed_ns",
            "checker_elapsed_ns",
            "certificate",
            "worker_returncode",
            "worker_wall_elapsed_ns",
        }
        prepare = value["prepare"]
        _verify_worker_meta(prepare, path + ".prepare", prepare_fields)
        for field in ("producer_elapsed_ns", "checker_elapsed_ns"):
            _integer(prepare[field], path + ".prepare." + field)
        _verify_certificate_summary(
            prepare["certificate"],
            path + ".prepare.certificate",
            checked=True,
            **summary_args,
        )
        expected_summary = prepare["certificate"]
        expected_hash = expected_summary["sha256"]

        def producer_detail(detail, detail_path):
            fields = {
                "status",
                "elapsed_ns",
                "certificate",
                "worker_returncode",
                "worker_wall_elapsed_ns",
            }
            _verify_worker_meta(detail, detail_path, fields)
            if detail["status"] != "verified":
                _fail(detail_path, "producer timing sample is not verified")
            _integer(detail["elapsed_ns"], detail_path + ".elapsed_ns")
            _verify_certificate_summary(
                detail["certificate"],
                detail_path + ".certificate",
                checked=True,
                **summary_args,
            )
            if detail["certificate"] != expected_summary:
                _fail(
                    detail_path + ".certificate",
                    "certificate differs across fresh runs",
                )

        _verify_time_summary(
            value["producer_time"],
            path + ".producer_time",
            repetitions,
            producer_detail,
        )
        producer_memory_fields = {
            "status",
            "tracemalloc",
            "certificate",
            "worker_returncode",
            "worker_wall_elapsed_ns",
        }
        producer_memory = value["producer_memory"]
        _verify_worker_meta(
            producer_memory,
            path + ".producer_memory",
            producer_memory_fields,
        )
        if producer_memory["status"] != "verified":
            _fail(
                path + ".producer_memory",
                "producer memory sample is not verified",
            )
        _verify_memory(
            producer_memory["tracemalloc"],
            path + ".producer_memory.tracemalloc",
        )
        _verify_certificate_summary(
            producer_memory["certificate"],
            path + ".producer_memory.certificate",
            checked=True,
            **summary_args,
        )
        if producer_memory["certificate"] != expected_summary:
            _fail(
                path + ".producer_memory.certificate",
                "certificate differs across fresh runs",
            )

        def checker_detail(detail, detail_path):
            fields = {
                "status",
                "elapsed_ns",
                "certificate_sha256",
                "checker_status",
                "checker_certificate_hash",
                "worker_returncode",
                "worker_wall_elapsed_ns",
            }
            _verify_worker_meta(detail, detail_path, fields)
            if (
                detail["status"] != "verified"
                or detail["checker_status"] != "VERIFIED"
            ):
                _fail(detail_path, "checker timing sample is not verified")
            _integer(detail["elapsed_ns"], detail_path + ".elapsed_ns")
            if (
                detail["certificate_sha256"] != expected_hash
                or detail["checker_certificate_hash"] != expected_hash
            ):
                _fail(detail_path, "checker certificate hash mismatch")

        if (
            value["checker_time"] is None
            or value["checker_memory"] is None
        ):
            _fail(path, "successful workflow lacks checker measurements")
        _verify_time_summary(
            value["checker_time"],
            path + ".checker_time",
            repetitions,
            checker_detail,
        )
        checker_memory_fields = {
            "status",
            "tracemalloc",
            "certificate_sha256",
            "checker_status",
            "checker_certificate_hash",
            "worker_returncode",
            "worker_wall_elapsed_ns",
        }
        checker_memory = value["checker_memory"]
        _verify_worker_meta(
            checker_memory,
            path + ".checker_memory",
            checker_memory_fields,
        )
        if (
            checker_memory["status"] != "verified"
            or checker_memory["checker_status"] != "VERIFIED"
        ):
            _fail(
                path + ".checker_memory",
                "checker memory sample is not verified",
            )
        _verify_memory(
            checker_memory["tracemalloc"],
            path + ".checker_memory.tracemalloc",
        )
        if (
            checker_memory["certificate_sha256"] != expected_hash
            or checker_memory["checker_certificate_hash"] != expected_hash
        ):
            _fail(
                path + ".checker_memory",
                "checker certificate hash mismatch",
            )
        _verify_certificate_summary(
            value["certificate"],
            path + ".certificate",
            checked=False,
            **summary_args,
        )
        expected_unchecked = dict(expected_summary)
        expected_unchecked.pop("checker_status")
        expected_unchecked.pop("checker_certificate_hash")
        if value["certificate"] != expected_unchecked:
            _fail(
                path + ".certificate", "final certificate summary mismatch"
            )
        if value["measurement_complete"] is not True:
            _fail(
                path + ".measurement_complete",
                "verified workflow marked incomplete",
            )
        return "verified"

    if expected_outcome == "success":
        _fail(path, "expected successful workflow")
    _verify_kernel_error(value["prepare"], path + ".prepare")

    def failed_detail(detail, detail_path):
        _verify_kernel_error(detail, detail_path)

    _verify_time_summary(
        value["producer_time"],
        path + ".producer_time",
        repetitions,
        failed_detail,
    )
    _verify_kernel_error(
        value["producer_memory"],
        path + ".producer_memory",
        memory=True,
    )
    if (
        value["checker_time"] is not None
        or value["checker_memory"] is not None
    ):
        _fail(
            path,
            "LIMIT_REACHED workflow must not claim checker measurements",
        )
    if value["measurement_complete"] is not False:
        _fail(
            path + ".measurement_complete",
            "LIMIT_REACHED workflow marked complete",
        )
    return "limit_reached"



def _build_boundary(config, contexts, revised=False):
    boundary = config["boundary_family"]
    outputs = {
        name: {"type": {"kind": "bool"}, "required": False}
        for name in config["outputs"]
    }
    return {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": f"T06 fixed-density boundary {contexts:05d}",
        "inputs": {
            boundary["input"]: {
                "kind": "int",
                "min": 0,
                "max": contexts - 1,
            }
        },
        "outputs": outputs,
        "constraints": [],
        "facts": [],
        "rules": [
            {
                "id": f"B{index:03d}",
                "source": (
                    "T06 fixed-density boundary workload rule "
                    f"{index:03d}"
                ),
                "when": {"const": True},
                "then": {
                    "output": config["outputs"][index % 10],
                    "value": revised and index == 0,
                },
                "overrides": [],
            }
            for index in range(boundary["rule_count"])
        ],
    }


def _verify_prepare_probe(response, path, outcome, operation, contexts):
    if outcome == "success":
        fields = {
            "status",
            "producer_elapsed_ns",
            "checker_elapsed_ns",
            "certificate",
            "worker_returncode",
            "worker_wall_elapsed_ns",
        }
        _verify_worker_meta(response, path, fields)
        if response["status"] != "verified":
            _fail(path, "successful probe worker is not verified")
        _integer(
            response["producer_elapsed_ns"],
            path + ".producer_elapsed_ns",
        )
        _integer(
            response["checker_elapsed_ns"],
            path + ".checker_elapsed_ns",
        )
        _verify_certificate_summary(
            response["certificate"],
            path + ".certificate",
            checked=True,
            operation=operation,
            total_contexts=contexts,
            admitted_contexts=None if operation == "diff" else contexts,
        )
    elif outcome == "limit_reached":
        _verify_kernel_error(response, path)
    else:
        _fail(path, "unexpected probe outcome in a formal report")


def _verify_search(search, path, operation, config):
    _exact(
        search,
        {
            "search_status",
            "last_success_contexts",
            "first_failure_contexts",
            "probe_order",
            "probes",
        },
        path,
    )
    if search["search_status"] not in {
        "consecutive_boundary_found",
        "no_limit_within_1_to_10000",
    }:
        _fail(path + ".search_status", "boundary search was not completed")
    if (
        type(search["probe_order"]) is not list
        or type(search["probes"]) is not list
    ):
        _fail(path, "probe fields must be arrays")
    contexts = []
    outcomes = {}
    for index, probe in enumerate(search["probes"]):
        probe_path = f"{path}.probes[{index}]"
        _exact(
            probe,
            {
                "contexts",
                "outcome",
                "base_model_sha256",
                "revision_model_sha256",
                "response",
                "certificate_published",
                "certificate_file_sha256",
            },
            probe_path,
        )
        _integer(probe["contexts"], probe_path + ".contexts", minimum=1)
        if probe["contexts"] > config["boundary_family"]["context_max"]:
            _fail(probe_path + ".contexts", "probe exceeds family")
        contexts.append(probe["contexts"])
        if probe["contexts"] in outcomes:
            _fail(probe_path + ".contexts", "duplicate probe")
        outcomes[probe["contexts"]] = probe["outcome"]
        base = _build_boundary(config, probe["contexts"], False)
        revision = _build_boundary(config, probe["contexts"], True)
        if probe["base_model_sha256"] != digest(base):
            _fail(
                probe_path + ".base_model_sha256",
                "boundary model hash mismatch",
            )
        expected_revision = (
            digest(revision) if operation == "diff" else None
        )
        if probe["revision_model_sha256"] != expected_revision:
            _fail(
                probe_path + ".revision_model_sha256",
                "boundary revision hash mismatch",
            )
        _verify_prepare_probe(
            probe["response"],
            probe_path + ".response",
            probe["outcome"],
            operation,
            probe["contexts"],
        )
        if probe["outcome"] == "success":
            if probe["certificate_published"] is not True:
                _fail(
                    probe_path,
                    "successful probe lacks published certificate",
                )
            expected_hash = probe["response"]["certificate"]["sha256"]
            if probe["certificate_file_sha256"] != expected_hash:
                _fail(
                    probe_path + ".certificate_file_sha256",
                    "certificate file hash mismatch",
                )
        else:
            if (
                probe["certificate_published"] is not False
                or probe["certificate_file_sha256"] is not None
            ):
                _fail(probe_path, "failed probe left a certificate")
    if contexts != sorted(contexts):
        _fail(path + ".probes", "probe records are not sorted")
    if (
        len(search["probe_order"]) != len(set(search["probe_order"]))
        or set(search["probe_order"]) != set(contexts)
    ):
        _fail(
            path + ".probe_order",
            "probe order is not a permutation of recorded probes",
        )
    if search["probe_order"][:2] != [1, 10000]:
        _fail(
            path + ".probe_order",
            "search did not start at both family endpoints",
        )
    if outcomes.get(1) != "success":
        _fail(path, "boundary family lacks verified lower endpoint")

    expected_order = [1, 10000]
    if outcomes.get(10000) == "success":
        if search["search_status"] != "no_limit_within_1_to_10000":
            _fail(path, "upper success has wrong search status")
        if (
            search["last_success_contexts"] != 10000
            or search["first_failure_contexts"] is not None
        ):
            _fail(path, "upper success endpoints mismatch")
    else:
        low, high = 1, 10000
        while high - low > 1:
            middle = (low + high) // 2
            expected_order.append(middle)
            if outcomes.get(middle) == "success":
                low = middle
            elif outcomes.get(middle) == "limit_reached":
                high = middle
            else:
                _fail(
                    path,
                    "binary-search probe is missing or invalid",
                )
        if search["search_status"] != "consecutive_boundary_found":
            _fail(path, "adjacent endpoints have wrong search status")
        if (
            search["last_success_contexts"] != low
            or search["first_failure_contexts"] != high
        ):
            _fail(
                path,
                "recorded endpoints are not the replayed adjacent pair",
            )
    if search["probe_order"] != expected_order:
        _fail(
            path + ".probe_order",
            "probe order differs from algorithm replay",
        )


def _verify_endpoint(
    endpoint,
    path,
    operation,
    label,
    contexts,
    config,
    endpoints_dir,
):
    if contexts is None:
        if endpoint is not None:
            _fail(path, "endpoint must be null")
        return None, None
    _exact(endpoint, {"contexts", "base", "revision"}, path)
    if endpoint["contexts"] != contexts:
        _fail(path + ".contexts", "search/endpoint mismatch")

    def check_binding(binding, binding_path, revised):
        _exact(
            binding,
            {
                "path",
                "model_sha256",
                "canonical_bytes",
                "file_sha256",
                "file_bytes",
                "inputs",
                "outputs",
                "rules",
            },
            binding_path,
        )
        suffix = "-revision" if revised else ""
        expected_path = (
            Path(endpoints_dir)
            / f"{operation}-{label}-{contexts:05d}{suffix}.json"
        )
        if binding["path"] != _display_path(expected_path):
            _fail(binding_path + ".path", "endpoint path mismatch")
        model = load_json(expected_path)
        expected_model = _build_boundary(config, contexts, revised)
        if model != expected_model:
            _fail(
                binding_path,
                "saved endpoint differs from independent rebuild",
            )
        validate_model(model)
        expected = {
            "path": _display_path(expected_path),
            "model_sha256": digest(model),
            "canonical_bytes": len(
                canonical_json(model).encode("utf-8")
            ),
            "file_sha256": _raw_sha256(expected_path),
            "file_bytes": expected_path.stat().st_size,
            "inputs": len(model["inputs"]),
            "outputs": len(model["outputs"]),
            "rules": len(model["rules"]),
        }
        if binding != expected:
            _fail(binding_path, "endpoint binding mismatch")
        return digest(model)

    base_hash = check_binding(endpoint["base"], path + ".base", False)
    revision_hash = None
    if operation == "diff":
        if endpoint["revision"] is None:
            _fail(path + ".revision", "diff endpoint lacks revision")
        revision_hash = check_binding(
            endpoint["revision"], path + ".revision", True
        )
    elif endpoint["revision"] is not None:
        _fail(path + ".revision", "non-diff endpoint has revision")
    return base_hash, revision_hash


def _verify_cli_run(value, path):
    _exact(
        value,
        {"timed_out", "returncode", "json", "stdout", "stderr"},
        path,
    )
    if value["timed_out"] is not False or value["returncode"] != 2:
        _fail(path, "LIMIT_REACHED CLI run must finish with exit 2")
    _exact(
        value["json"],
        {"status", "message", "finding"},
        path + ".json",
    )
    if (
        value["json"]["status"] != "LIMIT_REACHED"
        or value["json"]["finding"] != "undetermined"
    ):
        _fail(
            path + ".json",
            "CLI result is not LIMIT_REACHED/undetermined",
        )
    _text(value["json"]["message"], path + ".json.message")
    try:
        parsed_stdout = json.loads(value["stdout"])
    except (TypeError, json.JSONDecodeError):
        _fail(path + ".stdout", "stdout is not JSON")
    if parsed_stdout != value["json"]:
        _fail(path + ".stdout", "stdout and parsed JSON differ")
    if type(value["stderr"]) is not str:
        _fail(path + ".stderr", "stderr must be text")


def _verify_partial(value, path, operation, python_executable):
    _exact(
        value,
        {
            "command_shape",
            "absent_target_run",
            "existing_target_run",
            "checks",
            "passed",
        },
        path,
    )
    expected_command = [
        python_executable,
        "-m",
        "rulekernel",
        {
            "check": "check",
            "diff": "diff",
            "reachability": "reachability",
            "staged": "reachability-staged",
        }[operation],
        "<left>",
    ]
    if operation == "diff":
        expected_command.append("<right>")
    expected_command.extend(
        ["--certificate", "<certificate>", "--json"]
    )
    if value["command_shape"] != expected_command:
        _fail(path + ".command_shape", "CLI command shape mismatch")
    _verify_cli_run(
        value["absent_target_run"], path + ".absent_target_run"
    )
    _verify_cli_run(
        value["existing_target_run"], path + ".existing_target_run"
    )
    check_fields = {
        "absent_target_remained_absent",
        "existing_target_bytes_unchanged",
        "existing_target_sha256_before",
        "existing_target_sha256_after",
        "absent_run_exit_2",
        "existing_run_exit_2",
        "absent_run_limit_reached",
        "existing_run_limit_reached",
    }
    _exact(value["checks"], check_fields, path + ".checks")
    sentinel_hash = hashlib.sha256(
        b'{"sentinel":"t06-existing-artifact"}\n'
    ).hexdigest()
    boolean_fields = check_fields - {
        "existing_target_sha256_before",
        "existing_target_sha256_after",
    }
    for field in boolean_fields:
        if value["checks"][field] is not True:
            _fail(
                path + ".checks." + field,
                "atomic failure assertion is false",
            )
    if (
        value["checks"]["existing_target_sha256_before"]
        != sentinel_hash
        or value["checks"]["existing_target_sha256_after"]
        != sentinel_hash
    ):
        _fail(path + ".checks", "existing sentinel hash mismatch")
    if value["passed"] is not True:
        _fail(path + ".passed", "partial-artifact check did not pass")


def _verify_environment(value):
    _exact(
        value,
        {
            "captured_at_utc",
            "python",
            "platform",
            "worker_environment",
        },
        "body.environment",
    )
    _exact(
        value["python"],
        {"executable", "implementation", "version", "hash_seed"},
        "body.environment.python",
    )
    for field in ("executable", "implementation", "version", "hash_seed"):
        _text(
            value["python"][field],
            "body.environment.python." + field,
        )
    if value["python"]["hash_seed"] != "0 in measurement workers":
        _fail(
            "body.environment.python.hash_seed",
            "worker hash seed statement mismatch",
        )
    _exact(
        value["worker_environment"],
        {"PYTHONHASHSEED", "TZ", "LC_ALL"},
        "body.environment.worker_environment",
    )
    if value["worker_environment"] != {
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
        "LC_ALL": "C.UTF-8",
    }:
        _fail(
            "body.environment.worker_environment",
            "worker environment mismatch",
        )
    _exact(
        value["platform"],
        {
            "system",
            "release",
            "version",
            "machine",
            "processor",
            "cpu_model_linux",
            "mem_total_linux",
        },
        "body.environment.platform",
    )
    for field, item in value["platform"].items():
        _text(
            item,
            "body.environment.platform." + field,
            optional=True,
        )
    _text(
        value["captured_at_utc"],
        "body.environment.captured_at_utc",
    )
    try:
        stamp = datetime.fromisoformat(value["captured_at_utc"])
    except ValueError:
        _fail(
            "body.environment.captured_at_utc",
            "invalid ISO timestamp",
        )
    if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        _fail(
            "body.environment.captured_at_utc",
            "timestamp is not UTC",
        )


def _verify_contract(value, repetitions):
    fields = {
        "official_repetitions",
        "actual_repetitions",
        "standard_three_repetition_run",
        "time_unit",
        "byte_unit",
        "mib_bytes",
        "producer_timing",
        "checker_timing",
        "memory",
        "boundary_algorithm",
        "completion_rule",
        "limits",
    }
    _exact(value, fields, "body.measurement_contract")
    if (
        value["official_repetitions"] != 3
        or value["actual_repetitions"] != repetitions
        or value["standard_three_repetition_run"]
        is not (repetitions == 3)
        or value["time_unit"] != "nanoseconds"
        or value["byte_unit"] != "bytes"
        or value["mib_bytes"] != 1024 * 1024
    ):
        _fail(
            "body.measurement_contract",
            "measurement units or repetitions mismatch",
        )
    _exact(
        value["limits"],
        {"max_contexts", "max_certificate_bytes"},
        "body.measurement_contract.limits",
    )
    if value["limits"] != {
        "max_contexts": MAX_CONTEXTS,
        "max_certificate_bytes": MAX_CERTIFICATE_BYTES,
    }:
        _fail(
            "body.measurement_contract.limits",
            "kernel limits mismatch",
        )
    for field in (
        "producer_timing",
        "checker_timing",
        "memory",
        "boundary_algorithm",
        "completion_rule",
    ):
        _text(value[field], "body.measurement_contract." + field)



def _verify_artifact_paths(
    report_path, endpoints_dir, config_path, manifest_path, records
):
    report_path = Path(report_path).resolve()
    endpoints_dir = Path(endpoints_dir).resolve()
    generated_dir = Path(manifest_path).resolve().parent
    protected = {
        Path(config_path).resolve(),
        Path(manifest_path).resolve(),
        (HERE / "measure.py").resolve(),
        (HERE / "generate.py").resolve(),
    }
    protected.update((ROOT / relative).resolve() for relative in KERNEL_SOURCES)
    protected.update(record["path"].resolve() for record in records.values())
    if report_path in protected:
        _fail("body.command.arguments.output", "report collides with a bound input")
    if report_path == generated_dir or report_path.is_relative_to(generated_dir):
        _fail("body.command.arguments.output", "report is inside generated inputs")
    if (
        endpoints_dir == generated_dir
        or endpoints_dir.is_relative_to(generated_dir)
        or generated_dir.is_relative_to(endpoints_dir)
    ):
        _fail("body.command.arguments.endpoints", "endpoint tree overlaps generated inputs")
    if any(path == endpoints_dir or path.is_relative_to(endpoints_dir) for path in protected):
        _fail("body.command.arguments.endpoints", "endpoint tree contains a bound input")
    if report_path == endpoints_dir or report_path.is_relative_to(endpoints_dir):
        _fail("body.command.arguments.output", "report is inside the endpoint tree")


def verify_report(
    report_path,
    *,
    expected_report_sha256,
    config_path=DEFAULT_CONFIG,
    generated_dir=DEFAULT_GENERATED,
    endpoints_dir=None,
    require_full=True,
):
    """Verify a saved report without rerunning measured kernel operations."""
    report_path = Path(report_path)
    _hash(expected_report_sha256, "expected_report_sha256")
    actual_report_sha256 = _raw_sha256(report_path)
    if actual_report_sha256 != expected_report_sha256:
        _fail("report", "external report SHA-256 mismatch")
    report = load_json(report_path, max_bytes=MAX_REPORT_BYTES)
    _exact(report, {"format", "body_sha256", "body"}, "report")
    if report["format"] != REPORT_FORMAT:
        _fail("report.format", "unsupported report format")
    _hash(report["body_sha256"], "report.body_sha256")
    if report["body_sha256"] != digest(report["body"]):
        _fail("report.body_sha256", "body hash mismatch")

    body = report["body"]
    _exact(
        body,
        {
            "measurement_version",
            "provenance",
            "bindings",
            "environment",
            "command",
            "measurement_contract",
            "generated_manifest",
            "static_matrix",
            "boundaries",
        },
        "body",
    )
    if body["measurement_version"] != MEASUREMENT_VERSION:
        _fail("body.measurement_version", "unsupported version")
    _exact(
        body["provenance"],
        {"kind", "statement", "scope_claim"},
        "body.provenance",
    )
    if body["provenance"]["kind"] != PROVENANCE:
        _fail(
            "body.provenance.kind",
            "T04/T05 provenance must not be claimed",
        )
    _text(body["provenance"]["statement"], "body.provenance.statement")
    _text(body["provenance"]["scope_claim"], "body.provenance.scope_claim")

    config, manifest, manifest_path, records = _load_manifest(
        config_path, generated_dir
    )
    _verify_bindings(
        body["bindings"],
        config_path,
        manifest_path,
        config,
        manifest,
    )
    _verify_environment(body["environment"])
    _exact(
        body["generated_manifest"],
        {"path", "canonical_sha256", "model_entry_count"},
        "body.generated_manifest",
    )
    if body["generated_manifest"] != {
        "path": _display_path(manifest_path),
        "canonical_sha256": digest(manifest),
        "model_entry_count": len(records),
    }:
        _fail(
            "body.generated_manifest",
            "manifest report binding mismatch",
        )

    _exact(body["command"], {"module", "arguments"}, "body.command")
    if body["command"]["module"] != "benchmarks.t06.measure":
        _fail("body.command.module", "unexpected producer module")
    arguments = body["command"]["arguments"]
    _exact(
        arguments,
        {
            "config",
            "generated",
            "output",
            "endpoints",
            "profiles",
            "operations",
            "repetitions",
            "timeout_seconds",
            "skip_static",
            "skip_boundaries",
            "regenerate_static",
        },
        "body.command.arguments",
    )
    if arguments["config"] != _display_path(config_path):
        _fail("body.command.arguments.config", "config path mismatch")
    if arguments["generated"] != _display_path(generated_dir):
        _fail(
            "body.command.arguments.generated",
            "generated path mismatch",
        )
    output_path = _reported_path(
        arguments["output"], "body.command.arguments.output"
    )
    if output_path != report_path.resolve():
        _fail("body.command.arguments.output", "reported output path differs from report path")
    repetitions = arguments["repetitions"]
    if (
        type(repetitions) is not int
        or not 1 <= repetitions <= 9
        or repetitions % 2 == 0
    ):
        _fail(
            "body.command.arguments.repetitions",
            "invalid repetition count",
        )
    timeout = arguments["timeout_seconds"]
    if (
        type(timeout) not in (int, float)
        or isinstance(timeout, bool)
        or not isfinite(timeout)
        or timeout <= 0
    ):
        _fail(
            "body.command.arguments.timeout_seconds",
            "invalid timeout",
        )
    for field in (
        "skip_static",
        "skip_boundaries",
        "regenerate_static",
    ):
        if type(arguments[field]) is not bool:
            _fail(
                "body.command.arguments." + field,
                "expected Boolean",
            )
    if (
        type(arguments["profiles"]) is not list
        or any(type(item) is not str for item in arguments["profiles"])
        or len(arguments["profiles"]) != len(set(arguments["profiles"]))
    ):
        _fail(
            "body.command.arguments.profiles",
            "invalid profile selection",
        )
    scenarios = _matrix_scenarios(config)
    if any(
        profile not in scenarios for profile in arguments["profiles"]
    ):
        _fail("body.command.arguments.profiles", "unknown profile")
    if (
        type(arguments["operations"]) is not list
        or any(type(item) is not str for item in arguments["operations"])
        or len(arguments["operations"])
        != len(set(arguments["operations"]))
        or any(
            operation not in OPERATIONS
            for operation in arguments["operations"]
        )
    ):
        _fail(
            "body.command.arguments.operations",
            "invalid operation selection",
        )
    _verify_contract(body["measurement_contract"], repetitions)

    if endpoints_dir is None:
        endpoints_dir = _reported_path(
            arguments["endpoints"],
            "body.command.arguments.endpoints",
        )
    elif arguments["endpoints"] != _display_path(endpoints_dir):
        _fail(
            "body.command.arguments.endpoints",
            "endpoint directory mismatch",
        )
    _verify_artifact_paths(
        report_path, endpoints_dir, config_path, manifest_path, records
    )

    expected_static = (
        set() if arguments["skip_static"] else set(arguments["profiles"])
    )
    if (
        type(body["static_matrix"]) is not dict
        or set(body["static_matrix"]) != expected_static
    ):
        _fail(
            "body.static_matrix",
            "static section does not match command selection",
        )
    verified_workflows = 0
    limit_workflows = 0
    for scenario, value in body["static_matrix"].items():
        path = f"body.static_matrix[{scenario!r}]"
        _exact(
            value,
            {
                "scenario",
                "dimensions",
                "base",
                "revision",
                "characterization",
                "operations",
            },
            path,
        )
        if value["scenario"] != scenario:
            _fail(path + ".scenario", "scenario mismatch")
        _, count, guard, background = scenario.split("-")
        if value["dimensions"] != {
            "rule_count": int(count),
            "guard_profile": guard,
            "background_profile": background,
        }:
            _fail(path + ".dimensions", "scenario dimensions mismatch")
        base = records[scenario + ".json"]
        revision = records[scenario + "-revision.json"]
        _verify_model_binding(value["base"], base, path + ".base")
        _verify_model_binding(
            value["revision"], revision, path + ".revision"
        )
        characterization = value["characterization"]
        _verify_characterization(
            characterization,
            base["model"],
            path + ".characterization",
        )
        if (
            type(value["operations"]) is not dict
            or set(value["operations"]) != set(arguments["operations"])
        ):
            _fail(path + ".operations", "operation selection mismatch")
        for operation, workflow in value["operations"].items():
            outcome = _verify_workflow(
                workflow,
                path + f".operations[{operation!r}]",
                operation,
                digest(base["model"]),
                (
                    digest(revision["model"])
                    if operation == "diff"
                    else None
                ),
                repetitions,
                characterization["total_contexts"],
                (
                    None
                    if operation == "diff"
                    else characterization["admitted_contexts"]
                ),
            )
            verified_workflows += outcome == "verified"
            limit_workflows += outcome == "limit_reached"

    expected_boundaries = (
        set()
        if arguments["skip_boundaries"]
        else set(arguments["operations"])
    )
    if (
        type(body["boundaries"]) is not dict
        or set(body["boundaries"]) != expected_boundaries
    ):
        _fail(
            "body.boundaries",
            "boundary section does not match command selection",
        )
    for operation, value in body["boundaries"].items():
        path = f"body.boundaries[{operation!r}]"
        _exact(
            value,
            {
                "operation",
                "family",
                "search",
                "last_success_endpoint",
                "first_failure_endpoint",
                "last_success_measurement",
                "first_failure_measurement",
                "partial_artifact_check",
            },
            path,
        )
        if value["operation"] != operation:
            _fail(path + ".operation", "operation mismatch")
        expected_family = {
            **config["boundary_family"],
            "guard_profile": "all guards are constant true",
            "background_profile": "all contexts admitted",
            "provenance": PROVENANCE,
        }
        if value["family"] != expected_family:
            _fail(path + ".family", "boundary family mismatch")
        _verify_search(
            value["search"],
            path + ".search",
            operation,
            config,
        )
        if (
            require_full
            and value["search"]["search_status"]
            != "consecutive_boundary_found"
        ):
            _fail(
                path + ".search.search_status",
                "full official run requires a consecutive boundary",
            )
        last = value["search"]["last_success_contexts"]
        first = value["search"]["first_failure_contexts"]
        last_hash, last_revision = _verify_endpoint(
            value["last_success_endpoint"],
            path + ".last_success_endpoint",
            operation,
            "last-success",
            last,
            config,
            endpoints_dir,
        )
        first_hash, first_revision = _verify_endpoint(
            value["first_failure_endpoint"],
            path + ".first_failure_endpoint",
            operation,
            "first-failure",
            first,
            config,
            endpoints_dir,
        )
        _verify_workflow(
            value["last_success_measurement"],
            path + ".last_success_measurement",
            operation,
            last_hash,
            last_revision,
            repetitions,
            last,
            None if operation == "diff" else last,
            expected_outcome="success",
        )
        verified_workflows += 1
        if first is None:
            if (
                value["first_failure_measurement"] is not None
                or value["partial_artifact_check"] is not None
            ):
                _fail(
                    path,
                    "no-failure boundary contains failure artifacts",
                )
        else:
            _verify_workflow(
                value["first_failure_measurement"],
                path + ".first_failure_measurement",
                operation,
                first_hash,
                first_revision,
                repetitions,
                first,
                None if operation == "diff" else first,
                expected_outcome="limit_reached",
            )
            limit_workflows += 1
            _verify_partial(
                value["partial_artifact_check"],
                path + ".partial_artifact_check",
                operation,
                body["environment"]["python"]["executable"],
            )

    if require_full:
        if (
            arguments["skip_static"]
            or arguments["skip_boundaries"]
            or arguments["profiles"] != scenarios
            or arguments["operations"] != list(OPERATIONS)
            or repetitions != 3
        ):
            _fail(
                "body.command.arguments",
                "report is not the complete official T06 run",
            )
    return {
        "status": "VERIFIED",
        "format": REPORT_FORMAT,
        "report_sha256": actual_report_sha256,
        "body_sha256": report["body_sha256"],
        "externally_anchored": True,
        "full_official_run": require_full,
        "static_scenarios": len(body["static_matrix"]),
        "boundary_operations": len(body["boundaries"]),
        "verified_workflows": verified_workflows,
        "limit_reached_workflows": limit_workflows,
        "checker_file_sha256": _raw_sha256(__file__),
        "limitations": [
            (
                "timing and tracemalloc values are checked for integrity "
                "and arithmetic but are not rerun"
            ),
            (
                "environment fields are self-recorded and are not "
                "third-party attestation"
            ),
            (
                "the report self-hash is not an external anchor; "
                "expected_report_sha256 supplies that anchor"
            ),
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Verify a saved T06 report without rerunning benchmarks"
        )
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--generated", type=Path, default=DEFAULT_GENERATED
    )
    parser.add_argument("--endpoints", type=Path)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "accept a selected smoke report instead of requiring "
            "the full official matrix"
        ),
    )
    args = parser.parse_args(argv)
    try:
        result = verify_report(
            args.report,
            expected_report_sha256=args.expected_report_sha256,
            config_path=args.config,
            generated_dir=args.generated,
            endpoints_dir=args.endpoints,
            require_full=not args.allow_partial,
        )
    except (
        ReportVerificationError,
        KernelError,
        OSError,
        ValueError,
    ) as exc:
        print(
            canonical_json(
                {"status": "REPORT_INVALID", "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
