"""Run log — one JSONL file per run, so an agent can reconstruct what happened.

Every stage writes structured events to ``logs/<run_id>.jsonl``. One file per
run means several agents can work in parallel without ever writing to the same
file, so no locking is needed. The ``run_id`` defaults to timestamp + pid; set
``PNP_RUN_ID`` to group several stages (or a whole agent session) into one run.

Read it back with plain tools — the format is one JSON object per line:

    ls logs/
    grep '"level":"warn"' logs/<run_id>.jsonl
    python -c "import json,sys;[print(json.loads(l)['event']) for l in open(...)]"

Agents that edit articles by hand log into the same stream via the CLI:

    PNP_RUN_ID=agent-slix python runlog.py --stage agent --event edit \
        --target "Slix" --note "KB-Dublette entfernt"
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sys

import config

_RUN_ID: str | None = None


def run_id() -> str:
    """Stable id for this process (env override groups stages into one run)."""

    global _RUN_ID
    if _RUN_ID is None:
        _RUN_ID = os.environ.get("PNP_RUN_ID") or (
            f"{_dt.datetime.now(_dt.timezone.utc):%Y%m%dT%H%M%SZ}-{os.getpid()}"
        )
    return _RUN_ID


def sha8(text: str) -> str:
    """Short content hash — identifies "same bytes written twice" in a run."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def log(stage: str, event: str, *, level: str = "info", echo: str | None = None, **fields) -> None:
    """Append one event to this run's JSONL; optionally echo a human line.

    ``echo`` is the sentence a person reading the terminal wants; without it
    the event is machine-only (per-entity events would otherwise drown stdout).
    ``warn``/``error`` always surface, on stderr.
    """

    record = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id(),
        "stage": stage,
        "event": event,
        "level": level,
        **fields,
    }
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with (config.LOGS_DIR / f"{run_id()}.jsonl").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    if level in ("warn", "error"):
        detail = echo or " ".join(f"{k}={v!r}" for k, v in fields.items())
        print(f"{level.upper()} [{stage}] {event}: {detail}", file=sys.stderr)
    elif echo:
        print(echo)


def main(argv: list[str]) -> None:
    import argparse

    p = argparse.ArgumentParser(description="Append one event to the run log.")
    p.add_argument("--stage", default="agent")
    p.add_argument("--event", required=True)
    p.add_argument("--level", default="info")
    p.add_argument("--target", help="wiki title / file the event is about")
    p.add_argument("--note", help="what was done and why")
    p.add_argument("--source", help="where the content came from")
    args = p.parse_args(argv)

    fields = {
        k: v
        for k, v in (
            ("target", args.target),
            ("note", args.note),
            ("source", args.source),
        )
        if v
    }
    log(args.stage, args.event, level=args.level, **fields)
    print(f"{run_id()}: {args.event} {fields}")


if __name__ == "__main__":
    main(sys.argv[1:])
