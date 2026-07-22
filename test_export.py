"""Offline tests: md2wiki conversion + stage-2 planning + stage-3 proposals.

No network, no wiki, no KB API — pure-function coverage of the pipeline core.
Run: python -m pytest
"""

from __future__ import annotations

import importlib
import json

from md2wiki import LinkResolver, markdown_to_wikitext

extract = importlib.import_module("02_extract")
generate = importlib.import_module("03_generate")
upload = importlib.import_module("04_upload")


_RESOLVER = LinkResolver(
    {
        "npcs/hexe": "Die Hexe",
        "characters/lindo_laut": "Lindo Laut",
        "locations/hartwacht": "Hartwacht",
    }
)


# --- md2wiki -----------------------------------------------------------------


def test_headings_shift_one_level():
    assert markdown_to_wikitext("# Überblick", _RESOLVER) == "== Überblick ==\n"
    assert (
        markdown_to_wikitext("## Beziehungen", _RESOLVER)
        == "=== Beziehungen ===\n"
    )


def test_concept_links_resolve_to_wiki_links():
    md = "Sie trifft [Lindo](/characters/lindo_laut.md) in [Hartwacht](../locations/hartwacht.md)."
    wiki = markdown_to_wikitext(md, _RESOLVER)
    assert "[[Lindo Laut|Lindo]]" in wiki
    assert "[[Hartwacht]]" in wiki  # label == title -> plain wiki link


def test_unknown_concept_link_degrades_to_label():
    wiki = markdown_to_wikitext("Der [Gott](/gods/vasul.md) erscheint.", _RESOLVER)
    assert wiki == "Der Gott erscheint.\n"


def test_external_links_use_wiki_syntax():
    wiki = markdown_to_wikitext(
        "[Session](https://youtu.be/x) ansehen.", _RESOLVER
    )
    assert "[https://youtu.be/x Session]" in wiki


def test_bold_bullets_and_category():
    md = "*   **Musik:** Er spielt [Violine](geige.md).\n"
    wiki = markdown_to_wikitext(md, _RESOLVER, category="Charaktere")
    assert "* '''Musik:''' Er spielt Violine." in wiki
    assert wiki.rstrip().endswith("[[Kategorie:Charaktere]]")


# --- stage 2: planning -------------------------------------------------------


_CONCEPTS = [
    {
        "concept": "npcs/hexe",
        "id": "NPC_HEXE",
        "type": "NPC",
        "title": "Die Hexe",
        "aliases": ["Sumpfhexe"],
    },
    {
        "concept": "characters/lindo_laut",
        "id": "CHAR_LINDO_LAUT",
        "type": "Character",
        "title": "Lindo Laut",
        "aliases": [],
    },
]


def test_plan_marks_update_on_title_or_alias_hit():
    plan = extract.plan_entities(_CONCEPTS, ["Sumpfhexe", "Andere Seite"])
    by_concept = {e["concept"]: e["action"] for e in plan}
    assert by_concept == {
        "npcs/hexe": "update",  # via alias
        "characters/lindo_laut": "create",
    }


def test_plan_skips_duplicate_titles():
    dupe = dict(_CONCEPTS[0], concept="npcs/hexe_kopie")
    plan = extract.plan_entities([*_CONCEPTS, dupe], [])
    assert sum(1 for e in plan if e["title"] == "Die Hexe") == 1


# --- stage 3: proposals ------------------------------------------------------


def test_generate_proposals_writes_wikitext_diff_and_new_pages():
    plan = extract.plan_entities(_CONCEPTS, ["Die Hexe"])
    bodies = {
        "npcs/hexe": "# Überblick\n\nDie Hexe lebt in [Hartwacht](/locations/hartwacht.md).",
        "characters/lindo_laut": "# Überblick\n\nBarde.",
    }
    live = {"Die Hexe": "== Überblick ==\n\nDie Hexe lebt im Sumpf.\n"}
    outputs = generate.generate_proposals(plan, bodies, live)

    assert "Die Hexe.wikitext" in outputs
    assert "[[Kategorie:NPCs]]" in outputs["Die Hexe.wikitext"]
    # Link target has no wiki page in this plan -> plain label.
    assert "Hartwacht" in outputs["Die Hexe.wikitext"]
    assert "[[Hartwacht" not in outputs["Die Hexe.wikitext"]

    assert "Die Hexe.diff" in outputs
    assert "-" in outputs["Die Hexe.diff"] and "Sumpf" in outputs["Die Hexe.diff"]

    assert "Lindo Laut.wikitext" in outputs
    assert "Lindo Laut.diff" not in outputs
    assert "NEW_PAGES.md" in outputs
    assert "Lindo Laut" in outputs["NEW_PAGES.md"]


# --- stage 4: upload gate ----------------------------------------------------


def test_upload_only_targets_update_pages(tmp_path, monkeypatch):
    """The agent must never create pages: only 'update' plan entries upload."""

    cache = tmp_path / "wiki_cache"
    cache.mkdir()
    (cache / "entities.json").write_text(
        json.dumps(
            [
                {"wiki_title": "Die Hexe", "action": "update"},
                {"wiki_title": "Lindo Laut", "action": "create"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(upload.config, "WIKI_CACHE_DIR", cache)
    assert upload._update_titles() == {"Die Hexe"}


def test_upload_titles_none_without_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(upload.config, "WIKI_CACHE_DIR", tmp_path / "missing")
    assert upload._update_titles() is None
