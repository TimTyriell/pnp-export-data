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
