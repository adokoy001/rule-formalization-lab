"""Command line interface for finite procedure-and-time verification."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

from .checker import verify
from .engine import analyze
from .model import (
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    MAX_CONTEXT_TRACE_PAIRS,
    MAX_TRACES_PER_CONTEXT,
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
        raise KernelError("IO_ERROR", "Certificate output must differ from model input")
    if destination.exists() or destination.is_symlink():
        raise KernelError("IO_ERROR", "Certificate output already exists; refusing replacement")


def _save_new(path: str, certificate: dict) -> None:
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


def _limits(parser):
    parser.add_argument("--max-contexts", type=int, default=MAX_CONTEXTS)
    parser.add_argument(
        "--max-traces-per-context", type=int, default=MAX_TRACES_PER_CONTEXT
    )
    parser.add_argument("--max-pairs", type=int, default=MAX_CONTEXT_TRACE_PAIRS)
    parser.add_argument("--json", action="store_true")


def _human(result, model, path, generated):
    print(model["title"])
    print(f'Certificate verification: {result["status"]}')
    print(f'Contexts: {result["counts"]["total_contexts"]}')
    print("Feasibility: " + ", ".join(
        f"{key}={value}" for key, value in result["counts"]["feasibility"].items()
    ))
    print("Observed outcomes: " + ", ".join(
        f"{key}={value}" for key, value in result["counts"]["observed_outcomes"].items()
    ))
    if path:
        print(("Certificate saved: " if generated else "Certificate: ") + path)
    print(
        "VERIFIED means complete replay of the declared finite candidates; it is not "
        "a legal judgment or coverage of continuous time."
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Self-built exhaustive kernel for finite-procedure-time/1"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="generate, replay, and optionally save evidence")
    generate.add_argument("model")
    generate.add_argument("--certificate")
    _limits(generate)
    recheck = commands.add_parser("verify", help="independently replay saved evidence")
    recheck.add_argument("model")
    recheck.add_argument("certificate")
    recheck.add_argument("--expected-certificate-sha256")
    _limits(recheck)
    args = parser.parse_args(argv)
    try:
        model = load_json(args.model)
        keyword = {
            "max_contexts": args.max_contexts,
            "max_traces_per_context": args.max_traces_per_context,
            "max_pairs": args.max_pairs,
        }
        if args.command == "generate":
            _ensure_new_output(args.certificate, args.model)
            certificate = analyze(model, **keyword)
            checked = verify(model, certificate, **keyword)
            if args.certificate is not None:
                _save_new(args.certificate, certificate)
            path, generated = args.certificate, True
        else:
            certificate = _load_certificate(args.certificate)
            checked = verify(
                model,
                certificate,
                expected_certificate_sha256=args.expected_certificate_sha256,
                **keyword,
            )
            path, generated = args.certificate, False
        result = {
            "title": model["title"],
            "origin_kind": model["origin_kind"],
            **checked,
            "limits": {
                **keyword,
                "max_certificate_bytes": MAX_CERTIFICATE_BYTES,
            },
        }
        if args.command == "generate" and args.certificate is not None:
            result["published_certificate"] = args.certificate
        if args.command == "verify":
            result["certificate"] = args.certificate
        if args.json:
            print(canonical_json(result))
        else:
            _human(result, model, path, generated)
        return 1 if checked["diagnostics"]["has_findings"] else 0
    except (KernelError, OSError) as exc:
        status = exc.status if isinstance(exc, KernelError) else "IO_ERROR"
        message = exc.message if isinstance(exc, KernelError) else str(exc)
        if args.json:
            failure = {"status": status, "message": message, "finding": "undetermined"}
            if args.command == "generate":
                failure["published_certificate"] = None
            print(canonical_json(failure))
        else:
            print(f"{status}: {message}\nVerification is undetermined.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
