"""Offline tests: run log + the stage-3 anomaly detectors.

The detectors only *report* — they never change a merge. What they must catch
is the whole-article-twice case seen in the Aug 5 run: nothing on the live page
matched the KB headings, so every KB section got appended a second time.

Run: python -m pytest
"""

from __future__ import annotations

import importlib
import json

import runlog
from wikimerge import merge_wikitext_verbose

generate = importlib.import_module("03_generate")


# A live page seeded from a create proposal: md2wiki shifted its subsections to
# level 3, so no level-2 heading exists.
_LIVE_LEVEL3 = """'''Alte Götter''' sind die vergessenen Mächte.

=== Überblick ===

Die alten Götter herrschten vor dem Bruch.

=== Anhänger ===

Vereinzelte Kulte.
""" + "Fülltext. " * 60

_LIVE_LEVEL2 = """'''Alte Götter''' sind die vergessenen Mächte.

== Überblick ==

Die alten Götter herrschten vor dem Bruch.

== Anhänger ==

Vereinzelte Kulte.
""" + "Fülltext. " * 60

# A live page with no heading at all — nothing for the merge to match against.
_LIVE_HEADLESS = "'''Alte Götter''' sind die vergessenen Mächte.\n\n" + (
    "Fülltext. " * 80
)

_KB = """== Alte Götter ==

Die vergessenen Mächte der Vorzeit.

=== Überblick ===

Die alten Götter herrschten vor dem Bruch.

=== Anhänger ===

Vereinzelte Kulte.

== Belege ==

1. Session 2025-11-25 @ 00:03:22
"""


def _anomalies(live: str) -> dict[str, dict]:
    merged, decisions = merge_wikitext_verbose(live, _KB, "Alte Götter")
    found = generate.detect_anomalies("Alte Götter", decisions, merged)
    return {a["kind"]: a for a in found}


def test_headless_live_page_is_flagged_as_full_reappend():
    kinds = _anomalies(_LIVE_HEADLESS)
    assert "live_headings_empty" in kinds  # nothing to match against
    assert "full_reappend" in kinds  # so the whole article is appended again


def test_level3_live_page_is_clean():
    """Regression guard: heading matching is level-insensitive.

    A page seeded from a `create` proposal carries level-3 sections; matching
    only level-2 headings is what doubled these articles up.
    """

    assert _anomalies(_LIVE_LEVEL3) == {}


def test_level2_live_page_is_clean():
    assert _anomalies(_LIVE_LEVEL2) == {}


def test_merge_decisions_record_what_was_appended():
    _, decisions = merge_wikitext_verbose(_LIVE_LEVEL2, _KB, "Alte Götter")
    assert decisions["live_headings"] == ["Überblick", "Anhänger"]
    # "Übersicht" is the KB lead, which the live page has no heading for;
    # the two KB sections the live page already covers are skipped.
    assert decisions["appended"] == ["Übersicht", "Belege"]
    assert set(decisions["skipped"]) == {"Überblick", "Anhänger"}


def test_dup_content_flags_identical_files_under_different_titles():
    outputs = {
        "Arena von Willau.wikitext": "== Arena ==\n",
        "Arena von Willauch.wikitext": "== Arena ==\n",
        "Andere.wikitext": "== Andere ==\n",
        "NEW_PAGES.md": "== Arena ==\n",  # not a proposal, must not match
    }
    found = generate.detect_dup_content(outputs)
    assert len(found) == 1
    assert found[0]["files"] == [
        "Arena von Willau.wikitext",
        "Arena von Willauch.wikitext",
    ]


def test_log_writes_one_json_line_per_event(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog.config, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(runlog, "_RUN_ID", "testrun")
    runlog.log("03_generate", "write", name="Slix.wikitext", bytes=42)
    runlog.log("03_generate", "anomaly", level="warn", kind="dup_heading")

    lines = (tmp_path / "testrun.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["run_id"] == "testrun"
    assert first["stage"] == "03_generate"
    assert first["name"] == "Slix.wikitext"
    assert json.loads(lines[1])["level"] == "warn"
