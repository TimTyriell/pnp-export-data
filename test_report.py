"""Offline tests: stage 5 reports the pipeline's last run, not its own.

Run: python -m pytest
"""

from __future__ import annotations

import importlib
import json
import os

import pytest

report = importlib.import_module("05_report")


def _write_log(directory, name, records, mtime, truncated=False):
    path = directory / f"{name}.jsonl"
    lines = [json.dumps(r) for r in records]
    text = "\n".join(lines) + "\n"
    if truncated:
        text += '{"ts": "2026-08-09T16:5'  # a killed run leaves a half line
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(report.config, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(report.config, "WIKI_CACHE_DIR", tmp_path)
    return tmp_path


def test_last_pipeline_counts_skips_the_report_run(logs):
    _write_log(logs, "run-03", [
        {"ts": "2026-08-09T16:00:00Z", "stage": "03_generate", "event": "stage_end",
         "level": "info", "files": 4, "warnings": 2},
    ], mtime=1_000)
    _write_log(logs, "run-04", [
        {"ts": "2026-08-09T16:30:00Z", "stage": "04_upload", "event": "stage_end",
         "level": "info", "uploaded": 5, "skipped_new": 1, "failed": 0, "dry_run": False},
    ], mtime=2_000)
    _write_log(logs, "run-05", [
        {"ts": "2026-08-09T16:51:47Z", "stage": "05_report", "event": "stage_end",
         "level": "info", "pages": 9},
    ], mtime=3_000)  # newest: the report's own run

    counts = report._last_pipeline_counts()

    assert counts["upload"]["uploaded"] == 5
    assert counts["upload"]["run_id"] == "run-04"
    assert counts["generate"]["warnings"] == 2


def test_truncated_log_line_does_not_crash(logs):
    _write_log(logs, "run-04", [
        {"ts": "2026-08-09T16:30:00Z", "stage": "04_upload", "event": "stage_end",
         "level": "info", "uploaded": 3, "skipped_new": 0, "failed": 0},
    ], mtime=2_000, truncated=True)

    assert report._last_pipeline_counts()["upload"]["uploaded"] == 3
    assert report.latest_anomalies() == {}


def test_collect_reads_pages_in_one_batch(logs, monkeypatch):
    monkeypatch.setattr(report.config, "WIKI_USERNAME", "bot@pnp")

    class FakeClient:
        def __init__(self):
            self.batches = []

        def user_contributions(self, user):
            return [
                {"title": t, "timestamp": "2026-08-09T16:00:00Z",
                 "comment": "pnp-fandom-service update"}
                for t in ("Alpha", "Beta", "Gamma")
            ]

        def last_revisions(self, titles):
            return {}

        def read_many(self, titles):
            self.batches.append(list(titles))
            # "Gamma" is missing from the wiki: absent, not an error.
            return {t: "text" for t in titles if t != "Gamma"}

        def read(self, title):
            raise AssertionError("collect must not read page by page")

    client = FakeClient()
    rows = report.collect(client)

    assert len(client.batches) == 1
    assert sorted(client.batches[0]) == ["Alpha", "Beta", "Gamma"]
    by_title = {r["title"]: r for r in rows}
    assert by_title["Alpha"]["bytes"] == len("text")
    assert by_title["Gamma"]["bytes"] == 0
    assert by_title["Gamma"]["ki_state"] == "absent"
