"""Stage 2 — Plan: reconcile KB concepts against the wiki page index.

Since the Knowledge-Base (memory repo, pnp-graph-service) already holds
synthesized entity concepts, this stage needs no LLM: it lists exportable
concepts from the KB API, matches each against the stage-1 page index
(title or alias hit -> update, otherwise create), and writes the plan.

Output: config.WIKI_CACHE_DIR / "entities.json" — consumed by stage 3.
Each entry: {concept, id, type, title, wiki_title, action: create|update}.

Run:  python 02_extract.py        (KB API must be up, see config.KB_URL)
"""

from __future__ import annotations

import json
import sys

import requests

import config


def load_page_index() -> list[str]:
    path = config.WIKI_CACHE_DIR / "page_index.json"
    if not path.exists():
        print(
            f"WARNING: {path} missing (run 01_inventory.py first) — "
            "treating every concept as a new page.",
            file=sys.stderr,
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
        # Aliases live in the full frontmatter, not the listing.
        for c in concepts:
            detail = session.get(
                f"{config.KB_URL}/concepts/{c['concept']}", timeout=30
            )
            detail.raise_for_status()
            c["aliases"] = detail.json()["frontmatter"].get("aliases") or []
    return concepts


def plan_entities(concepts: list[dict], page_titles: list[str]) -> list[dict]:
    """Pure planning core (offline-testable): decide create vs update."""

    existing = {t.lower() for t in page_titles}
    plan: list[dict] = []
    seen_titles: dict[str, str] = {}
    for c in sorted(concepts, key=lambda c: c["concept"]):
        title = (c.get("title") or c["concept"].rsplit("/", 1)[-1]).strip()
        if title.lower() in seen_titles:
            print(
                f"WARNING: duplicate wiki title {title!r} "
                f"({c['concept']} vs {seen_titles[title.lower()]}) — skipped; "
                "merge the concepts in the KB registry first.",
                file=sys.stderr,
            )
            continue
        seen_titles[title.lower()] = c["concept"]
        names = [title] + [str(a) for a in c.get("aliases") or []]
        action = (
            "update"
            if any(n.lower() in existing for n in names)
            else "create"
        )
        plan.append(
            {
                "concept": c["concept"],
                "id": c.get("id"),
                "type": c.get("type"),
                "title": title,
                "wiki_title": title,
                "action": action,
            }
        )
    return plan


def main() -> None:
    page_titles = load_page_index()
    try:
        concepts = fetch_concepts()
    except requests.RequestException as exc:
        raise SystemExit(
            f"KB API not reachable at {config.KB_URL} ({exc}).\n"
            "Start it: cd ../pnp-graph-service/services/kb && python -m pnp_okf.api"
        )
    plan = plan_entities(concepts, page_titles)

    config.WIKI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = config.WIKI_CACHE_DIR / "entities.json"
    out.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    creates = sum(1 for e in plan if e["action"] == "create")
    print(
        f"Wrote {len(plan)} entities to {out} "
        f"({creates} create, {len(plan) - creates} update)"
    )


if __name__ == "__main__":
    main()
