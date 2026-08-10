"""Stage 3 — Generate: deterministic Wikitext proposals (the dry-run).

For each page in the stage-2 plan, fetch its members' KB concept bodies,
compose them into one body (pagemap.compose_body — a no-op for the 1:1
default) and convert that to German Wikitext with md2wiki (no LLM — the KB
body is already the synthesized, cited text; a deterministic conversion cannot
hallucinate). Internal links resolve via the plan's concept->wiki-title map,
which maps *every* member of a page to that page — so a link to a merged-away
concept lands on the page that now covers it. A category per type is appended.

Nothing is uploaded here. Per entity:
  proposals/<Title>.wikitext          the proposed page
  proposals/<Title>.diff              (updates only) unified diff vs live page
  proposals/NEW_PAGES.md              summary of proposed *new* pages — a
                                      human creates these on fandom.com
                                      manually; the agent never creates pages.

Files of those three kinds left in proposals/ by *earlier* runs are pruned at
the end (see prune_proposals) — the directory mirrors the current run, not the
history of all of them. The history stays in the run log.

Run:  python 03_generate.py          (KB API up; wiki reachable for diffs)
"""

from __future__ import annotations

import difflib
import json
import re

import requests

import config
import pagemap
import runlog
from md2wiki import (
    LinkResolver,
    markdown_to_wikitext,
    strip_transcription_variants,
)
from wiki_client import WikiClient
from wikimerge import _norm, _HEADING_RE, merge_wikitext_verbose

_STAGE = "03_generate"


def detect_anomalies(title: str, decisions: dict, wikitext: str) -> list[dict]:
    """Smells worth a warn in the run log. Reports only — fixes nothing.

    These do not decide anything; they exist so a broken merge shows up as a
    log line instead of only as a wrong file nobody opened.
    """

    found: list[dict] = []
    # The set the merge actually matches against (any level), not just the
    # level-2 headings sections are carved from.
    live_headings = decisions.get("live_headings_all") or decisions["live_headings"]
    kb_headings = decisions["kb_headings"]
    appended = decisions["appended"]

    # Both checks below describe the pre-KI-region failure mode: KB text landing
    # a second time beside live content the merge could not match. Once a page
    # has a KI region (or sections were reclaimed into a new one), rewriting the
    # whole region from the KB *is* the design, and having no headings outside
    # it is normal — so neither is a smell there.
    rewrites_region = decisions.get("ki_state") != "absent" or decisions.get("reclaimed")

    # A substantial live page with no heading at all: nothing can match, so
    # every KB section counts as new and the article is appended a second time.
    if not rewrites_region and decisions["live_bytes"] > 500 and not live_headings:
        found.append({"kind": "live_headings_empty", "live_bytes": decisions["live_bytes"]})

    if (
        not rewrites_region
        and decisions["live_bytes"] > 0
        and kb_headings
        and set(appended) >= set(kb_headings)
    ):
        found.append({"kind": "full_reappend", "appended": appended})

    # Level 2 only. That is the level a page is structured at, and the failure
    # this looks for (a whole article appended a second time) shows up there.
    # Deeper repeats are normal on a composed page: four members each having
    # their own nested "Überblick" is the structure working, not a smell.
    seen: set[str] = set()
    dupes: set[str] = set()
    for line in wikitext.splitlines():
        m = _HEADING_RE.match(line)
        if not m or len(m.group(1)) != 2:
            continue
        heading = _norm(m.group(2))
        (dupes if heading in seen else seen).add(heading)
    if dupes:
        found.append({"kind": "dup_heading", "headings": sorted(dupes)})

    for a in found:
        a["title"] = title
    return found


def detect_dup_content(outputs: dict[str, str]) -> list[dict]:
    """Different proposal files with byte-identical content (stale near-dupe
    titles like Willau/Willoch/Willauch all fed from the same concept)."""

    by_hash: dict[str, list[str]] = {}
    for name, text in outputs.items():
        if name.endswith(".wikitext"):
            by_hash.setdefault(runlog.sha8(text), []).append(name)
    return [
        {"kind": "dup_content", "sha8": h, "files": sorted(names)}
        for h, names in by_hash.items()
        if len(names) > 1
    ]


# What this stage owns in proposals/ and may therefore delete. Anything else a
# human dropped in there (notes, a .bak, a screenshot) is not ours to touch.
_OURS = (".wikitext", ".diff")


def prune_proposals(keep: set[str]) -> int:
    """Delete this stage's files in proposals/ that the current run did not
    write. Returns how many went.

    proposals/ is flat and was append-only, so it accumulated files from every
    older run — stale titles a reviewer cannot tell apart from current ones,
    and stage 4 globs the directory. Everything here is regenerable from the KB
    and the run log keeps a `prune` event per file (name, bytes, sha8), so the
    record survives even though the file does not.
    """

    pruned = 0
    for path in sorted(config.PROPOSALS_DIR.iterdir()):
        if not path.is_file() or path.name in keep:
            continue
        if path.suffix not in _OURS and path.name != "NEW_PAGES.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        runlog.log(
            _STAGE, "prune", name=path.name, bytes=len(text), sha8=runlog.sha8(text)
        )
        path.unlink()
        pruned += 1
    return pruned


def render_story_overview(plan: list[dict]) -> str:
    """The episode overview table as Wikitext.

    One collapsible block per season, newest season first, episodes oldest
    first inside it — the reading order of a campaign log. Built from the same
    Session concepts that get their own pages, so the table and the pages can
    never disagree about an episode's id, name or link target.

    Wikitext directly, not Markdown through md2wiki: the converter handles
    headings, lists and links, not tables, and this page *is* a table. It still
    goes through the normal merge afterwards, so it lands in the KI region and
    leaves anything hand-written on that page alone.
    """

    sessions = [e for e in plan if (e.get("episode") or {}).get("episode")]
    if not sessions:
        return ""

    seasons: dict[str, list[dict]] = {}
    for entry in sessions:
        seasons.setdefault(str(entry["episode"].get("season") or "?"), []).append(entry)

    def newest(item: tuple[str, list[dict]]) -> str:
        return max(e["episode"].get("timestamp") or "" for e in item[1])

    lines: list[str] = []
    for key, entries in sorted(seasons.items(), key=newest, reverse=True):
        label = entries[0]["episode"].get("season_label") or f"Staffel {key}"
        entries.sort(key=lambda e: e["episode"].get("timestamp") or "")
        lines += [
            '<div class="mw-collapsible mw-collapsed">',
            "",
            f"== {label} ==",
            "",
            '<div class="mw-collapsible-content">',
            '{| class="fandom-table"',
            "|+",
            "!Episode",
            "!Abenteuername",
            "!Kurze Beschreibung",
            "!Youtube",
        ]
        for entry in entries:
            ep = entry["episode"]
            name = (ep.get("episode_title") or "").strip()
            # The page exists either way; without an Abenteuername the id is
            # the only label there is.
            link = (
                f"[[{entry['wiki_title']}|{name}]]"
                if name
                else f"[[{entry['wiki_title']}]]"
            )
            lines += [
                "|-",
                f"|{ep['episode']}",
                f"|{link}",
                f"|{(ep.get('description') or '').strip()}",
                f"|{ep.get('resource') or ''}",
            ]
        lines += ["|}", "</div>", "</div>", ""]
    return "\n".join(lines)


def build_overview_proposal(
    plan: list[dict], live_pages: dict[str, str], events: list[dict] | None = None
) -> dict[str, str]:
    """``{filename: content}`` for the episode overview page, or ``{}``.

    Goes through the same merge as every concept page, so the hand-written
    parts of that page survive and only the KI region is rewritten.
    """

    title = config.STORY_OVERVIEW_PAGE
    table = render_story_overview(plan) if title else ""
    if not table:
        return {}

    if title not in live_pages:
        # Refuse to guess: writing an overview to a title that is not the live
        # page creates a duplicate table nobody maintains.
        if events is not None:
            events.append(
                {
                    "event": "overview_skipped",
                    "level": "warn",
                    "title": title,
                    "note": "page not found live — check PNP_STORY_OVERVIEW_PAGE "
                    "and refresh the page index (01_inventory.py)",
                }
            )
        return {}

    live = live_pages[title]
    merged, decisions = merge_wikitext_verbose(live, table, title)
    if events is not None:
        events.append(
            {
                "event": "merge",
                "title": title,
                "concept": "(overview)",
                **decisions,
                "out_sha8": runlog.sha8(merged),
            }
        )
    safe = re.sub(r'[<>:"/\\|?*]', "_", title)
    diff = "\n".join(
        difflib.unified_diff(
            live.splitlines(),
            merged.splitlines(),
            fromfile=f"live/{title}",
            tofile=f"merged/{title}",
            lineterm="",
        )
    )
    return {f"{safe}.wikitext": merged, f"{safe}.diff": diff + "\n"}


def load_plan() -> list[dict]:
    path = config.WIKI_CACHE_DIR / "entities.json"
    if not path.exists():
        raise SystemExit(f"{path} missing — run 02_extract.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_body(session: requests.Session, concept: str) -> str:
    resp = session.get(f"{config.KB_URL}/concepts/{concept}", timeout=30)
    resp.raise_for_status()
    return resp.json()["body_md"]


def cached_bodies() -> dict[str, str]:
    """Bodies stage 2 already fetched (wiki_cache/bodies.json), or ``{}``.

    Written by the same stage-2 run as entities.json, so plan and bodies are
    one snapshot. Missing (older cache, hand-edited plan) just means every body
    is fetched again — the file is an optimisation, never a requirement.
    """

    path = config.WIKI_CACHE_DIR / "bodies.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def generate_proposals(
    plan: list[dict],
    bodies: dict[str, str],
    live_pages: dict[str, str],
    events: list[dict] | None = None,
) -> dict[str, str]:
    """Pure core (offline-testable): return ``filename -> content``.

    ``events`` (optional) collects per-page merge decisions and anomalies for
    the caller to write to the run log — the core itself stays I/O-free.
    """

    resolver = LinkResolver(
        {
            m["concept"]: e["wiki_title"]
            for e in plan
            for m in pagemap.members_of(e)
        }
    )
    outputs: dict[str, str] = {}
    new_pages: list[dict] = []

    for entity in plan:
        members = pagemap.members_of(entity)
        body = pagemap.compose_body(members, bodies)
        if body is None:
            continue
        # A composed page carries one level-2 unit per member with that
        # member's sections nested below. The merge has to keep that nesting —
        # flattening it (the right thing for a single concept) would turn the
        # page back into several articles in a row.
        composed = len(members) > 1
        category = config.CATEGORY_BY_TYPE.get(entity["type"] or "")
        kb_wikitext = markdown_to_wikitext(
            strip_transcription_variants(body), resolver, category
        )
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", entity["wiki_title"])

        if entity["action"] == "update":
            live = live_pages.get(entity["wiki_title"], "")
            # Additive merge: never delete hand-authored content. With no live
            # copy fetched, fall back to the KB text (the diff makes that
            # obvious to the reviewer).
            #
            # Membership, not truthiness: an *empty but existing* page (a stub
            # a human just created, or one blanked to clear a bad sync) must go
            # through the merge, so its content lands inside a KI region like
            # every other page. Only a page we could not read at all falls back
            # to raw KB text.
            if entity["wiki_title"] in live_pages:
                wikitext, decisions = merge_wikitext_verbose(
                    live, kb_wikitext, entity["wiki_title"], composed
                )
                if events is not None:
                    events.append(
                        {
                            "event": "merge",
                            "title": entity["wiki_title"],
                            "concept": entity["concept"],
                            **decisions,
                            "out_sha8": runlog.sha8(wikitext),
                        }
                    )
                    for anomaly in detect_anomalies(
                        entity["wiki_title"], decisions, wikitext
                    ):
                        events.append({"event": "anomaly", "level": "warn", **anomaly})
            else:
                wikitext = kb_wikitext
                if events is not None:
                    events.append(
                        {
                            "event": "no_live_copy",
                            "level": "warn",
                            "title": entity["wiki_title"],
                            "note": "wiki page not fetched — proposal is raw KB text",
                        }
                    )
            outputs[f"{safe_title}.wikitext"] = wikitext
            diff = "\n".join(
                difflib.unified_diff(
                    live.splitlines(),
                    wikitext.splitlines(),
                    fromfile=f"live/{entity['wiki_title']}",
                    tofile=f"merged/{entity['wiki_title']}",
                    lineterm="",
                )
            )
            outputs[f"{safe_title}.diff"] = diff + "\n"
        else:
            outputs[f"{safe_title}.wikitext"] = kb_wikitext
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

    if events is not None:
        for dup in detect_dup_content(outputs):
            events.append({"event": "anomaly", "level": "warn", **dup})
    return outputs


def main() -> None:
    plan = load_plan()
    runlog.log(_STAGE, "stage_start", entities=len(plan))

    bodies = cached_bodies()
    missing = [
        m["concept"]
        for e in plan
        for m in pagemap.members_of(e)
        if m["concept"] not in bodies
    ]
    runlog.log(_STAGE, "bodies", cached=len(bodies), fetched=len(set(missing)))
    with requests.Session() as session:
        for concept in dict.fromkeys(missing):
            try:
                bodies[concept] = fetch_body(session, concept)
            except requests.RequestException as exc:
                runlog.log(
                    _STAGE, "error", level="error", concept=concept, detail=str(exc)
                )
                raise SystemExit(f"KB API not reachable ({exc}).")

    live_pages: dict[str, str] = {}
    updates = [e for e in plan if e["action"] == "update"]
    if updates or config.STORY_OVERVIEW_PAGE:
        titles = [e["wiki_title"] for e in updates]
        # The overview page is not a concept, so it is not in the plan — but it
        # is an existing hand-written page and needs the same merge.
        if config.STORY_OVERVIEW_PAGE:
            titles.append(config.STORY_OVERVIEW_PAGE)
        try:
            live_pages = WikiClient().read_many(titles)
        except requests.RequestException as exc:
            runlog.log(
                _STAGE, "wiki_unreachable", level="warn",
                detail=str(exc), remaining=len(titles),
                echo=f"wiki unreachable ({exc}) — diffs against empty pages.",
            )

    events: list[dict] = []
    outputs = generate_proposals(plan, bodies, live_pages, events)
    outputs |= build_overview_proposal(plan, live_pages, events)

    # Pages whose KI region a human edited: their text is knowledge the KB does
    # not have yet. Write it out for a human to move into
    # ../pnp-knowledge/knowledge/sources/ via the usual ingest branch — this
    # service never writes into the memory repo itself. The page stays as-is
    # until the KB has absorbed the text.
    harvested = 0
    for e in events:
        text = e.pop("harvest", None)
        if not text:
            continue
        harvested += 1
        config.HARVEST_DIR.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w.-]+", "_", e["concept"]) + ".md"
        path = config.HARVEST_DIR / name
        path.write_text(
            f"<!-- Aus dem KI-Abschnitt von \"{e['title']}\" im Wiki, von Hand "
            f"bearbeitet. Nach knowledge/sources/ übernehmen, damit die "
            f"Wissensbasis es aufnimmt. -->\n\n{text}\n",
            encoding="utf-8",
        )
        e["level"] = "warn"
        e["harvest_file"] = str(path)
        e["harvest_sha8"] = runlog.sha8(text)

    n_warn = sum(1 for e in events if e.get("level") == "warn")
    for e in events:
        runlog.log(_STAGE, e.pop("event"), level=e.pop("level", "info"), **e)
    if harvested:
        print(
            f"\n{harvested} Seite(n) mit von Hand bearbeitetem KI-Abschnitt — "
            f"Text liegt in {config.HARVEST_DIR}. Diese Seiten bleiben "
            "unverändert, bis die Wissensbasis den Text aufgenommen hat."
        )

    config.PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (config.PROPOSALS_DIR / name).write_text(content, encoding="utf-8")
        # proposals/ is flat, so the run log is the record of which run wrote
        # which file.
        runlog.log(
            _STAGE, "write", name=name, bytes=len(content), sha8=runlog.sha8(content)
        )

    pruned = prune_proposals(set(outputs))

    n_new = sum(1 for e in plan if e["action"] == "create")
    runlog.log(
        _STAGE, "stage_end", files=len(outputs), pages=len(plan), new=n_new,
        warnings=n_warn, pruned=pruned,
        echo=(
            f"Wrote {len(outputs)} file(s) to {config.PROPOSALS_DIR} "
            f"({len(plan)} pages, {n_new} proposed new — see NEW_PAGES.md, "
            f"{pruned} stale file(s) pruned, "
            f"{n_warn} warning(s) in {config.LOGS_DIR / (runlog.run_id() + '.jsonl')}). "
            "Review before running 04_upload.py."
        ),
    )


if __name__ == "__main__":
    main()
