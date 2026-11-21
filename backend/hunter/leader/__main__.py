"""Read pending drafts and send explicit revision-bound review decisions."""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_BASE = "http://127.0.0.1:8000/api/review"
_MAX_BYTES = 16 * 1024 * 1024
_PAGE_SIZE = 50


class LeaderError(RuntimeError):
    """Credential-free argument, transport or response error."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's default error output repeats arbitrary argument values.
        super().error("Invalid review arguments. Run with --help for usage.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str,
    ) -> None:
        return None


def _loopback(request: Request) -> bytes:
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=5) as response:
        return response.read(_MAX_BYTES + 1)


def _request(
    path: str, token: str, transport: Callable[[Request], bytes], *, data: dict[str, object] | None = None,
) -> object:
    request = Request(
        _BASE + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        raw = transport(request)
        if len(raw) <= _MAX_BYTES:
            return json.loads(raw)
    except HTTPError as error:
        status = error.code
        error.close()
        raise LeaderError(f"Review API returned HTTP {status}.") from None
    except OSError:
        raise LeaderError("Review API is unavailable on local port 8000.") from None
    except (ValueError, RecursionError):
        pass
    raise LeaderError("Review API returned an invalid response.")


def _compact(draft: object) -> dict[str, object]:
    if not isinstance(draft, dict):
        raise LeaderError("Review API returned an invalid draft.")
    fields = (
        "id", "revision_count", "title_vi", "original_title", "priority", "virality_score", "relevance_score",
        "credibility", "verification_level", "metadata_only", "metadata_note_vi", "why_notable", "summary_vi",
        "original_url", "related_urls",
    )
    return {field: draft[field] for field in fields if field in draft}


def _pending(token: str, transport: Callable[[Request], bytes]) -> list[dict[str, object]]:
    drafts: list[dict[str, object]] = []
    while True:
        page = _request(f"/pending?limit={_PAGE_SIZE}&offset={len(drafts)}", token, transport)
        if not isinstance(page, list) or len(page) > _PAGE_SIZE:
            raise LeaderError("Review API returned an invalid pending list.")
        drafts.extend(_compact(draft) for draft in page)
        if len(page) < _PAGE_SIZE:
            return drafts


def main(
    argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None,
    transport: Callable[[Request], bytes] = _loopback,
) -> int:
    parser = _Parser(prog="python -m hunter.leader")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pending")
    show = commands.add_parser("show")
    show.add_argument("brief_id")
    decide = commands.add_parser("decide")
    decide.add_argument("brief_id")
    decide.add_argument("--action", choices=("APPROVE", "REQUEST_REVISION", "REJECT"), required=True)
    decide.add_argument("--reason", required=True)
    decide.add_argument("--revision", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command != "pending" and not re.fullmatch(r"[A-Za-z0-9_-]+", args.brief_id):
        parser.error("Invalid brief ID")
    if args.command == "decide" and (not args.reason.strip() or not 0 <= args.revision <= 2):
        parser.error("A non-empty reason and a revision between 0 and 2 are required")

    env = os.environ if environ is None else environ
    token = env.get("HUNTER_AUTH__CLAUDE_SERVICE_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{32,}", token):
        print("Configure HUNTER_AUTH__CLAUDE_SERVICE_TOKEN for the Claude Leader client.", file=sys.stderr)
        return 2
    if (args.command != "pending" and token in args.brief_id) or (args.command == "decide" and token in args.reason):
        parser.error("The service token cannot be used in a review argument")
    try:
        if args.command == "pending":
            result = _pending(token, transport)
        elif args.command == "show":
            result = _request(f"/{args.brief_id}", token, transport)
            if not isinstance(result, dict):
                raise LeaderError("Review API returned an invalid draft.")
        else:
            result = _request(f"/{args.brief_id}/decision", token, transport, data={
                "action": args.action, "reason": args.reason.strip(), "expected_revision": args.revision,
            })
            if not isinstance(result, dict):
                raise LeaderError("Review API returned an invalid decision.")
        output = json.dumps(result, separators=(",", ":"))
    except LeaderError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(output.replace(token, "[redacted]"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
