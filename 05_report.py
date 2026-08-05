"""Stage 5 — Report: a shareable overview of every KI-edited wiki page.

Answers "which pages did the KI write, when was each last touched, and which
ones need a human?" in a form the team can read without access to this repo:

  reports/ki_pages.md    table + a "needs attention" list, paste-ready
  reports/ki_pages.csv   same rows + an empty "Zuständig" column for assigning
  reports/ki_pages.json  machine copy, includes each page's KI text

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
import urllib.parse

import config
import runlog
from wiki_client import WikiClient
from wikimerge import ki_region_state

_STAGE = "05_report"

# Every edit this pipeline makes carries this summary (see 04_upload.py), which
# is what separates the bot's edits from the human edits of the same account —
# a bot password logs in as the owning user, not as a separate one.
EDIT_SUMMARY = "pnp-fandom-service update"

_STATE_LABEL = {
    "clean": "unverändert",
    "edited": "vom Team überarbeitet",
    "absent": "kein KI-Abschnitt",
}


def page_url(title: str) -> str:
    base = config.WIKI_API_URL.rsplit("/api.php", 1)[0]
    return f"{base}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"


def ki_edits(client: WikiClient) -> dict[str, str]:
    """``title -> timestamp`` of the most recent KI edit, newest first."""

    user = config.WIKI_USERNAME.split("@", 1)[0]  # bot password -> owning user
    latest: dict[str, str] = {}
    for edit in client.user_contributions(user):
        if edit.get("comment") != EDIT_SUMMARY:
            continue
        ts = edit["timestamp"]
        if ts > latest.get(edit["title"], ""):
            latest[edit["title"]] = ts
    return latest


def latest_anomalies() -> dict[str, list[str]]:
    """``title -> [kind]`` from the newest run log that has any."""

    for path in sorted(glob.glob(str(config.LOGS_DIR / "*.jsonl")), reverse=True):
        found: dict[str, list[str]] = {}
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                if rec.get("event") == "anomaly" and rec.get("title"):
                    found.setdefault(rec["title"], []).append(rec["kind"])
        if found:
            return found
    return {}


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

    rows: list[dict] = []
    for title, ki_ts in edits.items():
        page = client.read(title)
        text = page.wikitext if page else ""
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
            }
        )
    rows.sort(key=lambda r: r["last_edit"], reverse=True)
    return rows


def _date(ts: str) -> str:
    return ts[:10] if ts else "—"


def render_markdown(rows: list[dict]) -> str:
    attention = [r for r in rows if r["ki_state"] != "clean" or r["anomalies"]]
    out = [
        "# KI-gepflegte Wiki-Seiten",
        "",
        f"{len(rows)} Seiten, zuletzt von der KI bearbeitet. Erzeugt aus den "
        "Bot-Beiträgen des Wikis (`05_report.py`) — Stand siehe Datum je Zeile.",
        "",
        "Der **KI-Abschnitt** einer Seite wird bei jedem Abgleich aus der "
        "Wissensbasis neu geschrieben. Steht dort *vom Team überarbeitet*, hat "
        "jemand von Hand hineingeschrieben: dieser Text ist Wissen, das die "
        "Wissensbasis noch nicht hat, und wird beim nächsten Abgleich zuerst "
        "übernommen und nicht überschrieben.",
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

    out += ["", "## Zu erledigen", ""]
    if attention:
        for r in attention:
            reasons = []
            if r["ki_state"] == "edited":
                reasons.append(
                    "Handschriftliche Ergänzung im KI-Abschnitt → in die "
                    "Wissensbasis übernehmen"
                )
            elif r["ki_state"] == "absent":
                reasons.append("kein KI-Abschnitt → beim nächsten Abgleich prüfen")
            if r["anomalies"]:
                reasons.append("Auffälligkeit: " + ", ".join(r["anomalies"]))
            out.append(f"- **[{r['title']}]({r['url']})** — {'; '.join(reasons)}")
    else:
        out.append("Nichts offen — alle KI-Abschnitte unverändert.")
    out.append("")
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
    return written


def main() -> None:
    runlog.log(_STAGE, "stage_start")
    rows = collect(WikiClient())
    written = write_reports(rows)
    edited = sum(1 for r in rows if r["ki_state"] == "edited")
    runlog.log(
        _STAGE, "stage_end", pages=len(rows), edited_by_team=edited,
        files=written,
        echo=(
            f"{len(rows)} KI-Seiten erfasst ({edited} vom Team überarbeitet). "
            + " · ".join(written)
        ),
    )


if __name__ == "__main__":
    main()
