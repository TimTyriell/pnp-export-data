"""Tests for the additive section-merge (never deletes hand-authored content)."""

from __future__ import annotations

from wikimerge import merge_wikitext

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
