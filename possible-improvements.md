# Possible improvements

External repos/tools evaluated for this pipeline (Sep 2026). See sibling files in `pnp-crawl/` and `pnp-knowledge/` for their own lists.

## Add now

### [pywikibot](https://github.com/wikimedia/pywikibot)
Applies to: stages 01–04

The reference Python library for MediaWiki API automation — page get/edit/diff, category walks, works against Fandom's MediaWiki install out of the box.

- **Pros:** handles auth, rate limits, edit conflicts, and API version drift for you — the boring parts of "talk to a wiki"; battle-tested against Fandom specifically (widely used by Fandom bot operators); frees `md2wiki.py` to stay a pure markdown→wikitext transform, not also an HTTP client.
- **Cons:** heavyweight framework (its own bot config, throttling, `user-config.py`) for what may be a handful of scripted edits; if current stages only read the KB API and write local files with no live push yet, this is future-facing, not urgent.

## Worth a look, not urgent

Nothing repo-specific beyond pywikibot itself right now — smaller wiki-bot forks considered were passed on, see below.

## Evaluated, passed on

| Repo | Category | Why not |
|---|---|---|
| G-Goldstein/Wikibot | Wiki bot | Small personal project, pywikibot covers the same ground with far more maturity |
| Hutchy68/pywiki-bot | Wiki bot | Thin wrapper, no advantage over pywikibot direct |

---
Full cross-repo report: see the artifact published 2026-09-05 (link in chat history) for context spanning all three repos.
