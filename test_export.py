"""Offline tests: md2wiki conversion + page map + stage-2 planning + stage-3.

No network, no wiki, no KB API — pure-function coverage of the pipeline core.
Run: python -m pytest
"""

from __future__ import annotations

import importlib
import json
import re

import pytest

import pagemap
import wikimerge
from md2wiki import LinkResolver, markdown_to_wikitext

extract = importlib.import_module("02_extract")
generate = importlib.import_module("03_generate")
upload = importlib.import_module("04_upload")


_RESOLVER = LinkResolver(
    {
        "npcs/hexe": "Die Hexe",
        "characters/lindo_laut": "Lindo Laut",
        "locations/hartwacht": "Hartwacht",
    },
    episode_titles={"P-08": "Folge P-08 – Zebros erkunden"},
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


def test_citation_marker_resolves_to_episode_link():
    assert (
        markdown_to_wikitext("Belorus [P-08] befiehlt.", _RESOLVER)
        == "Belorus [[Folge P-08 – Zebros erkunden|P-08]] befiehlt.\n"
    )


def test_double_bracket_citation_marker_also_resolves():
    """The KB is not consistent about single vs. double brackets."""

    assert (
        markdown_to_wikitext("Sieg errungen[[P-08]].", _RESOLVER)
        == "Sieg errungen[[Folge P-08 – Zebros erkunden|P-08]].\n"
    )


def test_unknown_episode_citation_degrades_to_bare_label():
    assert markdown_to_wikitext("Erwähnt[P-99].", _RESOLVER) == "ErwähntP-99.\n"


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
        "sessions": 2,  # above config.MIN_SESSIONS, so not dropped by the gate
    },
    {
        "concept": "characters/lindo_laut",
        "id": "CHAR_LINDO_LAUT",
        "type": "Character",
        "title": "Lindo Laut",
        "aliases": [],
        "sessions": 2,
    },
]


def test_plan_marks_update_on_title_or_alias_hit():
    plan = extract.plan_entities(_CONCEPTS, ["Sumpfhexe", "Andere Seite"])
    by_concept = {e["concept"]: e["action"] for e in plan}
    assert by_concept == {
        "npcs/hexe": "update",  # via alias
        "characters/lindo_laut": "create",
    }


def test_alias_match_targets_the_live_page_title():
    """KB title "Die Hexe", live page "Sumpfhexe" -> edit "Sumpfhexe".

    Taking the KB title instead would upload a second page beside the live one
    and orphan the hand-written article the alias just matched.
    """

    plan = extract.plan_entities(_CONCEPTS, ["Sumpfhexe"])
    hexe = next(e for e in plan if e["concept"] == "npcs/hexe")
    assert hexe["action"] == "update"
    assert hexe["title"] == "Die Hexe"  # the KB name stays the KB name
    assert hexe["wiki_title"] == "Sumpfhexe"  # but the edit targets the live page


def test_plan_skips_duplicate_titles():
    dupe = dict(_CONCEPTS[0], concept="npcs/hexe_kopie")
    plan = extract.plan_entities([*_CONCEPTS, dupe], [])
    assert sum(1 for e in plan if e["title"] == "Die Hexe") == 1


# --- stage 3: proposals ------------------------------------------------------


def test_generate_proposals_writes_wikitext_diff_and_new_pages():
    plan = extract.plan_entities(_CONCEPTS, ["Die Hexe"])
    bodies = {
        "npcs/hexe": "# Die Hexe\n\nAlt.\n\n## Herkunft\n\nAus dem Sumpf.",
        "characters/lindo_laut": "# Überblick\n\nBarde in [Hartwacht](/locations/hartwacht.md).",
    }
    live = {"Die Hexe": "== Überblick ==\n\nDie Hexe lebt im Sumpf.\n"}
    outputs = generate.generate_proposals(plan, bodies, live)

    # -- update (Die Hexe) is an additive merge --
    hexe = outputs["Die Hexe.wikitext"]
    assert "Die Hexe lebt im Sumpf." in hexe  # live content preserved
    assert "== Herkunft ==" in hexe  # new KB section appended
    assert "[[Kategorie:NPCs]]" in hexe  # KB category unioned in
    # diff is additions-only: no line removed from the live page.
    removals = [
        l
        for l in outputs["Die Hexe.diff"].splitlines()
        if l.startswith("-") and not l.startswith("---")
    ]
    assert removals == []

    # -- create (Lindo) uses raw KB wikitext: links + no diff --
    lindo = outputs["Lindo Laut.wikitext"]
    assert "[[Kategorie:Charaktere]]" in lindo
    assert "Hartwacht" in lindo and "[[Hartwacht" not in lindo  # no wiki page -> plain
    assert "Lindo Laut.diff" not in outputs
    assert "NEW_PAGES.md" in outputs
    assert "Lindo Laut" in outputs["NEW_PAGES.md"]


def test_generate_proposals_links_inline_citations_and_drops_belege():
    """A [P-08]/[[P-08]] marker in a body links to that episode's own page —
    built from the same plan, so id and link target can never disagree — and
    the KB's Belege list never reaches the wiki at all."""

    plan = [
        {
            "concept": "sessions/2025-05-14",
            "type": "Session",
            "title": "Zebros erkunden",
            "wiki_title": "Folge P-08 – Zebros erkunden",
            "action": "create",
            "members": [
                {"concept": "sessions/2025-05-14", "role": "lead", "title": "Zebros erkunden"}
            ],
            "episode": {"episode": "P-08"},
        },
        {
            "concept": "npcs/hexe",
            "type": "NPC",
            "title": "Die Hexe",
            "wiki_title": "Die Hexe",
            "action": "create",
            "members": [{"concept": "npcs/hexe", "role": "lead", "title": "Die Hexe"}],
        },
    ]
    bodies = {
        "sessions/2025-05-14": "# Überblick\n\nDie Gruppe erreicht Zebros.\n",
        "npcs/hexe": (
            "# Überblick\n\nSie kämpft im Sumpf[P-08].\n\n"
            "# Belege\n\n[P-08] Session 2025-05-14 @ 00:00:00 (https://x)\n"
        ),
    }
    out = generate.generate_proposals(plan, bodies, {})["Die Hexe.wikitext"]
    assert "[[Folge P-08 – Zebros erkunden|P-08]]" in out
    assert "Belege" not in out


# --- page map: loading -------------------------------------------------------


def _write_map(tmp_path, text):
    path = tmp_path / "wiki_pages.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_map_means_no_exceptions(tmp_path):
    assert pagemap.load(tmp_path / "nope.toml") == {"exclude": set(), "pages": {}}


def test_map_rejects_a_concept_owned_by_two_pages(tmp_path):
    path = _write_map(
        tmp_path,
        '[pages."A"]\nlead = ["npcs/x"]\n[pages."B"]\nlead = ["npcs/y"]\nsub = ["npcs/x"]\n',
    )
    with pytest.raises(pagemap.PageMapError, match="zwei Seiten"):
        pagemap.load(path)


def test_map_rejects_page_without_lead(tmp_path):
    path = _write_map(tmp_path, '[pages."A"]\nsub = ["npcs/x"]\n')
    with pytest.raises(pagemap.PageMapError, match="lead"):
        pagemap.load(path)


# --- page map: grouping ------------------------------------------------------


_BELORUS = {
    "concept": "npcs/belorus",
    "id": "NPC_BELORUS",
    "type": "NPC",
    "title": "Belorus der Stille",
    "aliases": ["Belorus"],
    "sessions": 6,
}
_ARMEE = {
    "concept": "factions/belorus_untotenarmee",
    "id": "FACTION_BELORUS_UNTOTENARMEE",
    "type": "Faction",
    "title": "Belorus’ Untotenarmee",
    "aliases": ["Untote Horde"],
    "sessions": 4,
}
_MAP = {
    "exclude": {"events/beschwoerung_von_slix"},
    "pages": {
        "Belorus der Stille": {
            "lead": ["npcs/belorus"],
            "sub": ["factions/belorus_untotenarmee"],
            "aliases": [],
        }
    },
}


def test_group_folds_sub_into_lead_and_leaves_others_alone():
    units = pagemap.group([_BELORUS, _ARMEE, *_CONCEPTS], _MAP)
    by_title = {u["title"]: u for u in units}
    assert "Belorus’ Untotenarmee" not in by_title  # no page of its own
    assert set(by_title) == {"Belorus der Stille", "Die Hexe", "Lindo Laut"}

    page = by_title["Belorus der Stille"]
    assert page["type"] == "NPC" and page["id"] == "NPC_BELORUS"  # lead owns identity
    assert page["aliases"] == ["Belorus"]  # sole lead keeps its own alias matching
    assert [(m["concept"], m["role"]) for m in page["members"]] == [
        ("npcs/belorus", "lead"),
        ("factions/belorus_untotenarmee", "sub"),
    ]
    # 1:1 concepts still carry themselves as their sole member.
    assert by_title["Die Hexe"]["members"] == [
        {"concept": "npcs/hexe", "role": "lead", "title": "Die Hexe"}
    ]


def test_group_drops_excluded_concepts_with_a_reason():
    excluded = {"concept": "events/beschwoerung_von_slix", "title": "Beschwörung", "sessions": 5}
    events = []
    units = pagemap.group([_BELORUS, _ARMEE, excluded], _MAP, events)
    assert [u["title"] for u in units] == ["Belorus der Stille"]
    assert {
        "event": "skip",
        "concept": "events/beschwoerung_von_slix",
        "title": "Beschwörung",
        "reason": "pagemap_exclude",
    } in events


def test_group_without_the_lead_concept_falls_back_to_1to1():
    """A lead missing from the KB must never swallow its subs silently."""

    events = []
    units = pagemap.group([_ARMEE], _MAP, events)
    assert [u["title"] for u in units] == ["Belorus’ Untotenarmee"]
    assert {e["event"] for e in events} == {
        "pagemap_missing_concept",
        "pagemap_page_dropped",
    }


# --- page map: composing -----------------------------------------------------


# Each member's own Belege list — dropped by compose_body, not merged.
_LEAD_BODY = (
    "## Überblick\n\nBelorus [P-08] befehligt sie [P-22].\n\n"
    "## Belege\n\n[P-08] Session A\n[P-22] Session B\n"
)
_SUB_BODY = (
    "## Überblick\n\nDie Armee [P-22] marschiert [P-34].\n\n"
    "## Belege\n\n[P-22] Session B\n[P-34] Session C\n"
)
_MEMBERS = [
    {"concept": "npcs/belorus", "role": "lead", "title": "Belorus der Stille"},
    {"concept": "factions/belorus_untotenarmee", "role": "sub", "title": "Belorus’ Untotenarmee"},
]
_BODIES = {"npcs/belorus": _LEAD_BODY, "factions/belorus_untotenarmee": _SUB_BODY}


def test_compose_passes_a_lone_lead_through_but_drops_belege():
    """The 1:1 default is all but a handful of pages — it must not otherwise
    change. The Belege list is the one exception: the wiki cites inline
    instead (md2wiki resolves each marker to that episode's own page), so the
    KB's citation list has no reader-facing role there."""

    out = pagemap.compose_body(_MEMBERS[:1], _BODIES)
    assert out == "## Überblick\n\nBelorus [P-08] befehligt sie [P-22].\n"
    assert "Belege" not in out


def test_compose_no_body_at_all_is_none():
    assert pagemap.compose_body(_MEMBERS, {}) is None


def test_compose_nests_a_sub_under_its_own_heading():
    out = pagemap.compose_body(_MEMBERS, _BODIES)

    lead_part, sub_part = out.split("# Belorus’ Untotenarmee\n", 1)
    # The sole lead *is* the page: no heading of its own, its sections promoted
    # to the level the members' titles sit at.
    assert "# Überblick\n" in lead_part and "## Überblick\n" not in lead_part
    # The sub is one unit with its own sections nested below it.
    assert "## Überblick\n" in sub_part

    # Both members' Belege lists are dropped entirely, not merged into one.
    assert "Belege" not in out
    assert out.count("[P-22]") == 2  # once per member's text, nothing else
    # Both members' text is untouched — episode labels are already global.
    assert "Belorus [P-08] befehligt sie [P-22]." in out
    assert "Die Armee [P-22] marschiert [P-34]." in out


def test_compose_equal_weight_merge_gives_every_member_a_heading():
    members = [dict(m, role="lead") for m in _MEMBERS]
    out = pagemap.compose_body(members, _BODIES)
    # No member dominates, so none of them is the page — each is a sub-entry
    # with its own sections one level further in.
    assert "# Belorus der Stille\n" in out
    assert "# Belorus’ Untotenarmee\n" in out
    assert out.count("## Überblick") == 2


def test_compose_leaves_numeric_link_labels_alone():
    body = "Siehe [1](/npcs/hexe.md) und [1].\n\n## Belege\n\n[1] Session A\n"
    members = [
        {"concept": "a", "role": "lead", "title": "A"},
        {"concept": "b", "role": "sub", "title": "B"},
    ]
    out = pagemap.compose_body(members, {"a": body, "b": "Nichts.\n"})
    assert "[1](/npcs/hexe.md)" in out


# --- merged pages end to end -------------------------------------------------


def test_merged_page_links_and_sections(tmp_path):
    plan = extract.plan_entities(
        [_BELORUS, _ARMEE, *_CONCEPTS], [], events=[], page_map=_MAP
    )
    bodies = dict(
        _BODIES,
        **{
            "npcs/hexe": "# Die Hexe\n\nSie kennt die [Armee](/factions/belorus_untotenarmee.md).",
            "characters/lindo_laut": "# Überblick\n\nBarde.",
        },
    )
    outputs = generate.generate_proposals(plan, bodies, {})

    assert "Belorus’ Untotenarmee.wikitext" not in outputs
    page = outputs["Belorus der Stille.wikitext"]
    assert "== Belorus’ Untotenarmee ==" in page
    # The sub's own sections sit *inside* it, not beside it.
    assert "=== Überblick ===" in page.split("== Belorus’ Untotenarmee ==", 1)[1]
    assert "[[Kategorie:NPCs]]" in page  # the lead's type gives the category

    # A link to the merged-away concept lands on the page that covers it now.
    assert "[[Belorus der Stille|Armee]]" in outputs["Die Hexe.wikitext"]


def test_merge_keeps_a_composed_pages_nesting():
    """The regression that made a merged page read as glued-together articles.

    The merge flattens every KB heading to level 2 so a single concept's
    subsections become mergeable units. On a composed page that dissolves the
    per-member nesting, leaving one flat run of sections — so it has to be told
    the page is already structured.
    """

    kb = (
        "== Thyrex ==\n\n=== Überblick ===\n\nEiner der Aspekte.\n\n"
        "== Slix ==\n\n=== Überblick ===\n\nDer verborgene Teil.\n"
    )
    flat = wikimerge.merge_wikitext("", kb, "Die fünf Seelen")
    nested = wikimerge.merge_wikitext("", kb, "Die fünf Seelen", structured=True)

    assert "=== Überblick ===" not in flat  # flattened to siblings
    assert flat.count("== Überblick ==") == 2  # …and duplicated
    assert nested.count("=== Überblick ===") == 2  # kept inside their member
    for member in ("== Thyrex ==", "== Slix =="):
        assert member in nested


def test_prune_removes_only_stale_files_of_ours(tmp_path, monkeypatch):
    """Stale .wikitext/.diff/NEW_PAGES.md go; this run's files and anything a
    human dropped in stay."""

    props = tmp_path / "proposals"
    props.mkdir()
    for name in (
        "Die Hexe.wikitext",
        "Die Hexe.diff",
        "Willoch.wikitext",  # stale near-duplicate title from an older run
        "Willoch.diff",
        "NEW_PAGES.md",
        "notizen.md",  # not ours
        "Hartwacht.wikitext.bak",  # not ours either
    ):
        (props / name).write_text("x", encoding="utf-8")
    (props / "unterordner").mkdir()

    monkeypatch.setattr(generate.config, "PROPOSALS_DIR", props)
    monkeypatch.setattr(generate.runlog, "log", lambda *a, **kw: None)

    pruned = generate.prune_proposals({"Die Hexe.wikitext", "Die Hexe.diff"})

    assert pruned == 3  # Willoch x2 + NEW_PAGES.md
    assert sorted(p.name for p in props.iterdir()) == [
        "Die Hexe.diff",
        "Die Hexe.wikitext",
        "Hartwacht.wikitext.bak",
        "notizen.md",
        "unterordner",
    ]


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
    # The overview page is not a concept and never in the plan, but it is an
    # existing page stage 3 merged — it rides the update path too.
    monkeypatch.setattr(upload.config, "STORY_OVERVIEW_PAGE", "Story Abschnitte")
    plan = upload._load_plan()
    assert upload._update_titles(plan) == {"Die Hexe", "Story Abschnitte"}

    monkeypatch.setattr(upload.config, "STORY_OVERVIEW_PAGE", "")
    assert upload._update_titles(plan) == {"Die Hexe"}


def test_upload_titles_none_without_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(upload.config, "WIKI_CACHE_DIR", tmp_path / "missing")
    assert upload._load_plan() is None


def test_upload_recovers_the_title_a_filename_cannot_hold():
    """"Katze (Ajani / Günther)" is a legal wiki title but not a filename.

    Uploading under the sanitised stem stored the page as
    "Katze (Ajani _ Günther)", which the wiki renders with a space — the slash
    is gone and the next run no longer finds its own page.
    """
    title = "Katze (Ajani / Günther)"
    stem = generate.proposal_filename(title)
    assert stem == "Katze (Ajani _ Günther)"
    assert upload._titles_by_stem([{"wiki_title": title}])[stem] == title


def test_upload_skips_pages_with_an_empty_diff(tmp_path, monkeypatch):
    """An empty .diff means merged == live: skip the no-op edit entirely."""

    cache = tmp_path / "wiki_cache"
    cache.mkdir()
    (cache / "entities.json").write_text(
        json.dumps(
            [
                {"wiki_title": "Die Hexe", "action": "update"},
                {"wiki_title": "Lindo Laut", "action": "update"},
                {"wiki_title": "Hartwacht", "action": "update"},
            ]
        ),
        encoding="utf-8",
    )
    props = tmp_path / "proposals"
    props.mkdir()
    (props / "Die Hexe.wikitext").write_text("== Überblick ==\n", encoding="utf-8")
    (props / "Die Hexe.diff").write_text("\n", encoding="utf-8")  # unchanged
    (props / "Lindo Laut.wikitext").write_text("== Überblick ==\n", encoding="utf-8")
    (props / "Lindo Laut.diff").write_text("+neu\n", encoding="utf-8")
    # No .diff at all is not proof of anything — that one still uploads.
    (props / "Hartwacht.wikitext").write_text("== Überblick ==\n", encoding="utf-8")

    monkeypatch.setattr(upload.config, "WIKI_CACHE_DIR", cache)
    monkeypatch.setattr(upload.config, "PROPOSALS_DIR", props)
    monkeypatch.setattr(upload.config, "DRY_RUN", True)
    events: list[dict] = []
    monkeypatch.setattr(
        upload.runlog, "log", lambda stage, event, **kw: events.append({"event": event, **kw})
    )

    upload.main(apply=False)

    assert [e["title"] for e in events if e["event"] == "upload"] == [
        "Hartwacht",
        "Lindo Laut",
    ]
    assert [
        e["title"] for e in events if e["event"] == "skip" and e["reason"] == "unchanged"
    ] == ["Die Hexe"]


# --- wiki client: batched reads ----------------------------------------------


def test_read_many_batches_and_keeps_empty_pages(monkeypatch):
    """Existing-but-empty maps to ""; missing pages are absent, not "" —
    stage 3 distinguishes the two by membership, not truthiness."""

    from wiki_client import WikiClient

    calls: list[list[str]] = []

    def fake_get(**params):
        calls.append(params["titles"].split("|"))
        return {
            "query": {
                "pages": {
                    "1": {
                        "title": "Die Hexe",
                        "revisions": [{"slots": {"main": {"*": "== Text =="}}}],
                    },
                    "2": {"title": "Leer", "revisions": [{"slots": {"main": {}}}]},
                    "3": {"title": "Fehlt", "missing": ""},
                }
            }
        }

    client = WikiClient()
    monkeypatch.setattr(client, "_get", fake_get)
    out = client.read_many(["Die Hexe", "Leer", "Fehlt"])

    assert out == {"Die Hexe": "== Text ==", "Leer": ""}
    assert "Fehlt" not in out
    assert len(calls) == 1  # one round trip, not three

    calls.clear()
    client.read_many([f"S{i}" for i in range(120)])
    assert [len(c) for c in calls] == [50, 50, 20]  # API caps titles= at 50


# --- episode overview table --------------------------------------------------


def _session(episode, season, label, title, ts, desc="", wiki_title=None):
    return {
        "concept": f"sessions/{ts[:10]}",
        "type": "Session",
        "wiki_title": wiki_title or f"Folge {episode} – {title}",
        "action": "create",
        "episode": {
            "episode": episode,
            "episode_title": title,
            "season": season,
            "season_label": label,
            "description": desc,
            "resource": f"https://www.youtube.com/watch?v={episode}",
            "timestamp": ts,
        },
    }


_OVERVIEW_PLAN = [
    _session("P-01", "P", "Prolog", "Session Zero", "2025-03-26T00:00:00Z", "Einleitung"),
    _session("P-02", "P", "Prolog", "Das Goblinlager", "2025-04-01T00:00:00Z"),
    _session("S1-01-A", "1", "Staffel 1", "Aufbruch", "2026-07-29T00:00:00Z"),
    {"concept": "npcs/belorus", "type": "NPC", "wiki_title": "Belorus", "action": "update"},
]


def test_overview_groups_by_season_oldest_first():
    out = generate.render_story_overview(_OVERVIEW_PLAN)
    assert out.index(">Prolog<") < out.index(">Staffel 1<")
    # Inside a season the campaign reads oldest first.
    assert out.index("|P-01") < out.index("|P-02")
    # Non-session concepts are not episodes.
    assert "Belorus" not in out


def test_overview_expands_only_the_newest_season():
    out = generate.render_story_overview(_OVERVIEW_PLAN)
    prolog, staffel = out.index(">Prolog<"), out.index(">Staffel 1<")
    assert "mw-collapsed" in out[prolog:staffel]
    assert "mw-collapsed" not in out[staffel:]


def test_overview_heading_is_the_toggle_for_its_own_block():
    """Whole heading row clicks; toggle and collapsible share the slug."""

    out = generate.render_story_overview(_OVERVIEW_PLAN)
    assert '== <span class="pnp-klapp mw-customtoggle-staffel-1">Staffel 1</span> ==' in out
    assert 'id="mw-customcollapsible-staffel-1"' in out
    # Every toggle has exactly one collapsible answering to it.
    assert re.findall(r"mw-customtoggle-([\w-]+)", out) == re.findall(
        r"mw-customcollapsible-([\w-]+)", out
    ) == ["prolog", "staffel-1"]


def test_overview_links_the_episode_page():
    out = generate.render_story_overview(_OVERVIEW_PLAN)
    assert "|[[Folge P-01 – Session Zero|Session Zero]]" in out
    assert "|Einleitung" in out
    assert "|https://www.youtube.com/watch?v=P-01" in out


def test_overview_falls_back_to_the_id_without_an_abenteuername():
    plan = [_session("S1-02-B", "1", "Staffel 1", "", "2026-07-23T00:00:00Z",
                     wiki_title="Folge S1-02-B")]
    out = generate.render_story_overview(plan)
    assert "|[[Folge S1-02-B]]" in out


def test_overview_empty_without_sessions():
    assert generate.render_story_overview([{"concept": "npcs/x", "type": "NPC"}]) == ""


def test_overview_proposal_creates_the_page_when_it_is_missing(monkeypatch):
    monkeypatch.setattr(generate.config, "STORY_OVERVIEW_PAGE", "Story Abschnitte")
    events: list[dict] = []
    fresh = generate.build_overview_proposal(_OVERVIEW_PLAN, {}, events)
    assert "|P-01" in fresh["Story Abschnitte.wikitext"]
    assert "overview_new" in [e["event"] for e in events]


def test_overview_proposal_merges_into_a_live_page(monkeypatch):
    monkeypatch.setattr(generate.config, "STORY_OVERVIEW_PAGE", "Story Abschnitte")
    events: list[dict] = []
    live = "== Über die Kampagne ==\n\nHandgeschrieben.\n"
    out = generate.build_overview_proposal(
        _OVERVIEW_PLAN, {"Story Abschnitte": live}, events
    )
    merged = out["Story Abschnitte.wikitext"]
    assert "Handgeschrieben." in merged          # human text survives
    assert "KI-Abschnitt" in merged              # table lands in the KI region
    assert "|P-01" in merged
    assert out["Story Abschnitte.diff"].strip()


def test_wiki_safe_title_removes_the_fragment_marker():
    from md2wiki import wiki_safe_title

    # "#" truncates the stored title at the fragment — the bug this exists for.
    assert wiki_safe_title("Folge P-53 – Abisalis #6") == "Folge P-53 – Abisalis Teil 6"
    assert wiki_safe_title("Die Sanddorn Inseln #1") == "Die Sanddorn Inseln Teil 1"
    assert wiki_safe_title("Folge P-01 – Session Zero") == "Folge P-01 – Session Zero"
    assert wiki_safe_title("A [B] {C} |D| <E>") == "A B C D E"


def test_plan_sanitises_the_page_title_but_not_the_kb_name():
    concepts = [
        {"concept": "sessions/2026-05-19", "type": "Session", "title": "Folge P-50 – Abisalis #5",
         "aliases": [], "sessions": 0, "episode": {"episode": "P-50"}},
    ]
    entry = extract.plan_entities(concepts, [])[0]
    assert entry["title"] == "Folge P-50 – Abisalis #5"        # KB name untouched
    assert entry["wiki_title"] == "Folge P-50 – Abisalis Teil 5"


def test_created_pages_are_born_with_their_ki_region():
    """A create proposal must carry the markers, or the next sync guesses.

    Without them the page comes back as ki_state='absent' and the reclaim
    heuristic decides per section what is KB output — which fails as soon as
    the KB regroups its headings, and appends the new body beside the old.
    """
    plan = extract.plan_entities(_CONCEPTS, [])  # nothing live -> both create
    bodies = {
        "npcs/hexe": "# Die Hexe\n\nAlt.",
        "characters/lindo_laut": "# Überblick\n\nBarde.",
    }
    out = generate.generate_proposals(plan, bodies, {})["Die Hexe.wikitext"]

    assert wikimerge.ki_region_state(out)[0] == "clean"
    # The category belongs to the page, not to the region.
    assert out.rstrip().endswith("[[Kategorie:NPCs]]")
    assert "[[Kategorie:NPCs]]" not in wikimerge.split_ki_region(out)[1]


def test_a_sanitised_title_still_recognises_its_live_page():
    """The page is live under the sanitised name — the plan must see that.

    Otherwise every run re-proposes it as a new page and stage 4 skips it.
    """
    concepts = [{"concept": "sessions/2026-05-19", "type": "Session",
                 "title": "Folge P-50 – Abisalis #5", "aliases": [], "sessions": 0}]
    entry = extract.plan_entities(concepts, ["Folge P-50 – Abisalis Teil 5"])[0]
    assert entry["action"] == "update"
    assert entry["wiki_title"] == "Folge P-50 – Abisalis Teil 5"


def test_ki_region_survives_mediawikis_whitespace_reflow():
    """The wiki reflows blank lines around block HTML; that is not an edit.

    Hashing the raw text made every region containing a <div> come back as
    'edited' on the next sync, which freezes the page and harvests our own
    output as if a human had written it.
    """
    page = wikimerge.render_ki_region(
        '<div class="mw-collapsible">\n<div class="mw-collapsible-content">\n{| class="t"\n|}\n</div>\n</div>'
    )
    assert wikimerge.ki_region_state(page)[0] == "clean"

    # What MediaWiki stores: blank lines inserted around the block tags.
    reflowed = page.replace('<div class="mw-collapsible">\n', '<div class="mw-collapsible">\n\n')
    assert reflowed != page
    assert wikimerge.ki_region_state(reflowed)[0] == "clean"

    # A real edit still shows up.
    edited = page.replace("|}", "|}\nvon Hand ergänzt")
    assert wikimerge.ki_region_state(edited)[0] == "edited"


def test_a_citation_resting_on_several_sessions_links_each_one():
    """"[P-24, P-31]" — one statement, two sessions. Both get a link.

    Left unhandled the marker stayed literal bracketed text on the page, which
    reads as a broken link.
    """
    resolver = LinkResolver({}, episode_titles={
        "P-24": "Folge P-24 – Banditen und Flüchtige",
        "P-31": "Folge P-31 – Seelenkälber",
    })
    out = markdown_to_wikitext("Er zog ab [P-24, P-31].", resolver)
    assert "[[Folge P-24 – Banditen und Flüchtige|P-24]], [[Folge P-31 – Seelenkälber|P-31]]" in out
    assert "[P-24" not in out

    # An episode without a page degrades to its bare id, the rest still links.
    out = markdown_to_wikitext("Beleg [P-24, P-99].", resolver)
    assert "[[Folge P-24 – Banditen und Flüchtige|P-24]], P-99" in out


def test_extract_refuses_a_kb_that_serves_an_empty_type(monkeypatch):
    """An empty 200 means the KB is up but not serving — that must abort.

    Continuing shrinks the plan, and the concept->page map is built from the
    plan: every link degrades to plain text and the next upload writes that
    over good pages.
    """
    class _Resp:
        def raise_for_status(self): pass
        def json(self): return []

    class _Session:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **kw): return _Resp()

    monkeypatch.setattr(extract.requests, "Session", _Session)
    with pytest.raises(SystemExit, match="no Character concepts"):
        extract.fetch_concepts()
