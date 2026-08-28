# pnp-fandom-service

Ein LLM-gesteuerter Agent, der unser Fandom/MediaWiki-Wiki aus den Session-Reports
unserer Pen-&-Paper-Runde befüllt und pflegt — strukturierte, querverlinkte Seiten,
ohne sie von Hand zu schreiben.

Eingabe sind die LLM-generierten Session-Reports (perspektivisch aus einem Graphen),
die upstream von **pnp-crawl** erzeugt werden. Der Service liest den Wiki-Bestand
über die MediaWiki Action API, baut sich einen Plan davon, *was schon im Fandom
steht*, generiert daraus neue/aktualisierte Wikitext-Seiten mit `[[Querverweisen]]`
und lädt sie nach einem **Review-Gate** hoch.

## Pipeline

```
01_inventory.py  Wiki lesen → Seitenindex/Plan nach wiki_cache/
02_extract.py    Reports → Entitäten (NPCs, Orte, Events, Fraktionen) via Ollama
03_generate.py   Entitäten + Index → Wikitext-Vorschläge nach proposals/ (Dry-run)
04_upload.py     geprüfte Vorschläge → Wiki (nur mit --apply + FANDOM_DRY_RUN=0)
```

## Seitenkarte (`wiki_pages.toml`)

Die Wissensbasis ist ein Graph und will pro Entität einen Knoten — über tausend,
bis hinunter zur einzelnen Untotenarmee. Das Wiki ist ein Nachschlagewerk und
will lesbare Artikel. **Entitäten sind darum keine Seiten.**
[wiki_pages.toml](wiki_pages.toml) ist die einzige Stelle, die zwischen beidem
übersetzt — und sie liegt hier, nicht in `pnp-knowledge`: ein Merge, den es nur
der Lesbarkeit wegen gibt, hat in der Wissensbasis nichts zu suchen (ADR-001).

Nur **Ausnahmen** stehen drin; alles Ungenannte bleibt wie bisher eine eigene
Seite, und den langen Schwanz hält schon `config.MIN_SESSIONS` fern.

```toml
exclude = ["events/beschwoerung_von_slix"]   # gar keine Seite

[pages."Belorus der Stille"]                 # 1:N, ein Leitknoten
lead = ["npcs/belorus"]
sub  = ["factions/belorus_untotenarmee"]     # nur ein Abschnitt dort

[pages."Die fünf Seelen Vhar'Zuls"]          # 1:N, alle gleichwertig
lead = ["deities/kollmereth", "deities/thyrex", "deities/ezhura", "npcs/slix_vasul"]
```

`lead` trägt die Identität der Seite (Typ, Kategorie, Aliase, Zuordnung
geernteter Handtexte), `sub` erscheint nur als Abschnitt. Links auf ein
zusammengeführtes Konzept landen automatisch auf der Seite, die es jetzt
abdeckt. Nach jeder Änderung `02_extract.py` und `03_generate.py` neu laufen
lassen; das Runlog meldet `member_has_live_page`, wenn eine dadurch verwaiste
Live-Seite eine Weiterleitung braucht.

## Setup

```bash
python -m venv fandom_env
fandom_env\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env                # dann ausfüllen (Bot-Account, Wiki-URL)
```

Ollama muss lokal laufen (`ollama serve`) mit dem in `.env` gesetzten Modell.

## Sicherheit

Standardmäßig ist `FANDOM_DRY_RUN=1`: es wird **nie** ins Wiki geschrieben.
Stage 4 gibt nur aus, was hochgeladen *würde*. Erst `python 04_upload.py --apply`
mit `FANDOM_DRY_RUN=0` schreibt — über einen Bot-Account (Special:BotPasswords).
