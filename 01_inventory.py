"""Stage 1 — Inventory: read the current wiki and build a plan of what exists.

Lists every page title (and later: categories, extracted entities) via the
MediaWiki API and writes a snapshot to config.WIKI_CACHE_DIR. Downstream stages
feed this index to the LLM so it can emit correct [[Page]] cross-references and
decide create-vs-update. Idempotent: re-run any time to refresh the snapshot.

Run:  python 01_inventory.py
"""

from __future__ import annotations

import json

import config
from wiki_client import WikiClient


def main() -> None:
    client = WikiClient()
    titles = client.all_pages(namespace=0)

    config.WIKI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    index_path = config.WIKI_CACHE_DIR / "page_index.json"
    index_path.write_text(
        json.dumps(sorted(titles), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(titles)} page titles to {index_path}")


if __name__ == "__main__":
    main()
