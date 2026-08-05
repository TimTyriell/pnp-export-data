"""Stage 2 — Plan: reconcile KB concepts against the wiki page index.

Since the Knowledge-Base (memory repo, pnp-knowledge) already holds
synthesized entity concepts, this stage needs no LLM: it lists exportable
concepts from the KB API, matches each against the stage-1 page index
(title or alias hit -> update, otherwise create), applies the relevance gate
(config.MIN_SESSIONS, see CHRONIST.md §5), and writes the plan.

Output: config.WIKI_CACHE_DIR / "entities.json" — consumed by stage 3.
Each entry: {concept, id, type, title, wiki_title, action: create|update}.

Run:  python 02_extract.py        (KB API must be up, see config.KB_URL)
"""

from __future__ import annotations

import json
import re

import requests

import config
import runlog

_STAGE = "02_extract"

# Concept bodies cite sources as "Session 2025-11-25 @ 00:03:22 (<url>)".
# Distinct dates = distinct sessions, which is what the relevance gate asks
# about; non-session citations (e.g. "[Kapitel 3, Der_Splitter_des_Ewigen.md]")
# correctly don't count towards it.
_SESSION_CITE_RE = re.compile(r"Session (\d{4}-\d{2}-\d{2})")


def count_sessions(body_md: str) -> int:
    return len(set(_SESSION_CITE_RE.findall(body_md)))


def load_page_index() -> list[str]:
    path = config.WIKI_CACHE_DIR / "page_index.json"
    if not path.exists():
        runlog.log(
            _STAGE, "page_index_missing", level="warn", path=str(path),
            echo=f"{path} missing (run 01_inventory.py first) — "
                 "treating every concept as a new page.",
        )
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_concepts() -> list[dict]:
    concepts: list[dict] = []
    with requests.Session() as session:
        for ctype in config.EXPORT_TYPES:
            resp = session.get(
                f"{config.KB_URL}/concepts", params={"type": ctype}, timeout=30
            )
            resp.raise_for_status()
            concepts.extend(resp.json())
        # Aliases live in the full frontmatter, not the listing. The same
        # response carries body_md, so the session count is free here.
        for c in concepts:
            detail = session.get(
                f"{config.KB_URL}/concepts/{c['concept']}", timeout=30
            )
            detail.raise_for_status()
            payload = detail.json()
            c["aliases"] = payload["frontmatter"].get("aliases") or []
            c["sessions"] = count_sessions(payload.get("body_md") or "")
    return concepts


def plan_entities(
    concepts: list[dict],
    page_titles: list[str],
    min_sessions: int | None = None,
    events: list[dict] | None = None,
) -> list[dict]:
    """Pure planning core (offline-testable): decide create vs update.

    Concepts below the relevance gate are dropped (CHRONIST.md §5) unless they
    already have a live page. ``events`` (optional) collects a record per
    entity — including every *dropped* one, which the plan file cannot show —
    for the caller to write to the run log.
    """

    if min_sessions is None:
        min_sessions = config.MIN_SESSIONS
    existing = {t.lower() for t in page_titles}
    plan: list[dict] = []
    seen_titles: dict[str, str] = {}
    for c in sorted(concepts, key=lambda c: c["concept"]):
        title = (c.get("title") or c["concept"].rsplit("/", 1)[-1]).strip()
        names = [title] + [str(a) for a in c.get("aliases") or []]
        action = (
            "update"
            if any(n.lower() in existing for n in names)
            else "create"
        )
        # Relevance gate before the duplicate check, so a filtered-out concept
        # never claims a title its more relevant namesake needs.
        if action == "create" and c.get("sessions", 0) < min_sessions:
            if events is not None:
                events.append(
                    {
                        "event": "skip",
                        "concept": c["concept"],
                        "title": title,
                        "reason": "min_sessions",
                        "sessions": c.get("sessions", 0),
                        "min_sessions": min_sessions,
                    }
                )
            continue
        if title.lower() in seen_titles:
            if events is not None:
                events.append(
                    {
                        "event": "skip",
                        "level": "warn",
                        "concept": c["concept"],
                        "title": title,
                        "reason": "dup_title",
                        "kept": seen_titles[title.lower()],
                        "note": "merge the concepts in the KB registry first",
                    }
                )
            continue
        seen_titles[title.lower()] = c["concept"]
        entry = {
            "concept": c["concept"],
            "id": c.get("id"),
            "type": c.get("type"),
            "title": title,
            "wiki_title": title,
            "action": action,
        }
        plan.append(entry)
        if events is not None:
            events.append(
                {"event": "plan_entry", **entry, "sessions": c.get("sessions", 0)}
            )
    return plan


def main() -> None:
    runlog.log(_STAGE, "stage_start", kb_url=config.KB_URL)
    page_titles = load_page_index()
    try:
        concepts = fetch_concepts()
    except requests.RequestException as exc:
        runlog.log(_STAGE, "error", level="error", detail=str(exc))
        raise SystemExit(
            f"KB API not reachable at {config.KB_URL} ({exc}).\n"
            "Start it: cd ../pnp-knowledge/services/kb && python -m pnp_okf.api"
        )
    events: list[dict] = []
    plan = plan_entities(concepts, page_titles, events=events)
    for e in events:
        runlog.log(_STAGE, e.pop("event"), level=e.pop("level", "info"), **e)

    config.WIKI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = config.WIKI_CACHE_DIR / "entities.json"
    out.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    creates = sum(1 for e in plan if e["action"] == "create")
    skipped = len(concepts) - len(plan)
    runlog.log(
        _STAGE, "stage_end", entities=len(plan), create=creates,
        update=len(plan) - creates, skipped=skipped,
        echo=(
            f"Wrote {len(plan)} entities to {out} "
            f"({creates} create, {len(plan) - creates} update, "
            f"{skipped} skipped — see the run log for each skip reason; "
            f"most are below the relevance gate of {config.MIN_SESSIONS} "
            "sessions, see CHRONIST.md §5)."
        ),
    )


if __name__ == "__main__":
    main()
