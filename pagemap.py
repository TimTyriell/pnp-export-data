"""The page map: which KB concepts become which wiki page.

The knowledge base is a graph and wants one node per entity — a thousand of
them, down to a single undead army and a single soul fragment. The wiki is a
reference work and wants readable articles. **Entities are therefore not
pages**, and this module is the only place that maps between the two. The map
lives here, in the output repo: it is presentation, not knowledge, so the
bundle never learns about it (ADR-001 — ``knowledge/`` is the system of
record, and a merge that exists only for readability has no business in it).

Only *exceptions* are listed. Every concept the file does not name stays a page
of its own exactly as before, and the relevance gate (``config.MIN_SESSIONS``)
already keeps the long tail off the wiki — this file is for the concepts that
clear the gate and still should not get their own article.

``wiki_pages.toml`` (TOML, so the reasoning can live in comments next to the
rule that needs it):

    exclude = ["events/beschwoerung_von_slix"]    # nur in der Session-Zusammenfassung

    [pages."Belorus der Stille"]                  # 1:N, ein Leitknoten
    lead = ["npcs/belorus"]
    sub  = ["factions/belorus_untotenarmee"]

    [pages."Die fünf Seelen Vhar'Zuls"]           # 1:N, gleichwertig
    lead = ["deities/kollmereth", "deities/thyrex"]

``lead`` is a main information node: it owns the page's identity — id, type,
category, aliases, and the concept a harvested KI region is attributed to. A
``sub`` is a side node that only ever appears as a section on that page. Two or
more leads mean an equal-weight merge with no dominant concept, and the page
carries a name of its own.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

EMPTY: dict = {"exclude": set(), "pages": {}}


class PageMapError(Exception):
    """A map that cannot be applied — the run must stop rather than guess."""


def _title_of(concept: dict) -> str:
    return (concept.get("title") or concept["concept"].rsplit("/", 1)[-1]).strip()


# --- loading -----------------------------------------------------------------


def load(path: Path) -> dict:
    """Parse and validate ``wiki_pages.toml``. Missing file = no exceptions."""

    if not Path(path).is_file():
        return {"exclude": set(), "pages": {}}
    with Path(path).open("rb") as fh:
        raw = tomllib.load(fh)  # TOMLDecodeError propagates: a broken map stops the run

    exclude = {str(c).strip() for c in raw.get("exclude") or []}
    pages: dict[str, dict] = {}
    owner: dict[str, str] = {}
    for title, spec in (raw.get("pages") or {}).items():
        lead = [str(c).strip() for c in spec.get("lead") or []]
        sub = [str(c).strip() for c in spec.get("sub") or []]
        if not lead:
            raise PageMapError(f'Seite "{title}": mindestens ein lead noetig.')
        for cid in lead + sub:
            if cid in owner:
                raise PageMapError(
                    f'"{cid}" steht in zwei Seiten: "{owner[cid]}" und "{title}".'
                )
            if cid in exclude:
                raise PageMapError(
                    f'"{cid}" ist zugleich in exclude und Mitglied von "{title}".'
                )
            owner[cid] = title
        pages[title] = {
            "lead": lead,
            "sub": sub,
            "aliases": [str(a) for a in spec.get("aliases") or []],
        }
    return {"exclude": exclude, "pages": pages}


# --- applying ----------------------------------------------------------------


def members_of(entry: dict) -> list[dict]:
    """The members of a plan entry — one lead (itself) for an unmapped 1:1."""

    return entry.get("members") or [
        {"concept": entry["concept"], "role": "lead", "title": entry["title"]}
    ]


def group(concepts: list[dict], pagemap: dict, events: list[dict] | None = None) -> list[dict]:
    """Fold the KB concept list into page units.

    A unit looks like a concept (so the planner downstream needs no special
    case) plus ``members``. Concepts the map does not mention pass through
    untouched.
    """

    by_id = {c["concept"]: c for c in concepts}
    consumed: set[str] = set()
    units: list[dict] = []

    for title, spec in pagemap["pages"].items():
        members: list[dict] = []
        missing: list[str] = []
        for role in ("lead", "sub"):
            for cid in spec[role]:
                concept = by_id.get(cid)
                if concept is None:
                    missing.append(cid)
                    continue
                members.append(
                    {"concept": cid, "role": role, "title": _title_of(concept)}
                )
        if missing and events is not None:
            events.append(
                {
                    "event": "pagemap_missing_concept",
                    "level": "warn",
                    "page": title,
                    "concepts": missing,
                    "note": "nicht in der KB — Tippfehler oder Konzept umbenannt",
                }
            )
        leads = [m for m in members if m["role"] == "lead"]
        if not leads:
            # Without a lead the page has no identity. Leaving its subs
            # unconsumed puts them back on the 1:1 path, i.e. exactly the
            # behaviour from before the map — never a silently dropped page.
            if events is not None:
                events.append(
                    {
                        "event": "pagemap_page_dropped",
                        "level": "warn",
                        "page": title,
                        "note": "kein lead-Konzept vorhanden — Seite uebersprungen",
                    }
                )
            continue

        primary = by_id[leads[0]["concept"]]
        consumed.update(m["concept"] for m in members)
        aliases = list(spec["aliases"])
        if len(leads) == 1:
            # A single lead still *is* its page, so it keeps matching live
            # pages by its own aliases — adding a sub must not change whether
            # the page is a create or an update. An equal-weight merge is a new
            # article, so it only answers to names the map gives it.
            aliases += [str(a) for a in primary.get("aliases") or []]
        units.append(
            {
                "concept": primary["concept"],
                "id": primary.get("id"),
                "type": primary.get("type"),
                "title": title,
                "aliases": aliases,
                # ponytail: gate on the most relevant member, not on the union
                # of their sessions — a side node must never push a thin page
                # over the gate, and this needs no extra data from the API.
                "sessions": max(
                    (by_id[m["concept"]].get("sessions", 0) for m in members),
                    default=0,
                ),
                "members": members,
            }
        )

    for concept in concepts:
        cid = concept["concept"]
        if cid in pagemap["exclude"]:
            if events is not None:
                events.append(
                    {
                        "event": "skip",
                        "concept": cid,
                        "title": _title_of(concept),
                        "reason": "pagemap_exclude",
                    }
                )
            continue
        if cid in consumed:
            continue
        units.append(
            dict(
                concept,
                members=[
                    {"concept": cid, "role": "lead", "title": _title_of(concept)}
                ],
            )
        )
    return units


# --- composing ---------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BELEGE_RE = re.compile(r"^#{1,6}\s*Belege\s*$", re.IGNORECASE)


def _strip_belege(body: str) -> str:
    """Drop the KB's trailing ``# Belege`` citation list.

    The wiki cites inline instead: md2wiki turns each ``[P-08]``/``[[P-08]]``
    marker in the text into a link to that episode's own wiki page, so the
    KB's numbered source list has no reader-facing role on the wiki. It stays
    in the bundle untouched — this only concerns what gets exported.
    """

    lines = body.splitlines()
    for i, line in enumerate(lines):
        if _BELEGE_RE.match(line.strip()):
            return "\n".join(lines[:i]).rstrip()
    return body.rstrip()


def _promote_headings(text: str) -> str:
    """``## Überblick`` -> ``# Überblick`` (level 1 stays level 1).

    Only for the sole lead of a composed page: its sections have to sit at the
    same level as the other members' *titles*, because that level is what the
    merge treats as a section. Without this the lead's whole article would
    collapse into the page's intro blob under one ``Übersicht`` heading.
    """

    out: list[str] = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) > 1:
            out.append(f"{m.group(1)[1:]} {m.group(2)}")
        else:
            out.append(line)
    return "\n".join(out)


def compose_body(members: list[dict], bodies: dict[str, str]) -> str | None:
    """Merge the members' KB bodies into one page body. None if none is known.

    Every member's ``# Belege`` citation list is dropped (see
    ``_strip_belege``) — the wiki cites inline instead, via md2wiki resolving
    each ``[P-08]``-style marker in the text to that episode's own page.

    A page with a single lead and nothing else — the 1:1 default, which is all
    but a handful of pages — is otherwise passed through unchanged, so the map
    cannot change a page it says nothing about.

    Everything else becomes **one markdown level per member**: each member gets
    a ``# Titel`` heading and keeps its own sections nested below it, so the
    page reads as one article with sub-entries rather than as several articles
    appended to each other. A sole lead has no heading of its own — it *is* the
    page — so its sections are promoted to that same level instead. The merge
    must be told about this (``merge_wikitext(..., structured=True)``), or it
    flattens the nesting straight back out.
    """

    present = [(m, bodies[m["concept"]]) for m in members if bodies.get(m["concept"])]
    if not present:
        return None
    if len(present) == 1 and present[0][0]["role"] == "lead":
        return _strip_belege(present[0][1]) + "\n"

    leads = [m for m, _ in present if m["role"] == "lead"]
    sole_lead = leads[0]["concept"] if len(leads) == 1 else None

    parts: list[str] = []
    for member, body in present:
        text = _strip_belege(body)
        if member["concept"] == sole_lead:
            text = _promote_headings(text)
        else:
            text = f"# {member['title']}\n\n{text}"
        parts.append(text.strip())

    return "\n\n".join(p for p in parts if p) + "\n"
