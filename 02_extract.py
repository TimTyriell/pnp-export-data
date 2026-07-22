"""Stage 2 — Extract: turn session reports into structured entities.

Reads the LLM-generated reports in config.REPORTS_DIR and, via the local Ollama
model, extracts the entities worth a wiki page (NPCs, locations, events,
factions) plus the facts about them. Cross-checked against the stage-1 page
index so existing pages are flagged for update rather than re-creation.

Output: config.WIKI_CACHE_DIR / "entities.json" — consumed by stage 3.

Run:  python 02_extract.py
"""

from __future__ import annotations

import json

import config

# TODO: implement Ollama call (POST {config.OLLAMA_HOST}/api/generate) with a
# German extraction prompt; load reports from config.REPORTS_DIR; reconcile
# against wiki_cache/page_index.json to set each entity's {"action": "create"|
# "update"}. Write wiki_cache/entities.json.


def main() -> None:
    raise NotImplementedError(
        "Stage 2 (entity extraction via Ollama) is scaffolded but not yet "
        "implemented. See module docstring."
    )


if __name__ == "__main__":
    main()
