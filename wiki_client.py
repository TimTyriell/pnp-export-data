"""Thin MediaWiki Action API client shared across all stages.

Wraps login (bot password), reading pages/categories/the page index, and
editing pages. All write paths honour config.DRY_RUN: when set, edit() does not
POST to the wiki and returns the would-be payload instead, so the review-gate
stages can produce a diff without touching live content.

Docs: https://www.mediawiki.org/wiki/API:Main_page
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

import config


@dataclass
class Page:
    title: str
    wikitext: str


class WikiClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.WIKI_USER_AGENT
        self.url = config.WIKI_API_URL
        self._logged_in = False

    # --- auth -------------------------------------------------------------

    def login(self) -> None:
        """Log in with the bot account (two-step token + login dance)."""
        token = self._get(action="query", meta="tokens", type="login")[
            "query"
        ]["tokens"]["logintoken"]
        resp = self._post(
            action="login",
            lgname=config.WIKI_USERNAME,
            lgpassword=config.WIKI_BOT_PASSWORD,
            lgtoken=token,
        )
        if resp.get("login", {}).get("result") != "Success":
            raise RuntimeError(f"Wiki login failed: {resp.get('login')}")
        self._logged_in = True

    def _csrf_token(self) -> str:
        return self._get(action="query", meta="tokens")["query"]["tokens"][
            "csrftoken"
        ]

    # --- read -------------------------------------------------------------

    def all_pages(self, namespace: int = 0) -> list[str]:
        """Return every page title in a namespace (paginated via apcontinue)."""
        titles: list[str] = []
        cont: dict[str, str] = {}
        while True:
            data = self._get(
                action="query",
                list="allpages",
                aplimit="max",
                apnamespace=namespace,
                **cont,
            )
            titles += [p["title"] for p in data["query"]["allpages"]]
            if "continue" not in data:
                break
            cont = data["continue"]
        return titles

    def read(self, title: str) -> Page | None:
        """Fetch raw Wikitext of a page, or None if it does not exist."""
        data = self._get(
            action="query",
            prop="revisions",
            rvprop="content",
            rvslots="main",
            titles=title,
        )
        page = next(iter(data["query"]["pages"].values()))
        if "missing" in page:
            return None
        content = page["revisions"][0]["slots"]["main"]["*"]
        return Page(title=title, wikitext=content)

    # --- write ------------------------------------------------------------

    def edit(self, title: str, text: str, summary: str) -> dict:
        """Create or replace a page. No-op (returns payload) when DRY_RUN."""
        payload = {
            "action": "edit",
            "title": title,
            "text": text,
            "summary": summary,
            "bot": True,
            "format": "json",
        }
        if config.DRY_RUN:
            return {"dry_run": True, **payload}
        if not self._logged_in:
            raise RuntimeError("Call login() before editing with DRY_RUN off.")
        payload["token"] = self._csrf_token()
        return self._post(**payload)

    # --- transport --------------------------------------------------------

    def _get(self, **params) -> dict:
        params["format"] = "json"
        return self.session.get(self.url, params=params).json()

    def _post(self, **params) -> dict:
        params["format"] = "json"
        return self.session.post(self.url, data=params).json()
