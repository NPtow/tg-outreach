#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CASES_PATH = Path(__file__).with_name("auto_reply_smoke_cases.json")


def _load_cases(path: Path) -> tuple[dict, list[dict]]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload.get("defaults") or {}, payload.get("cases") or []


def _case_value(case: dict, defaults: dict, key: str, fallback=None):
    value = case.get(key)
    if value is not None:
        return value
    value = defaults.get(key)
    if value is not None:
        return value
    return fallback


def _request_json(url: str, body: dict, *, timeout_s: float) -> tuple[int, dict]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw or "{}")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload
    except URLError as exc:
        return 0, {"detail": str(exc.reason)}


def _run_case(case: dict, defaults: dict, *, args) -> dict:
    base_url = (args.base_url or os.getenv("TG_OUTREACH_SMOKE_BASE_URL") or _case_value(case, defaults, "base_url", "")).rstrip("/")
    pipeline_id = int(args.pipeline_id or _case_value(case, defaults, "pipeline_id"))
    conversation_id = int(args.conversation_id or _case_value(case, defaults, "conversation_id"))
    expected = str(_case_value(case, defaults, "expected_verdict", "SEND")).upper()
    messages = case.get("messages") or []
    dry_run_tools = bool(_case_value(case, defaults, "dry_run_tools", True))
    replace_latest_user_batch = bool(_case_value(case, defaults, "replace_latest_user_batch", True))
    if not base_url:
        raise ValueError("base_url is required")
    if not messages:
        raise ValueError(f"case {case.get('name') or '<unnamed>'} has no messages")

    url = f"{base_url}/api/agent-pipelines/{pipeline_id}/smoke-auto-reply"
    started = time.monotonic()
    status_code, payload = _request_json(
        url,
        {
            "conversation_id": conversation_id,
            "messages": messages,
            "dry_run_tools": dry_run_tools,
            "replace_latest_user_batch": replace_latest_user_batch,
        },
        timeout_s=args.timeout,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    verdict = str(payload.get("verdict") or ("ERROR" if status_code != 200 else "NO_REPLY")).upper()
    passed = status_code == 200 and verdict == expected
    return {
        "name": case.get("name") or "ad_hoc",
        "description": case.get("description") or "",
        "passed": passed,
        "expected": expected,
        "verdict": verdict,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "pipeline_id": pipeline_id,
        "conversation_id": conversation_id,
        "messages": messages,
        "reply_preview": payload.get("reply_preview") or "",
        "policy_issues": payload.get("policy_issues") or [],
        "error": payload.get("error") or payload.get("detail") or "",
        "payload": payload,
    }


def _print_result(result: dict) -> None:
    marker = "PASS" if result["passed"] else "FAIL"
    issues = ",".join(result["policy_issues"]) if result["policy_issues"] else "-"
    print(
        f"{marker} {result['name']} "
        f"expected={result['expected']} verdict={result['verdict']} "
        f"http={result['status_code']} duration_ms={result['duration_ms']} issues={issues}"
    )
    if result["reply_preview"]:
        print(f"  reply: {result['reply_preview']}")
    if result["error"]:
        print(f"  error: {result['error']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run TG Outreach auto-reply smoke scenarios against a deployed backend.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="Path to smoke cases JSON.")
    parser.add_argument("--case", dest="case_name", action="append", help="Run only a named case. Can be repeated.")
    parser.add_argument("--base-url", default="", help="Override backend base URL.")
    parser.add_argument("--pipeline-id", type=int, default=None, help="Override pipeline id.")
    parser.add_argument("--conversation-id", type=int, default=None, help="Override conversation id.")
    parser.add_argument("--message", action="append", help="Ad-hoc synthetic message. Replaces cases file when provided.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout per case in seconds.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after first failed case.")
    parser.add_argument("--json", action="store_true", help="Print full JSON results.")
    args = parser.parse_args(argv)

    defaults, cases = _load_cases(Path(args.cases))
    if args.message:
        cases = [{"name": "ad_hoc", "messages": args.message, "expected_verdict": "SEND"}]
    elif args.case_name:
        wanted = set(args.case_name)
        cases = [case for case in cases if case.get("name") in wanted]
        missing = wanted - {case.get("name") for case in cases}
        if missing:
            print(f"Missing smoke case(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    results = []
    for case in cases:
        try:
            result = _run_case(case, defaults, args=args)
        except Exception as exc:
            result = {
                "name": case.get("name") or "ad_hoc",
                "passed": False,
                "expected": case.get("expected_verdict") or defaults.get("expected_verdict") or "SEND",
                "verdict": "ERROR",
                "status_code": 0,
                "duration_ms": 0,
                "policy_issues": [],
                "reply_preview": "",
                "error": str(exc),
                "payload": {},
            }
        results.append(result)
        if not args.json:
            _print_result(result)
        if args.fail_fast and not result["passed"]:
            break

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))

    failed = [result for result in results if not result["passed"]]
    if failed:
        print(f"Smoke failed: {len(failed)}/{len(results)} case(s)", file=sys.stderr)
        return 1
    print(f"Smoke passed: {len(results)} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
