"""Stage 3 — Generate: deterministic Wikitext proposals (the dry-run).

For each entity in the stage-2 plan, fetch its KB concept body and convert
it to German Wikitext with md2wiki (no LLM — the KB body is already the
synthesized, cited text; a deterministic conversion cannot hallucinate).
Internal links resolve via the plan's concept->wiki-title map; a category
per type is appended.

Nothing is uploaded here. Per entity:
  proposals/<Title>.wikitext          the proposed page
  proposals/<Title>.diff              (updates only) unified diff vs live page
  proposals/NEW_PAGES.md              summary of proposed *new* pages — a
                                      human creates these on fandom.com
                                      manually; the agent never creates pages.

Run:  python 03_generate.py          (KB API up; wiki reachable for diffs)
"""

from __future__ import annotations

import difflib
import json
import sys

import requests

import config
from md2wiki import LinkResolver, markdown_to_wikitext
from wiki_client import WikiClient


def load_plan() -> list[dict]:
    path = config.WIKI_CACHE_DIR / "entities.json"
    if not path.exists():
        raise SystemExit(f"{path} missing — run 02_extract.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_body(session: requests.Session, concept: str) -> str:
    resp = session.get(f"{config.KB_URL}/concepts/{concept}", timeout=30)
    resp.raise_for_status()
    return resp.json()["body_md"]


def generate_proposals(
    plan: list[dict],
    bodies: dict[str, str],
    live_pages: dict[str, str],
) -> dict[str, str]:
    """Pure core (offline-testable): return ``filename -> content``."""

    resolver = LinkResolver({e["concept"]: e["wiki_title"] for e in plan})
    outputs: dict[str, str] = {}
    new_pages: list[dict] = []

    for entity in plan:
        body = bodies.get(entity["concept"])
        if body is None:
            continue
        category = config.CATEGORY_BY_TYPE.get(entity["type"] or "")
        wikitext = markdown_to_wikitext(body, resolver, category)
        safe_title = entity["wiki_title"].replace("/", "_")
        outputs[f"{safe_title}.wikitext"] = wikitext

        if entity["action"] == "update":
            live = live_pages.get(entity["wiki_title"], "")
            diff = "\n".join(
                difflib.unified_diff(
                    live.splitlines(),
                    wikitext.splitlines(),
                    fromfile=f"wiki/{entity['wiki_title']}",
                    tofile=f"kb/{entity['concept']}",
                    lineterm="",
                )
            )
            outputs[f"{safe_title}.diff"] = diff + "\n"
        else:
            new_pages.append(entity)

    if new_pages:
        lines = [
            "# Vorgeschlagene neue Seiten",
            "",
            "Der Agent legt NIE selbst Seiten an. Für jede Zeile: Seite auf",
            "fandom.com manuell anlegen (leer genügt), dann füllt der nächste",
            "Sync sie über den Update-Pfad aus dem .wikitext-Vorschlag.",
            "",
        ]
        for e in sorted(new_pages, key=lambda e: e["wiki_title"]):
            lines.append(
                f"* **{e['wiki_title']}** ({e['type']}, `{e['concept']}`)"
                f" — Vorschlag: `{e['wiki_title'].replace('/', '_')}.wikitext`"
            )
        outputs["NEW_PAGES.md"] = "\n".join(lines) + "\n"
    return outputs


def main() -> None:
    plan = load_plan()

    bodies: dict[str, str] = {}
    with requests.Session() as session:
        for entity in plan:
            try:
                bodies[entity["concept"]] = fetch_body(session, entity["concept"])
            except requests.RequestException as exc:
                raise SystemExit(f"KB API not reachable ({exc}).")

    live_pages: dict[str, str] = {}
    updates = [e for e in plan if e["action"] == "update"]
    if updates:
        client = WikiClient()
        for entity in updates:
            try:
                page = client.read(entity["wiki_title"])
            except requests.RequestException as exc:
                print(
                    f"WARNING: wiki unreachable ({exc}) — diffs against "
                    "empty pages.",
                    file=sys.stderr,
                )
                break
            if page is not None:
                live_pages[entity["wiki_title"]] = page.wikitext

    outputs = generate_proposals(plan, bodies, live_pages)
    config.PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (config.PROPOSALS_DIR / name).write_text(content, encoding="utf-8")

    n_new = sum(1 for e in plan if e["action"] == "create")
    print(
        f"Wrote {len(outputs)} file(s) to {config.PROPOSALS_DIR} "
        f"({len(plan)} pages, {n_new} proposed new — see NEW_PAGES.md). "
        "Review before running 04_upload.py."
    )


if __name__ == "__main__":
    main()
