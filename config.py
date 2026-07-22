"""Single source of truth for all tunables of the pnp-fandom-service.

Mirrors the pattern used by the sibling project pnp-crawl: scripts import
values from here directly instead of taking CLI flags for them. When asked to
change behaviour, edit this file — not the stage scripts — unless the change is
structural.

Secrets / instance-specific values come from a .env file (via python-dotenv,
optional) and fall back to shell environment variables. Never hardcode the bot
password into this file or commit it.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # optional dependency, same approach as pnp-crawl
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # fall back to plain environment variables
    pass


# --- Wiki / MediaWiki API -------------------------------------------------

# Base API endpoint of your Fandom wiki, e.g. https://meinwiki.fandom.com/api.php
WIKI_API_URL = os.environ.get("WIKI_API_URL", "https://DEINWIKI.fandom.com/api.php")

# Bot credentials. Create a bot password under Special:BotPasswords on the wiki.
# Keep these in .env, never in this file.
WIKI_USERNAME = os.environ.get("WIKI_USERNAME", "")
WIKI_BOT_PASSWORD = os.environ.get("WIKI_BOT_PASSWORD", "")

# Polite User-Agent is required by Fandom/Wikimedia API policy.
WIKI_USER_AGENT = os.environ.get(
    "WIKI_USER_AGENT", "pnp-fandom-service/0.1 (contact: noahstreppel@gmail.com)"
)

# Namespace to write generated pages into during review (0 = main/live,
# 2 = User:, "Draft" if your wiki has a Draft namespace). The review-gate
# workflow promotes from a draft/sandbox namespace to live only after approval.
DRAFT_NAMESPACE = os.environ.get("WIKI_DRAFT_NAMESPACE", "User")


# --- LLM (local via Ollama) ----------------------------------------------

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")

# Campaign content is German (see pnp-crawl). Generate Wikitext in German.
LANGUAGE = "de"


# --- Directories ----------------------------------------------------------

ROOT = Path(__file__).resolve().parent

# LLM-generated session reports, the input to this service. Produced upstream by
# pnp-crawl's (planned) stage-4 report generator. Drop the .md/.json files here.
REPORTS_DIR = ROOT / "reports"

# Cached snapshot of the wiki: page index, categories, extracted entities.
# Stage 1 (inventory) writes here; later stages read it. Gitignored.
WIKI_CACHE_DIR = ROOT / "wiki_cache"

# Generated Wikitext awaiting review (the dry-run output). Stage 3 writes a
# proposed/ diff here; nothing is uploaded until approved. Gitignored.
PROPOSALS_DIR = ROOT / "proposals"


# --- Review gate ----------------------------------------------------------

# When True (default), stage 4 (upload) refuses to write to the wiki and only
# prints/serializes the diff. Set to False (or pass --apply) to actually upload.
DRY_RUN = os.environ.get("FANDOM_DRY_RUN", "1") not in ("0", "false", "False")
