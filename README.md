# Structuring Morning Brief

A daily automated market briefing built for a Mexico-focused CIB / Structuring workflow.

The idea came from a simple problem: useful market intelligence is usually scattered across market-data pages, news feeds, deal announcements, and trader chats. This script pulls those inputs together, filters for relevance, and sends a concise morning email focused on one question:

> **What changed, which clients could be affected, and what structuring conversations might become relevant?**

Gemini acts as the editor rather than the data source. Market levels are pulled directly by Python from public sources, while Gemini turns the collected news and transactions into a structured morning read.

---

## What it includes

### Market snapshot

Python retrieves market data directly from public sources before the news analysis is generated.

Current coverage includes:

- USD/MXN and relevant MXN FX crosses
- Banxico FIX and FX reference rates
- Banxico policy rate
- TIIE de Fondeo O/N
- TIIE 28D / 91D
- CETES 28D
- SOFR
- U.S. Treasury 2Y / 5Y / 10Y / 30Y
- UST 2s10s
- Selected global risk indicators

Primary sources include:

- Banco de México SIE
- New York Fed
- U.S. Treasury
- Yahoo Finance
- ECB reference rates as FX fallback

Market numbers are rendered directly by Python and are not rewritten by the LLM.

---

## News and deal discovery

The script monitors a combination of direct RSS feeds and targeted Google News searches.

### Mexico / local markets

- El Financiero
- El Economista
- Reuters
- Bloomberg

### Global markets

- Financial Times
- Reuters Global Markets
- Reuters LatAm

### Transactions

Dedicated searches monitor recent activity in:

- Bond issuance / DCM
- Syndicated loans
- Refinancing
- Project finance
- Structured finance
- Infrastructure financing
- Securitizations
- Acquisition finance
- M&A
- Santander-related transactions in Mexico and Latin America

Google News is mainly used as a discovery layer. The script applies additional filters for recency, relevance, transaction terms, and duplicate stories before anything is sent to Gemini.

---

## Briefing structure

Each email is organized into:

1. **Market Snapshot**  
   FX, MXN rates, SOFR, U.S. Treasuries and risk indicators.

2. **Open**  
   The two or three developments that matter most that morning.

3. **What Changed**  
   High-signal developments in rates, FX, commodities, macro and relevant sectors.

4. **Recent Transactions**  
   Recent financing, capital markets, project finance and M&A activity, with a short Structuring read-through.

5. **Client Radar**  
   Three exposures or client conversations worth discussing with Coverage / Sales.

6. **What to Watch**  
   Near-term developments that could change rates, FX, funding conditions or client behavior.

---

## AI layer

The briefing currently uses **Gemini 2.5 Flash**.

The model is instructed to:

- Separate confirmed facts from inference
- Never invent market levels or transaction terms
- Avoid assuming that a USD-equivalent headline means USD-denominated debt
- Avoid assuming that a financing involved a hedge, swap or derivative
- Distinguish closed transactions from deals still being structured
- Use conditional language for potential Structuring opportunities
- Focus on client relevance rather than general financial-news summaries

The goal is not to produce investment recommendations. It is a concise morning intelligence note for client and Structuring conversations.

---

## Duplicate protection

The script keeps a persistent history of stories already used in previous briefings.

This prevents the same article or transaction from repeatedly appearing in the morning email while still allowing new developments to enter the briefing.

The history is persisted automatically between GitHub Actions runs.

---

## Stack

`Python` · `feedparser` · `BeautifulSoup` · `requests` · `Google Gemini API` · `GitHub Actions` · `Banxico SIE API`

---

## Setup

Install the dependencies:

```bash
pip install -r requirements.txt
```

Then add the following repository secrets in:

**GitHub → Settings → Secrets and variables → Actions**

```text
GEMINI_API_KEY
GMAIL_FROM
GMAIL_APP_PASSWORD
GMAIL_TO
BANXICO_TOKEN
```

### Secret descriptions

- `GEMINI_API_KEY` — Google Gemini API key used to generate the written briefing
- `GMAIL_FROM` — Gmail account used to send the briefing
- `GMAIL_APP_PASSWORD` — Google App Password for SMTP authentication
- `GMAIL_TO` — Recipient email address
- `BANXICO_TOKEN` — Banco de México SIE API token used for Mexican FX and rate data

Run manually with:

```bash
python morning_briefing.py
```

For automated runs, use the included GitHub Actions workflow:

```text
.github/workflows/daily_morning_briefing.yml
```

You can also trigger it manually from:

**GitHub → Actions → Daily Morning Briefing → Run workflow**

---

## Notes

- GitHub Actions cron schedules use UTC.
- The briefing keeps a persistent history of previously used stories to reduce repetition.
- Market data comes directly from public data sources; Gemini is only used for interpretation and writing.
