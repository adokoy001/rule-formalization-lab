"""Small command-line entry point for the T10 manual binding checker."""
from __future__ import annotations

import argparse
import sys

from .binding_checker import verify_manual_model_binding
from .model import MAX_CERTIFICATE_BYTES, KernelError, canonical_json, load_json


_INTERNAL_ERROR_MESSAGE = "An unexpected internal error occurred"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify a manual source/model binding")
    parser.add_argument("task")
    parser.add_argument("candidate")
    parser.add_argument("review")
    parser.add_argument("model")
    parser.add_argument("certificate")
    parser.add_argument("binding")
    parser.add_argument("source_spec")
    parser.add_argument("source_bundle")
    parser.add_argument("--expected-binding-sha256")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify_manual_model_binding(
            load_json(args.task),
            load_json(args.candidate),
            load_json(args.review),
            load_json(args.model),
            load_json(args.certificate, max_bytes=MAX_CERTIFICATE_BYTES),
            load_json(args.binding, max_bytes=2 * 1024 * 1024),
            source_spec=args.source_spec,
            source_bundle=args.source_bundle,
            expected_binding_sha256=args.expected_binding_sha256,
        )
        if args.json:
            print(canonical_json(result))
        else:
            print(result["status"])
            print(f'Binding SHA-256: {result["binding_hash"]}')
            print("This verifies the recorded manual chain; it does not prove semantic lowering or legal correctness.")
        return 0
    except (KernelError, OSError) as exc:
        status = exc.status if isinstance(exc, KernelError) else "IO_ERROR"
        message = exc.message if isinstance(exc, KernelError) else str(exc)
        if args.json:
            print(canonical_json({"status": status, "message": message, "finding": "undetermined"}))
        else:
            print(f"{status}: {message}", file=sys.stderr)
        return 2
    except Exception:
        if args.json:
            print(canonical_json({
                "status": "INTERNAL_ERROR",
                "message": _INTERNAL_ERROR_MESSAGE,
                "finding": "undetermined",
            }))
        else:
            print(
                f"INTERNAL_ERROR: {_INTERNAL_ERROR_MESSAGE}\n"
                "Verification is undetermined.",
                file=sys.stderr,
            )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
