# E6 — Catch the wiki up with the bundle (runbook, human)

| | |
|---|---|
| Kind | Runbook. No branch, no code |
| Needs | E0, **E1, E2 merged** (safe upload), pnp-knowledge **T1 HUMAN RUN** (complete episodes.yaml, re-emitted bundle) |

## State on 2026-10-18

- Wiki snapshot `wiki_cache/*` dated 2026-08-10: 175 planned pages, 60
  sessions (P-01..P-55, S1-01-A/B, S1-02-A/B, S1-03-B).
- The bundle has 68 sessions (through 2026-09-22) and was re-emitted on
  2026-09-23.
- 13 non-empty diffs were generated *after* the last live upload and never
  went up: Der Goblin-Magier, Folge P-02, Folge P-07, Folge P-13, Folge P-14,
  Nerash, Nox, Orlanius Schwarzhorn, Perry, Schriftrolle von Nerash, Totem
  von Nerash, Voras der Heilige, Zwergenmine. They are stale now; stage 3
  regenerates them.
- 1 page to create by hand: **Heiliger Duran** (`deities/heiliger_duran`).
- `harvest/` holds team-written text not yet in the KB: `characters_kaya.md`,
  `characters_lindo_laut.md` (19.5 KB), `characters_sange.md`,
  `deities_vorgul_tar.md`.

## Steps

1. **Harvest first.** Move the four `harvest/*.md` texts into
   `../pnp-knowledge/knowledge/sources/` through that repo's normal
   ingest-branch PR. Until the KB absorbs them, those pages stay `edited`
   and are left alone, which is correct.
2. Start the KB API: `cd ../pnp-knowledge/services/kb && .venv/Scripts/python.exe -m pnp_okf.api`.
3. Refresh:
   ```bash
   fandom_env/Scripts/python.exe 01_inventory.py
   fandom_env/Scripts/python.exe 02_extract.py
   fandom_env/Scripts/python.exe 03_generate.py
   ```
   Expect 68 Session pages planned, titled "Folge <id> – <Abenteuername>".
   If any Session title is a raw YouTube title, episodes.yaml is still
   incomplete: stop and finish pnp-crawl C3.
4. **Review:** read every non-empty `proposals/*.diff`. Additions only;
   E1 guarantees no raw-KB replacement.
5. **Create pages by hand** from `proposals/NEW_PAGES.md` (Heiliger Duran
   plus the 8 new episode pages, if the wiki has no pages for them yet).
   Empty pages are enough. Then repeat step 3 so they become updates.
6. **Upload in two steps:**
   ```bash
   FANDOM_DRY_RUN=0 fandom_env/Scripts/python.exe 04_upload.py --apply --only "Heiliger Duran"
   ```
   Look at the page live. Then the rest:
   `FANDOM_DRY_RUN=0 fandom_env/Scripts/python.exe 04_upload.py --apply`.
   An `editconflict` failure means someone edited the page since step 3:
   re-run step 3 for it.
7. `fandom_env/Scripts/python.exe 05_report.py`, and check
   `reports/ki_pages.html`.

## Done when

- [ ] The wiki shows 68 episode pages and the overview table lists them.
- [ ] 0 upload failures, or each failure explained.
- [ ] `harvest/` is empty after the KB absorbed the texts and a later sync.
