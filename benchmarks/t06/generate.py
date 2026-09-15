"""Generate deterministic T06 authored-Core benchmark models.

The generated source strings describe synthetic workloads.  They do not come
from a T04 source package or a T05 interpretation/review chain.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import tempfile

from rulekernel.model import canonical_json, digest, load_json, validate_model


CONFIG_FORMAT = "t06-benchmark-config/1"
MANIFEST_FORMAT = "t06-generated-model-manifest/1"
PROVENANCE = "synthetic_not_t05_derived"
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
DEFAULT_OUTPUT = Path(__file__).with_name("generated")


def _exact(value, fields, path):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"{path} must have exactly {sorted(fields)}")


def validate_config(config):
    _exact(config, {
        "format", "generator_profile", "provenance", "variables", "outputs",
        "matrix", "boundary_family",
    }, "config")
    if config["format"] != CONFIG_FORMAT:
        raise ValueError("unsupported T06 config format")
    if config["generator_profile"] != "t06-deterministic-matrix/1":
        raise ValueError("unsupported T06 generator profile")
    if config["provenance"] != PROVENANCE:
        raise ValueError("T06 benchmark provenance must remain explicit")
    if config["variables"] != [f"b{i:02d}" for i in range(13)]:
        raise ValueError("config.variables must be b00..b12 in order")
    if config["outputs"] != [f"o{i:02d}" for i in range(10)]:
        raise ValueError("config.outputs must be o00..o09 in order")
    matrix = config["matrix"]
    _exact(matrix, {"rule_counts", "guard_profiles", "background_profiles"},
           "config.matrix")
    if matrix != {"rule_counts": [50, 100],
                  "guard_profiles": ["sparse", "dense"],
                  "background_profiles": ["full", "eighth"]}:
        raise ValueError("unsupported fixed T06 matrix")
    boundary = config["boundary_family"]
    _exact(boundary, {"context_max", "input", "output_count", "override_edges",
                      "rule_count"}, "config.boundary_family")
    if boundary != {"context_max": 10000, "input": "case_id", "output_count": 10,
                    "override_edges": 0, "rule_count": 100}:
        raise ValueError("unsupported fixed T06 boundary family")


def _var(name):
    return {"var": name}


def _const(value):
    return {"const": value}


def _not(expression):
    return {"op": "not", "args": [expression]}


def _op(name, *arguments):
    return {"op": name, "args": list(arguments)}


def _literal(name, positive):
    expression = _var(name)
    return expression if positive else _not(expression)


def _guard(index, profile):
    """Three independent workload bits give exact 1/8 or 7/8 truth density."""
    offsets = (0, 1, 4)
    names = [f"b{(index * 3 + offset) % 10:02d}" for offset in offsets]
    terms = [_literal(name, (index + position) % 2 == 0)
             for position, name in enumerate(names)]
    return _op("and" if profile == "sparse" else "or", *terms)


def _outputs(config):
    return {name: {"type": {"kind": "bool"}, "required": False}
            for name in config["outputs"]}


def profile_id(rule_count, guard_profile, background_profile):
    return f"matrix-{rule_count}-{guard_profile}-{background_profile}"


def build_matrix(config, rule_count, guard_profile, background_profile, *, revised=False):
    validate_config(config)
    matrix = config["matrix"]
    if rule_count not in matrix["rule_counts"]:
        raise ValueError("matrix rule_count must be 50 or 100")
    if guard_profile not in matrix["guard_profiles"]:
        raise ValueError("unsupported matrix guard profile")
    if background_profile not in matrix["background_profiles"]:
        raise ValueError("unsupported matrix background profile")
    scenario = profile_id(rule_count, guard_profile, background_profile)
    model = {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": f"T06 synthetic {scenario}",
        "inputs": {name: {"kind": "bool"} for name in config["variables"]},
        "outputs": _outputs(config),
        "constraints": [],
        "facts": [],
        "rules": [],
    }
    if background_profile == "eighth":
        model["facts"] = [{"var": "b10", "value": True}]
        model["constraints"] = [_op("and", _var("b11"), _var("b12"))]
    for index in range(rule_count):
        model["rules"].append({
            "id": f"R{index:03d}",
            "source": (f"T06 synthetic workload rule {index:03d}; "
                       f"guard={guard_profile}; background={background_profile}"),
            "when": _guard(index, guard_profile),
            "then": {"output": config["outputs"][index % 10],
                     "value": revised and index == 0},
            "overrides": [],
        })
    validate_model(model)
    return model


def build_boundary(config, contexts, *, revised=False):
    validate_config(config)
    boundary = config["boundary_family"]
    if type(contexts) is not int or not 1 <= contexts <= boundary["context_max"]:
        raise ValueError("boundary contexts must be 1..10000")
    model = {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": f"T06 fixed-density boundary {contexts:05d}",
        "inputs": {boundary["input"]: {"kind": "int", "min": 0,
                                         "max": contexts - 1}},
        "outputs": _outputs(config),
        "constraints": [],
        "facts": [],
        "rules": [],
    }
    for index in range(boundary["rule_count"]):
        model["rules"].append({
            "id": f"B{index:03d}",
            "source": f"T06 fixed-density boundary workload rule {index:03d}",
            "when": _const(True),
            "then": {"output": config["outputs"][index % 10],
                     "value": revised and index == 0},
            "overrides": [],
        })
    validate_model(model)
    return model


def build_sentinel(config, sentinel_id):
    validate_config(config)
    base = {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": f"T06 synthetic sentinel {sentinel_id}",
        "inputs": {"x": {"kind": "bool"}, "y": {"kind": "bool"}},
        "outputs": {"decision": {"type": {"kind": "bool"}, "required": False}},
        "constraints": [], "facts": [], "rules": [],
    }
    first = {"id": "AREA_A", "source": "synthetic local area A",
             "when": _var("x"), "then": {"output": "decision", "value": False},
             "overrides": []}
    second = {"id": "AREA_B", "source": "synthetic local area B",
              "when": _var("y"), "then": {"output": "decision", "value": True},
              "overrides": []}
    if sentinel_id == "local-a":
        base["rules"] = [first]
    elif sentinel_id == "local-b":
        base["rules"] = [second]
    elif sentinel_id == "union-conflict":
        base["rules"] = [first, second]
    elif sentinel_id == "override-revival":
        base["rules"] = [
            {"id": "BASE", "source": "synthetic base", "when": _const(True),
             "then": {"output": "decision", "value": False}, "overrides": []},
            {"id": "MIDDLE", "source": "synthetic exception", "when": _var("x"),
             "then": {"output": "decision", "value": True}, "overrides": ["BASE"]},
            {"id": "TOP", "source": "synthetic exception to exception",
             "when": _var("y"), "then": {"output": "decision", "value": False},
             "overrides": ["MIDDLE"]},
        ]
    else:
        raise ValueError("unknown T06 sentinel")
    validate_model(base)
    return base


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8", newline="\n")


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _entry(filename, model, scenario, revision):
    return {
        "file": filename, "scenario": scenario, "revision": revision,
        "provenance": PROVENANCE, "source_unit_count": None,
        "source_unit_count_reason": "synthetic workload has no T04 source package",
        "model_sha256": digest(model),
        "bytes": len(canonical_json(model).encode("utf-8")),
        "inputs": len(model["inputs"]), "outputs": len(model["outputs"]),
        "rules": len(model["rules"]),
    }


def generate_static(config_path=DEFAULT_CONFIG, output_dir=DEFAULT_OUTPUT):
    config_path, output_dir = Path(config_path), Path(output_dir)
    config = load_json(config_path)
    validate_config(config)
    entries = []
    matrix = config["matrix"]
    for rule_count in matrix["rule_counts"]:
        for guard_profile in matrix["guard_profiles"]:
            for background_profile in matrix["background_profiles"]:
                scenario = profile_id(rule_count, guard_profile, background_profile)
                for revised in (False, True):
                    model = build_matrix(config, rule_count, guard_profile,
                                         background_profile, revised=revised)
                    filename = scenario + ("-revision" if revised else "") + ".json"
                    _write(output_dir / filename, model)
                    entries.append(_entry(filename, model, scenario, revised))
    for sentinel_id in ("local-a", "local-b", "union-conflict", "override-revival"):
        model = build_sentinel(config, sentinel_id)
        filename = "sentinel-" + sentinel_id + ".json"
        _write(output_dir / filename, model)
        entries.append(_entry(filename, model, "sentinel-" + sentinel_id, False))
    manifest = {
        "format": MANIFEST_FORMAT, "provenance": PROVENANCE,
        "config_canonical_sha256": digest(config),
        "config_file_sha256": file_sha256(config_path),
        "generator_file_sha256": file_sha256(__file__),
        "models": entries,
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest


def check_static(config_path=DEFAULT_CONFIG, output_dir=DEFAULT_OUTPUT):
    output_dir = Path(output_dir)
    with tempfile.TemporaryDirectory() as temporary:
        expected_dir = Path(temporary) / "generated"
        manifest = generate_static(config_path, expected_dir)
        expected = {path.relative_to(expected_dir): path.read_bytes()
                    for path in expected_dir.rglob("*") if path.is_file()}
    actual = ({path.relative_to(output_dir): path.read_bytes()
               for path in output_dir.rglob("*") if path.is_file()}
              if output_dir.is_dir() else {})
    if actual != expected:
        missing = sorted(str(path) for path in expected.keys() - actual.keys())
        extra = sorted(str(path) for path in actual.keys() - expected.keys())
        changed = sorted(str(path) for path in expected.keys() & actual.keys()
                         if expected[path] != actual[path])
        return {"status": "MISMATCH", "missing": missing, "extra": extra,
                "changed": changed, "manifest": manifest}
    return {"status": "MATCH", "missing": [], "extra": [], "changed": [],
            "manifest": manifest}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate deterministic T06 models")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="compare generated bytes without changing the output")
    args = parser.parse_args(argv)
    if args.check:
        result = check_static(args.config, args.output)
        print(canonical_json(result))
        return 0 if result["status"] == "MATCH" else 1
    print(canonical_json(generate_static(args.config, args.output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
