"""Additive section-merge of KB Wikitext into a hand-authored wiki page.

The live wiki pages are hand-curated (infoboxes, images, prose, categories).
A full replace would destroy that, so updates merge instead:

  * The live page is kept **verbatim** — lead/infobox, every section, every
    category. Nothing human-written is ever deleted.
  * From the KB proposal, only sections whose heading is *not already on the
    live page* are appended (plus the citation section, ``Belege``). The KB
    intro becomes an ``Übersicht`` section if the page has none.
  * Categories are unioned (live order first, then KB extras).

Heading matching is fuzzy on text only (case/whitespace-insensitive) and
**level-insensitive** — a live ``=== Überblick ===`` blocks the KB's
``Überblick`` just as a ``== Überblick ==`` does. That matters because
md2wiki renders the KB's ``## Foo`` one level deeper (``=== Foo ===``), so a
page filled from a `create` proposal carries level-3 sections; matching only
level-2 headings made such a page look section-less and appended the entire
article again. Genuinely different headings still both survive, and the
reviewer trims any semantic overlap. The ``.diff`` a reviewer sees is
therefore additions-only.
"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

import config

_HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_CATEGORY_RE = re.compile(r"^\[\[\s*Kategorie\s*:.*?\]\]\s*$", re.IGNORECASE)

# The KI-maintained region. Humans may edit inside it — the checksum in the
# opening marker is what tells a later sync whether they did: it records the
# text this pipeline last wrote. Content still matching it is ours to replace;
# content that drifted is a human contribution and must reach the KB before
# anything overwrites it (knowledge/sources/, per pnp_okf.context).
KI_START_RE = re.compile(
    r"^<!--\s*KI-Abschnitt\b[^>]*?\bsha=([0-9a-f]{8})\b[^>]*-->\s*$", re.MULTILINE
)
KI_END_RE = re.compile(r"^<!--\s*/KI-Abschnitt\s*-->\s*$", re.MULTILINE)

KI_NOTICE = (
    "Automatisch gepflegt durch KI aus der Wissensbasis. Änderungen hier sind "
    "erlaubt und werden beim nächsten Abgleich in die Wissensbasis übernommen, "
    "bevor der Abschnitt neu geschrieben wird."
)


def sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def render_ki_region(content: str) -> str:
    """Wrap ``content`` in the KI markers, stamping its checksum."""

    body = content.strip()
    return (
        f"<!-- KI-Abschnitt: {KI_NOTICE} sha={sha8(body)} -->\n"
        f"{body}\n"
        f"<!-- /KI-Abschnitt -->"
    )


def split_ki_region(text: str) -> tuple[str, str, str, str] | None:
    """``(before, region_body, declared_sha, after)`` or None if unmarked."""

    start = KI_START_RE.search(text)
    if not start:
        return None
    end = KI_END_RE.search(text, start.end())
    if not end:
        return None
    return (
        text[: start.start()],
        text[start.end() : end.start()].strip(),
        start.group(1),
        text[end.end() :],
    )


def ki_region_state(live: str) -> tuple[str, str | None]:
    """``(state, region_body)`` — ``absent``, ``clean`` or ``edited``.

    ``edited`` means a human changed the region since we wrote it, so its text
    is knowledge we do not have yet and must not overwrite.
    """

    split = split_ki_region(live)
    if split is None:
        return "absent", None
    _, body, declared, _ = split
    return ("clean" if sha8(body) == declared else "edited"), body


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _similarity(a: str, b: str) -> float:
    """0..1 on normalised text. Only ever used to recognise our own drifted
    output, never to decide that two human sections mean the same thing."""

    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _strip_categories(text: str) -> tuple[str, list[str]]:
    body, cats = [], []
    for line in text.splitlines():
        (cats if _CATEGORY_RE.match(line) else body).append(line)
    return "\n".join(body).strip(), cats


def _split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return ``(lead, [(heading, body)])`` splitting on level-2 headings.

    Level-3+ headings stay inside their parent section's body.
    """

    lead: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == 2:
            sections.append((m.group(2).strip(), []))
            current = sections[-1][1]
        elif current is None:
            lead.append(line)
        else:
            current.append(line)
    return (
        "\n".join(lead).strip(),
        [(h, "\n".join(b).strip()) for h, b in sections],
    )


def _flatten_kb(kb_wikitext: str, title: str) -> tuple[str, list[tuple[str, str]]]:
    """Drop the KB title heading and flatten every remaining heading to level 2.

    KB bodies wrap content as ``== Title ==`` > ``=== Sub ===`` … ``== Belege
    ==``. Flattening makes the real content units (subsections + Belege)
    top-level so they can be merged into the live page; the intro before the
    first heading is returned as the lead.

    A parent heading whose whole body was its subsections (e.g. ``Wichtige
    Merkmale``) is left empty by the flattening and is dropped — its children
    survive as siblings, so nothing is lost.
    """

    out: list[str] = []
    title_norm = _norm(title)
    dropped_title = False
    for line in kb_wikitext.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            heading = m.group(2).strip()
            if not dropped_title and _norm(heading) == title_norm:
                dropped_title = True
                continue  # the page name already is this heading
            out.append(f"== {heading} ==")
        else:
            out.append(line)
    lead, sections = _split_sections("\n".join(out))
    return lead, [(h, b) for h, b in sections if b]


def merge_wikitext(live: str, kb_wikitext: str, title: str) -> str:
    return merge_wikitext_verbose(live, kb_wikitext, title)[0]


def merge_wikitext_verbose(
    live: str, kb_wikitext: str, title: str
) -> tuple[str, dict]:
    """As ``merge_wikitext``, plus the decisions taken — for the run log.

    The merge itself is silent by design (pure function, no I/O); the caller
    logs the returned dict. Without it a bad merge is only visible by diffing
    the output file by hand.
    """

    ki_state, region_body = ki_region_state(live)
    if ki_state == "edited":
        # A human wrote into the KI region, so it holds knowledge the KB does
        # not have. Touching the page now would destroy it. Hands off until the
        # text has been harvested into knowledge/sources/ and re-synthesized —
        # then the region is ours to rewrite again.
        return live, {
            "live_bytes": len(live),
            "ki_state": "edited",
            "harvest": region_body,
            "live_headings": [],
            "live_headings_all": [],
            "kb_headings": [],
            "appended": [],
            "skipped": [],
            "out_bytes": len(live),
        }

    # Everything outside the region is human territory and stays verbatim.
    split = split_ki_region(live)
    human_part = (split[0] + split[3]) if split else live

    live_body, live_cats = _strip_categories(human_part)
    kb_body, kb_cats = _strip_categories(kb_wikitext)

    live_lead, live_sections = _split_sections(live_body)
    kb_lead, kb_sections = _flatten_kb(kb_body, title)

    # Recorded before reclaiming, so this stays "the level-2 sections the live
    # page had" — reclaimed ones are reported separately.
    live_section_headings = [h for h, _ in live_sections]

    reclaimed: list[str] = []
    if ki_state == "absent":
        # Legacy page: earlier syncs appended KB sections inline, before the
        # KI region existed. Those are ours and belong inside it — otherwise
        # they count as human text and stay frozen forever. Byte-identity is
        # too strict to find them (the KB has been regenerated since, and
        # citation numbering was corrected by hand), so reclaim on similarity:
        # a section close enough to today's KB text is drifted KI output, a
        # rewritten one is a human's and stays outside, untouched.
        kb_bodies = {_norm(h): b for h, b in kb_sections}
        kept = []
        for heading, body in live_sections:
            same = kb_bodies.get(_norm(heading))
            score = _similarity(body, same) if same is not None else 0.0
            if score >= config.RECLAIM_SIMILARITY:
                reclaimed.append(heading)
            else:
                kept.append((heading, body))
        live_sections = kept

        # A page seeded from a `create` proposal is KI output end to end, and
        # its headings are level 3 — so it has no level-2 section to reclaim
        # one by one and the loop above finds nothing. Judge the whole body
        # instead: close enough to today's KB render means the page *is* the
        # region, and nothing on it is human.
        if not live_sections and live_lead:
            whole_kb = "\n\n".join(
                [kb_lead] + [b for _, b in kb_sections]
            ).strip()
            if _similarity(live_lead, whole_kb) >= config.RECLAIM_SIMILARITY:
                reclaimed.append("(ganze Seite)")
                live_lead = ""

    # Match against EVERY heading on the live page, at any level — not just the
    # level-2 ones _split_sections carves sections from. md2wiki renders the
    # KB's "## Foo" as "=== Foo ===", so a page seeded from a `create` proposal
    # (and any page a human wrote with level-3 sections) has no level-2 heading
    # at all. Comparing only level-2 headings made those pages look
    # section-less, so every KB section counted as new and the whole article
    # was appended a second time on the next sync.
    # Built from what actually stays as human content, not from the original
    # page: a reclaimed section belongs to the KI region now, so its heading
    # must NOT block the KB from putting it there. Scanning live_body instead
    # left the region empty and blanked pages that were reclaimed whole.
    retained = "\n".join(
        [live_lead] + [f"== {h} ==\n{b}" for h, b in live_sections]
    )
    live_headings = {
        _norm(m.group(2))
        for m in (_HEADING_RE.match(line) for line in retained.splitlines())
        if m
    }

    appended: list[tuple[str, str]] = []
    if kb_lead and "übersicht" not in live_headings:
        appended.append(("Übersicht", kb_lead))
    for heading, body in kb_sections:
        if _norm(heading) not in live_headings:
            appended.append((heading, body))

    parts: list[str] = []
    if live_lead:
        parts.append(live_lead)
    for heading, body in live_sections:
        parts.append(f"== {heading} ==\n\n{body}".rstrip())

    # The KI-maintained block is rebuilt from the KB on every sync, so new
    # findings from later sessions actually reach the page — appending only
    # once meant a section could never be revised again.
    region_parts: list[str] = []
    for heading, body in appended:
        block = f"== {heading} =="
        if body:
            block += f"\n\n{body}"
        region_parts.append(block)
    if region_parts:
        parts.append(render_ki_region("\n\n".join(region_parts)))

    live_cat_norms = {_norm(c) for c in live_cats}
    cats = live_cats + [c for c in kb_cats if _norm(c) not in live_cat_norms]

    text = "\n\n".join(p for p in parts if p).strip() + "\n"
    if cats:
        text += "\n" + "\n".join(cats) + "\n"

    appended_headings = [h for h, _ in appended]
    decisions = {
        "live_bytes": len(live),
        "ki_state": ki_state,
        "harvest": None,
        "reclaimed": reclaimed,
        # Structural (level-2 sections) vs. everything matched against; they
        # differ exactly on the pages that used to double up.
        "live_headings": live_section_headings,
        "live_headings_all": sorted(live_headings),
        "kb_headings": [h for h, _ in kb_sections],
        "appended": appended_headings,
        "skipped": [h for h, _ in kb_sections if h not in appended_headings],
        "out_bytes": len(text),
    }
    return text, decisions
