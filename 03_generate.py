"""Stage 3 — Generate: produce structured Wikitext proposals (the dry-run).

For each entity from stage 2, the Ollama model writes a German Wikitext page
with sections (== Überschrift ==), internal links ([[Andere Seite]]) drawn from
the stage-1 page index, and infoboxes where appropriate. For entities marked
"update", the existing page (fetched via wiki_client.read) is given as context
so the model merges rather than overwrites.

Nothing is uploaded here. Each proposed page is written to config.PROPOSALS_DIR
as a .wikitext file plus a .diff against the live page, for the review gate.

Run:  python 03_generate.py
"""

from __future__ import annotations

import config

# TODO: load wiki_cache/entities.json + page_index.json; for each entity build a
# German generation prompt (inject the page index so links resolve), call
# Ollama, and write proposals/<Title>.wikitext. For "update" entities, fetch the
# current page via WikiClient.read and emit proposals/<Title>.diff.


def main() -> None:
    raise NotImplementedError(
        "Stage 3 (Wikitext generation via Ollama) is scaffolded but not yet "
        "implemented. See module docstring."
    )


if __name__ == "__main__":
    main()
