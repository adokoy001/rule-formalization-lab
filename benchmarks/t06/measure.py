"""Reproducible measurement harness for the synthetic T06 workloads.

The harness never treats a producer result as complete until the matching
independent checker accepts it.  Timed and tracemalloc runs use fresh Python
processes.  The generated models are synthetic authored-Core workloads; they
do not carry a T04/T05 source, review, or scope-expectation chain.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import heapq
from itertools import product
import json
from math import prod
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from time import perf_counter_ns
import tracemalloc


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.t06.generate import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT,
    MANIFEST_FORMAT,
    build_boundary,
    check_static,
    generate_static,
    validate_config,
)
from rulekernel.checker import verify  # noqa: E402
from rulekernel.diff import analyze_diff  # noqa: E402
from rulekernel.diff_checker import verify_diff  # noqa: E402
from rulekernel.engine import analyze  # noqa: E402
from rulekernel.model import (  # noqa: E402
    KernelError,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    canonical_json,
    digest,
    load_json,
    validate_model,
)
from rulekernel.reachability import analyze_reachability  # noqa: E402
from rulekernel.reachability_checker import verify_reachability  # noqa: E402
from rulekernel.staged_reachability import analyze_staged_reachability  # noqa: E402
from rulekernel.staged_reachability_checker import (  # noqa: E402
    verify_staged_reachability,
)


REPORT_FORMAT = "t06-benchmark-report/1"
MEASUREMENT_VERSION = "0.1.0"
OPERATIONS = ("check", "diff", "reachability", "staged")
DEFAULT_ENDPOINTS = HERE / "results" / "boundary-endpoints"
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


class MeasurementError(Exception):
    """A benchmark-definition or harness error."""


def _raw_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_bytes(value):
    return len(canonical_json(value).encode("utf-8"))


def _display_path(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _write_replace(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = canonical_json(value)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _write_new_or_same(path, value, *, overwrite):
    path = Path(path)
    rendered = canonical_json(value)
    encoded = rendered.encode("utf-8")
    if path.exists():
        if path.read_bytes() == encoded:
            return
        if not overwrite:
            raise MeasurementError(f"refusing to replace different endpoint model: {path}")
    _write_replace(path, value)


def _domain_values(domain):
    if domain["kind"] == "bool":
        return (False, True)
    if domain["kind"] == "int":
        return range(domain["min"], domain["max"] + 1)
    return domain["values"]


def _eval_expression(expression, assignment):
    if "var" in expression:
        return assignment[expression["var"]]
    if "const" in expression:
        return expression["const"]
    operation = expression["op"]
    arguments = expression["args"]
    if operation == "not":
        return not _eval_expression(arguments[0], assignment)
    if operation == "and":
        return all(_eval_expression(argument, assignment) for argument in arguments)
    if operation == "or":
        return any(_eval_expression(argument, assignment) for argument in arguments)
    left = _eval_expression(arguments[0], assignment)
    right = _eval_expression(arguments[1], assignment)
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
    raise MeasurementError(f"unsupported validated operator: {operation}")


def _override_order(rules):
    by_id = {rule["id"]: rule for rule in rules}
    blockers = {rule_id: [] for rule_id in by_id}
    degree = dict.fromkeys(by_id, 0)
    for rule in rules:
        for target in rule["overrides"]:
            blockers[target].append(rule["id"])
            degree[target] += 1
    ready = [rule_id for rule_id, count in degree.items() if count == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        rule_id = heapq.heappop(ready)
        order.append(rule_id)
        for target in by_id[rule_id]["overrides"]:
            degree[target] -= 1
            if degree[target] == 0:
                heapq.heappush(ready, target)
    if len(order) != len(rules):
        raise MeasurementError("validated model unexpectedly contains an override cycle")
    return order, blockers


def _fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator}


def characterize_model(model):
    """Stream over a model to describe workload density without making evidence."""
    validate_model(model)
    names = sorted(model["inputs"])
    domains = [_domain_values(model["inputs"][name]) for name in names]
    total = prod(len(domain) for domain in domains)
    if total > MAX_CONTEXTS:
        raise MeasurementError("characterization scope exceeds the kernel hard limit")
    rules = {rule["id"]: rule for rule in model["rules"]}
    rule_ids = sorted(rules)
    order, blockers = _override_order(model["rules"])
    facts_total = constraints_total = admitted_total = 0
    guard_activations = enabled_activations = effective_activations = 0
    max_guard = max_enabled = max_effective = 0
    per_rule_guard = dict.fromkeys(rule_ids, 0)
    per_rule_enabled = dict.fromkeys(rule_ids, 0)
    per_rule_effective = dict.fromkeys(rule_ids, 0)
    started = perf_counter_ns()
    for values in product(*domains):
        assignment = dict(zip(names, values))
        facts_match = all(
            assignment[fact["var"]] == fact["value"] for fact in model["facts"])
        constraints_match = all(
            _eval_expression(expression, assignment)
            for expression in model["constraints"])
        admitted = facts_match and constraints_match
        facts_total += int(facts_match)
        constraints_total += int(constraints_match)
        admitted_total += int(admitted)
        guard_truth = {
            rule_id: _eval_expression(rules[rule_id]["when"], assignment)
            for rule_id in rule_ids
        }
        guard_ids = [rule_id for rule_id in rule_ids if guard_truth[rule_id]]
        enabled_ids = guard_ids if admitted else []
        effective_ids = []
        if admitted:
            surviving = {}
            for rule_id in order:
                surviving[rule_id] = guard_truth[rule_id] and not any(
                    surviving[parent] for parent in blockers[rule_id])
            effective_ids = [
                rule_id for rule_id in rule_ids if surviving[rule_id]]
        guard_activations += len(guard_ids)
        enabled_activations += len(enabled_ids)
        effective_activations += len(effective_ids)
        max_guard = max(max_guard, len(guard_ids))
        max_enabled = max(max_enabled, len(enabled_ids))
        max_effective = max(max_effective, len(effective_ids))
        for rule_id in guard_ids:
            per_rule_guard[rule_id] += 1
        for rule_id in enabled_ids:
            per_rule_enabled[rule_id] += 1
        for rule_id in effective_ids:
            per_rule_effective[rule_id] += 1
    elapsed = perf_counter_ns() - started
    rule_denominator = total * len(rule_ids)
    return {
        "algorithm": "measure-streaming-characterization/1",
        "elapsed_ns_not_a_kernel_benchmark": elapsed,
        "total_contexts": total,
        "facts_matching_contexts": facts_total,
        "constraints_matching_contexts": constraints_total,
        "admitted_contexts": admitted_total,
        "background_fit": _fraction(admitted_total, total),
        "guard_activations": guard_activations,
        "enabled_activations": enabled_activations,
        "effective_activations": effective_activations,
        "guard_density": _fraction(guard_activations, rule_denominator),
        "enabled_density_declared_scope": _fraction(
            enabled_activations, rule_denominator),
        "effective_density_declared_scope": _fraction(
            effective_activations, rule_denominator),
        "average_guard_ids_per_context": _fraction(guard_activations, total),
        "average_enabled_ids_per_context": _fraction(enabled_activations, total),
        "average_effective_ids_per_context": _fraction(
            effective_activations, total),
        "max_guard_ids_per_context": max_guard,
        "max_enabled_ids_per_context": max_enabled,
        "max_effective_ids_per_context": max_effective,
        "rules_with_no_guard_witness": sum(
            count == 0 for count in per_rule_guard.values()),
        "rules_with_no_enabled_witness": sum(
            count == 0 for count in per_rule_enabled.values()),
        "rules_with_no_effective_witness": sum(
            count == 0 for count in per_rule_effective.values()),
        "per_rule_guard_min_max": [
            min(per_rule_guard.values(), default=0),
            max(per_rule_guard.values(), default=0),
        ],
        "per_rule_enabled_min_max": [
            min(per_rule_enabled.values(), default=0),
            max(per_rule_enabled.values(), default=0),
        ],
        "per_rule_effective_min_max": [
            min(per_rule_effective.values(), default=0),
            max(per_rule_effective.values(), default=0),
        ],
    }


def _producer(operation, left, right=None):
    if operation == "check":
        return analyze(left)
    if operation == "diff":
        return analyze_diff(left, right)
    if operation == "reachability":
        return analyze_reachability(left)
    if operation == "staged":
        return analyze_staged_reachability(left)
    raise MeasurementError(f"unknown operation: {operation}")


def _checker(operation, left, certificate, right=None):
    if operation == "check":
        return verify(left, certificate)
    if operation == "diff":
        return verify_diff(left, right, certificate)
    if operation == "reachability":
        return verify_reachability(left, certificate)
    if operation == "staged":
        return verify_staged_reachability(left, certificate)
    raise MeasurementError(f"unknown operation: {operation}")


def _certificate_summary(certificate, checked=None):
    finding_total = None
    if type(certificate.get("queries")) is list:
        finding_total = sum(query["count"] for query in certificate["queries"])
    attention_count = None
    if type(certificate.get("attention")) is list:
        attention_count = len(certificate["attention"])
    summary = {
        "sha256": digest(certificate),
        "canonical_bytes": _canonical_bytes(certificate),
        "remaining_to_8_mib_bytes": (
            MAX_CERTIFICATE_BYTES - _canonical_bytes(certificate)),
        "format": certificate.get("format"),
        "total_contexts": certificate.get("total_contexts"),
        "admitted_contexts": certificate.get("admitted_contexts"),
        "finding_total": finding_total,
        "attention_count": attention_count,
    }
    if checked is not None:
        summary["checker_status"] = checked.get("status")
        summary["checker_certificate_hash"] = checked.get("certificate_hash")
    return summary


def _kernel_error_result(exc, *, phase, elapsed_ns=None, memory=None):
    result = {
        "status": "kernel_error",
        "failure_phase": phase,
        "kernel_status": exc.status,
        "message": exc.message,
    }
    if elapsed_ns is not None:
        result["elapsed_ns"] = elapsed_ns
    if memory is not None:
        result["tracemalloc"] = memory
    return result


def _memory_snapshot(baseline, current, peak):
    return {
        "baseline_current_bytes": baseline,
        "final_current_bytes": current,
        "peak_bytes": peak,
        "incremental_peak_above_loaded_inputs_bytes": max(0, peak - baseline),
        "traceback_frames": 1,
    }


def _load_worker_models(args):
    left = load_json(args.left)
    right = None if args.right is None else load_json(args.right)
    return left, right


def _worker_prepare(args):
    left, right = _load_worker_models(args)
    started = perf_counter_ns()
    try:
        certificate = _producer(args.operation, left, right)
    except KernelError as exc:
        return _kernel_error_result(
            exc, phase="producer", elapsed_ns=perf_counter_ns() - started)
    producer_elapsed = perf_counter_ns() - started
    started = perf_counter_ns()
    try:
        checked = _checker(args.operation, left, certificate, right)
    except KernelError as exc:
        return _kernel_error_result(
            exc, phase="checker", elapsed_ns=perf_counter_ns() - started)
    checker_elapsed = perf_counter_ns() - started
    if checked.get("status") != "VERIFIED":
        return {
            "status": "checker_rejected",
            "failure_phase": "checker",
            "checker_status": checked.get("status"),
        }
    if args.output_certificate is None:
        raise MeasurementError("prepare worker requires --output-certificate")
    _write_replace(args.output_certificate, certificate)
    return {
        "status": "verified",
        "producer_elapsed_ns": producer_elapsed,
        "checker_elapsed_ns": checker_elapsed,
        "certificate": _certificate_summary(certificate, checked),
    }


def _worker_producer_time(args):
    left, right = _load_worker_models(args)
    started = perf_counter_ns()
    try:
        certificate = _producer(args.operation, left, right)
    except KernelError as exc:
        return _kernel_error_result(
            exc, phase="producer", elapsed_ns=perf_counter_ns() - started)
    elapsed = perf_counter_ns() - started
    try:
        checked = _checker(args.operation, left, certificate, right)
    except KernelError as exc:
        return {
            **_kernel_error_result(exc, phase="post_time_checker"),
            "elapsed_ns": elapsed,
        }
    if checked.get("status") != "VERIFIED":
        return {"status": "checker_rejected", "failure_phase": "post_time_checker",
                "elapsed_ns": elapsed, "checker_status": checked.get("status")}
    return {
        "status": "verified",
        "elapsed_ns": elapsed,
        "certificate": _certificate_summary(certificate, checked),
    }


def _worker_checker_time(args):
    left, right = _load_worker_models(args)
    certificate = load_json(
        args.certificate, max_bytes=MAX_CERTIFICATE_BYTES)
    started = perf_counter_ns()
    try:
        checked = _checker(args.operation, left, certificate, right)
    except KernelError as exc:
        return _kernel_error_result(
            exc, phase="checker", elapsed_ns=perf_counter_ns() - started)
    if checked.get("status") != "VERIFIED":
        return {"status": "checker_rejected", "failure_phase": "checker",
                "elapsed_ns": perf_counter_ns() - started,
                "checker_status": checked.get("status")}
    return {
        "status": "verified",
        "elapsed_ns": perf_counter_ns() - started,
        "certificate_sha256": digest(certificate),
        "checker_status": checked.get("status"),
        "checker_certificate_hash": checked.get("certificate_hash"),
    }


def _worker_producer_memory(args):
    tracemalloc.start(1)
    try:
        left, right = _load_worker_models(args)
        gc.collect()
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        try:
            certificate = _producer(args.operation, left, right)
        except KernelError as exc:
            current, peak = tracemalloc.get_traced_memory()
            memory = _memory_snapshot(baseline, current, peak)
            return _kernel_error_result(exc, phase="producer", memory=memory)
        current, peak = tracemalloc.get_traced_memory()
        memory = _memory_snapshot(baseline, current, peak)
    finally:
        tracemalloc.stop()
    try:
        checked = _checker(args.operation, left, certificate, right)
    except KernelError as exc:
        return {
            **_kernel_error_result(exc, phase="post_memory_checker"),
            "tracemalloc": memory,
        }
    if checked.get("status") != "VERIFIED":
        return {"status": "checker_rejected", "failure_phase": "post_memory_checker",
                "tracemalloc": memory, "checker_status": checked.get("status")}
    return {
        "status": "verified",
        "tracemalloc": memory,
        "certificate": _certificate_summary(certificate, checked),
    }


def _worker_checker_memory(args):
    tracemalloc.start(1)
    try:
        left, right = _load_worker_models(args)
        certificate = load_json(
            args.certificate, max_bytes=MAX_CERTIFICATE_BYTES)
        gc.collect()
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        try:
            checked = _checker(args.operation, left, certificate, right)
        except KernelError as exc:
            current, peak = tracemalloc.get_traced_memory()
            return _kernel_error_result(
                exc, phase="checker",
                memory=_memory_snapshot(baseline, current, peak))
        current, peak = tracemalloc.get_traced_memory()
        memory = _memory_snapshot(baseline, current, peak)
    finally:
        tracemalloc.stop()
    if checked.get("status") != "VERIFIED":
        return {"status": "checker_rejected", "failure_phase": "checker",
                "tracemalloc": memory, "checker_status": checked.get("status")}
    return {
        "status": "verified",
        "tracemalloc": memory,
        "certificate_sha256": digest(certificate),
        "checker_status": checked.get("status"),
        "checker_certificate_hash": checked.get("certificate_hash"),
    }


def _worker_main(args):
    try:
        if args.phase == "prepare":
            result = _worker_prepare(args)
        elif args.phase == "producer-time":
            result = _worker_producer_time(args)
        elif args.phase == "checker-time":
            result = _worker_checker_time(args)
        elif args.phase == "producer-memory":
            result = _worker_producer_memory(args)
        elif args.phase == "checker-memory":
            result = _worker_checker_memory(args)
        else:
            raise MeasurementError(f"unknown worker phase: {args.phase}")
    except MemoryError:
        result = {
            "status": "memory_error",
            "failure_phase": args.phase,
            "message": "Python raised MemoryError; this is not LIMIT_REACHED",
        }
    except Exception as exc:
        result = {
            "status": "worker_exception",
            "failure_phase": args.phase,
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
    print(canonical_json(result))
    return 0


def _read_first_matching(path, prefix):
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                return line.split(":", 1)[-1].strip()
    except OSError:
        return None
    return None


def _environment():
    uname = platform.uname()
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": {
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "hash_seed": "0 in measurement workers",
        },
        "platform": {
            "system": uname.system,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
            "processor": uname.processor or None,
            "cpu_model_linux": _read_first_matching("/proc/cpuinfo", "model name"),
            "mem_total_linux": _read_first_matching("/proc/meminfo", "MemTotal"),
        },
        "worker_environment": {
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
            "LC_ALL": "C.UTF-8",
        },
    }


def _source_bindings(config_path, manifest_path, config, manifest):
    paths = {
        "measure": Path(__file__),
        "generator": HERE / "generate.py",
        "config": Path(config_path),
        "manifest": Path(manifest_path),
    }
    for relative in KERNEL_SOURCES:
        paths[relative] = ROOT / relative
    return {
        "measurement_version": MEASUREMENT_VERSION,
        "files": {
            label: {
                "path": _display_path(path),
                "sha256": _raw_sha256(path),
                "bytes": path.stat().st_size,
            }
            for label, path in paths.items()
        },
        "config_canonical_sha256": digest(config),
        "manifest_canonical_sha256": digest(manifest),
    }


def _safe_generated_path(root, relative):
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise MeasurementError(f"manifest model path escapes generated directory: {relative}")
    return candidate


def _load_static(config_path, generated_dir, *, regenerate=False):
    config_path = Path(config_path)
    generated_dir = Path(generated_dir)
    config = load_json(config_path)
    validate_config(config)
    if regenerate:
        generate_static(config_path, generated_dir)
    generation_check = check_static(config_path, generated_dir)
    if generation_check["status"] != "MATCH":
        raise MeasurementError(
            "generated model bytes do not match the deterministic generator")
    manifest_path = generated_dir / "manifest.json"
    manifest = load_json(manifest_path)
    if type(manifest) is not dict:
        raise MeasurementError("generated manifest must be an object")
    if manifest.get("format") != MANIFEST_FORMAT:
        raise MeasurementError("unsupported generated manifest format")
    if manifest.get("provenance") != "synthetic_not_t05_derived":
        raise MeasurementError("generated manifest provenance is not synthetic")
    if manifest.get("config_canonical_sha256") != digest(config):
        raise MeasurementError("generated manifest does not bind the canonical config")
    if manifest.get("config_file_sha256") != _raw_sha256(config_path):
        raise MeasurementError("generated manifest does not bind the config file bytes")
    generator_path = HERE / "generate.py"
    if manifest.get("generator_file_sha256") != _raw_sha256(generator_path):
        raise MeasurementError("generated manifest does not bind the generator bytes")
    entries = manifest.get("models")
    if type(entries) is not list or not entries:
        raise MeasurementError("generated manifest models must be a non-empty list")
    records = {}
    seen_files = set()
    for index, entry in enumerate(entries):
        if type(entry) is not dict:
            raise MeasurementError(f"manifest model entry {index} must be an object")
        required = {
            "file", "scenario", "revision", "provenance", "source_unit_count",
            "source_unit_count_reason", "model_sha256", "bytes", "inputs",
            "outputs", "rules",
        }
        if set(entry) != required:
            raise MeasurementError(
                f"manifest model entry {index} has unexpected fields")
        if type(entry["file"]) is not str or entry["file"] in seen_files:
            raise MeasurementError(f"manifest model entry {index} has an invalid file")
        seen_files.add(entry["file"])
        if entry["provenance"] != "synthetic_not_t05_derived":
            raise MeasurementError(f"manifest model entry {index} loses provenance")
        if entry["source_unit_count"] is not None:
            raise MeasurementError(f"manifest model entry {index} claims T04 sources")
        path = _safe_generated_path(generated_dir, entry["file"])
        model = load_json(path)
        validate_model(model)
        actual = {
            "model_sha256": digest(model),
            "bytes": _canonical_bytes(model),
            "inputs": len(model["inputs"]),
            "outputs": len(model["outputs"]),
            "rules": len(model["rules"]),
        }
        for field, value in actual.items():
            if entry[field] != value:
                raise MeasurementError(
                    f"manifest mismatch for {entry['file']}: {field}")
        records[entry["file"]] = {
            "entry": entry,
            "path": path,
            "model": model,
            "file_sha256": _raw_sha256(path),
            "file_bytes": path.stat().st_size,
        }
    pairs = {}
    expected_scenarios = set()
    matrix = config["matrix"]
    for rule_count in matrix["rule_counts"]:
        for guard_profile in matrix["guard_profiles"]:
            for background_profile in matrix["background_profiles"]:
                scenario = (
                    f"matrix-{rule_count}-{guard_profile}-{background_profile}")
                expected_scenarios.add(scenario)
                base_name = scenario + ".json"
                revision_name = scenario + "-revision.json"
                if base_name not in records or revision_name not in records:
                    raise MeasurementError(f"generated matrix pair is missing: {scenario}")
                base = records[base_name]
                revision = records[revision_name]
                if base["entry"]["scenario"] != scenario or base["entry"]["revision"] is not False:
                    raise MeasurementError(f"invalid base manifest entry: {scenario}")
                if revision["entry"]["scenario"] != scenario or revision["entry"]["revision"] is not True:
                    raise MeasurementError(f"invalid revision manifest entry: {scenario}")
                pairs[scenario] = {"base": base, "revision": revision}
    actual_scenarios = {
        entry["scenario"] for entry in entries
        if isinstance(entry.get("scenario"), str)
        and entry["scenario"].startswith("matrix-")
    }
    if actual_scenarios != expected_scenarios:
        raise MeasurementError("generated manifest has an unexpected matrix scenario set")
    return config, manifest, manifest_path, pairs, records


def _worker_command(phase, operation, left, *, right=None,
                    certificate=None, output_certificate=None):
    command = [
        sys.executable, "-m", "benchmarks.t06.measure", "_worker",
        "--phase", phase, "--operation", operation, "--left", str(left),
    ]
    if right is not None:
        command.extend(["--right", str(right)])
    if certificate is not None:
        command.extend(["--certificate", str(certificate)])
    if output_certificate is not None:
        command.extend(["--output-certificate", str(output_certificate)])
    return command


def _run_worker(phase, operation, left, *, right=None, certificate=None,
                output_certificate=None, timeout_seconds):
    command = _worker_command(
        phase, operation, left, right=right, certificate=certificate,
        output_certificate=output_certificate)
    environment = os.environ.copy()
    environment.update({"PYTHONHASHSEED": "0", "TZ": "UTC", "LC_ALL": "C.UTF-8"})
    started = perf_counter_ns()
    try:
        completed = subprocess.run(
            command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
            check=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "worker_timeout",
            "failure_phase": phase,
            "timeout_seconds": timeout_seconds,
            "wall_elapsed_ns": perf_counter_ns() - started,
            "stdout": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else None,
            "stderr": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else None,
        }
    wall_elapsed = perf_counter_ns() - started
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return {
            "status": "worker_process_error",
            "failure_phase": phase,
            "returncode": completed.returncode,
            "wall_elapsed_ns": wall_elapsed,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        }
    if type(payload) is not dict:
        return {
            "status": "worker_process_error",
            "failure_phase": phase,
            "returncode": completed.returncode,
            "wall_elapsed_ns": wall_elapsed,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        }
    payload["worker_returncode"] = completed.returncode
    payload["worker_wall_elapsed_ns"] = wall_elapsed
    if completed.stderr:
        payload["worker_stderr"] = completed.stderr[-2000:]
    return payload


def _time_summary(samples):
    raw = [sample.get("elapsed_ns") for sample in samples]
    valid = [value for value in raw if type(value) is int and value >= 0]
    ordered = sorted(valid)
    return {
        "raw_ns": raw,
        "timed_samples": len(valid),
        "verified_samples": sum(
            sample.get("status") == "verified" for sample in samples),
        "min_ns": min(valid) if valid else None,
        "median_ns": ordered[len(ordered) // 2] if ordered else None,
        "max_ns": max(valid) if valid else None,
        "statuses": [sample.get("status") for sample in samples],
        "details": samples,
    }


def _assert_certificate_binding(expected_hash, sample, label):
    if sample.get("status") != "verified":
        return
    actual = sample.get("certificate_sha256")
    if actual is None and type(sample.get("certificate")) is dict:
        actual = sample["certificate"].get("sha256")
    if actual != expected_hash:
        raise MeasurementError(f"{label} returned a different certificate hash")
    checker_hash = sample.get("checker_certificate_hash")
    if checker_hash is None and type(sample.get("certificate")) is dict:
        checker_hash = sample["certificate"].get("checker_certificate_hash")
    if checker_hash != expected_hash:
        raise MeasurementError(f"{label} checker hash does not bind the certificate")


def _measure_workflow(operation, left, right, *, repetitions, timeout_seconds):
    with tempfile.TemporaryDirectory(prefix="t06-measure-") as temporary:
        certificate_path = Path(temporary) / "certificate.json"
        prepare = _run_worker(
            "prepare", operation, left, right=right,
            output_certificate=certificate_path, timeout_seconds=timeout_seconds)
        producer_samples = [
            _run_worker(
                "producer-time", operation, left, right=right,
                timeout_seconds=timeout_seconds)
            for _ in range(repetitions)
        ]
        producer_memory = _run_worker(
            "producer-memory", operation, left, right=right,
            timeout_seconds=timeout_seconds)
        result = {
            "operation": operation,
            "left_model_sha256": digest(load_json(left)),
            "right_model_sha256": None if right is None else digest(load_json(right)),
            "prepare": prepare,
            "producer_time": _time_summary(producer_samples),
            "producer_memory": producer_memory,
            "checker_time": None,
            "checker_memory": None,
            "measurement_complete": False,
        }
        if prepare.get("status") != "verified":
            return result
        if not certificate_path.is_file():
            raise MeasurementError("verified prepare run did not publish a certificate")
        certificate = load_json(
            certificate_path, max_bytes=MAX_CERTIFICATE_BYTES)
        expected_hash = digest(certificate)
        if prepare.get("certificate", {}).get("sha256") != expected_hash:
            raise MeasurementError("prepare result does not bind its certificate file")
        for index, sample in enumerate(producer_samples):
            _assert_certificate_binding(
                expected_hash, sample, f"producer timing sample {index}")
        _assert_certificate_binding(
            expected_hash, producer_memory, "producer memory sample")
        checker_samples = [
            _run_worker(
                "checker-time", operation, left, right=right,
                certificate=certificate_path, timeout_seconds=timeout_seconds)
            for _ in range(repetitions)
        ]
        checker_memory = _run_worker(
            "checker-memory", operation, left, right=right,
            certificate=certificate_path, timeout_seconds=timeout_seconds)
        for index, sample in enumerate(checker_samples):
            _assert_certificate_binding(
                expected_hash, sample, f"checker timing sample {index}")
        _assert_certificate_binding(
            expected_hash, checker_memory, "checker memory sample")
        result["checker_time"] = _time_summary(checker_samples)
        result["checker_memory"] = checker_memory
        result["certificate"] = _certificate_summary(certificate)
        result["measurement_complete"] = (
            all(sample.get("status") == "verified"
                for sample in producer_samples + checker_samples)
            and producer_memory.get("status") == "verified"
            and checker_memory.get("status") == "verified"
        )
        return result


def _model_binding(record):
    entry = record["entry"]
    return {
        "path": _display_path(record["path"]),
        "model_sha256": entry["model_sha256"],
        "canonical_bytes": entry["bytes"],
        "file_sha256": record["file_sha256"],
        "file_bytes": record["file_bytes"],
        "inputs": entry["inputs"],
        "outputs": entry["outputs"],
        "rules": entry["rules"],
        "provenance": entry["provenance"],
        "source_unit_count": entry["source_unit_count"],
        "source_unit_count_reason": entry["source_unit_count_reason"],
    }


def _run_static_matrix(pairs, selected_profiles, operations, *,
                       repetitions, timeout_seconds):
    results = {}
    for scenario in selected_profiles:
        pair = pairs[scenario]
        base = pair["base"]
        revision = pair["revision"]
        parts = scenario.split("-")
        result = {
            "scenario": scenario,
            "dimensions": {
                "rule_count": int(parts[1]),
                "guard_profile": parts[2],
                "background_profile": parts[3],
            },
            "base": _model_binding(base),
            "revision": _model_binding(revision),
            "characterization": characterize_model(base["model"]),
            "operations": {},
        }
        for operation in operations:
            right = revision["path"] if operation == "diff" else None
            result["operations"][operation] = _measure_workflow(
                operation, base["path"], right,
                repetitions=repetitions, timeout_seconds=timeout_seconds)
        results[scenario] = result
    return results


def _write_boundary_model(path, model):
    _write_replace(path, model)
    return {
        "path": _display_path(path),
        "model_sha256": digest(model),
        "canonical_bytes": _canonical_bytes(model),
        "file_sha256": _raw_sha256(path),
        "file_bytes": Path(path).stat().st_size,
        "inputs": len(model["inputs"]),
        "outputs": len(model["outputs"]),
        "rules": len(model["rules"]),
    }


def _make_boundary_inputs(config, contexts, directory, operation):
    base_model = build_boundary(config, contexts, revised=False)
    base_path = Path(directory) / f"{operation}-{contexts:05d}-base.json"
    _write_replace(base_path, base_model)
    revision_model = revision_path = None
    if operation == "diff":
        revision_model = build_boundary(config, contexts, revised=True)
        revision_path = Path(directory) / f"{operation}-{contexts:05d}-revision.json"
        _write_replace(revision_path, revision_model)
    return base_model, base_path, revision_model, revision_path


def _probe_boundary(config, operation, contexts, directory, *,
                    timeout_seconds):
    base, base_path, revision, revision_path = _make_boundary_inputs(
        config, contexts, directory, operation)
    certificate_path = Path(directory) / f"{operation}-{contexts:05d}.certificate.json"
    response = _run_worker(
        "prepare", operation, base_path, right=revision_path,
        output_certificate=certificate_path, timeout_seconds=timeout_seconds)
    outcome = "unexpected"
    if response.get("status") == "verified":
        outcome = "success"
    elif (response.get("status") == "kernel_error"
          and response.get("kernel_status") == "LIMIT_REACHED"):
        outcome = "limit_reached"
    return {
        "contexts": contexts,
        "outcome": outcome,
        "base_model_sha256": digest(base),
        "revision_model_sha256": None if revision is None else digest(revision),
        "response": response,
        "certificate_published": certificate_path.exists(),
        "certificate_file_sha256": (
            _raw_sha256(certificate_path) if certificate_path.exists() else None),
    }


def _search_boundary(config, operation, *, timeout_seconds):
    maximum = config["boundary_family"]["context_max"]
    cache = {}
    probe_order = []
    with tempfile.TemporaryDirectory(prefix=f"t06-boundary-{operation}-") as temporary:
        directory = Path(temporary)

        def probe(contexts):
            if contexts not in cache:
                cache[contexts] = _probe_boundary(
                    config, operation, contexts, directory,
                    timeout_seconds=timeout_seconds)
                probe_order.append(contexts)
            return cache[contexts]

        first = probe(1)
        if first["outcome"] == "unexpected":
            return {
                "search_status": "unexpected_probe_result",
                "last_success_contexts": None,
                "first_failure_contexts": None,
                "probe_order": probe_order,
                "probes": [cache[key] for key in sorted(cache)],
            }
        if first["outcome"] == "limit_reached":
            return {
                "search_status": "no_success_in_boundary_family",
                "last_success_contexts": None,
                "first_failure_contexts": 1,
                "probe_order": probe_order,
                "probes": [cache[key] for key in sorted(cache)],
            }
        final = probe(maximum)
        if final["outcome"] == "unexpected":
            return {
                "search_status": "unexpected_probe_result",
                "last_success_contexts": 1,
                "first_failure_contexts": None,
                "probe_order": probe_order,
                "probes": [cache[key] for key in sorted(cache)],
            }
        if final["outcome"] == "success":
            return {
                "search_status": "no_limit_within_1_to_10000",
                "last_success_contexts": maximum,
                "first_failure_contexts": None,
                "probe_order": probe_order,
                "probes": [cache[key] for key in sorted(cache)],
            }
        low, high = 1, maximum
        while high - low > 1:
            middle = (low + high) // 2
            candidate = probe(middle)
            if candidate["outcome"] == "success":
                low = middle
            elif candidate["outcome"] == "limit_reached":
                high = middle
            else:
                return {
                    "search_status": "unexpected_probe_result",
                    "last_success_contexts": low,
                    "first_failure_contexts": high,
                    "probe_order": probe_order,
                    "probes": [cache[key] for key in sorted(cache)],
                }
        success = probe(low)
        failure = probe(high)
        if success["outcome"] != "success" or failure["outcome"] != "limit_reached":
            raise MeasurementError("boundary endpoint verification is inconsistent")
        return {
            "search_status": "consecutive_boundary_found",
            "last_success_contexts": low,
            "first_failure_contexts": high,
            "probe_order": probe_order,
            "probes": [cache[key] for key in sorted(cache)],
        }


def _save_endpoint_set(config, operation, label, contexts, endpoints_dir, *,
                       overwrite):
    if contexts is None:
        return None
    destination = Path(endpoints_dir)
    base_model = build_boundary(config, contexts, revised=False)
    base_path = destination / f"{operation}-{label}-{contexts:05d}.json"
    _write_new_or_same(base_path, base_model, overwrite=overwrite)
    result = {
        "contexts": contexts,
        "base": _write_boundary_model(base_path, base_model),
        "revision": None,
    }
    if operation == "diff":
        revision_model = build_boundary(config, contexts, revised=True)
        revision_path = (
            destination / f"{operation}-{label}-{contexts:05d}-revision.json")
        _write_new_or_same(revision_path, revision_model, overwrite=overwrite)
        result["revision"] = _write_boundary_model(revision_path, revision_model)
    return result


def _cli_command(operation, left, right, certificate):
    subcommand = {
        "check": "check",
        "diff": "diff",
        "reachability": "reachability",
        "staged": "reachability-staged",
    }[operation]
    command = [sys.executable, "-m", "rulekernel", subcommand, str(left)]
    if right is not None:
        command.append(str(right))
    command.extend(["--certificate", str(certificate), "--json"])
    return command


def _run_cli(command, timeout_seconds):
    environment = os.environ.copy()
    environment.update({"PYTHONHASHSEED": "0", "TZ": "UTC", "LC_ALL": "C.UTF-8"})
    try:
        completed = subprocess.run(
            command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
            check=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
            "stdout": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else None,
            "stderr": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else None,
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    return {
        "timed_out": False,
        "returncode": completed.returncode,
        "json": payload,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }


def _partial_artifact_check(operation, endpoint, *, timeout_seconds):
    if endpoint is None:
        return None
    left = Path(endpoint["base"]["path"])
    if not left.is_absolute():
        left = ROOT / left
    revision = endpoint.get("revision")
    right = None
    if revision is not None:
        right = Path(revision["path"])
        if not right.is_absolute():
            right = ROOT / right
    with tempfile.TemporaryDirectory(prefix=f"t06-partial-{operation}-") as temporary:
        certificate = Path(temporary) / "result.certificate.json"
        absent_run = _run_cli(
            _cli_command(operation, left, right, certificate), timeout_seconds)
        absent_after = certificate.exists()
        sentinel = b'{"sentinel":"t06-existing-artifact"}\n'
        certificate.write_bytes(sentinel)
        before_hash = _raw_sha256(certificate)
        existing_run = _run_cli(
            _cli_command(operation, left, right, certificate), timeout_seconds)
        after_hash = _raw_sha256(certificate)
        checks = {
            "absent_target_remained_absent": not absent_after,
            "existing_target_bytes_unchanged": certificate.read_bytes() == sentinel,
            "existing_target_sha256_before": before_hash,
            "existing_target_sha256_after": after_hash,
            "absent_run_exit_2": absent_run.get("returncode") == 2,
            "existing_run_exit_2": existing_run.get("returncode") == 2,
            "absent_run_limit_reached": (
                type(absent_run.get("json")) is dict
                and absent_run["json"].get("status") == "LIMIT_REACHED"),
            "existing_run_limit_reached": (
                type(existing_run.get("json")) is dict
                and existing_run["json"].get("status") == "LIMIT_REACHED"),
        }
        return {
            "command_shape": _cli_command(
                operation, "<left>", "<right>" if right is not None else None,
                "<certificate>"),
            "absent_target_run": absent_run,
            "existing_target_run": existing_run,
            "checks": checks,
            "passed": all(
                value for key, value in checks.items()
                if key not in {
                    "existing_target_sha256_before",
                    "existing_target_sha256_after",
                }),
        }


def _measure_boundaries(config, operations, endpoints_dir, *, repetitions,
                        timeout_seconds, overwrite):
    results = {}
    for operation in operations:
        search = _search_boundary(
            config, operation, timeout_seconds=timeout_seconds)
        success = _save_endpoint_set(
            config, operation, "last-success",
            search["last_success_contexts"], endpoints_dir,
            overwrite=overwrite)
        failure = _save_endpoint_set(
            config, operation, "first-failure",
            search["first_failure_contexts"], endpoints_dir,
            overwrite=overwrite)
        result = {
            "operation": operation,
            "family": {
                **config["boundary_family"],
                "guard_profile": "all guards are constant true",
                "background_profile": "all contexts admitted",
                "provenance": "synthetic_not_t05_derived",
            },
            "search": search,
            "last_success_endpoint": success,
            "first_failure_endpoint": failure,
            "last_success_measurement": None,
            "first_failure_measurement": None,
            "partial_artifact_check": None,
        }
        if success is not None:
            left = Path(success["base"]["path"])
            if not left.is_absolute():
                left = ROOT / left
            right = None
            if success["revision"] is not None:
                right = Path(success["revision"]["path"])
                if not right.is_absolute():
                    right = ROOT / right
            result["last_success_measurement"] = _measure_workflow(
                operation, left, right, repetitions=repetitions,
                timeout_seconds=timeout_seconds)
        if failure is not None:
            left = Path(failure["base"]["path"])
            if not left.is_absolute():
                left = ROOT / left
            right = None
            if failure["revision"] is not None:
                right = Path(failure["revision"]["path"])
                if not right.is_absolute():
                    right = ROOT / right
            result["first_failure_measurement"] = _measure_workflow(
                operation, left, right, repetitions=repetitions,
                timeout_seconds=timeout_seconds)
            result["partial_artifact_check"] = _partial_artifact_check(
                operation, failure, timeout_seconds=timeout_seconds)
        results[operation] = result
    return results


DEFAULT_REPORT = HERE / "results" / "report.json"


def _parse_selection(args, pairs):
    profiles = args.profile or list(pairs)
    unknown = sorted(set(profiles) - set(pairs))
    if unknown:
        raise MeasurementError("unknown matrix profile(s): " + ", ".join(unknown))
    if len(profiles) != len(set(profiles)):
        raise MeasurementError("matrix profiles must not be repeated")
    operations = args.operation or list(OPERATIONS)
    if len(operations) != len(set(operations)):
        raise MeasurementError("operations must not be repeated")
    return profiles, operations


def _run(args):
    if not 1 <= args.repetitions <= 9 or args.repetitions % 2 == 0:
        raise MeasurementError("--repetitions must be an odd integer from 1 to 9")
    if args.timeout_seconds <= 0:
        raise MeasurementError("--timeout-seconds must be positive")
    config, manifest, manifest_path, pairs, records = _load_static(
        args.config, args.generated, regenerate=args.regenerate_static)
    profiles, operations = _parse_selection(args, pairs)
    static_matrix = {}
    if not args.skip_static:
        static_matrix = _run_static_matrix(
            pairs, profiles, operations, repetitions=args.repetitions,
            timeout_seconds=args.timeout_seconds)
    boundaries = {}
    if not args.skip_boundaries:
        boundaries = _measure_boundaries(
            config, operations, args.endpoints,
            repetitions=args.repetitions,
            timeout_seconds=args.timeout_seconds,
            overwrite=args.overwrite)
    command = {
        "module": "benchmarks.t06.measure",
        "arguments": {
            "config": _display_path(args.config),
            "generated": _display_path(args.generated),
            "output": _display_path(args.output),
            "endpoints": _display_path(args.endpoints),
            "profiles": profiles,
            "operations": operations,
            "repetitions": args.repetitions,
            "timeout_seconds": args.timeout_seconds,
            "skip_static": args.skip_static,
            "skip_boundaries": args.skip_boundaries,
            "regenerate_static": args.regenerate_static,
        },
    }
    body = {
        "measurement_version": MEASUREMENT_VERSION,
        "provenance": {
            "kind": "synthetic_not_t05_derived",
            "statement": (
                "These authored-Core workloads are synthetic. They have no T04 "
                "source package and no T05 task/candidate/review/scope chain."),
            "scope_claim": (
                "Results cover only each saved finite model and operation. They "
                "are not legal-source validation or a general performance limit."),
        },
        "bindings": _source_bindings(
            args.config, manifest_path, config, manifest),
        "environment": _environment(),
        "command": command,
        "measurement_contract": {
            "official_repetitions": 3,
            "actual_repetitions": args.repetitions,
            "standard_three_repetition_run": args.repetitions == 3,
            "time_unit": "nanoseconds",
            "byte_unit": "bytes",
            "mib_bytes": 1024 * 1024,
            "producer_timing": (
                "Each raw sample is a fresh process; model loading and checker "
                "replay are outside the producer timer."),
            "checker_timing": (
                "Each raw sample is a fresh process; model and certificate "
                "loading are outside the checker timer."),
            "memory": (
                "tracemalloc is a separate fresh process and reports incremental "
                "Python allocation peak above loaded input objects; it is not RSS."),
            "boundary_algorithm": (
                "Probe 1 and 10000, binary-search the first LIMIT_REACHED under "
                "the fixed monotone-size family, then re-use the cached adjacent "
                "last-success/first-failure probes."),
            "completion_rule": (
                "A success is reportable only after the operation-specific "
                "independent checker returns VERIFIED."),
            "limits": {
                "max_contexts": MAX_CONTEXTS,
                "max_certificate_bytes": MAX_CERTIFICATE_BYTES,
            },
        },
        "generated_manifest": {
            "path": _display_path(manifest_path),
            "canonical_sha256": digest(manifest),
            "model_entry_count": len(records),
        },
        "static_matrix": static_matrix,
        "boundaries": boundaries,
    }
    report = {
        "format": REPORT_FORMAT,
        "body_sha256": digest(body),
        "body": body,
    }
    _write_new_or_same(args.output, report, overwrite=args.overwrite)
    return {
        "status": "MEASURED",
        "report": _display_path(args.output),
        "report_file_sha256": _raw_sha256(args.output),
        "report_body_sha256": report["body_sha256"],
        "static_scenarios": len(static_matrix),
        "boundary_operations": len(boundaries),
        "standard_three_repetition_run": args.repetitions == 3,
    }


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Measure the reproducible synthetic T06 matrix and limits")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="write a hash-bound T06 measurement report")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run.add_argument("--generated", type=Path, default=DEFAULT_OUTPUT)
    run.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    run.add_argument("--endpoints", type=Path, default=DEFAULT_ENDPOINTS)
    run.add_argument(
        "--profile", action="append",
        help="matrix scenario id; repeat to select; default is the full matrix")
    run.add_argument(
        "--operation", action="append", choices=OPERATIONS,
        help="operation; repeat to select; default is all four")
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--timeout-seconds", type=float, default=180.0)
    run.add_argument("--skip-static", action="store_true")
    run.add_argument("--skip-boundaries", action="store_true")
    run.add_argument(
        "--regenerate-static", action="store_true",
        help="regenerate the fixed manifest before validating and measuring it")
    run.add_argument(
        "--overwrite", action="store_true",
        help="atomically replace different endpoint/report files")

    worker = commands.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument(
        "--phase", required=True,
        choices=("prepare", "producer-time", "checker-time",
                 "producer-memory", "checker-memory"))
    worker.add_argument("--operation", required=True, choices=OPERATIONS)
    worker.add_argument("--left", type=Path, required=True)
    worker.add_argument("--right", type=Path)
    worker.add_argument("--certificate", type=Path)
    worker.add_argument("--output-certificate", type=Path)
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "_worker":
        return _worker_main(args)
    try:
        result = _run(args)
    except (MeasurementError, KernelError, OSError, ValueError) as exc:
        if isinstance(exc, KernelError):
            status, message = exc.status, exc.message
        else:
            status, message = "MEASUREMENT_ERROR", str(exc)
        print(canonical_json({"status": status, "message": message}), file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
