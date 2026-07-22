"""Stage 4 — Upload: push approved proposals to the wiki (gated).

Reads the reviewed .wikitext files from config.PROPOSALS_DIR and edits the
corresponding wiki pages via the MediaWiki API. This is the only stage that
writes to the wiki, and it refuses to do so unless the review gate is cleared:

  * config.DRY_RUN must be False (env FANDOM_DRY_RUN=0), or pass --apply.
  * Without that, it prints what *would* be uploaded and exits.

Run:  python 04_upload.py            # dry-run, prints planned edits
      python 04_upload.py --apply    # actually uploads (needs bot login)
"""

from __future__ import annotations

import sys

import config
from wiki_client import WikiClient


def main(apply: bool) -> None:
    if not config.PROPOSALS_DIR.exists():
        print("No proposals/ directory — run stage 3 first.")
        return

    proposals = sorted(config.PROPOSALS_DIR.glob("*.wikitext"))
    if not proposals:
        print("No reviewed proposals to upload.")
        return

    client = WikiClient()
    do_apply = apply and not config.DRY_RUN
    if do_apply:
        client.login()

    for path in proposals:
        title = path.stem
        text = path.read_text(encoding="utf-8")
        if do_apply:
            result = client.edit(title, text, summary="pnp-fandom-service update")
            print(f"Uploaded {title}: {result.get('edit', result)}")
        else:
            print(f"[dry-run] would upload {title} ({len(text)} chars)")

    if not do_apply:
        print("\nReview gate active. Re-run with --apply and FANDOM_DRY_RUN=0 "
              "to upload.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
