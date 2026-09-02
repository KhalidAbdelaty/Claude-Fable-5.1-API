"""Minimal client for the streaming endpoint, useful for checking the events."""

import json
import sys

import httpx2 as httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BODY = {
    "feature_request": (
        "Add rate limiting to the public API endpoints so one client cannot exhaust "
        "the search endpoint or brute force the token endpoint."
    ),
    "project": "bookmarks-api",
}

with httpx.stream("POST", "http://127.0.0.1:8000/plan/stream", json=BODY, timeout=300) as response:
    print("status", response.status_code, response.headers.get("content-type"))
    for line in response.iter_lines():
        if not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        kind = event["type"]
        if kind == "progress":
            print(f"  progress[{event['turn']}] {event['message'][:110]}")
        elif kind == "tool":
            path = event.get("path") or ""
            print(f"  tool     {event['name']} {path} refused={event['refused']}")
        elif kind == "plan":
            print(f"  PLAN     turns={event['turns']} tool_calls={event['tool_calls']}")
            print(f"           steps={len(event['plan']['implementation_steps'])}")
            print(f"           usage={json.dumps(event['usage'])}")
        else:
            print("  ", event)
