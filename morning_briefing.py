"""
MORNING BRIEFING — MODO TEST (sin Gemini, sin tokens)
Verifica: RSS fetch → filtrado → email HTML
"""

import feedparser
import datetime
import json
import os
import smtplib
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
GMAIL_USER = os.getenv("GMAIL_FROM")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT  = os.getenv("GMAIL_TO")

VISTAS_PATH = Path.home() / ".morning_briefing_seen.json"

# ─── FUENTES RSS ──────────────────────────────────────────────────────────────
RSS_FEEDS = {
    "Expansión":           "https://expansion.mx/rss",
    "El Financiero Eco":   "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/?outputType=xml&hierarchy=economia",
    "El Financiero Mdo":   "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/?outputType=xml&hierarchy=mercados",
    "Forbes México":       "https://www.forbes.com.mx/feed/",
    "El Economista":       "https://www.eleconomista.com.mx/rss/economia.xml",
    "Reforma Negocios":    "https://www.reforma.com/rss/negocios.xml",
    "FT Markets":          "https://www.ft.com/markets?format=rss",
    "CNBC Economy":        "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "Yahoo Finance":       "https://finance.yahoo.com/news/rssindex",
    "Reuters Business":    "https://feeds.reuters.com/reuters/businessNews",
    "Econbrowser":         "https://econbrowser.com/feed",
    "Macario Schettino":   "https://macario.substack.com/feed",
    "ECONOMEX":            "https://economex.substack.com/feed",
    "Michael Burry":       "https://michaeljburry.substack.com/feed",
    "Adam Tooze":          "https://adamtooze.substack.com/feed",
    "Noah Smith":          "https://noahpinion.substack.com/feed",
    "Paul Krugman":        "https://paulkrugman.substack.com/feed",
}

OPINION_SOURCES = {
    "Macario Schettino", "ECONOMEX", "Michael Burry",
    "Adam Tooze", "Noah Smith", "Paul Krugman",
}

KEYWORDS_MEXICO = [
    "mexico", "méxico", "banxico", "mxn", "peso mexicano", "pemex",
    "sheinbaum", "usmca", "t-mec", "nearshoring", "citibanamex",
    "bbva mexico", "inegi", "coneval", "fibra", "bmv", "cetes",
    "udibonos", "secretaría de hacienda", "reforma fiscal", "aifa",
]
KEYWORDS_MACRO = [
    "fed", "federal reserve", "inflation", "cpi", "pce", "gdp",
    "recession", "rate hike", "rate cut", "treasury", "yields",
    "fomc", "powell", "warsh", "emerging markets", "latam",
    "oil", "wti", "brent", "opec", "dollar", "dxy",
    "tariff", "trade war", "arancel", "strait of hormuz",
    "iran", "interest rate", "employment", "jobs report",
    "central bank", "monetary policy",
]
BLACKLIST = [
    "crypto", "bitcoin", "nft", "soccer", "celebrity",
    "lifestyle", "fashion", "kardashian", "horoscope",
    "mortgage and refinance", "best high-yield savings", "best cd rate",
    "heloc and home equity", "best money market", "mortgage rate sale",
    "when will mortgage", "historical mortgage", "savings rate today",
    "analyst report:", "stock forecast", "earnings call highlights",
    "world cup", "masterchef", "rose farts",
]

MAX_ARTICLES_PER_FEED = 3
MAX_TOTAL_ARTICLES    = 25
HORAS_MAX_ARTICULO    = 72


# ─── MEMORIA ──────────────────────────────────────────────────────────────────

def cargar_vistos() -> set:
    try:
        data = json.loads(VISTAS_PATH.read_text())
        hace_7_dias = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        return {url for url, fecha in data.items() if fecha >= hace_7_dias}
    except Exception:
        return set()


def guardar_vistos(urls_nuevas: set, urls_previas: set):
    hoy = datetime.date.today().isoformat()
    try:
        data = json.loads(VISTAS_PATH.read_text())
    except Exception:
        data = {}
    for url in urls_previas | urls_nuevas:
        data[url] = hoy
    VISTAS_PATH.write_text(json.dumps(data, indent=2))


# ─── FILTRADO ─────────────────────────────────────────────────────────────────

def es_relevante(texto: str, fuente: str = "") -> tuple:
    t = texto.lower().replace("new mexico", "new_mexico")
    if any(bl in t for bl in BLACKLIST):
        return False, ""
    if fuente in OPINION_SOURCES:
        return True, "opinion"
    if any(kw in t for kw in KEYWORDS_MEXICO):
        return True, "mexico"
    if any(kw in t for kw in KEYWORDS_MACRO):
        return True, "macro"
    return False, ""


def es_reciente(entry) -> bool:
    publicado = entry.get("published_parsed")
    if not publicado:
        return True
    pub_dt = datetime.datetime(*publicado[:6])
    antiguedad = (
        datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - pub_dt
    ).total_seconds()
    return antiguedad <= HORAS_MAX_ARTICULO * 3600


# ─── FETCH ────────────────────────────────────────────────────────────────────

def fetch_noticias(urls_vistas: set) -> tuple:
    noticias    = {"mexico": [], "macro": [], "opinion": []}
    urls_nuevas = set()

    for fuente, feed_url in RSS_FEEDS.items():
        if sum(len(v) for v in noticias.values()) >= MAX_TOTAL_ARTICLES:
            print(f"\n   ⛔ Tope de {MAX_TOTAL_ARTICLES} artículos alcanzado.")
            break

        print(f"\n   📡 {fuente}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"      ⚠️  Error: {e}")
            continue

        print(f"      → {len(feed.entries)} entradas")
        if not feed.entries:
            print("      ⚠️  Feed vacío o URL incorrecta")
            continue

        count = 0
        for entry in feed.entries:
            if count >= MAX_ARTICLES_PER_FEED:
                break
            if sum(len(v) for v in noticias.values()) >= MAX_TOTAL_ARTICLES:
                break

            titulo  = entry.get("title", "").strip()
            resumen = entry.get("summary", "").strip()[:300]
            link    = entry.get("link", "")

            if link and link in urls_vistas:
                print(f"      ⏭️  Ya visto:      {titulo[:55]}")
                continue
            if not es_reciente(entry):
                pub = entry.get("published", "sin fecha")
                print(f"      🕰️  Muy viejo:     {titulo[:45]} [{pub[:16]}]")
                continue

            relevante, categoria = es_relevante(titulo + " " + resumen, fuente)
            if not relevante:
                print(f"      🚫 No relevante:  {titulo[:55]}")
                continue

            emoji = {"mexico": "🇲🇽", "macro": "🌎", "opinion": "💬"}.get(categoria, "✅")
            print(f"      {emoji} [{categoria.upper():7}]  {titulo[:55]}")

            noticias[categoria].append({
                "fuente":  fuente,
                "titulo":  titulo,
                "resumen": resumen,
                "url":     link,
                "cuerpo":  resumen,   # Sin scraping en modo test
            })

            if link:
                urls_nuevas.add(link)
            count += 1

    return noticias, urls_nuevas


# ─── MOCK GEMINI — HTML estático de prueba ────────────────────────────────────

def generar_analisis_mock(noticias: dict) -> str:
    """
    Reemplaza la llamada a Gemini por un briefing HTML de prueba.
    Usa los artículos reales que SÍ descargaste, así puedes ver qué llegó.
    No consume ningún token de Gemini.
    """
    fecha = datetime.date.today().strftime("%A, %d de %B de %Y")

    def make_arts(articulos, tag_class, tag_label):
        if not articulos:
            return f'<p style="color:#888;font-size:13px">No se encontraron artículos en esta categoría hoy.</p>'
        html = ""
        for a in articulos[:4]:
            url = a["url"] or "#"
            html += f"""
            <div class="art">
              <span class="tag {tag_class}">{tag_label}</span>
              <span class="art-title">{a["titulo"]}</span>
              <p class="art-body">{a["resumen"] or "Sin resumen disponible."}</p>
              <a href="{url}" class="read-more" target="_blank">Leer artículo completo →</a>
            </div>"""
        return html

    mx_arts  = make_arts(noticias.get("mexico",  []), "tag-mx", "MÉXICO")
    us_arts  = make_arts(noticias.get("macro",   []), "tag-us", "GLOBAL")
    op_arts  = make_arts(noticias.get("opinion", []), "tag-op", "OPINIÓN")

    total = sum(len(v) for v in noticias.values())

    return f"""
<div class="sec">
  <div class="sec-label">⚠️ Modo Test — Sin Gemini</div>
  <p class="lead-text">
    Este es un briefing de prueba generado sin llamar a Gemini.
    El pipeline de RSS funcionó correctamente y encontró <strong>{total} artículos</strong>
    ({len(noticias.get("mexico",[]))} MX · {len(noticias.get("macro",[]))} macro ·
    {len(noticias.get("opinion",[]))} opinión).
    Si ves esto en tu bandeja de entrada, el sistema funciona de extremo a extremo. ✅
  </p>
</div>

<div class="sec">
  <div class="sec-label">México hoy</div>
  {mx_arts}
</div>

<div class="sec">
  <div class="sec-label">El mundo</div>
  {us_arts}
</div>

<div class="sec">
  <div class="sec-label">Opinión y análisis</div>
  {op_arts}
</div>

<div class="sec">
  <div class="sec-label">Talking points de prueba</div>
  <div class="tp">
    <div class="tp-num">01 / TEST</div>
    <div class="tp-title">El pipeline funciona</div>
    <p class="tp-body">
      Se descargaron {total} artículos de {len([f for f in RSS_FEEDS])} fuentes RSS,
      se filtraron por keywords y blacklist, y el email llegó correctamente formateado.
    </p>
    <p class="tp-q">¿Qué pasa cuando reemplazas esta función mock por la llamada real a Gemini?</p>
  </div>
  <div class="tp">
    <div class="tp-num">02 / SIGUIENTE PASO</div>
    <div class="tp-title">Activar Gemini</div>
    <p class="tp-body">
      Cuando confirmes que el email se ve bien, reemplaza <code>generar_analisis_mock()</code>
      por <code>generar_analisis()</code> en el main() y restaura el import de google.generativeai.
    </p>
    <p class="tp-q">¿El diseño del email se renderiza correctamente en tu cliente de correo?</p>
  </div>
</div>

<div class="sec">
  <div class="sec-label">Para seguir esta semana</div>
  <div class="art">
    <span class="tag tag-us">TEST</span>
    <span class="art-title">Verificar que el historial se guarda</span>
    <p class="art-body">
      Revisa tu repo en GitHub — debe haber un commit automático que actualiza
      <code>morning_briefing_seen.json</code> con las {total} URLs procesadas hoy.
    </p>
    <a href="https://github.com" class="read-more" target="_blank">Ver repo en GitHub →</a>
  </div>
</div>
"""


# ─── EMAIL ────────────────────────────────────────────────────────────────────

def enviar_email(contenido_html: str):
    msg = MIMEMultipart()
    msg['From']    = GMAIL_USER
    msg['To']      = RECIPIENT
    msg['Subject'] = f"[TEST] The Daily Brief | {datetime.date.today().strftime('%d %b %Y')}"

    fecha_larga = datetime.date.today().strftime("%A, %d de %B de %Y").upper()

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Source+Serif+4:ital,opsz,wght@0,8..60,300;0,8..60,400;1,8..60,300&family=IBM+Plex+Mono:wght@400&display=swap');
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #f0ebe0; font-family: 'Source Serif 4', Georgia, serif; color: #1a1a1a; font-size: 15px; line-height: 1.65; }}
    .wrapper {{ max-width: 640px; margin: 0 auto; background: #faf7f2; }}
    .masthead {{ background: #111; padding: 28px 32px 20px; text-align: center; border-bottom: 3px solid #c8a84b; }}
    .masthead-title {{ font-family: 'Playfair Display', Georgia, serif; font-size: 30px; font-weight: 900; color: #faf7f2; letter-spacing: 3px; text-transform: uppercase; }}
    .masthead-sub {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: #c8a84b; letter-spacing: 2px; margin-top: 6px; }}
    .masthead-date {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: #666; margin-top: 4px; letter-spacing: 1px; }}
    .body-content {{ padding: 28px 32px; }}
    .sec {{ margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid #ddd8cc; }}
    .sec:last-child {{ border-bottom: none; margin-bottom: 0; }}
    .sec-label {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 3px; text-transform: uppercase; color: #c8a84b; margin-bottom: 14px; padding-bottom: 6px; border-bottom: 1px solid #c8a84b; }}
    .lead-text {{ font-size: 16px; font-weight: 300; font-style: italic; color: #222; line-height: 1.75; }}
    .art {{ margin-bottom: 20px; padding-left: 12px; border-left: 2px solid #ddd8cc; }}
    .art-title {{ font-family: 'Playfair Display', Georgia, serif; font-size: 14px; font-weight: 700; display: block; margin-bottom: 5px; color: #1a1a1a; }}
    .art-body {{ font-size: 13px; line-height: 1.65; color: #444; margin-bottom: 6px; }}
    .read-more {{ display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 1px; color: #c8a84b; text-decoration: none; border-bottom: 1px solid #c8a84b; padding-bottom: 1px; }}
    .tag {{ display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 8px; letter-spacing: 1.5px; text-transform: uppercase; padding: 2px 6px; border-radius: 2px; margin-bottom: 6px; }}
    .tag-mx {{ background: #006847; color: #d0ead8; }}
    .tag-us {{ background: #1a3a6b; color: #ccdcf0; }}
    .tag-op {{ background: #5a3010; color: #f0dcc8; }}
    .tp {{ background: #111; border-radius: 4px; padding: 16px 18px; margin-bottom: 12px; }}
    .tp-num {{ font-family: 'IBM Plex Mono', monospace; font-size: 8px; letter-spacing: 2px; color: #c8a84b; text-transform: uppercase; margin-bottom: 6px; }}
    .tp-title {{ font-family: 'Playfair Display', Georgia, serif; font-size: 14px; font-weight: 700; color: #faf7f2; margin-bottom: 8px; }}
    .tp-body {{ font-size: 13px; line-height: 1.6; color: #ccc; }}
    .tp-q {{ margin-top: 10px; padding-top: 10px; border-top: 1px solid #2a2a2a; font-style: italic; color: #c8a84b; font-size: 13px; }}
    .footer {{ background: #111; padding: 18px 32px; text-align: center; }}
    .footer p {{ font-family: 'IBM Plex Mono', monospace; font-size: 8px; color: #555; letter-spacing: 0.5px; line-height: 1.9; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="masthead">
      <div class="masthead-title">The Daily Brief</div>
      <div class="masthead-sub">⚠️ TEST MODE — Sin Gemini</div>
      <div class="masthead-date">{fecha_larga}</div>
    </div>
    <div class="body-content">{contenido_html}</div>
    <div class="footer">
      <p>
        MODO TEST · SIN TOKENS GEMINI · SOLO VERIFICACIÓN DE PIPELINE<br>
        Fuentes RSS activas · Filtrado funcional · Email HTML verificado
      </p>
    </div>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.send_message(msg)
    print(f"   ✅ Email TEST enviado a {RECIPIENT}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("\n🧪 Morning Briefing — MODO TEST (sin Gemini)\n")

    print("💾 Cargando historial...")
    urls_vistas = cargar_vistos()
    print(f"   {len(urls_vistas)} URLs en memoria.\n")

    print("📡 Descargando y filtrando noticias...")
    noticias, urls_nuevas = fetch_noticias(urls_vistas)

    total_mx      = len(noticias["mexico"])
    total_macro   = len(noticias["macro"])
    total_opinion = len(noticias["opinion"])
    total         = total_mx + total_macro + total_opinion

    print(f"\n{'─'*50}")
    print(f"✅ {total} artículos: {total_mx} MX · {total_macro} macro · {total_opinion} opinión\n")

    if total == 0:
        print("❌ Sin noticias nuevas. Revisa los feeds manualmente.")
        # Enviamos el email de todas formas para verificar el diseño
        print("   Enviando email de prueba vacío de todas formas...")

    print("📝 Generando HTML mock (sin Gemini)...")
    analisis = generar_analisis_mock(noticias)

    print("📧 Enviando email...")
    enviar_email(analisis)

    print("💾 Guardando historial...")
    guardar_vistos(urls_nuevas, urls_vistas)

    print("\n✅ Test completo. Revisa tu bandeja.\n")
    print("   Cuando el email se vea bien, cambia generar_analisis_mock()")
    print("   por generar_analisis() y restaura el import de google.generativeai.")


if __name__ == "__main__":
    main()
