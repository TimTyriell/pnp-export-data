"""Stage 5 — Report: a shareable overview of every KI-edited wiki page.

Answers "which pages did the KI write, when was each last touched, and which
ones need a human?" in a form the team can read without access to this repo:

  reports/ki_pages.md    table + a "needs attention" list, paste-ready
  reports/ki_pages.csv   same rows + an empty "Zuständig" column for assigning
  reports/ki_pages.html  self-contained page: same overview, texts readable
                         inline, searchable — the one to hand to the group
  reports/ki_pages.json  machine copy, includes each page's text

Which pages count as KI-edited comes from the wiki itself (the bot account's
contributions, filtered by the pipeline's edit summary), not from local run
logs — the wiki knows about every run, this machine only about its own. Run
logs are still read for the latest anomalies per page.

Read-only: this stage never edits the wiki.

Run:  python 05_report.py
"""

from __future__ import annotations

import csv
import glob
import json
import re
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import config
import report_html
import runlog
from wiki_client import WikiClient
from wikimerge import KI_LABEL, ki_region_state

_STAGE = "05_report"

_STATE_LABEL = {
    "clean": "unverändert",
    "edited": "vom Team überarbeitet",
    "absent": "kein KI-Abschnitt",
}


def page_url(title: str) -> str:
    base = config.WIKI_API_URL.rsplit("/api.php", 1)[0]
    return f"{base}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"


def create_page_url(title: str) -> str:
    """Direct link to the wiki's editor for a page that doesn't exist yet.

    MediaWiki opens the "create new page" editor for any non-existing title
    when ?action=edit is appended — no API call needed, just a link a human
    clicks to type the page by hand (pages are never created by the agent,
    see CLAUDE.md).
    """
    return f"{page_url(title)}?action=edit"


def ki_edits(client: WikiClient) -> dict[str, str]:
    """``title -> timestamp`` of the most recent KI edit, newest first."""

    user = config.WIKI_USERNAME.split("@", 1)[0]  # bot password -> owning user
    latest: dict[str, str] = {}
    for edit in client.user_contributions(user):
        # The summary separates the bot's edits from human edits of the same
        # account (a bot password logs in as the owning user).
        if edit.get("comment") != config.EDIT_SUMMARY:
            continue
        ts = edit["timestamp"]
        if ts > latest.get(edit["title"], ""):
            latest[edit["title"]] = ts
    return latest


def _records(path: str) -> list[dict]:
    """Every parsable record of one run log.

    A killed run leaves a half-written last line; skip it rather than let one
    bad line crash the whole report.
    """

    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def run_logs_newest_first() -> list[str]:
    """Run logs by mtime, newest first — a custom PNP_RUN_ID ("agent-foo")
    makes the filename useless for ordering."""

    return sorted(
        glob.glob(str(config.LOGS_DIR / "*.jsonl")),
        key=lambda p: Path(p).stat().st_mtime,
        reverse=True,
    )


def latest_anomalies() -> dict[str, list[str]]:
    """``title -> [kind]`` from the most recent generate run.

    Deliberately the *newest* generate log, even when it is clean: falling
    back to an older log that still has anomalies would report defects the
    last run already resolved.
    """

    for path in run_logs_newest_first():
        found: dict[str, list[str]] = {}
        is_generate_run = False
        for rec in _records(path):
            if rec.get("stage") == "03_generate":
                is_generate_run = True
            if rec.get("event") == "anomaly" and rec.get("title"):
                found.setdefault(rec["title"], []).append(rec["kind"])
        if is_generate_run:
            return found
    return {}


_HARVEST_TITLE_RE = re.compile(r'Aus dem KI-Abschnitt von "(.+?)" im Wiki')


def harvest_pending() -> list[dict]:
    """Rescued hand-written text still waiting to reach the KB.

    The live ``edited`` state only lasts until the next sync rewrites the
    region, but the obligation outlives it — these files are the task.
    """

    if not config.HARVEST_DIR.is_dir():
        return []
    out = []
    for path in sorted(config.HARVEST_DIR.glob("*.md")):
        head = path.read_text(encoding="utf-8")[:300]
        match = _HARVEST_TITLE_RE.search(head)
        out.append(
            {
                "title": match.group(1) if match else path.stem,
                "file": path.name,
                "saved": datetime.fromtimestamp(
                    path.stat().st_mtime, UTC
                ).strftime("%Y-%m-%d"),
            }
        )
    return out


def entity_types() -> dict[str, str]:
    path = config.WIKI_CACHE_DIR / "entities.json"
    if not path.exists():
        return {}
    plan = json.loads(path.read_text(encoding="utf-8"))
    return {e["wiki_title"]: e.get("type") or "" for e in plan}


def collect(client: WikiClient) -> list[dict]:
    edits = ki_edits(client)
    types = entity_types()
    anomalies = latest_anomalies()
    revisions = client.last_revisions(sorted(edits))
    wikitext = client.read_many(sorted(edits))

    rows: list[dict] = []
    for title, ki_ts in edits.items():
        text = wikitext.get(title, "")  # absent from the result = page missing
        state, region = ki_region_state(text)
        rev = revisions.get(title, {})
        rows.append(
            {
                "title": title,
                "url": page_url(title),
                "type": types.get(title, ""),
                "ki_last_edit": ki_ts,
                "last_edit": rev.get("timestamp", ""),
                "last_editor": rev.get("user", ""),
                "ki_state": state,
                "bytes": len(text),
                "ki_bytes": len(region or ""),
                "anomalies": anomalies.get(title, []),
                "ki_text": region or "",
                # Pages synced before the region existed have no region text,
                # and the team still needs to be able to read those.
                "page_text": text,
            }
        )
    rows.sort(key=lambda r: r["last_edit"], reverse=True)
    return rows


def _date(ts: str) -> str:
    return ts[:10] if ts else "—"


def render_markdown(rows: list[dict]) -> str:
    out = [
        "# KI-gepflegte Wiki-Seiten",
        "",
        f"{len(rows)} Seiten, zuletzt von der KI bearbeitet. Erzeugt aus den "
        "Bot-Beiträgen des Wikis (`05_report.py`) — Stand siehe Datum je Zeile.",
        "",
        "Jede Seite hat zwei Teile, getrennt durch die Zeile "
        f"*„{KI_LABEL}“*. Oben steht die Handarbeit des Teams, unten der Teil "
        "aus der Wissensbasis, der bei jedem Abgleich neu geschrieben wird. "
        "Steht bei einer Seite *vom Team überarbeitet*, hat jemand unter der "
        "Trennlinie geschrieben: dieser Text ist Wissen, das die Wissensbasis "
        "noch nicht hat. Die Seite bleibt dann unangetastet, bis er dort "
        "angekommen ist — überschrieben wird er nie.",
        "",
        "| Seite | Typ | Letzte KI-Bearbeitung | Letzte Bearbeitung | Von | KI-Abschnitt | Hinweise |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        notes = ", ".join(r["anomalies"]) or "—"
        out.append(
            f"| [{r['title']}]({r['url']}) | {r['type'] or '—'} | "
            f"{_date(r['ki_last_edit'])} | {_date(r['last_edit'])} | "
            f"{r['last_editor'] or '—'} | {_STATE_LABEL[r['ki_state']]} | {notes} |"
        )

    # Only what a person should act on. "kein KI-Abschnitt" is a pipeline
    # state, not a task — those pages get their region on the next sync, so
    # they are counted below instead of padding the list to every page.
    harvest = [r for r in rows if r["ki_state"] == "edited"]
    flagged = [r for r in rows if r["anomalies"]]
    absent = [r for r in rows if r["ki_state"] == "absent"]
    saved = {h["title"]: h for h in harvest_pending()}

    out += ["", "## Zu erledigen", ""]
    if harvest:
        out += [
            "**Team-Text in die Wissensbasis übernehmen** — jemand hat unter "
            "der Trennlinie geschrieben. Die Seite wird bis dahin nicht mehr "
            "angefasst, der Text also auch nicht aktualisiert:",
            "",
        ]
        for r in harvest:
            file = saved.get(r["title"])
            where = f" · gesichert in `harvest/{file['file']}`" if file else ""
            out.append(
                f"- [{r['title']}]({r['url']}) — {r['last_editor']}, "
                f"{_date(r['last_edit'])}{where}"
            )
        out.append("")
    if flagged:
        out += [
            "**Gegenlesen** — die letzte Generierung war bei diesen Seiten "
            "auffällig (meist doppelter Text):",
            "",
        ]
        out += [f"- [{r['title']}]({r['url']}) — {', '.join(r['anomalies'])}" for r in flagged]
        out.append("")
    if not harvest and not flagged:
        out += ["Nichts offen.", ""]
    if absent:
        out += [
            f"*{len(absent)} Seite(n) haben noch keinen markierten KI-Abschnitt "
            "(vor dessen Einführung hochgeladen). Der nächste Abgleich holt das "
            "nach — kein Handlungsbedarf.*",
            "",
        ]
    return "\n".join(out)


def write_reports(rows: list[dict]) -> list[str]:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    md = config.REPORTS_DIR / "ki_pages.md"
    md.write_text(render_markdown(rows), encoding="utf-8")
    written.append(str(md))

    csv_path = config.REPORTS_DIR / "ki_pages.csv"
    fields = [
        "title", "url", "type", "ki_last_edit", "last_edit", "last_editor",
        "ki_state", "bytes", "ki_bytes", "anomalies", "Zuständig",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        # utf-8-sig: Excel reads umlauts wrong without the BOM.
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    **{k: r[k] for k in fields if k in r},
                    "anomalies": " ".join(r["anomalies"]),
                    "Zuständig": "",
                }
            )
    written.append(str(csv_path))

    json_path = config.REPORTS_DIR / "ki_pages.json"
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    written.append(str(json_path))

    html_path = config.REPORTS_DIR / "ki_pages.html"
    html_path.write_text(report_html.render(rows), encoding="utf-8")
    written.append(str(html_path))
    return written


def _stage_summary(path: str, records: list[dict], end: dict) -> dict:
    """The fields of one ``stage_end`` event, plus where its run log sits."""

    meta = ("ts", "run_id", "stage", "event", "level")
    stamps = sorted(r["ts"] for r in records if "ts" in r)
    return {
        **{k: v for k, v in end.items() if k not in meta},
        "run_id": Path(path).stem,
        "ts": end.get("ts"),
        "started_at": stamps[0] if stamps else None,
        "ended_at": stamps[-1] if stamps else None,
    }


def _last_pipeline_counts() -> dict | None:
    """Summaries of the newest 04_upload and 03_generate runs, or None.

    Stage 5 writes its own run log, so logs that contain only 05_report
    records are skipped: the report must describe the run that uploaded, not
    the run that read the result back.
    """

    found: dict[str, tuple[str, list[dict], dict]] = {}
    for path in run_logs_newest_first():
        records = _records(path)
        if not records or all(r.get("stage") == _STAGE for r in records):
            continue
        for stage in ("04_upload", "03_generate"):
            if stage in found:
                continue
            end = next(
                (r for r in records if r.get("stage") == stage and r.get("event") == "stage_end"),
                None,
            )
            if end is not None:
                found[stage] = (path, records, end)
        if len(found) == 2:
            break
    if not found:
        return None

    # ok/error come from the runs found above, not from stage 5's own log.
    failures = [
        r for _, records, _ in found.values() for r in records if r.get("level") == "error"
    ]
    upload = found.get("04_upload")
    generate = found.get("03_generate")
    return {
        "upload": _stage_summary(*upload) if upload else None,
        "generate": _stage_summary(*generate) if generate else None,
        "ok": not failures,
        "error": str(failures[0].get("detail") or failures[0].get("event")) if failures else None,
    }


def _last_run(pipeline: dict | None) -> dict | None:
    """The status envelope's ``last_run``, from the pipeline's last upload."""

    if pipeline is None:
        return None
    up = pipeline["upload"] or {}
    return {
        "run_id": up.get("run_id"),
        "started_at": up.get("started_at"),
        "ended_at": up.get("ended_at"),
        "ok": pipeline["ok"],
        "error": pipeline["error"],
        "counts": {
            "uploaded": up.get("uploaded", 0),
            "skipped_new": up.get("skipped_new", 0),
            "failed": up.get("failed", 0),
            "dry_run": up.get("dry_run"),
        },
        # Additive: the generate run's summary, so the dashboard can show warnings.
        "generate": pipeline["generate"],
    }


def _planned_stubs() -> list[str]:
    """Planned pages (entities.json, action: create) not yet live on the wiki."""

    entities_path = config.WIKI_CACHE_DIR / "entities.json"
    index_path = config.WIKI_CACHE_DIR / "page_index.json"
    if not entities_path.exists() or not index_path.exists():
        return []
    plan = json.loads(entities_path.read_text(encoding="utf-8"))
    live = set(json.loads(index_path.read_text(encoding="utf-8")))
    return sorted({e["wiki_title"] for e in plan if e.get("action") == "create" and e["wiki_title"] not in live})


def build_actions(rows: list[dict]) -> list[dict]:
    actions = []
    for path in sorted(config.HARVEST_DIR.glob("*.md")) if config.HARVEST_DIR.is_dir() else []:
        actions.append({"kind": "harvest", "label": "Team-Text muss in KB übernommen werden", "ref": path.name})
    for title in _planned_stubs():
        actions.append({
            "kind": "stub",
            "label": "Seite noch nicht angelegt",
            "ref": title,
            "url": create_page_url(title),
        })
    for r in rows:
        if r["ki_state"] == "edited":
            actions.append({"kind": "edited", "label": "KI-Abschnitt vom Team überarbeitet", "ref": r["title"]})
        for anomaly in r["anomalies"]:
            actions.append({"kind": "anomaly", "label": anomaly, "ref": r["title"]})
    return actions


def write_status(rows: list[dict]) -> dict:
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    status = {
        "schema": 1,
        "service": "pnp-export-data",
        "generated_at": now,
        "last_run": _last_run(_last_pipeline_counts()),
        # Without the page bodies — the dashboard lists pages, it does not
        # render them, and they are ~300 KB.
        "items": [{k: v for k, v in r.items() if k != "page_text"} for r in rows],
        "actions": build_actions(rows),
    }
    config.STATUS_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATUS_DIR / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    history_line = {
        "ts": now,
        "pages_ki": len(rows),
        "pages_clean": sum(1 for r in rows if r["ki_state"] == "clean"),
        "pages_edited": sum(1 for r in rows if r["ki_state"] == "edited"),
        "uploaded": (status["last_run"] or {}).get("counts", {}).get("uploaded", 0),
        "failed": (status["last_run"] or {}).get("counts", {}).get("failed", 0),
    }
    with open(config.STATUS_DIR / "history.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(history_line, ensure_ascii=False) + "\n")

    return status


def main() -> None:
    runlog.log(_STAGE, "stage_start")
    rows = collect(WikiClient())
    written = write_reports(rows)
    status = write_status(rows)
    edited = sum(1 for r in rows if r["ki_state"] == "edited")
    runlog.log(
        _STAGE, "stage_end", pages=len(rows), edited_by_team=edited,
        files=written, actions=len(status["actions"]),
        echo=(
            f"{len(rows)} KI-Seiten erfasst ({edited} vom Team überarbeitet). "
            + " · ".join(written)
        ),
    )


if __name__ == "__main__":
    main()
