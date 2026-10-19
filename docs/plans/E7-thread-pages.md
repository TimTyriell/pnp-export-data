# E7 — Quests and open threads on the wiki

| | |
|---|---|
| Branch | `feat/thread-pages` |
| Depends on | pnp-knowledge **T6** merged and re-emitted (Thread concepts exist in the API) |
| Size | M |
| Gate | Human decides page policy (step 1) |

## Goal

Show the campaign's threads (quests, mysteries, promises, debts,
deadlines) on the wiki:

- an overview page, **"Offene Fäden"**, with a generated table in its KI
  region, like "Stream Folgen";
- individual pages only for threads that span ≥ `MIN_SESSIONS` sessions.

## Steps

1. **STOP — the human decides** (defaults in bold):
   - Overview page title: **"Offene Fäden"**.
   - Include resolved threads? **Yes, in a collapsed second table**
     ("Erledigt"), using the same collapsible markup as
     `render_story_overview`.
   - Individual thread pages: **only via the normal gate**
     (`MIN_SESSIONS = 2`), category "Handlungsfäden".
   - Team filter: **no** (the wiki is for everyone).
2. `config.py`:
   - add `"Thread"` to `EXPORT_TYPES`;
   - `CATEGORY_BY_TYPE["Thread"] = "Handlungsfäden"`;
   - `THREADS_OVERVIEW_PAGE = os.environ.get("PNP_THREADS_OVERVIEW_PAGE", "Offene Fäden")`.
3. `02_extract.py`: for `type == "Thread"`, copy `kind`, `thread_status`,
   `opened`, `resolved` and `teams` from the frontmatter into the plan entry,
   field by field, like `_EPISODE_FIELDS`.
   - Thread bodies cite `Session YYYY-MM-DD` in `## Verlauf` and `# Belege`
     (pnp-knowledge T6 guarantees it), so the session gate counts them.
4. `03_generate.py`:
   - `render_threads_overview(plan) -> str`: table columns Art | Faden |
     Seit | Stand, with German labels (Auftrag, Rätsel, Versprechen, Schuld,
     Frist; offen/erledigt/aufgegeben);
   - link `[[wiki_title|title]]` when the thread has its own page, else the
     plain title;
   - escape cells (E4 `_cell`);
   - `build_threads_overview_proposal` mirrors `build_overview_proposal`,
     **including E1's fail-closed rule**.
5. `04_upload._update_titles`: add `THREADS_OVERVIEW_PAGE` like
   `STORY_OVERVIEW_PAGE`.
6. Tests mirror the overview tests: grouping, collapse, link vs. plain
   title, fail closed without a live copy.
7. **HUMAN:** create the empty "Offene Fäden" page on the wiki, then run
   E6 steps 3–6.

Message: `feat: generate an open-threads overview page from KB threads`
