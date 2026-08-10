"""Stage 2 — Plan: reconcile KB concepts against the wiki page index.

Since the Knowledge-Base (memory repo, pnp-knowledge) already holds
synthesized entity concepts, this stage needs no LLM: it lists exportable
concepts from the KB API, folds them into pages via the page map (pagemap.py —
entities are not pages), matches each against the stage-1 page index (title or
alias hit -> update, otherwise create), applies the relevance gate
(config.MIN_SESSIONS, see CHRONIST.md §5), and writes the plan.

Output: config.WIKI_CACHE_DIR / "entities.json" — consumed by stage 3, plus
"bodies.json" (the planned concepts' body_md, which the detail call above
already returned) so stage 3 does not fetch them a second time.
Each entry: {concept, id, type, title, wiki_title, action: create|update,
members: [{concept, role: lead|sub, title}]}. For the 1:1 default — all but a
handful of pages — ``members`` is the concept itself as the sole lead.

Run:  python 02_extract.py        (KB API must be up, see config.KB_URL)
"""

from __future__ import annotations

import json
import re

import requests

import config
import pagemap
import runlog

_STAGE = "02_extract"

# Concept bodies cite sources as "Session 2025-11-25 @ 00:03:22 (<url>)".
# Distinct dates = distinct sessions, which is what the relevance gate asks
# about; non-session citations (e.g. "[Kapitel 3, Der_Splitter_des_Ewigen.md]")
# correctly don't count towards it.
_SESSION_CITE_RE = re.compile(r"Session (\d{4}-\d{2}-\d{2})")

# Session frontmatter the overview table needs. Set by the KB from
# ../pnp-knowledge/knowledge/episodes.yaml; absent on a pre-episode bundle.
_EPISODE_FIELDS = (
    "episode",
    "episode_title",
    "season",
    "season_label",
    "team",
    "description",
    "resource",
    "timestamp",
)


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


def fetch_concepts() -> tuple[list[dict], dict[str, str]]:
    """Return ``(concepts, bodies)`` — every concept plus its raw body_md.

    The bodies come back from the same detail call the aliases need, so stage 3
    does not have to fetch them a second time (see the bodies.json write in
    ``main``).
    """

    concepts: list[dict] = []
    bodies: dict[str, str] = {}
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
            fm = payload["frontmatter"]
            c["aliases"] = fm.get("aliases") or []
            body = payload.get("body_md") or ""
            bodies[c["concept"]] = body
            c["sessions"] = count_sessions(body)
            # Episode identity for the overview table (stage 3). Copied field
            # by field rather than keeping the whole frontmatter: entities.json
            # is reviewed by hand and carries 900+ concepts.
            if c.get("type") == "Session":
                c["episode"] = {k: fm.get(k) for k in _EPISODE_FIELDS}
    return concepts, bodies


def plan_entities(
    concepts: list[dict],
    page_titles: list[str],
    min_sessions: int | None = None,
    events: list[dict] | None = None,
    page_map: dict | None = None,
) -> list[dict]:
    """Pure planning core (offline-testable): decide create vs update.

    ``page_map`` (see pagemap.load) folds several concepts into one page and
    drops excluded ones first; without it every concept is its own page.
    Concepts below the relevance gate are dropped (CHRONIST.md §5) unless they
    already have a live page. ``events`` (optional) collects a record per
    entity — including every *dropped* one, which the plan file cannot show —
    for the caller to write to the run log.
    """

    if min_sessions is None:
        min_sessions = config.MIN_SESSIONS
    if page_map:
        concepts = pagemap.group(concepts, page_map, events)
    existing = {t.lower(): t for t in page_titles}
    plan: list[dict] = []
    seen_titles: dict[str, str] = {}
    for c in sorted(concepts, key=lambda c: c["concept"]):
        title = (c.get("title") or c["concept"].rsplit("/", 1)[-1]).strip()
        names = [title] + [str(a) for a in c.get("aliases") or []]
        # The live page the match landed on — its *own* title, which is not the
        # KB title when an alias matched (KB "Königreich Zebros" vs. live
        # "Zebros"). wiki_title has to be that one: stage 3 fetches the live
        # page by it and stage 4 edits it, so taking the KB title instead would
        # diff against nothing and then upload a *new* page beside the live
        # one, orphaning the hand-written article the alias just matched.
        matched = next(
            (existing[n.lower()] for n in names if n.lower() in existing), None
        )
        action = "update" if matched else "create"
        # Relevance gate before the duplicate check, so a filtered-out concept
        # never claims a title its more relevant namesake needs.
        if (
            action == "create"
            and c.get("type") not in config.NO_GATE_TYPES
            and c.get("sessions", 0) < min_sessions
        ):
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
            "wiki_title": matched or title,
            "action": action,
            "members": pagemap.members_of({**c, "title": title}),
        }
        if c.get("episode"):
            entry["episode"] = c["episode"]
        plan.append(entry)
        if events is not None:
            events.append(
                {"event": "plan_entry", **entry, "sessions": c.get("sessions", 0)}
            )
            # A merged-away member that still has its own live page is now
            # orphaned — nothing links to it and nothing updates it any more.
            # The fix is a redirect, which only a human can create.
            for m in entry["members"]:
                if m["title"].lower() != title.lower() and m["title"].lower() in existing:
                    events.append(
                        {
                            "event": "member_has_live_page",
                            "level": "warn",
                            "page": title,
                            "member": m["concept"],
                            "member_title": m["title"],
                            "note": "Live-Seite verwaist — Weiterleitung anlegen",
                        }
                    )
    return plan


def main() -> None:
    runlog.log(_STAGE, "stage_start", kb_url=config.KB_URL)
    page_titles = load_page_index()
    try:
        concepts, bodies = fetch_concepts()
    except requests.RequestException as exc:
        runlog.log(_STAGE, "error", level="error", detail=str(exc))
        raise SystemExit(
            f"KB API not reachable at {config.KB_URL} ({exc}).\n"
            "Start it: cd ../pnp-knowledge/services/kb && python -m pnp_okf.api"
        )
    try:
        page_map = pagemap.load(config.PAGEMAP_PATH)
    except (pagemap.PageMapError, ValueError) as exc:
        runlog.log(_STAGE, "error", level="error", detail=str(exc))
        raise SystemExit(f"{config.PAGEMAP_PATH} ist fehlerhaft: {exc}")
    runlog.log(
        _STAGE, "pagemap_loaded",
        pages=len(page_map["pages"]), excluded=len(page_map["exclude"]),
    )

    events: list[dict] = []
    plan = plan_entities(concepts, page_titles, events=events, page_map=page_map)
    for e in events:
        runlog.log(_STAGE, e.pop("event"), level=e.pop("level", "info"), **e)

    config.WIKI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = config.WIKI_CACHE_DIR / "entities.json"
    out.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # The bodies stage 3 needs, from the same snapshot as the plan beside it —
    # it would otherwise re-fetch every one of them from the KB. Only the
    # concepts that survived into the plan; the ~800 filtered-out ones are dead
    # weight on disk.
    planned = {m["concept"] for e in plan for m in pagemap.members_of(e)}
    bodies_path = config.WIKI_CACHE_DIR / "bodies.json"
    bodies_path.write_text(
        json.dumps(
            {c: b for c, b in bodies.items() if c in planned},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    runlog.log(_STAGE, "write", name=bodies_path.name, concepts=len(planned))
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
