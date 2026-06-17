#!/usr/bin/env python3
"""
AI Daily Brief — Informe diario de novedades en IA, gobierno de IA,
vulnerabilidades y regulacion.

Recolecta de fuentes RSS/API publicas, filtra por relevancia y ultimas 24-48h,
arma un informe Markdown y opcionalmente lo envia por email.

Uso:
    python brief.py                  # genera brief.md y lo imprime
    python brief.py --email          # ademas lo envia por email (requiere env vars)

Configuracion por variables de entorno (para email):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM, MAIL_TO
"""

import argparse
import datetime as dt
import html
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET

import brief_ai  # capa de IA compartida (Groq) con fallback a modo simple

# ----------------------------------------------------------------------------
# CONFIGURACION DE FUENTES
# Cada fuente: (categoria, nombre, url, tipo)
# tipo: "rss" (feed estandar) o "atom"
# Agrega o quita fuentes libremente segun tu interes.
# ----------------------------------------------------------------------------
SOURCES = [
    # --- Regulacion / leyes / politica ---
    ("Regulacion", "EU AI Act Newsroom", "https://artificialintelligenceact.eu/feed/", "rss"),
    ("Regulacion", "NIST News", "https://www.nist.gov/news-events/news/rss.xml", "rss"),
    ("Regulacion", "IAPP - Privacy & AI", "https://iapp.org/feed/", "rss"),
    ("Regulacion", "AlgorithmWatch", "https://algorithmwatch.org/en/feed/", "rss"),
    ("Regulacion", "Future of Life Institute", "https://futureoflife.org/feed/", "rss"),

    # --- Gobierno de IA / governance ---
    ("Gobierno IA", "Stanford HAI", "https://hai.stanford.edu/news/rss.xml", "rss"),
    ("Gobierno IA", "OECD AI Policy", "https://oecd.ai/en/rss", "rss"),
    ("Gobierno IA", "AI Now Institute", "https://ainowinstitute.org/feed", "rss"),

    # --- Vulnerabilidades / seguridad ---
    # NVD entrega un feed con CVEs recientes. Filtramos por palabras IA/ML mas abajo.
    ("Vulnerabilidades", "The Hacker News", "https://feeds.feedburner.com/TheHackersNews", "rss"),
    ("Vulnerabilidades", "BleepingComputer", "https://www.bleepingcomputer.com/feed/", "rss"),

    # --- Tecnologia / mercado / modelos ---
    ("Tecnologia", "Anthropic News", "https://www.anthropic.com/rss.xml", "rss"),
    ("Tecnologia", "Google DeepMind Blog", "https://deepmind.google/blog/rss.xml", "rss"),
    ("Tecnologia", "The Verge - AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "atom"),
    ("Tecnologia", "VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "rss"),
    ("Tecnologia", "MIT Technology Review", "https://www.technologyreview.com/feed/", "rss"),
    ("Tecnologia", "Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss", "rss"),
    ("Tecnologia", "TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "rss"),

    # --- Nuevos modelos / releases ---
    ("Modelos", "OpenAI News", "https://openai.com/news/rss.xml", "rss"),
    ("Modelos", "Meta AI Blog", "https://ai.meta.com/blog/rss/", "rss"),
    ("Modelos", "Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "atom"),
    ("Modelos", "Mistral AI News", "https://mistral.ai/news/rss", "rss"),
]

# Palabras clave para decidir si una noticia es relevante.
# Si una fuente ya es 100% de IA, su contenido pasa igual; estas keywords
# se usan sobre todo para filtrar feeds generalistas (seguridad, tech).
KEYWORDS = [
    "ai", "a.i.", "artificial intelligence", "inteligencia artificial",
    "machine learning", "llm", "gpt", "genai", "generative",
    "prompt injection", "model", "ml ", "deepfake", "neural",
    "openai", "anthropic", "gemini", "claude", "mistral", "llama",
    "ai act", "ai governance", "nist ai", "iso 42001", "ai risk",
    # nuevos modelos y releases
    "gpt-5", "gpt-4", "grok", "qwen", "deepseek", "phi-", "gemma",
    "release", "launched", "benchmark", "sota", "state of the art",
    "multimodal", "reasoning model", "open source model", "weights",
    "hugging face", "ollama", "fine-tune", "context window",
]

LOOKBACK_HOURS = 48  # ventana de tiempo a considerar
MAX_PER_SOURCE = 6   # tope de items por fuente para no saturar
USER_AGENT = "Mozilla/5.0 (AI-Daily-Brief/1.0)"

# Keywords que elevan la importancia de una noticia
IMPORTANT_KEYWORDS = [
    "ban", "banned", "mandatory", "fine", "penalty", "breach", "hack",
    "critical", "emergency", "executive order", "regulation", "law",
    "signed", "enforcement", "lawsuit", "billion", "shutdown", "blocked",
    "prohibited", "vulnerability", "exploit", "zero-day", "attack",
    "leaked", "exposed", "sanctioned", "illegal",
]


def fetch(url):
    """Descarga el contenido de una URL con timeout y user-agent."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=25) as resp:
        return resp.read()


def parse_date(text):
    """Intenta parsear fechas RSS/Atom en varios formatos comunes."""
    if not text:
        return None
    text = text.strip()
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    cleaned = text.replace("GMT", "+0000").replace("UTC", "+0000")
    # Normaliza 'Z' final
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+0000"
    for fmt in formats:
        try:
            d = dt.datetime.strptime(cleaned, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def clean_text(s):
    """Quita HTML y normaliza espacios."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def translate_batch(texts):
    """Traduce lista de textos EN->ES via Google Translate (sin API key).
    Requiere: pip install deep-translator
    Si no esta instalado o falla, devuelve los textos originales.
    """
    if not texts:
        return texts
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        return texts
    translator = GoogleTranslator(source="en", target="es")
    results = []
    batch_size = 20
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        try:
            results.extend(translator.translate_batch(chunk))
        except Exception:
            results.extend(chunk)
    return results


def score_item(item):
    """Puntua la importancia de un item (sin LLM) por categoria, keywords y recencia."""
    score = {"Regulacion": 3, "Vulnerabilidades": 2, "Gobierno IA": 1, "Tecnologia": 0}.get(
        item["category"], 0)
    blob = f"{item['title']} {item['summary']}".lower()
    score += sum(1 for kw in IMPORTANT_KEYWORDS if kw in blob)
    if item["date"]:
        age_h = (dt.datetime.now(dt.timezone.utc) - item["date"]).total_seconds() / 3600
        score += 2 if age_h < 12 else (1 if age_h < 24 else 0)
    return score


def mark_important(items, top_n=5):
    """Marca los top_n items mas importantes con item['important'] = True."""
    scored = sorted(enumerate(items), key=lambda x: score_item(x[1]), reverse=True)
    top = {i for i, _ in scored[:top_n]}
    for i, it in enumerate(items):
        it["important"] = i in top
    return items


def add_translations(items):
    """Agrega item['summary_es'] con la traduccion al espanol de cada resumen."""
    texts = [it["summary"] for it in items]
    translated = translate_batch(texts)
    for it, es in zip(items, translated):
        it["summary_es"] = es if es and es.strip() != it["summary"].strip() else ""
    return items


def is_relevant(source_name, title, summary):
    """Decide si un item es relevante exigiendo al menos una keyword de IA.

    Se aplica a todas las fuentes por igual. La lista KEYWORDS es amplia, asi
    que las fuentes tematicas de IA pasan casi siempre, mientras que las
    generalistas (seguridad, tech) solo dejan pasar lo que menciona IA/ML.
    """
    blob = f"{title} {summary}".lower()
    return any(kw in blob for kw in KEYWORDS)


def parse_feed(category, name, raw, kind):
    """Parsea un feed RSS o Atom y devuelve lista de items relevantes."""
    items = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return items

    # RSS clasico: channel/item ; Atom: entry
    nodes = root.findall(".//item")
    is_atom = False
    if not nodes:
        # namespace de Atom
        ns = {"a": "http://www.w3.org/2005/Atom"}
        nodes = root.findall(".//a:entry", ns)
        is_atom = True

    for node in nodes[:MAX_PER_SOURCE * 2]:
        if is_atom:
            ns = {"a": "http://www.w3.org/2005/Atom"}
            title = node.findtext("a:title", default="", namespaces=ns)
            link_el = node.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            summary = node.findtext("a:summary", default="", namespaces=ns) or \
                      node.findtext("a:content", default="", namespaces=ns)
            date_txt = node.findtext("a:updated", default="", namespaces=ns) or \
                       node.findtext("a:published", default="", namespaces=ns)
        else:
            title = node.findtext("title", default="")
            link = node.findtext("link", default="")
            summary = node.findtext("description", default="")
            date_txt = node.findtext("pubDate", default="")

        title = clean_text(title)
        summary = clean_text(summary)
        pub = parse_date(date_txt)

        if not title:
            continue
        if not is_relevant(name, title, summary):
            continue

        items.append({
            "category": category,
            "source": name,
            "title": title,
            "link": link.strip(),
            "summary": summary[:280],
            "date": pub,
        })
    return items


def collect():
    """Recorre todas las fuentes y devuelve items dentro de la ventana de tiempo."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=LOOKBACK_HOURS)
    all_items = []
    errors = []

    for category, name, url, kind in SOURCES:
        try:
            raw = fetch(url)
            feed_items = parse_feed(category, name, raw, kind)
            # filtra por fecha (si hay fecha; si no, lo incluye igual)
            recent = [it for it in feed_items
                      if it["date"] is None or it["date"] >= cutoff]
            all_items.extend(recent[:MAX_PER_SOURCE])
        except (URLError, HTTPError, TimeoutError) as e:
            errors.append(f"{name}: {e}")
        except Exception as e:  # noqa
            errors.append(f"{name}: {type(e).__name__}: {e}")

    return all_items, errors


# ----------------------------------------------------------------------------
# CAPA DE IA (Groq) -- ver brief_ai.py
# Si hay GROQ_API_KEY se genera resumen ejecutivo, deteccion de tendencias,
# priorizacion con propuestas de accion y traduccion real al espanol. Sin key
# (o si la llamada falla) se cae limpiamente al modo simple. Toda la logica de
# IA vive en brief_ai.py.
# ----------------------------------------------------------------------------

def build_markdown(items, errors, analysis=None, norm=None):
    """Arma el informe en Markdown agrupado por categoria.

    Si analysis (dict de brief_ai.analyze) viene dado, se usa como resumen
    ejecutivo con IA; si es None, se arma el resumen simple por prioridad.
    """
    today = dt.datetime.now().strftime("%Y-%m-%d")
    order = ["Modelos", "Regulacion", "Gobierno IA", "Vulnerabilidades", "Tecnologia"]
    titles = {
        "Modelos":          "Nuevos modelos y releases",
        "Regulacion":       "Regulacion y leyes",
        "Gobierno IA":      "Gobierno de IA",
        "Vulnerabilidades": "Vulnerabilidades y seguridad",
        "Tecnologia":       "Tecnologia y mercado",
    }

    lines = []
    lines.append(f"# AI Daily Brief — {today}")
    lines.append("")
    lines.append(f"_Ventana: ultimas {LOOKBACK_HOURS}h · {len(items)} novedades · "
                 f"generado automaticamente_")
    lines.append("")

    # Resumen ejecutivo: usa el analisis de IA si esta; si no, modo simple.
    lines.append("## Resumen ejecutivo")
    analysis_md = brief_ai.analysis_to_markdown(analysis, norm or []) if analysis else None
    if analysis_md:
        lines.append(f"_Analisis por IA ({brief_ai.provider_label()})_")
        lines.append("")
        lines.append(analysis_md)
    else:
        priority = ["Regulacion", "Vulnerabilidades", "Gobierno IA", "Tecnologia"]
        exec_items = []
        for cat in priority:
            for it in items:
                if it["category"] == cat:
                    exec_items.append(it)
        if exec_items:
            for it in exec_items[:5]:
                lines.append(f"- **[{it['category']}]** {it['title']} "
                             f"([fuente]({it['link']}))")
        else:
            lines.append("- Sin novedades relevantes en la ventana de tiempo.")
    lines.append("")

    # Secciones por categoria
    for cat in order:
        cat_items = [it for it in items if it["category"] == cat]
        if not cat_items:
            continue
        lines.append(f"## {titles[cat]}")
        for it in cat_items:
            date_str = it["date"].strftime("%d/%m %H:%M") if it["date"] else "s/f"
            marker = "**[IMPORTANTE]** " if it.get("important") else ""
            lines.append(f"### {marker}{it['title']}")
            lines.append(f"_{it['source']} · {date_str} UTC_")
            if it["summary"]:
                lines.append("")
                lines.append(it["summary"])
            if it.get("summary_es"):
                lines.append("")
                lines.append(f"> **ES:** {it['summary_es']}")
            lines.append("")
            lines.append(f"[Leer mas]({it['link']})")
            lines.append("")

    lines.append("---")
    lines.append("## Accion recomendada")
    lines.append("- Revisar items de **Regulacion** y **Vulnerabilidades** primero.")
    lines.append("- Escalar lo que afecte tu stack o jurisdiccion.")
    lines.append("")

    if errors:
        lines.append("<details><summary>Fuentes con error</summary>")
        lines.append("")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("</details>")

    return "\n".join(lines)


def build_html_page(items, errors, analysis=None, norm=None):
    """Genera una pagina HTML completa y autocontenida para publicar en la web.

    A diferencia de md_to_basic_html (pensada para el cuerpo del email), esta
    arma un documento con estilos propios, pensado como briefing ejecutivo.
    """
    today_h = dt.datetime.now().strftime("%d/%m/%Y")
    gen_h = dt.datetime.now().strftime("%H:%M")
    order = ["Modelos", "Regulacion", "Gobierno IA", "Vulnerabilidades", "Tecnologia"]
    titles = {
        "Modelos":          "Nuevos modelos y releases",
        "Regulacion":       "Regulacion y leyes",
        "Gobierno IA":      "Gobierno de IA",
        "Vulnerabilidades": "Vulnerabilidades y seguridad",
        "Tecnologia":       "Tecnologia y mercado",
    }
    # color de acento por categoria (sobrio, no semaforo chillon)
    cat_color = {
        "Modelos":          "#e67700",
        "Regulacion":       "#3b5bdb",
        "Gobierno IA":      "#0c8599",
        "Vulnerabilidades": "#c92a2a",
        "Tecnologia":       "#5f3dc4",
    }

    def esc(s):
        return html.escape(s or "")

    # --- Resumen ejecutivo (destacado) ---
    analysis_html = brief_ai.analysis_to_html(analysis, norm or [], cat_color) if analysis else None
    if analysis_html:
        modo = f"Analisis por IA · {brief_ai.provider_label()}"
        highlight_html = analysis_html
    else:
        modo = "Seleccion automatica por categoria"
        priority = ["Regulacion", "Vulnerabilidades", "Gobierno IA", "Tecnologia"]
        exec_items = [it for cat in priority for it in items if it["category"] == cat][:5]
        if exec_items:
            lis = []
            for it in exec_items:
                lis.append(
                    f'<li><span class="tag" style="--c:{cat_color.get(it["category"], "#555")}">'
                    f'{esc(it["category"])}</span> {esc(it["title"])} '
                    f'<a class="more" href="{esc(it["link"])}" target="_blank" '
                    f'rel="noopener">Leer mas &rarr;</a></li>'
                )
            highlight_html = "<ul class='highlights'>" + "\n".join(lis) + "</ul>"
        else:
            highlight_html = "<p class='empty'>Sin novedades en la ventana de tiempo.</p>"

    # --- Secciones por categoria ---
    sections = []
    for cat in order:
        cat_items = [it for it in items if it["category"] == cat]
        if not cat_items:
            continue
        cards = []
        for it in cat_items:
            date_str = it["date"].strftime("%d/%m %H:%M") if it["date"] else "s/f"
            important_badge = '<span class="badge-imp">IMPORTANTE</span>' if it.get("important") else ""
            summ_en = f'<p class="summary">{esc(it["summary"])}</p>' if it["summary"] else ""
            summ_es = (f'<p class="summary-es"><span class="es-label">ES</span> {esc(it["summary_es"])}</p>'
                       if it.get("summary_es") else "")
            cards.append(
                f'<article class="card{"  card-imp" if it.get("important") else ""}">'
                f'<h3>{important_badge}<a href="{esc(it["link"])}" target="_blank" rel="noopener">{esc(it["title"])}</a></h3>'
                f'<div class="meta">{esc(it["source"])} &middot; {date_str} UTC</div>'
                f'{summ_en}{summ_es}'
                f'<a class="more" href="{esc(it["link"])}" target="_blank" rel="noopener">Leer la noticia &rarr;</a>'
                f'</article>'
            )
        sections.append(
            f'<section><h2 style="--c:{cat_color.get(cat, "#555")}">{esc(titles[cat])}'
            f'<span class="count">{len(cat_items)}</span></h2>'
            f'<div class="cards">{"".join(cards)}</div></section>'
        )

    errors_html = ""
    if errors:
        err_items = "".join(f"<li>{esc(e)}</li>" for e in errors)
        errors_html = (
            f'<details class="errors"><summary>Fuentes con error ({len(errors)})</summary>'
            f'<ul>{err_items}</ul></details>'
        )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Daily Brief — {today_h}</title>
<style>
  :root {{
    --ink: #1a1c23; --muted: #6b7280; --line: #e5e7eb;
    --bg: #fbfbfd; --card: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.55; -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 48px 22px 80px; }}
  header {{ border-bottom: 2px solid var(--ink); padding-bottom: 18px; margin-bottom: 32px; }}
  .eyebrow {{ font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
    color: var(--muted); font-weight: 600; }}
  h1 {{ font-size: 34px; margin: 6px 0 4px; letter-spacing: -.02em; }}
  .sub {{ color: var(--muted); font-size: 14px; }}
  .exec {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 22px 24px; margin-bottom: 40px; box-shadow: 0 1px 3px rgba(0,0,0,.04); }}
  .exec h2 {{ font-size: 13px; letter-spacing: .12em; text-transform: uppercase;
    margin: 0 0 4px; color: var(--ink); }}
  .exec .mode {{ font-size: 12px; color: var(--muted); margin-bottom: 14px; }}
  ul.highlights {{ list-style: none; margin: 0; padding: 0; }}
  ul.highlights li {{ padding: 12px 0; border-top: 1px solid var(--line); }}
  ul.highlights li:first-child {{ border-top: none; }}
  .tag {{ display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: var(--c); border: 1px solid var(--c);
    border-radius: 4px; padding: 1px 7px; margin-right: 8px; vertical-align: middle; }}
  .why {{ color: var(--muted); font-size: 14px; font-style: italic; margin: 4px 0 4px 2px; }}
  section {{ margin-bottom: 38px; }}
  section h2 {{ font-size: 20px; border-left: 4px solid var(--c); padding-left: 12px;
    margin: 0 0 16px; display: flex; align-items: center; gap: 10px; }}
  .count {{ font-size: 12px; font-weight: 600; color: var(--muted); background: var(--line);
    border-radius: 20px; padding: 2px 9px; }}
  .cards {{ display: grid; gap: 14px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 16px 18px; }}
  .card h3 {{ font-size: 16px; margin: 0 0 6px; line-height: 1.4; }}
  .card h3 a {{ color: var(--ink); text-decoration: none; }}
  .card h3 a:hover {{ text-decoration: underline; }}
  .meta {{ font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
  .summary {{ font-size: 14px; margin: 0 0 6px; color: #374151; }}
  .summary-es {{ font-size: 14px; margin: 0 0 10px; color: #1e3a5f;
    background: #f0f4ff; border-left: 3px solid #3b5bdb;
    padding: 6px 10px; border-radius: 0 6px 6px 0; }}
  .es-label {{ font-size: 10px; font-weight: 700; letter-spacing: .08em;
    color: #3b5bdb; text-transform: uppercase; margin-right: 6px; }}
  .badge-imp {{ display: inline-block; font-size: 10px; font-weight: 700;
    letter-spacing: .06em; text-transform: uppercase; background: #fff3bf;
    color: #835400; border: 1px solid #f0c040; border-radius: 4px;
    padding: 1px 7px; margin-right: 8px; vertical-align: middle; }}
  .card-imp {{ border-left: 3px solid #f0c040 !important; }}
  .more {{ font-size: 13px; font-weight: 600; color: #3b5bdb; text-decoration: none; }}
  .more:hover {{ text-decoration: underline; }}
  .empty {{ color: var(--muted); }}
  .errors {{ margin-top: 30px; font-size: 13px; color: var(--muted); }}
  .errors summary {{ cursor: pointer; }}
  footer {{ margin-top: 50px; padding-top: 18px; border-top: 1px solid var(--line);
    font-size: 12px; color: var(--muted); }}
  @media (prefers-reduced-motion: no-preference) {{
    .card {{ transition: border-color .15s; }}
    .card:hover {{ border-color: #cbd2dc; }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="eyebrow">AI Daily Brief</div>
      <h1>Novedades en IA</h1>
      <div class="sub">{today_h} &middot; generado {gen_h} &middot; ultimas {LOOKBACK_HOURS}h &middot; {len(items)} novedades</div>
    </header>
    <div class="exec">
      <h2>Resumen ejecutivo</h2>
      <div class="mode">{modo}</div>
      {highlight_html}
    </div>
    {"".join(sections) if sections else "<p class='empty'>Sin novedades relevantes hoy.</p>"}
    {errors_html}
    <footer>Generado automaticamente. Cada titulo enlaza a la fuente original.</footer>
  </div>
</body>
</html>"""


def md_to_basic_html(md):
    """Conversion minima Markdown -> HTML para el email."""
    out = []
    for line in md.split("\n"):
        if line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            out.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "---":
            out.append("<hr>")
        elif line.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p>{line}</p>")
    body = "\n".join(out)
    # links markdown [txt](url) -> <a>
    body = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', body)
    # bold
    body = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", body)
    return f"<html><body style='font-family:sans-serif;max-width:700px'>{body}</body></html>"


def send_email(subject, md_body):
    """Envia el informe por email usando SMTP (config por env vars)."""
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    mail_from = os.environ.get("MAIL_FROM", user)
    mail_to = os.environ.get("MAIL_TO")

    if not all([host, user, password, mail_to]):
        print("[email] Faltan variables de entorno SMTP. No se envia.", file=sys.stderr)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.attach(MIMEText(md_body, "plain", "utf-8"))
    msg.attach(MIMEText(md_to_basic_html(md_body), "html", "utf-8"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(mail_from, [a.strip() for a in mail_to.split(",")], msg.as_string())
    print(f"[email] Enviado a {mail_to}")
    return True


def main():
    parser = argparse.ArgumentParser(description="AI Daily Brief")
    parser.add_argument("--email", action="store_true", help="enviar por email")
    parser.add_argument("--out", default="brief.md", help="archivo Markdown de salida (ingles)")
    parser.add_argument("--out-es", default="brief_es.md",
                        help="archivo Markdown en español (requiere API key)")
    parser.add_argument("--html", default="index.html",
                        help="archivo HTML de salida para la web (GitHub Pages)")
    parser.add_argument("--html-es", default="index_es.html",
                        help="archivo HTML en español para la web")
    parser.add_argument("--no-llm", action="store_true",
                        help="forzar modo simple aunque haya API key")
    args = parser.parse_args()

    print("Recolectando fuentes...", file=sys.stderr)
    items, errors = collect()
    print(f"  {len(items)} items, {len(errors)} fuentes con error", file=sys.stderr)

    # Marca los mas importantes y traduce resumenes (sin API key, via Google Translate).
    mark_important(items)
    print("[traduccion] Traduciendo resumenes al espanol (Google)...", file=sys.stderr)
    add_translations(items)

    # Lista normalizada para la capa de IA (idx alineado con `items`).
    norm = [{"idx": i, "category": it["category"], "title": it["title"],
             "summary": it["summary"], "link": it["link"]}
            for i, it in enumerate(items)]

    # Capa de IA (Groq) con fallback automatico al modo simple.
    analysis = None
    use_ai = not args.no_llm and brief_ai.ai_available()
    if args.no_llm:
        print("[modo] simple (forzado por --no-llm)", file=sys.stderr)
    elif not brief_ai.ai_available():
        print("[modo] simple (sin GROQ_API_KEY)", file=sys.stderr)
    else:
        print("[modo] analizando con IA (Groq)...", file=sys.stderr)
        analysis = brief_ai.analyze(norm, "un CAIO (Chief AI Officer)")
        print("[modo] IA OK" if analysis else "[modo] IA no disponible -> simple",
              file=sys.stderr)

    # --- Salida en ingles (items originales) ---
    md = build_markdown(items, errors, analysis=analysis, norm=norm)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Informe escrito en {args.out}", file=sys.stderr)

    page = build_html_page(items, errors, analysis=analysis, norm=norm)
    with open(args.html, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Pagina web escrita en {args.html}", file=sys.stderr)

    # --- Salida en espanol: traduccion real de titulo+resumen con IA ---
    import copy
    items_es, norm_es = items, norm
    translations = brief_ai.translate(norm) if use_ai else None
    if translations:
        print(f"[es] {len(translations)} items traducidos con IA", file=sys.stderr)
        items_es = copy.deepcopy(items)
        for i, it in enumerate(items_es):
            tr = translations.get(i)
            if tr:
                it["title"] = tr["title"] or it["title"]
                it["summary"] = tr["summary"] or it["summary"]
                it["summary_es"] = ""  # ya esta todo en ES; evita duplicar
        norm_es = [{"idx": i, "category": it["category"], "title": it["title"],
                    "summary": it["summary"], "link": it["link"]}
                   for i, it in enumerate(items_es)]
    else:
        print("[es] sin traduccion IA -> usa resumenes de Google Translate", file=sys.stderr)

    md_es = build_markdown(items_es, errors, analysis=analysis, norm=norm_es)
    with open(args.out_es, "w", encoding="utf-8") as f:
        f.write(md_es)
    print(f"[es] Informe en espanol escrito en {args.out_es}", file=sys.stderr)
    page_es = build_html_page(items_es, errors, analysis=analysis, norm=norm_es)
    with open(args.html_es, "w", encoding="utf-8") as f:
        f.write(page_es)
    print(f"[es] Pagina web en espanol escrita en {args.html_es}", file=sys.stderr)

    if args.email:
        today = dt.datetime.now().strftime("%Y-%m-%d")
        send_email(f"AI Daily Brief — {today}", md)
    else:
        print("\n" + md)


if __name__ == "__main__":
    main()
