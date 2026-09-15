"""Command line entry point for the independent finite normative kernel."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

from .checker import verify
from .engine import analyze
from .model import (
    MAX_ACTION_ASSIGNMENTS,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    MAX_CONTEXT_TRACE_PAIRS,
    KernelError,
    canonical_json,
    load_json,
)


def _load_certificate(path: str) -> object:
    try:
        return load_json(path, max_bytes=MAX_CERTIFICATE_BYTES)
    except KernelError as exc:
        if exc.status == "MODEL_INVALID":
            raise KernelError("CERTIFICATE_INVALID", exc.message) from exc
        raise


def _ensure_new_output(output: str | None, model_path: str) -> None:
    if output is None:
        return
    destination = Path(output)
    if destination.resolve() == Path(model_path).resolve():
        raise KernelError("IO_ERROR", "Certificate output must differ from the model input")
    if destination.exists() or destination.is_symlink():
        raise KernelError("IO_ERROR", "Certificate output already exists; refusing to replace it")


def _save_new(path: str, certificate: dict) -> None:
    """Publish canonical evidence atomically while refusing every replacement."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(canonical_json(certificate))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def _add_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-contexts", type=int, default=MAX_CONTEXTS)
    parser.add_argument(
        "--max-action-assignments",
        type=int,
        default=MAX_ACTION_ASSIGNMENTS,
    )
    parser.add_argument("--max-pairs", type=int, default=MAX_CONTEXT_TRACE_PAIRS)
    parser.add_argument("--json", action="store_true", help="print canonical JSON")


def _show(result: dict, *, certificate_path: str | None, generated: bool) -> None:
    counts = result["counts"]
    diagnostics = result["diagnostics"]
    print(result["title"])
    print(f'Certificate verification: {result["status"]}')
    print(
        "Contexts: "
        f'{counts["total_contexts"]} total / {counts["admitted_contexts"]} admitted / '
        f'{counts["excluded"]} excluded'
    )
    print(
        "Diagnostics: "
        f'{diagnostics["background_trace_impossible_contexts"]} background-impossible / '
        f'{diagnostics["normatively_infeasible_contexts"]} normatively-infeasible / '
        f'{diagnostics["unusable_permission_context_pairs"]} unusable permission/context pairs '
        f'across {diagnostics["contexts_with_unusable_permissions"]} contexts'
    )
    for permission in result["permission_summaries"]:
        print(
            f'- {permission["permission_id"]}: '
            f'applicable {permission["applicable_context_count"]} / '
            f'usable traces {permission["usable_count"]} / '
            f'nonexercise traces {permission["nonexercise_count"]}'
        )
    if certificate_path is not None:
        label = "Certificate saved" if generated else "Certificate"
        print(f"{label}: {certificate_path}")
    print(
        "VERIFIED means the complete finite certificate matched independent replay; "
        "it does not mean that the model has no contradiction or that its legal "
        "interpretation is correct."
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Self-built exhaustive kernel for finite-norms/1"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check", help="produce evidence, independently replay it, then optionally save it"
    )
    check.add_argument("model")
    check.add_argument("--certificate", help="new path for canonical complete evidence")
    _add_limits(check)
    recheck = commands.add_parser(
        "verify", help="independently replay and verify an existing certificate"
    )
    recheck.add_argument("model")
    recheck.add_argument("certificate")
    recheck.add_argument("--expected-certificate-sha256")
    _add_limits(recheck)
    args = parser.parse_args(argv)

    try:
        model = load_json(args.model)
        if args.command == "check":
            _ensure_new_output(args.certificate, args.model)
            certificate = analyze(
                model,
                max_contexts=args.max_contexts,
                max_action_assignments=args.max_action_assignments,
                max_pairs=args.max_pairs,
            )
            checked = verify(
                model,
                certificate,
                max_contexts=args.max_contexts,
                max_action_assignments=args.max_action_assignments,
                max_pairs=args.max_pairs,
            )
            if args.certificate is not None:
                _save_new(args.certificate, certificate)
            certificate_path = args.certificate
            generated = True
        else:
            certificate = _load_certificate(args.certificate)
            checked = verify(
                model,
                certificate,
                expected_certificate_sha256=args.expected_certificate_sha256,
                max_contexts=args.max_contexts,
                max_action_assignments=args.max_action_assignments,
                max_pairs=args.max_pairs,
            )
            certificate_path = args.certificate
            generated = False

        result = {
            "title": model["title"],
            "origin_kind": model["origin_kind"],
            **checked,
            "limits": {
                "max_contexts": args.max_contexts,
                "max_action_assignments": args.max_action_assignments,
                "max_pairs": args.max_pairs,
                "max_certificate_bytes": MAX_CERTIFICATE_BYTES,
            },
        }
        if args.command == "check" and args.certificate is not None:
            result["published_certificate"] = args.certificate
        if args.command == "verify":
            result["certificate"] = args.certificate
        if args.json:
            print(canonical_json(result))
        else:
            _show(result, certificate_path=certificate_path, generated=generated)
        return 1 if checked["diagnostics"]["has_findings"] else 0
    except (KernelError, OSError) as exc:
        status = exc.status if isinstance(exc, KernelError) else "IO_ERROR"
        message = exc.message if isinstance(exc, KernelError) else str(exc)
        if args.json:
            failure = {
                "status": status,
                "message": message,
                "finding": "undetermined",
            }
            if args.command == "check":
                failure["published_certificate"] = None
            print(canonical_json(failure))
        else:
            print(f"{status}: {message}\nVerification is undetermined.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
