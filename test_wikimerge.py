"""Tests for the additive section-merge (never deletes hand-authored content)."""

from __future__ import annotations

from wikimerge import (
    _HEADING_RE,
    ki_region_state,
    merge_wikitext,
    merge_wikitext_verbose,
)

_LIVE = """{{Infobox Charakter
|Name = Lindo Laut
|Spezies = Faerie
}}

'''Lindo Laut''' ist ein [[Faerie]]-Barde.

== Persönlichkeit ==

Charismatisch und verspielt.

== Ausrüstung ==

Eine magische Violine.

[[Kategorie:Charaktere]]
[[Kategorie:Faerie]]
"""

_KB = """== Lindo Laut ==

Ein geflügelter Feen-Barde, gespielt von Tim.

=== Persönlichkeit ===

KB-Text zur Persönlichkeit.

=== Besondere Gegenstände ===

* Amulett des Heiligen Duran

== Belege ==

1. Session 2025-03-26 @ 00:09:18

[[Kategorie:Charaktere]]
"""


def test_merge_preserves_all_live_content():
    merged = merge_wikitext(_LIVE, _KB, "Lindo Laut")
    # Infobox, both hand sections, both hand categories survive.
    assert "{{Infobox Charakter" in merged
    assert "Eine magische Violine." in merged
    assert "Charismatisch und verspielt." in merged
    assert "[[Kategorie:Faerie]]" in merged


def test_merge_appends_only_new_kb_sections():
    merged = merge_wikitext(_LIVE, _KB, "Lindo Laut")
    # New KB sections are added...
    assert "== Besondere Gegenstände ==" in merged
    assert "Amulett des Heiligen Duran" in merged
    assert "== Belege ==" in merged
    # ...but a heading the human already has is NOT duplicated.
    assert merged.count("== Persönlichkeit ==") == 1
    # The human's version wins (KB body for that heading is dropped).
    assert "KB-Text zur Persönlichkeit." not in merged


def test_merge_drops_kb_title_heading():
    merged = merge_wikitext(_LIVE, _KB, "Lindo Laut")
    # KB's leading "== Lindo Laut ==" (page-name echo) is not re-added...
    assert "== Lindo Laut ==" not in merged
    # ...but its intro text survives as an Übersicht section.
    assert "== Übersicht ==" in merged
    assert "geflügelter Feen-Barde" in merged


def test_merge_unions_categories_without_duplicates():
    merged = merge_wikitext(_LIVE, _KB, "Lindo Laut")
    assert merged.count("[[Kategorie:Charaktere]]") == 1


def test_merge_is_purely_additive_line_count():
    merged = merge_wikitext(_LIVE, _KB, "Lindo Laut")
    # Every non-blank line of the live page is still present.
    for line in _LIVE.splitlines():
        if line.strip():
            assert line in merged


# A page filled from a `create` proposal has level-3 sections, because md2wiki
# renders the KB's "## Foo" as "=== Foo ===". Matching only level-2 headings
# made such a page look section-less and re-appended the whole article on the
# next sync — the "kompletter Artikel steht zweimal drin" defect.
_LIVE_LEVEL3 = """'''Lindo Laut''' ist ein Barde.

=== Persönlichkeit ===

Charismatisch und verspielt.

=== Besondere Gegenstände ===

* Amulett des Heiligen Duran

[[Kategorie:Charaktere]]
"""


def _heading_names(text: str) -> list[str]:
    """Heading texts in order, any level. Substring checks are unsafe here —
    '== Foo ==' is a substring of '=== Foo ==='."""

    return [
        m.group(2).strip()
        for m in (_HEADING_RE.match(line) for line in text.splitlines())
        if m
    ]


def test_merge_matches_headings_regardless_of_level():
    merged = merge_wikitext(_LIVE_LEVEL3, _KB, "Lindo Laut")
    names = _heading_names(merged)
    # Each heading the live page already carried appears exactly once — no
    # level-2 twin appended beside the level-3 original.
    assert names.count("Persönlichkeit") == 1
    assert names.count("Besondere Gegenstände") == 1
    assert len(names) == len(set(names)), f"duplicate headings: {names}"
    # Genuinely new sections still land, and the KB intro still becomes one.
    assert "Belege" in names
    assert "Übersicht" in names
    # Nothing hand-written was dropped.
    assert "Charismatisch und verspielt." in merged
    assert "Amulett des Heiligen Duran" in merged
    # The live page's own body for a matched heading is the one that survives.
    assert "KB-Text zur Persönlichkeit." not in merged


# --- the KI-maintained region ------------------------------------------------
#
# The region is rebuilt from the KB on every sync, so later sessions actually
# reach the page. Humans may edit inside it; the checksum in the marker is what
# distinguishes "ours, safe to rewrite" from "a human contributed knowledge we
# have not absorbed yet".

_HAND = """'''Nox''' ist der Gildenmeister.

== Verschiedenes ==

Mag Kaffee.

[[Kategorie:NPCs]]
"""

_KB_V1 = """== Nox ==

Nox ist Gildenmeister.

=== Wichtige Merkmale ===

Nox lebt.

== Belege ==

1. Session 2025-01-01
"""

_KB_V2 = _KB_V1.replace("Nox lebt.", "Nox ist gestorben.")


def test_first_sync_wraps_kb_content_and_keeps_hand_text():
    merged = merge_wikitext(_HAND, _KB_V1, "Nox")
    assert ki_region_state(merged)[0] == "clean"
    assert "Mag Kaffee." in merged
    assert "== Verschiedenes ==" in merged


def test_later_kb_findings_reach_an_already_synced_page():
    """The write-once defect: an appended section could never be revised."""

    first = merge_wikitext(_HAND, _KB_V1, "Nox")
    second = merge_wikitext(first, _KB_V2, "Nox")
    assert "Nox ist gestorben." in second
    assert "Nox lebt." not in second
    assert "Mag Kaffee." in second  # hand-written text still untouched


def test_sync_is_idempotent():
    once = merge_wikitext(_HAND, _KB_V2, "Nox")
    twice = merge_wikitext(once, _KB_V2, "Nox")
    assert once == twice


def test_human_edit_inside_the_region_is_never_overwritten():
    synced = merge_wikitext(_HAND, _KB_V2, "Nox")
    edited = synced.replace(
        "Nox ist gestorben.", "Nox ist gestorben. Begraben in Ehrenfels."
    )
    assert ki_region_state(edited)[0] == "edited"

    out, decisions = merge_wikitext_verbose(edited, _KB_V1, "Nox")
    assert out == edited  # page untouched, even though the KB says otherwise
    assert decisions["ki_state"] == "edited"
    # ...and the human's text is handed to the caller to harvest into the KB.
    assert "Begraben in Ehrenfels." in decisions["harvest"]
