# Morning Brief

Briefing diario automatizado de mercados, diseñado para un flujo de trabajo de CIB / Structuring con enfoque en México.

La idea nace de un problema simple: la información útil para arrancar el día suele estar dispersa entre páginas de mercado, feeds de noticias, anuncios de operaciones y chats de traders. Este script reúne esas fuentes, filtra el ruido y envía un correo matutino conciso centrado en una sola pregunta:

> **¿Qué cambió, qué clientes podrían verse afectados y qué conversaciones de Structuring podrían volverse relevantes?**

Gemini actúa como editor, no como fuente de datos. Los niveles de mercado se obtienen directamente mediante Python desde fuentes públicas, mientras que Gemini convierte las noticias y operaciones recopiladas en una lectura estructurada para la mañana.

---

## Qué incluye

### Foto de mercado

Python obtiene los datos de mercado directamente desde fuentes públicas antes de generar el análisis de noticias.

La cobertura actual incluye:

- USD/MXN y cruces relevantes contra MXN
- FIX de Banxico y referencias cambiarias
- Tasa objetivo de Banxico
- TIIE de Fondeo O/N
- TIIE 28D / 91D
- CETES 28D
- SOFR
- U.S. Treasury 2Y / 5Y / 10Y / 30Y
- UST 2s10s
- Indicadores globales de riesgo seleccionados

Las principales fuentes son:

- Banco de México SIE
- New York Fed
- U.S. Treasury
- Yahoo Finance
- Referencias cambiarias del BCE como respaldo

Los niveles de mercado se renderizan directamente desde Python y no son reescritos por el LLM.

---

## Noticias y búsqueda de operaciones

El script monitorea una combinación de feeds RSS directos y búsquedas dirigidas en Google News.

### México / mercados locales

- El Financiero
- El Economista
- Reuters
- Bloomberg

### Mercados globales

- Financial Times
- Reuters Global Markets
- Reuters LatAm

### Operaciones

Las búsquedas dedicadas monitorean actividad reciente en:

- Emisiones de bonos / DCM
- Préstamos sindicados
- Refinanciamientos
- Project finance
- Structured finance
- Financiamiento de infraestructura
- Bursatilizaciones / securitizations
- Acquisition finance
- M&A
- Operaciones relacionadas con Santander en México y Latinoamérica

Google News se utiliza principalmente como capa de descubrimiento. Después, el script aplica filtros adicionales de recencia, relevancia, términos de transacción y duplicados antes de enviar cualquier contenido a Gemini.

---

## Estructura del briefing

Cada correo se organiza en:

1. **Foto de mercado**  
   FX, tasas MXN, SOFR, U.S. Treasuries e indicadores de riesgo.

2. **Apertura**  
   Los dos o tres desarrollos más importantes de la mañana.

3. **Qué cambió**  
   Temas de alta señal en tasas, FX, commodities, macro y sectores relevantes.

4. **Operaciones recientes**  
   Financiamientos, mercados de capitales, project finance y M&A recientes, con una breve lectura desde la óptica de Structuring.

5. **Radar de clientes**  
   Tres exposiciones o conversaciones que vale la pena discutir con Coverage / Sales.

6. **Qué vigilar**  
   Desarrollos de corto plazo que podrían cambiar tasas, FX, condiciones de fondeo o comportamiento de clientes.

---

## Capa de IA

El briefing utiliza actualmente **Gemini 2.5 Flash**.

El modelo está instruido para:

- Separar hechos confirmados de inferencias
- No inventar niveles de mercado ni términos de operaciones
- No asumir que un titular expresado en equivalente USD implica deuda denominada en USD
- No asumir que un financiamiento incluyó hedge, swap o derivado
- Distinguir operaciones cerradas de operaciones aún en estructuración
- Utilizar lenguaje condicional para posibles oportunidades de Structuring
- Priorizar la relevancia para clientes sobre un simple resumen de noticias financieras

El objetivo no es generar recomendaciones de inversión. Es una nota matutina concisa de inteligencia para conversaciones con clientes y equipos de Structuring.

---

## Protección contra duplicados

El script mantiene un historial persistente de las historias ya utilizadas en briefings anteriores.

Esto evita que el mismo artículo u operación aparezca repetidamente en el correo matutino, mientras permite que nuevos desarrollos sigan entrando al briefing.

El historial se conserva automáticamente entre ejecuciones de GitHub Actions.

---

## Stack

`Python` · `feedparser` · `BeautifulSoup` · `requests` · `Google Gemini API` · `GitHub Actions` · `Banxico SIE API`

---

## Configuración

Instala las dependencias:

```bash
pip install -r requirements.txt
```

Después, agrega los siguientes secretos del repositorio en:

**GitHub → Settings → Secrets and variables → Actions**

```text
GEMINI_API_KEY
GMAIL_FROM
GMAIL_APP_PASSWORD
GMAIL_TO
BANXICO_TOKEN
```

### Descripción de los secretos

- `GEMINI_API_KEY` — API key de Google Gemini utilizada para generar el briefing escrito
- `GMAIL_FROM` — Cuenta de Gmail utilizada para enviar el briefing
- `GMAIL_APP_PASSWORD` — App Password de Google para autenticación SMTP
- `GMAIL_TO` — Dirección de correo que recibirá el briefing
- `BANXICO_TOKEN` — Token de la API SIE de Banco de México para obtener datos de FX y tasas mexicanas

Para ejecutarlo manualmente:

```bash
python morning_briefing.py
```

Para ejecuciones automáticas, utiliza el workflow de GitHub Actions incluido:

```text
.github/workflows/daily_morning_briefing.yml
```

También se puede ejecutar manualmente desde:

**GitHub → Actions → Daily Morning Briefing → Run workflow**

---

## Notas

- Los cron jobs de GitHub Actions utilizan UTC.
- El briefing mantiene un historial persistente de noticias ya utilizadas para reducir repeticiones.
- Los datos de mercado provienen directamente de fuentes públicas; Gemini se utiliza únicamente para interpretación y redacción.
