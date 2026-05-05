"""
MORNING BRIEFING — Tu periódico financiero personal
Cubre: México + EE.UU. | Mercados + Opinión + Ideas de conversación
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
import google.generativeai as genai

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_FROM")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT  = os.getenv("GMAIL_TO")

VISTAS_PATH = Path.home() / ".morning_briefing_seen.json"

# ─── FUENTES RSS ──────────────────────────────────────────────────────────────
# Todas verificadas y activas (Mayo 2026)
RSS_FEEDS = {
    # ── México ────────────────────────────────────────────────────────────────
    "Expansión":          "https://expansion.mx/rss",
    "El Financiero Eco":  "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/?outputType=xml&hierarchy=economia",
    "El Financiero Mdo":  "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/?outputType=xml&hierarchy=mercados",
    "El Economista":      "https://www.eleconomista.com.mx/rss/mercados", # Sustituto de Milenio
    "Forbes México":      "https://www.forbes.com.mx/category/negocios/feed/",
    "Reforma Negocios":   "https://www.reforma.com/rss/negocios.xml",

    # ── EE.UU. / Global ───────────────────────────────────────────────────────
    "WSJ Markets":        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", # Sustituto de Reuters
    "FT Markets":         "https://www.ft.com/markets?format=rss",
    "CNBC Economy":       "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", # URL nativa de CNBC
    "Yahoo Finance":      "https://finance.yahoo.com/news/rssindex",
    "Investing Macro":    "https://mx.investing.com/rss/news_285", # Excelente para datos duros macroeconómicos

    # ── Opinión / Análisis ────────────────────────────────────────────────────
    "Econbrowser":        "https://econbrowser.com/feed",
    "Calculated Risk":    "https://www.calculatedriskblog.com/feeds/posts/default",
    "Marginal Revolution":"https://marginalrevolution.com/feed", # URL corregida (Feedburner ya no sirve)
}

# ─── FILTROS ──────────────────────────────────────────────────────────────────
KEYWORDS_MEXICO = [
    "mexico", "méxico", "banxico", "mxn", "peso mexicano", "pemex",
    "sheinbaum", "usmca", "t-mec", "nearshoring", "citibanamex",
    "bbva mexico", "inegi", "coneval", "fibra", "bmv", "cetes",
    "udibonos", "hacienda mexico", "secretaría de hacienda",
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
    "mortgage rate today", "cd rate", "savings rate today",
    "heloc", "analyst report:", "stock forecast",
]

MAX_ARTICLES_PER_FEED = 5
SCRAPE_TIMEOUT        = 8
HORAS_MAX_ARTICULO    = 72  # ampliado a 72h para no perder noticias del fin de semana


# ─── MEMORIA ANTI-REPETICIÓN ──────────────────────────────────────────────────

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

def es_relevante(texto: str) -> tuple:
    t = texto.lower()
    t = t.replace("new mexico", "new_mexico")  # evitar falsos positivos
    # Blacklist por frase exacta
    if any(bl in t for bl in BLACKLIST):
        return False, ""
    if any(kw in t for kw in KEYWORDS_MEXICO):
        return True, "mexico"
    if any(kw in t for kw in KEYWORDS_MACRO):
        return True, "macro"
    return False, ""


def es_reciente(entry) -> bool:
    publicado = entry.get("published_parsed")
    if not publicado:
        return True  # sin fecha → no descartar
    pub_dt = datetime.datetime(*publicado[:6])
    antiguedad = (
        datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - pub_dt
    ).total_seconds()
    return antiguedad <= HORAS_MAX_ARTICULO * 3600


# ─── SCRAPING DEL ARTÍCULO COMPLETO ──────────────────────────────────────────

def scrape_articulo(url: str) -> str:
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=SCRAPE_TIMEOUT)
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "iframe", "noscript"]):
            tag.decompose()

        content = ""
        for selector in [
            "article",
            "[class*='article-body']",
            "[class*='story-body']",
            "[class*='content-body']",
            "[class*='entry-content']",
            "[class*='post-content']",
            "main",
        ]:
            found = soup.select_one(selector)
            if found:
                content = found.get_text(separator=" ", strip=True)
                break

        if not content:
            content = soup.get_text(separator=" ", strip=True)

        words = content.split()
        return " ".join(words[:800])

    except Exception:
        return ""


# ─── FETCH DE NOTICIAS ────────────────────────────────────────────────────────

def fetch_noticias(urls_vistas: set) -> tuple:
    noticias    = {"mexico": [], "macro": []}
    urls_nuevas = set()

    for fuente, feed_url in RSS_FEEDS.items():
        print(f"\n   📡 {fuente}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"      ⚠️  Error leyendo feed: {e}")
            continue

        print(f"      → {len(feed.entries)} entradas en el feed")

        if len(feed.entries) == 0:
            print("      ⚠️  Feed vacío o URL incorrecta")
            continue

        count = 0
        for entry in feed.entries:
            if count >= MAX_ARTICLES_PER_FEED:
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

            relevante, categoria = es_relevante(titulo + " " + resumen)
            if not relevante:
                print(f"      🚫 No relevante:  {titulo[:55]}")
                continue

            print(f"      ✅ [{categoria.upper():6}]    {titulo[:55]}")

            cuerpo = ""
            if link:
                cuerpo = scrape_articulo(link)
                time.sleep(0.4)

            noticias[categoria].append({
                "fuente":  fuente,
                "titulo":  titulo,
                "resumen": resumen,
                "url":     link,
                "cuerpo":  cuerpo if cuerpo else resumen,
            })

            if link:
                urls_nuevas.add(link)
            count += 1

    return noticias, urls_nuevas


# ─── FORMATEAR PARA GEMINI ────────────────────────────────────────────────────

def formatear_para_prompt(noticias: dict) -> str:
    bloques = []
    for categoria, articulos in noticias.items():
        label = "NOTICIAS MÉXICO" if categoria == "mexico" else "MACRO / EE.UU."
        bloques.append(f"\n{'='*60}\n{label}\n{'='*60}")
        for a in articulos:
            bloques.append(
                f"\nFUENTE: {a['fuente']}\n"
                f"TÍTULO: {a['titulo']}\n"
                f"CONTENIDO: {a['cuerpo'][:600]}..."
            )
    return "\n".join(bloques)


# ─── ANÁLISIS CON GEMINI ──────────────────────────────────────────────────────
def generar_analisis(noticias: dict) -> str:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
 
    noticias_texto = formatear_para_prompt(noticias)
    fecha = datetime.date.today().strftime("%A, %d de %B de %Y")
 
    prompt = f"""
Eres el editor en jefe de un periódico financiero de élite, como el FT o Reforma Financiero.
Hoy es {fecha}.
 
Tu tarea: escribir el briefing matutino en HTML para un lector que es un profesional de finanzas o economía en formación.
El tono es el de un buen periódico: claro, directo, inteligente — no jerga de trading, no buzzwords corporativos.
 
El lector usa este briefing para:
  1. Mantenerse al día con lo que importa
  2. Tener IDEAS sobre qué hablar en entrevistas o conversaciones de negocios
  3. Entender el contexto detrás de los números
 
INSTRUCCIONES DE FORMATO:
- Escribe SOLO HTML interno (sin <html>, <head> ni <body>)
- Usa estas clases CSS que ya existen: section-title, lead, article-item, talking-point, tag-mx, tag-us, tag-opinion
- NO uses Markdown. NO uses asteriscos. NO uses guiones para listas.
- Separa secciones con <div class="section">
- Cada artículo/tema: <div class="article-item">
- Títulos de sección: <h2 class="section-title">
- Etiquetas: <span class="tag-mx">MÉXICO</span> o <span class="tag-us">EE.UU.</span>
 
ESTRUCTURA DEL BRIEFING:
 
1. PORTADA (1 párrafo editorial, la historia más importante del día y por qué importa)
 
2. MÉXICO HOY (3-4 temas clave de México con 2-3 oraciones cada uno.
   Incluye: tipo de cambio si hay movimiento, tasa Banxico, cualquier noticia política-económica)
 
3. EL MUNDO (3-4 temas macro: Fed, economía americana, commodities, lo que mueve mercados)
 
4. DE QUÉ HABLAR HOY
   3 talking points concretos para una entrevista o conversación:
   - Qué pasó
   - Por qué importa
   - Una pregunta inteligente que puedes hacer
 
5. PARA LEER MÁS (2-3 temas de fondo que vale la pena seguir esta semana)
 
NOTICIAS DEL DÍA:
{noticias_texto}
"""
 
    response = model.generate_content(prompt)
    return response.text
# ─── EMAIL HTML ───────────────────────────────────────────────────────────────

def enviar_email(contenido_html: str):
    msg = MIMEMultipart()
    msg['From']    = GMAIL_USER
    msg['To']      = RECIPIENT
    msg['Subject'] = f"The Daily Brief | {datetime.date.today().strftime('%d %b %Y')}"

    fecha_larga = datetime.date.today().strftime("%A, %d de %B de %Y").upper()

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Source+Serif+4:ital,opsz,wght@0,8..60,300;0,8..60,400;1,8..60,300&family=IBM+Plex+Mono:wght@400&display=swap');

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #f0ebe0;
      font-family: 'Source Serif 4', Georgia, serif;
      color: #1a1a1a;
      font-size: 15px;
      line-height: 1.65;
    }}
    .wrapper {{ max-width: 640px; margin: 0 auto; background: #faf7f2; }}

    .masthead {{
      background: #111;
      padding: 28px 32px 20px;
      text-align: center;
      border-bottom: 3px solid #c8a84b;
    }}
    .masthead-title {{
      font-family: 'Playfair Display', Georgia, serif;
      font-size: 30px; font-weight: 900;
      color: #faf7f2; letter-spacing: 3px; text-transform: uppercase;
    }}
    .masthead-sub {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 9px; color: #c8a84b; letter-spacing: 2px; margin-top: 6px;
    }}
    .masthead-date {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 9px; color: #666; margin-top: 4px; letter-spacing: 1px;
    }}

    .body-content {{ padding: 28px 32px; }}

    .sec {{
      margin-bottom: 28px; padding-bottom: 24px;
      border-bottom: 1px solid #ddd8cc;
    }}
    .sec:last-child {{ border-bottom: none; margin-bottom: 0; }}

    .sec-label {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 9px; letter-spacing: 3px; text-transform: uppercase;
      color: #c8a84b; margin-bottom: 14px;
      padding-bottom: 6px; border-bottom: 1px solid #c8a84b;
    }}

    .lead-text {{
      font-size: 16px; font-weight: 300; font-style: italic;
      color: #222; line-height: 1.75;
    }}

    .art {{
      margin-bottom: 18px; padding-left: 12px;
      border-left: 2px solid #ddd8cc;
    }}
    .art-title {{
      font-family: 'Playfair Display', Georgia, serif;
      font-size: 14px; font-weight: 700;
      display: block; margin-bottom: 5px; color: #1a1a1a;
    }}
    .art-body {{ font-size: 13px; line-height: 1.65; color: #444; }}

    .tag {{
      display: inline-block;
      font-family: 'IBM Plex Mono', monospace;
      font-size: 8px; letter-spacing: 1.5px; text-transform: uppercase;
      padding: 2px 6px; border-radius: 2px; margin-bottom: 6px;
    }}
    .tag-mx  {{ background: #006847; color: #d0ead8; }}
    .tag-us  {{ background: #1a3a6b; color: #ccdcf0; }}
    .tag-op  {{ background: #5a3010; color: #f0dcc8; }}

    .tp {{
      background: #111; border-radius: 4px;
      padding: 16px 18px; margin-bottom: 12px;
    }}
    .tp-num {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 8px; letter-spacing: 2px; color: #c8a84b;
      text-transform: uppercase; margin-bottom: 6px;
    }}
    .tp-title {{
      font-family: 'Playfair Display', Georgia, serif;
      font-size: 14px; font-weight: 700; color: #faf7f2; margin-bottom: 8px;
    }}
    .tp-body {{ font-size: 13px; line-height: 1.6; color: #ccc; }}
    .tp-q {{
      margin-top: 10px; padding-top: 10px;
      border-top: 1px solid #2a2a2a;
      font-style: italic; color: #c8a84b; font-size: 13px;
    }}

    .footer {{ background: #111; padding: 18px 32px; text-align: center; }}
    .footer p {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 8px; color: #555; letter-spacing: 0.5px; line-height: 1.9;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="masthead">
      <div class="masthead-title">The Daily Brief</div>
      <div class="masthead-sub">Economía · Mercados · México · Global</div>
      <div class="masthead-date">{fecha_larga}</div>
    </div>

    <div class="body-content">
      {contenido_html}
    </div>

    <div class="footer">
      <p>
        GENERADO AUTOMÁTICAMENTE · SOLO USO PERSONAL<br>
        Fuentes: Reuters · AP · FT · CNBC · Expansión · El Financiero · Milenio<br>
        Análisis: Google Gemini 2.5 Flash
      </p>
    </div>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.send_message(msg)

    print(f"   ✅ Email enviado a {RECIPIENT}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("\n🗞️  Morning Briefing — iniciando...\n")

    print("💾 Cargando historial de noticias vistas...")
    urls_vistas = cargar_vistos()
    print(f"   {len(urls_vistas)} URLs en memoria.\n")

    print("📡 Descargando y filtrando noticias...")
    noticias, urls_nuevas = fetch_noticias(urls_vistas)

    total_mx    = len(noticias["mexico"])
    total_macro = len(noticias["macro"])
    total       = total_mx + total_macro

    print(f"\n{'─'*50}")
    if total == 0:
        print("❌ Sin noticias nuevas relevantes hoy.")
        print("   Revisa los 🕰️  y 🚫 arriba para entender por qué.")
        return

    print(f"✅ {total} artículos nuevos: {total_mx} de México / {total_macro} macro\n")

    print("🤖 Generando análisis con Gemini 2.5 Flash...")
    analisis = generar_analisis(noticias)

    print("📧 Enviando email...")
    enviar_email(analisis)

    print("💾 Guardando historial actualizado...")
    guardar_vistos(urls_nuevas, urls_vistas)

    print("\n✅ ¡Listo! Revisa tu bandeja de entrada.\n")


if __name__ == "__main__":
    main()