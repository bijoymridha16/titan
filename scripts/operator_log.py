#!/usr/bin/env python
"""Append an operator decision to the operator_decisions journal.

Usage:
    echo '{"category":"risk","title":"...","action":"...","rationale":"...",
           "thinking":"...","params":{...},"expected":"..."}' \
        | python scripts/operator_log.py

Reads a single JSON object from stdin. Required: category, title, action,
rationale. Optional: thinking, params (object), expected, status, actor.
Prints the inserted row id. Best-effort: prints an error but never raises into
whatever orchestration calls it.
"""
from __future__ import annotations

import json
import sys

from sqlalchemy import create_engine, text

from titan.config import settings


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception as e:
        print(f"operator_log: bad JSON on stdin: {e}", file=sys.stderr)
        return 1

    for req in ("category", "title", "action", "rationale"):
        if not d.get(req):
            print(f"operator_log: missing required field '{req}'", file=sys.stderr)
            return 1

    row = {
        "actor": d.get("actor", "claude-operator"),
        "category": d["category"],
        "title": d["title"],
        "action": d["action"],
        "rationale": d["rationale"],
        "thinking": d.get("thinking"),
        "params": json.dumps(d["params"]) if d.get("params") is not None else None,
        "expected": d.get("expected"),
        "status": d.get("status", "applied"),
    }

    eng = create_engine(settings.db_url)
    with eng.begin() as cx:
        rid = cx.execute(text("""
            INSERT INTO operator_decisions
              (actor, category, title, action, rationale, thinking, params, expected, status)
            VALUES
              (:actor, :category, :title, :action, :rationale, :thinking,
               CAST(:params AS JSONB), :expected, :status)
            RETURNING id
        """), row).scalar_one()
    print(f"operator_decision #{rid} logged: [{row['category']}] {row['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
