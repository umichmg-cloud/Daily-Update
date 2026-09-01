import datetime
import html
import json
import os
import re
import smtplib
import time
from pathlib import Path
from urllib.parse import quote, quote_plus
from zoneinfo import ZoneInfo

import feedparser
import google.api_core.exceptions
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ─── CONFIG ───────────────────────────────────────────────────────────────────
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_FROM")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT = os.getenv("GMAIL_TO")
BANXICO_TOKEN = os.getenv("BANXICO_TOKEN")

MX_TZ = ZoneInfo("America/Mexico_City")
SEEN_PATH = Path.home() / ".structuring_brief_seen.json"

SCRAPE_TIMEOUT = 8
ARTICLE_MAX_HOURS = 96
BODY_CHARS = 750
MAX_PER_FEED = 4
CATEGORY_CAPS = {"mexico": 12, "global": 10, "deals": 12}

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


def google_news_rss(query: str, lang="en-US", country="US", ceid="US:en") -> str:
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + f"&hl={lang}&gl={country}&ceid={quote_plus(ceid)}"
    )


# Direct feeds + targeted Google News searches.
# The point is not volume. It is to maximize signal for a Structuring MD.
FEEDS = [
    # Mexico / local markets
    {
        "name": "El Financiero Mercados",
        "url": "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/?outputType=xml&hierarchy=mercados",
        "category": "mexico",
    },
    {
        "name": "El Financiero Economía",
        "url": "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/?outputType=xml&hierarchy=economia",
        "category": "mexico",
    },
    {
        "name": "El Economista",
        "url": "https://www.eleconomista.com.mx/rss/ultimas-noticias",
        "category": "mexico",
    },
    {
        "name": "Reuters México Markets",
        "url": google_news_rss(
            'site:reuters.com (Mexico OR Mexican OR peso OR Banxico) '
            '(rates OR bonds OR currency OR markets OR economy) when:3d'
        ),
        "category": "mexico",
    },
    {
        "name": "Bloomberg México Markets",
        "url": google_news_rss(
            'site:bloomberg.com (Mexico OR Mexican OR peso OR Banxico) '
            '(rates OR bonds OR currency OR markets) when:3d'
        ),
        "category": "mexico",
    },

    # Global macro / markets
    {
        "name": "FT Markets",
        "url": "https://www.ft.com/markets?format=rss",
        "category": "global",
    },
    {
        "name": "Reuters Global Markets",
        "url": google_news_rss(
            'site:reuters.com (Fed OR Treasury OR dollar OR oil OR tariffs OR inflation) '
            '(markets OR rates OR yields OR currency) when:2d'
        ),
        "category": "global",
    },
    {
        "name": "Reuters LatAm Markets",
        "url": google_news_rss(
            'site:reuters.com (Latin America OR Brazil OR Chile OR Colombia) '
            '(bonds OR rates OR currency OR financing) when:3d'
        ),
        "category": "global",
    },

    # Deal tape
    {
        "name": "Mexico DCM / Loans",
        "url": google_news_rss(
            '(Mexico OR Mexican) '
            '(bond issuance OR notes offering OR syndicated loan OR refinancing OR debt financing) when:10d'
        ),
        "category": "deals",
    },
    {
        "name": "Mexico Project / Structured Finance",
        "url": google_news_rss(
            '(Mexico OR Mexican) '
            '(project finance OR structured finance OR infrastructure financing OR securitization OR data center financing) when:14d'
        ),
        "category": "deals",
    },
    {
        "name": "Mexico M&A / Acquisition Finance",
        "url": google_news_rss(
            '(Mexico OR Mexican) '
            '(acquisition financing OR acquisition loan OR M&A deal OR takeover OR buyout) when:14d'
        ),
        "category": "deals",
    },
    {
        "name": "Santander CIB Deal Watch",
        "url": google_news_rss(
            'Santander (Mexico OR Latin America) '
            '(bond OR financing OR loan OR project finance OR transaction OR deal) when:21d'
        ),
        "category": "deals",
    },
]

KEYWORDS = [
    # FX / rates
    "mxn", "peso", "dollar", "dólar", "currency", "fx", "foreign exchange",
    "banxico", "tiie", "sofr", "swap", "curve", "yield", "treasury", "rate cut",
    "rate hike", "interest rate", "fomc", "fed", "inflation", "cpi", "pce",
    # Financing / deals
    "bond", "bono", "debt", "deuda", "issuance", "emisión", "notes", "loan",
    "financing", "financiamiento", "refinancing", "refinanciamiento", "syndicated",
    "project finance", "structured finance", "securitization", "bursatilización",
    "acquisition", "merger", "m&a", "takeover", "liability management",
    # Client / sector exposures
    "oil", "brent", "wti", "gas", "energy", "power", "electricity", "infrastructure",
    "airport", "toll road", "data center", "telecom", "industrial", "automotive",
    "trade", "tariff", "usmca", "t-mec", "nearshoring", "export", "import",
    "commodity", "hedge", "hedging", "derivative", "option", "volatility",
]

BLACKLIST = [
    "crypto", "bitcoin", "nft", "celebrity", "soccer", "football club", "horoscope",
    "mortgage rate today", "best savings account", "best cd rate", "credit card rewards",
    "stock forecast", "earnings call highlights", "world cup", "lifestyle",
]

# ─── MARKET DATA: BANXICO ─────────────────────────────────────────────────────
# Official Banxico SIE series.
BANXICO_REFERENCES = {
    "USD/MXN FIX": "SF43718",
}

YAHOO_FX = {
    "USD/MXN": "MXN=X",
    "EUR/MXN": "EURMXN=X",
    "GBP/MXN": "GBPMXN=X",
    "JPY/MXN": "JPYMXN=X",
    "CAD/MXN": "CADMXN=X",
    "BRL/MXN": "BRLMXN=X",
    "CNY/MXN": "CNYMXN=X",
}

BANXICO_RATES = {
    "Banxico target": "SF61745",
    "TIIE Funding O/N": "SF331451",
    "TIIE 28d": "SF60648",
    "TIIE 91d": "SF60649",
    "CETES 28d": "SF60633",
}

# Optional risk proxies from Yahoo's public chart endpoint. If it fails, the brief still works.
YAHOO_MARKETS = {
    "S&P 500": "^GSPC",
    "IPC México": "^MXX",
    "VIX": "^VIX",
    "DXY": "DX-Y.NYB",
    "WTI": "CL=F",
    "Brent": "BZ=F",
}


# ─── MEMORY / DE-DUP ──────────────────────────────────────────────────────────
def load_seen() -> dict:
    try:
        data = json.loads(SEEN_PATH.read_text())
    except Exception:
        return {}

    cutoff = datetime.date.today() - datetime.timedelta(days=10)
    clean = {}
    for url, date_str in data.items():
        try:
            if datetime.date.fromisoformat(date_str) >= cutoff:
                clean[url] = date_str
        except Exception:
            pass
    return clean


def save_seen(new_urls: set, old_seen: dict):
    today = datetime.date.today().isoformat()
    merged = dict(old_seen)
    for url in new_urls:
        merged[url] = today
    SEEN_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False))


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def clean_text(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def is_recent(entry, max_hours=ARTICLE_MAX_HOURS) -> bool:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return True
    pub_dt = datetime.datetime(*published[:6], tzinfo=datetime.timezone.utc)
    age = datetime.datetime.now(datetime.timezone.utc) - pub_dt
    return age.total_seconds() <= max_hours * 3600


def is_relevant(text: str, forced_category: str) -> bool:
    t = text.lower().replace("new mexico", "new_mexico")
    if any(x in t for x in BLACKLIST):
        return False
    if forced_category == "deals":
        # Deal feeds are already narrow, but still require a financing/transaction signal.
        deal_terms = [
            "bond", "bono", "loan", "financing", "refinancing", "issuance", "emisión",
            "project finance", "structured finance", "securitization", "acquisition",
            "merger", "m&a", "transaction", "deal", "notes offering",
        ]
        return any(x in t for x in deal_terms)
    return any(x in t for x in KEYWORDS)


def scrape_article(url: str) -> str:
    # Google News redirect pages are not useful to scrape. RSS summary is enough.
    if not url or "news.google.com" in url:
        return ""
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=SCRAPE_TIMEOUT)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe", "noscript"]):
            tag.decompose()

        for selector in [
            "article", "[class*='article-body']", "[class*='story-body']",
            "[class*='content-body']", "[class*='entry-content']", "main",
        ]:
            found = soup.select_one(selector)
            if found:
                return " ".join(found.get_text(" ", strip=True).split()[:700])
        return ""
    except Exception:
        return ""


# ─── FETCH NEWS / DEALS ───────────────────────────────────────────────────────
def fetch_news(seen: dict) -> tuple[dict, set]:
    items = {"mexico": [], "global": [], "deals": []}
    new_urls = set()

    for cfg in FEEDS:
        category = cfg["category"]
        if len(items[category]) >= CATEGORY_CAPS[category]:
            continue

        print(f"\n   📡 {cfg['name']}")
        try:
            feed = feedparser.parse(cfg["url"])
        except Exception as exc:
            print(f"      ⚠️ Feed error: {exc}")
            continue

        count = 0
        for entry in feed.entries:
            if count >= MAX_PER_FEED or len(items[category]) >= CATEGORY_CAPS[category]:
                break

            title = clean_text(entry.get("title", ""))
            summary = clean_text(entry.get("summary", ""))[:650]
            link = entry.get("link", "")

            if not title:
                continue
            if link and link in seen:
                continue
            # Deals get a longer lookback because transaction news is less frequent.
            max_hours = 24 * 21 if category == "deals" else ARTICLE_MAX_HOURS
            if not is_recent(entry, max_hours=max_hours):
                continue
            if not is_relevant(f"{title} {summary}", category):
                continue

            body = scrape_article(link) if link else ""
            items[category].append({
                "source": cfg["name"],
                "title": title,
                "summary": summary,
                "url": link,
                "body": body or summary,
            })

            if link:
                new_urls.add(link)
            count += 1
            time.sleep(0.15)

    return items, new_urls


# ─── MARKET DATA HELPERS ──────────────────────────────────────────────────────
def safe_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return None


def banxico_history(series_id: str, lookback_days=14):
    if not BANXICO_TOKEN:
        return []

    end = datetime.datetime.now(MX_TZ).date()
    start = end - datetime.timedelta(days=lookback_days)
    url = (
        f"https://www.banxico.org.mx/SieAPIRest/service/v1/series/{series_id}/datos/"
        f"{start.isoformat()}/{end.isoformat()}"
    )
    try:
        resp = requests.get(
            url,
            headers={**HTTP_HEADERS, "Bmx-Token": BANXICO_TOKEN},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        raw = payload["bmx"]["series"][0].get("datos", [])
        rows = []
        for x in raw:
            value = safe_float(x.get("dato"))
            if value is None:
                continue
            try:
                d = datetime.datetime.strptime(x["fecha"], "%d/%m/%Y").date()
            except Exception:
                continue
            rows.append((d, value))
        rows.sort(key=lambda x: x[0])
        return rows
    except Exception as exc:
        print(f"   ⚠️ Banxico {series_id}: {exc}")
        return []


def fetch_banxico_group(series_map: dict, change_type: str):
    out = []
    for label, series_id in series_map.items():
        rows = banxico_history(series_id)
        if not rows:
            continue
        latest_date, latest = rows[-1]
        previous = rows[-2][1] if len(rows) >= 2 else None

        if previous is None:
            change = None
        elif change_type == "pct":
            change = (latest / previous - 1) * 100 if previous else None
        else:
            change = (latest - previous) * 100  # percentage points -> bps

        out.append({
            "label": label,
            "value": latest,
            "change": change,
            "date": latest_date.isoformat(),
            "series": series_id,
        })
    return out


def fetch_sofr():
    url = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/3.json"
    try:
        data = requests.get(url, headers=HTTP_HEADERS, timeout=10).json()
        rows = data.get("refRates", [])
        parsed = []
        for r in rows:
            value = safe_float(r.get("percentRate") or r.get("rate"))
            date_str = r.get("effectiveDate") or r.get("date")
            if value is None or not date_str:
                continue
            parsed.append((date_str, value))
        parsed.sort(key=lambda x: x[0])
        if not parsed:
            return None
        latest = parsed[-1]
        prev = parsed[-2] if len(parsed) >= 2 else None
        return {
            "label": "SOFR O/N",
            "value": latest[1],
            "change": (latest[1] - prev[1]) * 100 if prev else None,
            "date": latest[0],
        }
    except Exception as exc:
        print(f"   ⚠️ SOFR: {exc}")
        return None


def previous_month(dt: datetime.date) -> datetime.date:
    first = dt.replace(day=1)
    return first - datetime.timedelta(days=1)


def parse_treasury_month(year_month: str):
    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"TextView?field_tdr_date_value_month={year_month}&type=daily_treasury_yield_curve"
    )
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        target_table = None
        for table in soup.find_all("table"):
            headers = [clean_text(th.get_text(" ", strip=True)) for th in table.find_all("th")]
            if "2 Yr" in headers and "10 Yr" in headers:
                target_table = table
                break
        if not target_table:
            return []

        headers = [clean_text(th.get_text(" ", strip=True)) for th in target_table.find_all("th")]
        rows = []
        for tr in target_table.find_all("tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            if len(cells) != len(headers):
                continue
            row = dict(zip(headers, cells))
            if not row.get("Date"):
                continue
            rows.append(row)
        return rows
    except Exception as exc:
        print(f"   ⚠️ Treasury {year_month}: {exc}")
        return []


def fetch_treasury_curve():
    today = datetime.datetime.now(MX_TZ).date()
    month_keys = [today.strftime("%Y%m"), previous_month(today).strftime("%Y%m")]
    rows = []
    for key in month_keys:
        rows.extend(parse_treasury_month(key))

    parsed = []
    for row in rows:
        try:
            d = datetime.datetime.strptime(row["Date"], "%m/%d/%Y").date()
        except Exception:
            continue
        values = {tenor: safe_float(row.get(tenor)) for tenor in ["2 Yr", "5 Yr", "10 Yr", "30 Yr"]}
        if values["2 Yr"] is None or values["10 Yr"] is None:
            continue
        parsed.append((d, values))

    parsed.sort(key=lambda x: x[0])
    if not parsed:
        return []

    latest_date, latest = parsed[-1]
    prev = parsed[-2][1] if len(parsed) >= 2 else None
    out = []
    for tenor in ["2 Yr", "5 Yr", "10 Yr", "30 Yr"]:
        value = latest.get(tenor)
        if value is None:
            continue
        change = None
        if prev and prev.get(tenor) is not None:
            change = (value - prev[tenor]) * 100
        out.append({
            "label": f"UST {tenor.replace(' Yr', 'Y')}",
            "value": value,
            "change": change,
            "date": latest_date.isoformat(),
        })

    curve = (latest["10 Yr"] - latest["2 Yr"]) * 100
    prev_curve = ((prev["10 Yr"] - prev["2 Yr"]) * 100) if prev else None
    out.append({
        "label": "UST 2s10s",
        "value": curve,
        "change": curve - prev_curve if prev_curve is not None else None,
        "date": latest_date.isoformat(),
        "unit": "bp",
    })
    return out


def fetch_yahoo_quote(symbol: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    params = {"range": "5d", "interval": "1d", "includePrePost": "false"}
    try:
        data = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=10).json()
        result = data["chart"]["result"][0]
        meta = result.get("meta", {})
        closes = result["indicators"]["quote"][0]["close"]
        timestamps = result["timestamp"]
        valid = [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]

        latest = safe_float(meta.get("regularMarketPrice"))
        prev = safe_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
        latest_ts = meta.get("regularMarketTime")

        if latest is None and valid:
            latest_ts, latest = valid[-1]
        if prev is None and len(valid) >= 2:
            prev = valid[-2][1]
        if latest is None:
            return None

        if latest_ts:
            dt = datetime.datetime.fromtimestamp(int(latest_ts), tz=datetime.timezone.utc).date()
        elif valid:
            dt = datetime.datetime.fromtimestamp(valid[-1][0], tz=datetime.timezone.utc).date()
        else:
            dt = datetime.date.today()

        return {
            "value": float(latest),
            "change": ((latest / prev - 1) * 100) if prev else None,
            "date": dt.isoformat(),
        }
    except Exception as exc:
        print(f"   ⚠️ Yahoo {symbol}: {exc}")
        return None


def fetch_market_snapshot():
    print("\n📊 Descargando market snapshot...")
    snapshot = {
        "fx": [],
        "references": fetch_banxico_group(BANXICO_REFERENCES, "pct"),
        "mx_rates": fetch_banxico_group(BANXICO_RATES, "bp"),
        "us_rates": [],
        "risk": [],
    }

    for label, symbol in YAHOO_FX.items():
        q = fetch_yahoo_quote(symbol)
        if q:
            snapshot["fx"].append({"label": label, **q})

    sofr = fetch_sofr()
    if sofr:
        snapshot["us_rates"].append(sofr)
    snapshot["us_rates"].extend(fetch_treasury_curve())

    for label, symbol in YAHOO_MARKETS.items():
        q = fetch_yahoo_quote(symbol)
        if q:
            snapshot["risk"].append({"label": label, **q})

    return snapshot


# ─── MARKET SNAPSHOT HTML (NO LLM) ────────────────────────────────────────────
def fmt_change(value, suffix="%"):
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}{suffix}"


def render_table(title: str, rows: list, kind: str):
    if not rows:
        return ""
    trs = []
    for r in rows:
        unit = r.get("unit")
        if kind == "fx":
            val = f"{r['value']:.4f}"
            chg = fmt_change(r.get("change"), "%")
        elif kind == "rates":
            val = f"{r['value']:.3f}%" if unit != "bp" else f"{r['value']:.0f} bp"
            chg = fmt_change(r.get("change"), " bp")
        else:
            if r["label"] in {"WTI", "Brent"}:
                val = f"${r['value']:.2f}"
            else:
                val = f"{r['value']:.2f}"
            chg = fmt_change(r.get("change"), "%")

        trs.append(
            "<tr>"
            f"<td class='mkt-name'>{html.escape(r['label'])}</td>"
            f"<td class='mkt-val'>{html.escape(val)}</td>"
            f"<td class='mkt-chg'>{html.escape(chg)}</td>"
            f"<td class='mkt-date'>{html.escape(r.get('date', ''))}</td>"
            "</tr>"
        )

    return f"""
    <div class="market-block">
      <div class="market-title">{html.escape(title)}</div>
      <table class="market-table">
        <thead><tr><th>Instrumento</th><th>Nivel</th><th>Δ día</th><th>Dato</th></tr></thead>
        <tbody>{''.join(trs)}</tbody>
      </table>
    </div>
    """


def render_market_snapshot(snapshot: dict) -> str:
    note = ""
    if not BANXICO_TOKEN:
        note = (
            '<div class="data-note">⚠️ BANXICO_TOKEN no configurado: '
            'FX y tasas MX no aparecen hasta agregarlo.</div>'
        )

    return f"""
    <div class="sec">
      <div class="sec-label">Market snapshot</div>
      <p class="market-intro">Niveles de mercado antes de las noticias. Los datos se insertan directamente desde las fuentes; Gemini no los reescribe.</p>
      {note}
      {render_table('FX — market proxy, MXN por unidad de divisa', snapshot.get('fx', []), 'fx')}
      {render_table('Banxico reference', snapshot.get('references', []), 'fx')}
      {render_table('México — tasas', snapshot.get('mx_rates', []), 'rates')}
      {render_table('EE.UU. — SOFR / Treasury', snapshot.get('us_rates', []), 'rates')}
      {render_table('Risk proxies', snapshot.get('risk', []), 'risk')}
    </div>
    """


def market_text_for_prompt(snapshot: dict) -> str:
    blocks = []
    for group_name, rows in [
        ("FX", snapshot.get("fx", [])),
        ("BANXICO_REFERENCES", snapshot.get("references", [])),
        ("MEXICO_RATES", snapshot.get("mx_rates", [])),
        ("US_RATES", snapshot.get("us_rates", [])),
        ("RISK", snapshot.get("risk", [])),
    ]:
        blocks.append(f"\n[{group_name}]")
        for r in rows:
            blocks.append(
                f"{r['label']}: value={r['value']}; change={r.get('change')}; "
                f"date={r.get('date')}; unit={r.get('unit', '')}"
            )
    return "\n".join(blocks)


# ─── FORMAT ARTICLES FOR GEMINI ────────────────────────────────────────────────
def format_articles(items: dict) -> str:
    labels = {"mexico": "MEXICO / LOCAL", "global": "GLOBAL", "deals": "DEAL TAPE CANDIDATES"}
    blocks = []
    for category in ["mexico", "global", "deals"]:
        if not items.get(category):
            continue
        blocks.append(f"\n{'=' * 70}\n{labels[category]}\n{'=' * 70}")
        for a in items[category]:
            blocks.append(
                f"\nSOURCE: {a['source']}\n"
                f"TITLE: {a['title']}\n"
                f"URL: {a['url']}\n"
                f"CONTENT: {a['body'][:BODY_CHARS]}"
            )
    return "\n".join(blocks)


# ─── GEMINI ANALYSIS ──────────────────────────────────────────────────────────
def generate_analysis(items: dict, snapshot: dict) -> str:
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    now_mx = datetime.datetime.now(MX_TZ)
    date_str = now_mx.strftime("%A, %d %B %Y")
    market_data = market_text_for_prompt(snapshot)
    article_data = format_articles(items)

    prompt = f"""
You are writing the morning desk note for a Managing Director in Structuring at Santander Mexico CIB.
Today is {date_str} (Mexico City).

This is NOT a general financial newspaper and NOT a student briefing.
The reader already understands markets. His time is scarce.

PRIMARY OBJECTIVE
Turn overnight information into client-relevant structuring intelligence:
1) what moved,
2) what changed the distribution of risks,
3) which corporates / sponsors / issuers may now care,
4) which hedge, financing or optionality conversation becomes more relevant,
5) which recent transactions are worth knowing.

HARD RULES
- Use ONLY facts present in the supplied market data and articles.
- NEVER invent prices, spreads, vols, forward points, deal sizes, maturities, counterparties, Santander roles, mandates or client names.
- Clearly separate FACT from INFERENCE. Phrases like "read-through", "could increase demand for", or "worth discussing" are acceptable for inference.
- Do not claim a derivative was executed merely because a financing occurred.
- If a deal candidate lacks enough detail, say so briefly rather than filling gaps.
- If there are no high-confidence deal candidates, explicitly say that the public tape is light today.
- Do not give investment advice or directional trade recommendations.
- Avoid generic phrases such as "markets remain volatile" unless you explain exactly why it matters.
- No Markdown. Return HTML fragments only.

WHAT MATTERS MOST FOR THIS READER
Priority 1: MXN rates / TIIE Funding / Banxico path / SOFR / UST curve.
Priority 2: USD/MXN and major MXN crosses; moves that create hedging urgency for Mexican corporates.
Priority 3: Energy and commodity moves with natural corporate exposures.
Priority 4: DCM, loans, acquisition finance, project finance, securitizations and liability management in Mexico/LatAm.
Priority 5: macro/geopolitics only when it changes rates, FX, credit, funding or client behavior.

STRUCTURING LENS
Possible products may include IRS, cross-currency swaps, FX forwards, vanilla options, collars, caps/floors,
commodity hedges, liability management, local-vs-hard-currency funding or project-finance risk allocation.
Mention a product ONLY when the facts make the relevance plausible. Do not force a product into every story.

AVAILABLE CSS CLASSES
sec, sec-label, lead-text, art, art-title, art-body, tag, tag-mx, tag-us, tag-deal,
angle, angle-label, deal-meta, read-more, radar, radar-title, radar-body, watch-item

OUTPUT STRUCTURE

1. THE OPEN
<div class="sec">
  <div class="sec-label">The open</div>
  <p class="lead-text">One tight paragraph: the 2-3 variables that matter most this morning and the single biggest client implication.</p>
</div>

2. WHAT CHANGED OVERNIGHT
<div class="sec">
  <div class="sec-label">What changed overnight</div>
  Select only 4-6 high-signal items. For each:
  <div class="art">
    <span class="tag tag-mx">MX / FX / RATES / ENERGY as appropriate</span>
    <span class="art-title">Decision-useful headline</span>
    <p class="art-body">Facts first: what happened, catalyst, why it matters for Mexico/client exposures.</p>
    <div class="angle"><span class="angle-label">STRUCTURING ANGLE</span> One concise read-through for hedging/funding/optionality.</div>
    <a href="EXACT_SOURCE_URL" class="read-more" target="_blank">Source →</a>
  </div>
</div>

3. DEAL TAPE
<div class="sec">
  <div class="sec-label">Deal tape</div>
  Select 2-5 genuinely recent financing / capital markets / M&A transactions, prioritizing Mexico, then LatAm.
  For each, state only confirmed terms from source. Then provide a clearly-labelled inference:
  <div class="art">
    <span class="tag tag-deal">DEAL</span>
    <span class="art-title">Issuer / asset / transaction</span>
    <div class="deal-meta">Confirmed transaction facts only.</div>
    <p class="art-body">Why this transaction is strategically notable.</p>
    <div class="angle"><span class="angle-label">STRUCTURING READ-THROUGH</span> Potential rates/FX/commodity/funding relevance, explicitly as inference.</div>
    <a href="EXACT_SOURCE_URL" class="read-more" target="_blank">Source →</a>
  </div>
</div>

4. CLIENT RADAR
<div class="sec">
  <div class="sec-label">Client radar</div>
  Give exactly 3 themes worth raising with Coverage / Sales today.
  <div class="radar">
    <div class="radar-title">Theme</div>
    <div class="radar-body">Which exposure is becoming more relevant, who conceptually has it, and what question to ask. No invented client names.</div>
  </div>
</div>

5. WATCH NEXT
<div class="sec">
  <div class="sec-label">Watch next</div>
  3 concise watch items. Only use catalysts supported by the supplied material; do not invent calendar events or release times.
  <div class="watch-item">...</div>
</div>

IMPORTANT ON MARKET DATA
The market snapshot is rendered separately by Python and will appear above your text.
Use the supplied market numbers for interpretation, but DO NOT recreate a market table and DO NOT contradict the supplied values.

MARKET DATA
{market_data}

ARTICLES / DEAL CANDIDATES
{article_data}
"""

    for attempt in range(3):
        try:
            print(f"   Gemini attempt {attempt + 1}/3...")
            response = model.generate_content(prompt, request_options={"timeout": 180})
            text = response.text.strip()
            # Strip accidental code fences.
            text = re.sub(r"^```html\s*", "", text, flags=re.I)
            text = re.sub(r"```$", "", text).strip()
            return text
        except google.api_core.exceptions.DeadlineExceeded:
            print("   ⚠️ Gemini timeout")
            if attempt < 2:
                time.sleep(12)
        except Exception as exc:
            print(f"   ⚠️ Gemini error: {exc}")
            if attempt < 2:
                time.sleep(12)

    raise RuntimeError("Gemini did not return a response after 3 attempts")


# ─── EMAIL ────────────────────────────────────────────────────────────────────
def send_email(content_html: str):
    if not all([GMAIL_USER, GMAIL_PASS, RECIPIENT]):
        raise RuntimeError("GMAIL_FROM, GMAIL_APP_PASSWORD and GMAIL_TO must be configured")

    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT
    msg["Subject"] = f"Structuring Morning Brief | {datetime.datetime.now(MX_TZ).strftime('%d %b %Y')}"

    date_long = datetime.datetime.now(MX_TZ).strftime("%A, %d %B %Y").upper()

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#ece9e3; font-family: Georgia, 'Times New Roman', serif; color:#171717; }}
  .wrapper {{ max-width:720px; margin:0 auto; background:#fbfaf7; }}
  .masthead {{ background:#111; padding:28px 34px 22px; border-bottom:4px solid #ec0000; }}
  .masthead-title {{ color:#fff; font-family:Arial,sans-serif; font-size:27px; font-weight:800; letter-spacing:1.5px; }}
  .masthead-sub {{ color:#d6d6d6; font-family:Arial,sans-serif; font-size:10px; letter-spacing:1.8px; margin-top:7px; text-transform:uppercase; }}
  .masthead-date {{ color:#8f8f8f; font-family:Arial,sans-serif; font-size:9px; letter-spacing:1px; margin-top:5px; }}
  .body-content {{ padding:28px 34px 34px; }}
  .sec {{ margin-bottom:30px; padding-bottom:26px; border-bottom:1px solid #ddd8d0; }}
  .sec-label {{ font-family:Arial,sans-serif; font-size:10px; font-weight:700; letter-spacing:2.4px; text-transform:uppercase; color:#ec0000; margin-bottom:14px; }}
  .lead-text {{ margin:0; font-size:17px; line-height:1.62; color:#222; }}

  .market-intro {{ font-family:Arial,sans-serif; color:#666; font-size:11px; margin:-4px 0 14px; }}
  .data-note {{ font-family:Arial,sans-serif; font-size:11px; background:#fff3cd; padding:9px 10px; margin-bottom:12px; border:1px solid #f2d98b; }}
  .market-block {{ margin:13px 0 17px; }}
  .market-title {{ font-family:Arial,sans-serif; font-size:11px; font-weight:800; margin-bottom:6px; color:#222; }}
  .market-table {{ width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:11px; }}
  .market-table th {{ text-align:left; color:#777; font-size:9px; text-transform:uppercase; letter-spacing:.7px; padding:6px 5px; border-bottom:1px solid #bbb; }}
  .market-table td {{ padding:7px 5px; border-bottom:1px solid #ece8e1; }}
  .mkt-name {{ font-weight:700; }}
  .mkt-val, .mkt-chg {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .mkt-date {{ text-align:right; color:#999; font-size:9px; }}

  .art {{ margin:0 0 21px; padding-left:13px; border-left:2px solid #d8d3ca; }}
  .art-title {{ display:block; font-size:15px; font-weight:700; line-height:1.35; margin:2px 0 6px; }}
  .art-body {{ margin:0 0 8px; color:#444; font-size:13px; line-height:1.62; }}
  .tag {{ display:inline-block; font-family:Arial,sans-serif; font-size:8px; font-weight:800; letter-spacing:1.2px; padding:3px 6px; margin-bottom:4px; border-radius:2px; }}
  .tag-mx {{ background:#e7f2ed; color:#006847; }}
  .tag-us {{ background:#e8eef7; color:#214a7a; }}
  .tag-deal {{ background:#111; color:#fff; }}
  .deal-meta {{ font-family:Arial,sans-serif; font-size:11px; line-height:1.5; color:#666; margin:5px 0 8px; }}
  .angle {{ background:#f2f0ec; padding:9px 10px; margin:9px 0 8px; font-family:Arial,sans-serif; font-size:11.5px; line-height:1.5; color:#333; }}
  .angle-label {{ color:#ec0000; font-size:9px; font-weight:800; letter-spacing:1px; margin-right:5px; }}
  .read-more {{ font-family:Arial,sans-serif; font-size:10px; color:#a60000; text-decoration:none; border-bottom:1px solid #a60000; }}

  .radar {{ background:#111; color:#fff; padding:14px 15px; margin-bottom:10px; }}
  .radar-title {{ font-family:Arial,sans-serif; font-weight:800; font-size:12px; margin-bottom:5px; }}
  .radar-body {{ font-family:Arial,sans-serif; color:#d0d0d0; font-size:11.5px; line-height:1.55; }}
  .watch-item {{ font-family:Arial,sans-serif; font-size:12px; line-height:1.55; padding:8px 0; border-bottom:1px solid #ece8e1; }}

  .footer {{ background:#111; padding:17px 34px; }}
  .footer p {{ margin:0; font-family:Arial,sans-serif; font-size:8px; line-height:1.7; color:#666; letter-spacing:.4px; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="masthead">
    <div class="masthead-title">STRUCTURING MORNING BRIEF</div>
    <div class="masthead-sub">MXN · Rates · FX · Credit · Deal Tape</div>
    <div class="masthead-date">{html.escape(date_long)}</div>
  </div>
  <div class="body-content">{content_html}</div>
  <div class="footer">
    <p>PUBLIC-SOURCE MORNING NOTE · AUTOMATED · NOT INVESTMENT ADVICE<br>
    Market data: Banxico SIE · New York Fed · U.S. Treasury · Yahoo market proxies<br>
    News: Reuters / Bloomberg via Google News · FT · El Financiero · El Economista · public deal sources<br>
    AI analysis: Gemini 2.5 Flash</p>
  </div>
</div>
</body>
</html>"""

    msg.attach(MIMEText(html_doc, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.send_message(msg)
    print(f"   ✅ Email sent to {RECIPIENT}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("\n📈 Structuring Morning Brief — starting...\n")

    seen = load_seen()
    print(f"💾 {len(seen)} URLs in de-dup memory")

    snapshot = fetch_market_snapshot()

    print("\n📰 Fetching news and deal tape...")
    items, new_urls = fetch_news(seen)
    print(
        f"\n✅ News: {len(items['mexico'])} MX · {len(items['global'])} global · "
        f"{len(items['deals'])} deals"
    )

    print("\n🤖 Generating MD-level analysis...")
    analysis_html = generate_analysis(items, snapshot)

    market_html = render_market_snapshot(snapshot)
    full_content = market_html + analysis_html

    print("📧 Sending email...")
    send_email(full_content)

    save_seen(new_urls, seen)
    print("\n✅ Done.\n")


if __name__ == "__main__":
    main()
