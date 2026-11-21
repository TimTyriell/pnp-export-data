"""Setzt die Seitenleiste ("Infobox Charakter") auf Spielercharakter-Seiten, die keine haben.

Additiv wie wikimerge: hat die Live-Seite schon irgendeine Infobox, bleibt sie
unberuehrt. Daten kommen aus char_infobox.toml; unbekannte Felder werden "-".
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_PATH = Path(__file__).parent / "char_infobox.toml"
_HAS_BOX = re.compile(r"\{\{\s*Infobox", re.IGNORECASE)
FIELDS = ["Name", "Bild", "Darsteller", "Zugehörigkeit", "Beruf", "Geburtstag",
          "Geburtsort", "Spezies", "Geschlecht", "Körpergröße", "Körpergewicht",
          "Beschreibung", "Level", "Klasse", "Unterklasse", "Kommunity"]


def load(path: Path = _PATH) -> dict[str, dict[str, str]]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def add_infobox(wikitext: str, title: str, data: dict[str, dict[str, str]]) -> str:
    row = data.get(title)
    if row is None or _HAS_BOX.search(wikitext):
        return wikitext
    row = {"Name": title, **row}
    # Bild bleibt leer statt "-": ein Dateilink auf "-" waere ein kaputtes Bild.
    lines = [f"|{f:<13}= {row.get(f) or ('' if f == 'Bild' else '-')}" for f in FIELDS]
    return "{{Infobox Charakter\n" + "\n".join(lines) + "\n}}\n" + wikitext
