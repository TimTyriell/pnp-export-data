"""Additive section-merge of KB Wikitext into a hand-authored wiki page.

The live wiki pages are hand-curated (infoboxes, images, prose, categories).
A full replace would destroy that, so updates merge instead:

  * The live page is kept **verbatim** — lead/infobox, every section, every
    category. Nothing human-written is ever deleted.
  * From the KB proposal, only sections whose heading is *not already on the
    live page* are appended (plus the citation section, ``Belege``). The KB
    intro becomes an ``Übersicht`` section if the page has none.
  * Categories are unioned (live order first, then KB extras).

Heading matching is fuzzy on text only (case/whitespace-insensitive), so a
human "Persönlichkeit" and a KB "Persönlichkeit" won't double up — but
genuinely different headings both survive, and the reviewer trims any
semantic overlap. The ``.diff`` a reviewer sees is therefore additions-only.
"""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_CATEGORY_RE = re.compile(r"^\[\[\s*Kategorie\s*:.*?\]\]\s*$", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


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
    return _split_sections("\n".join(out))


def merge_wikitext(live: str, kb_wikitext: str, title: str) -> str:
    live_body, live_cats = _strip_categories(live)
    kb_body, kb_cats = _strip_categories(kb_wikitext)

    live_lead, live_sections = _split_sections(live_body)
    kb_lead, kb_sections = _flatten_kb(kb_body, title)

    live_headings = {_norm(h) for h, _ in live_sections}

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
    for heading, body in appended:
        block = f"== {heading} =="
        if body:
            block += f"\n\n{body}"
        parts.append(block)

    live_cat_norms = {_norm(c) for c in live_cats}
    cats = live_cats + [c for c in kb_cats if _norm(c) not in live_cat_norms]

    text = "\n\n".join(p for p in parts if p).strip() + "\n"
    if cats:
        text += "\n" + "\n".join(cats) + "\n"
    return text
