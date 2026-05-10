# Morning Briefing

I read a lot of financial news but found myself jumping between too many tabs every morning. So I built this — a script that pulls from the sources I actually read, filters out the noise, and sends me a single email every day before markets open.

Gemini acts as editor: it reads everything collected and writes a structured briefing rather than just dumping headlines.

---

## How it works

- Pulls RSS feeds from ~15 sources (FT, Reuters, El Financiero, Expansión, Econbrowser, several Substacks)
- Filters articles by keyword relevance — focused on Mexico, EM macro, Fed, commodities, FX
- Scrapes full article bodies where accessible
- Tracks seen URLs so the same story never appears twice
- Sends the output to Gemini 2.5 Flash, which organizes everything into sections: Mexico, Global Macro, Opinion, Talking Points, and what to follow this week
- Delivers as a styled HTML email via Gmail SMTP
- Runs automatically every morning via GitHub Actions

---

## Stack

`Python` · `feedparser` · `BeautifulSoup` · `Google Gemini API` · `GitHub Actions`

---

## Setup

```bash
pip install -r requirements.txt
```

Set the following as environment variables (or GitHub secrets for automated runs):

```
GEMINI_API_KEY
GMAIL_FROM
GMAIL_APP_PASSWORD
GMAIL_TO
```

Then run manually with:

```bash
python morning_briefing.py
```

---

## Sources

**Mexico:** Expansión, El Financiero, El Economista, Reforma Negocios

**Global:** FT Markets, Reuters, CNBC, Yahoo Finance, Econbrowser

**Opinion:** Adam Tooze, Noah Smith, Paul Krugman, Michael Burry, Macario Schettino, ECONOMEX
