"""CLI for compact streaming evidence without changing the historical rule CLI."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

from rulekernel.model import (
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    KernelError,
    canonical_json,
    load_json,
)

from .checker import verify_path
from .engine import estimate_certificate, write_certificate


_INTERNAL_ERROR_MESSAGE = "An unexpected internal error occurred"


def _fsync_directory(directory) -> None:
    """Best-effort durability barrier for directory entry changes."""
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        pass


def _ensure_distinct(output, model):
    if Path(output).resolve() == Path(model).resolve():
        raise KernelError(
            "IO_ERROR",
            "Compact certificate output must differ from the model input",
        )


def _publish_checked(model, destination, max_contexts):
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    published_identity = None
    completed = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=target.parent,
            prefix=".compact-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            write_certificate(model, stream, max_contexts=max_contexts)
            stream.flush()
            os.fsync(stream.fileno())

        checked = verify_path(
            model,
            temporary,
            max_contexts=max_contexts,
        )
        temporary_stat = os.stat(temporary, follow_symlinks=False)
        os.link(temporary, target)
        published_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
        _fsync_directory(target.parent)
        os.unlink(temporary)
        temporary = None
        _fsync_directory(target.parent)
        completed = True
        return checked
    finally:
        active_failure = sys.exc_info()[0] is not None
        if not completed and published_identity is not None:
            try:
                current = os.lstat(target)
                if (current.st_dev, current.st_ino) == published_identity:
                    os.unlink(target)
            except OSError:
                pass
            except Exception:
                if not active_failure:
                    raise
        if temporary is not None:
            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except Exception:
                if not active_failure:
                    raise


def _show_result(model, result):
    print(model["title"])
    print(f'compact証拠検査: {result["status"]}')
    print(
        f'元の有限範囲 {result["total_contexts"]} 状況 / '
        f'境界セル {result["cell_count"]} / '
        f'入力・背景条件に合う範囲 {result["admitted_contexts"]}'
    )
    print(
        f'圧縮: {"あり" if result["compressed"] else "なし"} / '
        f'証拠 {result["certificate_bytes"]} bytes'
    )
    for query in result["queries"]:
        label = "結論の衝突" if query["kind"] == "conflict" else "扱いの抜け"
        print(
            f'- {query["output"]} / {label}: {query["count"]} 状況 '
            f'[{query["status"]}]'
        )
        if query["witness"] is not None:
            print("  具体例: " + canonical_json(query["witness"]["input"]))
    print("結果は宣言した有限範囲と手書きモデルに限ります。")


def _show_estimate(model, result):
    print(model["title"])
    print("compact証拠の生成前見積り")
    print(
        f'元の有限範囲 {result["concrete_contexts"]} / '
        f'境界セル {result["cell_count"]}'
    )
    print(
        f'保証下限 {result["guaranteed_min_bytes"]} bytes / '
        f'hard cap {result["max_certificate_bytes"]} bytes'
    )
    print("保証下限だけでは実際の証拠が収まることを保証しません。")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="境界セルとJSON Linesによる有限decision証拠",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    estimate = commands.add_parser(
        "estimate",
        help="構文だけから証拠bytesの保証下限を計算",
    )
    estimate.add_argument("model")
    estimate.add_argument("--max-contexts", type=int, default=MAX_CONTEXTS)
    estimate.add_argument("--json", action="store_true")

    check = commands.add_parser(
        "check",
        help="compact証拠を逐次生成し、独立検査後に新規保存",
    )
    check.add_argument("model")
    check.add_argument("--certificate", required=True)
    check.add_argument("--max-contexts", type=int, default=MAX_CONTEXTS)
    check.add_argument("--json", action="store_true")

    verify = commands.add_parser(
        "verify",
        help="保存済みcompact証拠を逐次再検査",
    )
    verify.add_argument("model")
    verify.add_argument("certificate")
    verify.add_argument("--expected-certificate-sha256")
    verify.add_argument("--max-contexts", type=int, default=MAX_CONTEXTS)
    verify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        model = load_json(args.model)
        if args.command == "estimate":
            estimate_result = estimate_certificate(
                model,
                max_contexts=args.max_contexts,
            )
            result = {
                "status": "ESTIMATE_AVAILABLE",
                "finding": "undetermined",
                **estimate_result,
            }
            if args.json:
                print(canonical_json(result))
            else:
                _show_estimate(model, result)
            return 2 if result["guaranteed_min_exceeds_cap"] else 0

        if args.command == "check":
            _ensure_distinct(args.certificate, args.model)
            checked = _publish_checked(
                model,
                args.certificate,
                args.max_contexts,
            )
            result = {
                "title": model["title"],
                "origin_kind": model["origin_kind"],
                **checked,
                "published_certificate": str(args.certificate),
                "limits": {
                    "max_contexts": args.max_contexts,
                    "max_certificate_bytes": MAX_CERTIFICATE_BYTES,
                },
            }
        else:
            checked = verify_path(
                model,
                args.certificate,
                expected_certificate_sha256=(
                    args.expected_certificate_sha256
                ),
                max_contexts=args.max_contexts,
            )
            result = {
                "title": model["title"],
                "origin_kind": model["origin_kind"],
                **checked,
                "certificate": str(args.certificate),
                "limits": {
                    "max_contexts": args.max_contexts,
                    "max_certificate_bytes": MAX_CERTIFICATE_BYTES,
                },
            }

        if args.json:
            print(canonical_json(result))
        else:
            _show_result(model, result)
            if args.command == "check":
                print(f'証拠保存: {args.certificate}')
        return 1 if any(query["count"] for query in result["queries"]) else 0
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
            print(
                f"{status}: {message}\n検査は確定していません。",
                file=sys.stderr,
            )
        return 2
    except Exception:
        if args.json:
            failure = {
                "status": "INTERNAL_ERROR",
                "message": _INTERNAL_ERROR_MESSAGE,
                "finding": "undetermined",
            }
            if args.command == "check":
                failure["published_certificate"] = None
            print(canonical_json(failure))
        else:
            print(
                f"INTERNAL_ERROR: {_INTERNAL_ERROR_MESSAGE}\n"
                "検査は確定していません。",
                file=sys.stderr,
            )
        return 2


if __name__ == "__main__":
    sys.exit(main())
