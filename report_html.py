"""Renders the KI-page overview as one self-contained HTML file.

Written by 05_report.py next to the Markdown and CSV. Everything is inlined
(no fonts, scripts or images from the network) so the file can be sent around,
opened from disk, or published as a link and still work.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from wikimerge import KI_LABEL

_TEMPLATE = """<title>KI-gepflegte Wiki-Seiten — Der Splitter des Ewigen</title>
<style>
  /* Light is the base palette; the two blocks below only re-declare tokens, so
     an un-stamped document (viewer on "system") still resolves a full set. */
  :root {
    --ground: #f6f6f9;
    --surface: #ffffff;
    --surface-2: #f0f0f5;
    --ink: #16161d;
    --muted: #5c5c6c;
    --line: #e2e2eb;
    --accent: #4b3fa8;
    --accent-soft: #ebe8fa;
    --warn: #8a5300;
    --warn-soft: #fbf0dd;
    --ok: #1c6b58;
    --ok-soft: #e3f2ec;
    --shadow: 0 1px 2px rgba(22, 22, 29, .06), 0 8px 24px rgba(22, 22, 29, .05);
    --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    --mono: ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --ground: #0f0f16;
      --surface: #18181f;
      --surface-2: #1f1f28;
      --ink: #e9e9f1;
      --muted: #9494a6;
      --line: #292933;
      --accent: #a395ff;
      --accent-soft: #232038;
      --warn: #e3a75b;
      --warn-soft: #2e2517;
      --ok: #56c7a5;
      --ok-soft: #14261f;
      --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 8px 24px rgba(0, 0, 0, .3);
    }
  }
  :root[data-theme="dark"] {
    --ground: #0f0f16;
    --surface: #18181f;
    --surface-2: #1f1f28;
    --ink: #e9e9f1;
    --muted: #9494a6;
    --line: #292933;
    --accent: #a395ff;
    --accent-soft: #232038;
    --warn: #e3a75b;
    --warn-soft: #2e2517;
    --ok: #56c7a5;
    --ok-soft: #14261f;
    --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 8px 24px rgba(0, 0, 0, .3);
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--ground);
    color: var(--ink);
    font-family: var(--sans);
    font-size: 16px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  .wrap {
    max-width: 1100px;
    margin: 0 auto;
    padding: 40px 24px 96px;
    display: flex;
    flex-direction: column;
    gap: 40px;
  }
  a { color: var(--accent); }

  .eyebrow {
    font-size: 12px;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
  }
  h1 {
    margin: 6px 0 0;
    font-size: clamp(28px, 4vw, 40px);
    line-height: 1.1;
    letter-spacing: -.02em;
    text-wrap: balance;
  }
  .lede { margin: 12px 0 0; max-width: 62ch; color: var(--muted); }

  .counts { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
  .count {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 12px 18px;
    min-width: 132px;
    box-shadow: var(--shadow);
  }
  .count b {
    display: block;
    font-size: 26px;
    font-variant-numeric: tabular-nums;
    letter-spacing: -.02em;
  }
  .count span { font-size: 13px; color: var(--muted); }
  .count.is-warn b { color: var(--warn); }
  .count.is-ok b { color: var(--ok); }

  section > h2 {
    margin: 0 0 4px;
    font-size: 19px;
    letter-spacing: -.01em;
  }
  section > p.hint { margin: 0 0 16px; color: var(--muted); max-width: 62ch; }

  .tasks { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .task-card {
    background: var(--surface);
    border: 1px solid var(--line);
    border-left: 3px solid var(--accent);
    border-radius: 10px;
    padding: 18px 20px;
    box-shadow: var(--shadow);
  }
  .task-card.is-harvest { border-left-color: var(--warn); }
  .task-card h3 { margin: 0 0 4px; font-size: 15px; }
  .task-card p { margin: 0 0 12px; font-size: 14px; color: var(--muted); }
  .task-card ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
  .task-card li { font-size: 14px; }
  .task-card .who { color: var(--muted); font-family: var(--mono); font-size: 12px; }

  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .controls input[type="search"] {
    flex: 1 1 240px;
    min-width: 200px;
    padding: 9px 12px;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 14px;
  }
  .chip {
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--muted);
    border-radius: 999px;
    padding: 7px 14px;
    font: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .chip[aria-pressed="true"] {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--accent);
    font-weight: 600;
  }
  .chip:focus-visible, summary:focus-visible, input:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .rows { display: flex; flex-direction: column; gap: 8px; }
  .row {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .row[hidden] { display: none; }
  .row > summary {
    list-style: none;
    cursor: pointer;
    padding: 14px 18px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 4px 16px;
    align-items: center;
  }
  .row > summary::-webkit-details-marker { display: none; }
  .row > summary:hover { background: var(--surface-2); }
  .row .name { font-weight: 600; letter-spacing: -.01em; }
  .row .meta {
    grid-column: 1 / -1;
    display: flex;
    flex-wrap: wrap;
    gap: 6px 14px;
    font-size: 13px;
    color: var(--muted);
  }
  .row .meta .date { font-family: var(--mono); font-variant-numeric: tabular-nums; }

  .state {
    font-size: 12px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 999px;
    white-space: nowrap;
  }
  .state.clean { background: var(--ok-soft); color: var(--ok); }
  .state.edited { background: var(--warn-soft); color: var(--warn); }
  .state.absent { background: var(--surface-2); color: var(--muted); }
  .flag {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--warn);
    border: 1px solid var(--warn);
    border-radius: 4px;
    padding: 1px 6px;
  }

  .body { padding: 4px 18px 22px; border-top: 1px solid var(--line); }
  .body .source { font-size: 13px; color: var(--muted); margin: 14px 0; }
  .prose {
    font-family: var(--serif);
    font-size: 17px;
    line-height: 1.65;
    max-width: 66ch;
  }
  .prose h4 {
    font-family: var(--sans);
    font-size: 12px;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 26px 0 6px;
  }
  .prose p { margin: 0 0 12px; }
  .prose ul { margin: 0 0 12px; padding-left: 22px; }
  .prose hr { border: 0; border-top: 1px solid var(--line); margin: 22px 0 16px; }
  .prose small { font-family: var(--sans); font-size: 13px; color: var(--muted); }
  .empty { color: var(--muted); font-size: 14px; }

  footer { color: var(--muted); font-size: 13px; border-top: 1px solid var(--line); padding-top: 16px; }
  @media (max-width: 560px) {
    .row > summary { grid-template-columns: 1fr; }
  }
</style>

<div class="wrap">
  <header>
    <div class="eyebrow">Splitter des Ewigen · Wiki-Pflege</div>
    <h1>KI-gepflegte Seiten</h1>
    <p class="lede">
      Jede Seite hat zwei Teile, getrennt durch die Zeile
      <strong>„__KI_LABEL__“</strong>: oben die Handarbeit des Teams, unten der
      Teil aus der Wissensbasis, der bei jedem Abgleich neu erzeugt wird. Was
      ihr unter der Trennlinie schreibt, bleibt stehen und blockiert die Seite,
      bis es in der Wissensbasis gelandet ist. Aufklappen zeigt den Text, ohne
      ins Wiki zu wechseln.
    </p>
    <div class="counts">
      <div class="count"><b>__N_TOTAL__</b><span>Seiten insgesamt</span></div>
      <div class="count is-warn"><b>__N_EDITED__</b><span>Team-Text zu übernehmen</span></div>
      <div class="count is-warn"><b>__N_FLAGGED__</b><span>zum Gegenlesen</span></div>
      <div class="count is-ok"><b>__N_CLEAN__</b><span>unverändert</span></div>
    </div>
  </header>

  <section>
    <h2>Zu erledigen</h2>
    <p class="hint">Alles andere läuft automatisch weiter.</p>
    <div class="tasks">__TASKS__</div>
  </section>

  <section>
    <h2>Alle Seiten</h2>
    <p class="hint">Sortiert nach letzter Bearbeitung. Zeile anklicken zum Lesen.</p>
    <div class="controls">
      <input type="search" id="q" placeholder="Seite suchen …" aria-label="Seite suchen">
      <button class="chip" data-filter="all" aria-pressed="true">Alle</button>
      <button class="chip" data-filter="edited" aria-pressed="false">Team-Text</button>
      <button class="chip" data-filter="flagged" aria-pressed="false">Gegenlesen</button>
      <button class="chip" data-filter="clean" aria-pressed="false">Unverändert</button>
    </div>
    <div class="rows" id="rows">__ROWS__</div>
    <p class="empty" id="noresult" hidden>Keine Seite passt zur Suche.</p>
  </section>

  <footer>
    Stand __GENERATED__ · erzeugt von <code>05_report.py</code> aus den
    Bot-Beiträgen des Wikis. Neu erzeugen: <code>python 05_report.py</code>.
  </footer>
</div>

<script>
  const rows = Array.from(document.querySelectorAll(".row"));
  const q = document.getElementById("q");
  const noresult = document.getElementById("noresult");
  const chips = Array.from(document.querySelectorAll(".chip"));
  let filter = "all";

  function apply() {
    const term = q.value.trim().toLowerCase();
    let shown = 0;
    for (const row of rows) {
      const matchesTerm = !term || row.dataset.title.toLowerCase().includes(term);
      const matchesFilter =
        filter === "all" ||
        (filter === "flagged" && row.dataset.flagged === "1") ||
        row.dataset.state === filter;
      const visible = matchesTerm && matchesFilter;
      row.hidden = !visible;
      if (visible) shown++;
    }
    noresult.hidden = shown > 0;
  }

  q.addEventListener("input", apply);
  for (const chip of chips) {
    chip.addEventListener("click", () => {
      filter = chip.dataset.filter;
      for (const c of chips) c.setAttribute("aria-pressed", String(c === chip));
      apply();
    });
  }
</script>
"""


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _inline(text: str) -> str:
    """Wikitext inline markup -> HTML. Links lose their target on purpose: the
    page they point at is in this same list, and a half-working link is worse
    than plain text."""

    import re

    out = _esc(text)
    out = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", out)
    out = re.sub(r"\[\[([^\]]*)\]\]", r"\1", out)
    out = re.sub(r"'''(.+?)'''", r"<strong>\1</strong>", out)
    out = re.sub(r"''(.+?)''", r"<em>\1</em>", out)
    # The KI label carries its hint in <small>; keep that one tag working.
    out = re.sub(r"&lt;small&gt;(.*?)&lt;/small&gt;", r"<small>\1</small>", out)
    return out


def wikitext_to_html(text: str) -> str:
    """Headings, bullets and paragraphs — enough to read prose comfortably."""

    import re

    html: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if paragraph:
            html.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if bullets:
            items = "".join(f"<li>{_inline(b)}</li>" for b in bullets)
            html.append(f"<ul>{items}</ul>")
            bullets.clear()

    for line in text.splitlines():
        stripped = line.strip()
        heading = re.match(r"^(={2,6})\s*(.*?)\s*\1$", stripped)
        if heading:
            flush()
            html.append(f"<h4>{_inline(heading.group(2))}</h4>")
        elif stripped.startswith("----"):
            flush()
            html.append("<hr>")
        elif stripped.startswith("*"):
            if paragraph:
                flush()
            bullets.append(stripped.lstrip("*").strip())
        elif not stripped:
            flush()
        elif stripped.startswith(("<!--", "[[Kategorie:", "{{", "|", "}}")):
            continue  # markers, infoboxes and categories are not prose
        else:
            if bullets:
                flush()
            paragraph.append(stripped)
    flush()
    return "\n".join(html)


_STATE_LABEL = {
    "clean": "unverändert",
    "edited": "vom Team überarbeitet",
    "absent": "kein KI-Abschnitt",
}


def _row(r: dict) -> str:
    flagged = "1" if r["anomalies"] else "0"
    flags = "".join(f'<span class="flag">{_esc(a)}</span>' for a in r["anomalies"])
    text = r.get("ki_text") or r.get("page_text") or ""
    source = (
        "KI-Abschnitt der Seite"
        if r.get("ki_text")
        else "Ganze Seite — diese Seite hat noch keinen markierten KI-Abschnitt"
    )
    body = wikitext_to_html(text) or '<p class="empty">Kein Text abrufbar.</p>'
    return f"""<details class="row" data-title="{_esc(r['title'])}" data-state="{r['ki_state']}" data-flagged="{flagged}">
  <summary>
    <span class="name">{_esc(r['title'])}</span>
    <span class="state {r['ki_state']}">{_STATE_LABEL[r['ki_state']]}</span>
    <span class="meta">
      <span>{_esc(r['type'] or 'ohne Typ')}</span>
      <span class="date">zuletzt bearbeitet {r['last_edit'][:10]}</span>
      <span>von {_esc(r['last_editor'] or '—')}</span>
      {flags}
    </span>
  </summary>
  <div class="body">
    <p class="source">{source} · <a href="{_esc(r['url'])}" target="_blank" rel="noopener">im Wiki öffnen</a></p>
    <div class="prose">{body}</div>
  </div>
</details>"""


def _tasks(rows: list[dict]) -> str:
    harvest = [r for r in rows if r["ki_state"] == "edited"]
    flagged = [r for r in rows if r["anomalies"]]
    cards: list[str] = []
    if harvest:
        items = "".join(
            f'<li>{_esc(r["title"])} <span class="who">{_esc(r["last_editor"])}, '
            f'{r["last_edit"][:10]}</span></li>'
            for r in harvest
        )
        cards.append(
            '<div class="task-card is-harvest"><h3>Team-Text in die Wissensbasis</h3>'
            "<p>Jemand hat unter der Trennlinie geschrieben. Der Text bleibt "
            "stehen und die Seite wird nicht mehr aktualisiert, bis er "
            "aufgenommen ist.</p>"
            f"<ul>{items}</ul></div>"
        )
    if flagged:
        items = "".join(
            f'<li>{_esc(r["title"])} <span class="who">{_esc(", ".join(r["anomalies"]))}'
            "</span></li>"
            for r in flagged
        )
        cards.append(
            '<div class="task-card"><h3>Gegenlesen</h3>'
            "<p>Bei der letzten Erzeugung auffällig — meist steht Text doppelt "
            "auf der Seite.</p>"
            f"<ul>{items}</ul></div>"
        )
    if not cards:
        cards.append(
            '<div class="task-card"><h3>Nichts offen</h3>'
            "<p>Alle KI-Abschnitte sind unverändert und unauffällig.</p></div>"
        )
    return "\n".join(cards)


def render(rows: list[dict]) -> str:
    generated = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    replacements = {
        "__N_TOTAL__": str(len(rows)),
        "__N_EDITED__": str(sum(1 for r in rows if r["ki_state"] == "edited")),
        "__N_FLAGGED__": str(sum(1 for r in rows if r["anomalies"])),
        "__N_CLEAN__": str(sum(1 for r in rows if r["ki_state"] == "clean")),
        "__TASKS__": _tasks(rows),
        "__ROWS__": "\n".join(_row(r) for r in rows),
        "__GENERATED__": generated,
        "__KI_LABEL__": _esc(KI_LABEL.rstrip(":")),
    }
    html = _TEMPLATE
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html


if __name__ == "__main__":  # smoke check against the last report
    import config

    data = json.loads(
        (config.REPORTS_DIR / "ki_pages.json").read_text(encoding="utf-8")
    )
    import re

    out = render(data)
    # Underscores are all over the wiki URLs, so look for the token shape only.
    leftover = re.findall(r"__[A-Z][A-Z_]+__", out)
    assert not leftover, f"unreplaced placeholder: {leftover}"
    assert out.count('class="row"') == len(data)
    print(f"ok — {len(out)} bytes, {len(data)} rows")
