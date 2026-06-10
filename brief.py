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
]

LOOKBACK_HOURS = 48  # ventana de tiempo a considerar
MAX_PER_SOURCE = 6   # tope de items por fuente para no saturar
USER_AGENT = "Mozilla/5.0 (AI-Daily-Brief/1.0)"


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
# CAPA LLM OPCIONAL
# Si existe ANTHROPIC_API_KEY, el informe usa Claude Haiku para elegir y
# resumir las noticias mas importantes. Si NO hay key, si la llamada falla, o
# si se acabo el credito, se cae limpiamente al modo simple (sin romperse).
# ----------------------------------------------------------------------------
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_MAX_INPUT_ITEMS = 60   # tope de items que se mandan al LLM por corrida
LLM_MAX_OUTPUT_TOKENS = 1500  # tope duro de salida -> acota costo por corrida


def llm_available():
    """True si hay API key configurada para intentar el modo LLM."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def llm_highlight(items):
    """Pide a Claude que elija y resuma las noticias mas importantes.

    Devuelve texto Markdown para el bloque destacado, o None si algo falla
    (sin key, error de red, sin credito, respuesta invalida). El llamador
    debe tratar None como 'usar modo simple'.
    """
    import json
    from urllib.request import Request as _Req, urlopen as _open
    from urllib.error import URLError as _URLErr, HTTPError as _HTTPErr

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    if not items:
        return None

    # Arma una lista compacta y numerada para que el modelo pueda referenciar.
    catalog = []
    for i, it in enumerate(items[:LLM_MAX_INPUT_ITEMS]):
        catalog.append(
            f"[{i}] ({it['category']}) {it['title']} — {it['summary'][:200]}"
        )
    catalog_txt = "\n".join(catalog)

    system = (
        "Sos analista para un CAIO (Chief AI Officer). Te paso titulares de "
        "novedades en IA, gobierno de IA, vulnerabilidades y regulacion. "
        "Eligi las 5 a 7 MAS IMPORTANTES para un ejecutivo (priorizando "
        "regulacion, riesgos de seguridad e impacto de negocio). Para cada una "
        "escribi una linea de por que importa, en espanol, clara y concreta. "
        "Devolve SOLO un JSON valido, sin texto extra, con esta forma: "
        '{"destacadas": [{"idx": <numero>, "porque": "<una frase>"}]}'
    )
    user = f"Titulares disponibles:\n{catalog_txt}"

    payload = json.dumps({
        "model": LLM_MODEL,
        "max_tokens": LLM_MAX_OUTPUT_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")

    req = _Req(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with _open(req, timeout=40) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except _HTTPErr as e:
        # 401 = key invalida, 400/429 = credito/limite, etc. -> fallback
        print(f"[llm] HTTP {e.code}: se usa modo simple", file=sys.stderr)
        return None
    except (_URLErr, TimeoutError, ValueError) as e:
        print(f"[llm] error ({e}): se usa modo simple", file=sys.stderr)
        return None

    # Extrae el texto de la respuesta y parsea el JSON que pedimos.
    try:
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ).strip()
        # Limpia posibles cercos ```json
        text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
        parsed = json.loads(text)
        destacadas = parsed.get("destacadas", [])
    except (ValueError, KeyError, AttributeError) as e:
        print(f"[llm] respuesta no parseable ({e}): se usa modo simple",
              file=sys.stderr)
        return None

    if not destacadas:
        return None

    # Construye el bloque Markdown destacado mapeando idx -> item real.
    out = []
    for d in destacadas:
        try:
            idx = int(d["idx"])
            it = items[idx]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        porque = clean_text(str(d.get("porque", "")))[:300]
        out.append(f"- **[{it['category']}]** {it['title']}  ")
        if porque:
            out.append(f"  _{porque}_  ")
        out.append(f"  [Leer mas]({it['link']})")
    if not out:
        return None
    return "\n".join(out)


def llm_translate_items(items):
    """Usa Claude para traducir al español los títulos y resúmenes de los items.

    Devuelve una copia de la lista con title/summary traducidos, o None si falla.
    """
    import json
    from urllib.request import Request as _Req, urlopen as _open
    from urllib.error import URLError as _URLErr, HTTPError as _HTTPErr

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not items:
        return None

    catalog = []
    for i, it in enumerate(items[:LLM_MAX_INPUT_ITEMS]):
        catalog.append({"i": i, "t": it["title"], "s": it["summary"][:200]})

    system = (
        "Sos un traductor tecnico. Te paso un JSON con noticias de IA en ingles. "
        "Traducí cada 't' (title) y 's' (summary) al español rioplatense, claro y preciso. "
        "Devolvé SOLO un JSON valido, sin texto extra, con esta forma exacta: "
        '{"items": [{"i": <numero>, "t": "<titulo traducido>", "s": "<resumen traducido>"}]}'
    )
    user = json.dumps(catalog, ensure_ascii=False)

    payload = json.dumps({
        "model": LLM_MODEL,
        "max_tokens": 4000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")

    req = _Req(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with _open(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (_HTTPErr, _URLErr, TimeoutError, ValueError) as e:
        print(f"[translate] error ({e}): se omite traduccion", file=sys.stderr)
        return None

    try:
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
        parsed = json.loads(text)
        translations = {entry["i"]: entry for entry in parsed.get("items", [])}
    except (ValueError, KeyError, AttributeError) as e:
        print(f"[translate] respuesta no parseable ({e}): se omite traduccion", file=sys.stderr)
        return None

    import copy
    translated = copy.deepcopy(items)
    for i, it in enumerate(translated[:LLM_MAX_INPUT_ITEMS]):
        if i in translations:
            it["title"] = clean_text(translations[i].get("t", it["title"]))
            it["summary"] = clean_text(translations[i].get("s", it["summary"]))
    return translated


def build_markdown(items, errors, highlight_md=None):
    """Arma el informe en Markdown agrupado por categoria.

    Si highlight_md viene dado (texto del LLM), se usa como resumen ejecutivo;
    si es None, se arma el resumen simple por prioridad de categoria.
    """
    today = dt.datetime.now().strftime("%Y-%m-%d")
    order = ["Regulacion", "Gobierno IA", "Vulnerabilidades", "Tecnologia"]
    titles = {
        "Regulacion": "Regulacion y leyes",
        "Gobierno IA": "Gobierno de IA",
        "Vulnerabilidades": "Vulnerabilidades y seguridad",
        "Tecnologia": "Tecnologia y mercado",
    }

    lines = []
    lines.append(f"# AI Daily Brief — {today}")
    lines.append("")
    lines.append(f"_Ventana: ultimas {LOOKBACK_HOURS}h · {len(items)} novedades · "
                 f"generado automaticamente_")
    lines.append("")

    # Resumen ejecutivo: usa el LLM si hay highlight; si no, modo simple.
    lines.append("## Resumen ejecutivo")
    if highlight_md:
        lines.append("_Seleccion y analisis por IA (Claude)_")
        lines.append("")
        lines.append(highlight_md)
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
            lines.append(f"### {it['title']}")
            lines.append(f"_{it['source']} · {date_str} UTC_")
            if it["summary"]:
                lines.append("")
                lines.append(it["summary"])
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


def build_html_page(items, errors, highlight_md=None):
    """Genera una pagina HTML completa y autocontenida para publicar en la web.

    A diferencia de md_to_basic_html (pensada para el cuerpo del email), esta
    arma un documento con estilos propios, pensado como briefing ejecutivo.
    """
    today_h = dt.datetime.now().strftime("%d/%m/%Y")
    gen_h = dt.datetime.now().strftime("%H:%M")
    order = ["Regulacion", "Gobierno IA", "Vulnerabilidades", "Tecnologia"]
    titles = {
        "Regulacion": "Regulacion y leyes",
        "Gobierno IA": "Gobierno de IA",
        "Vulnerabilidades": "Vulnerabilidades y seguridad",
        "Tecnologia": "Tecnologia y mercado",
    }
    # color de acento por categoria (sobrio, no semaforo chillon)
    cat_color = {
        "Regulacion": "#3b5bdb",
        "Gobierno IA": "#0c8599",
        "Vulnerabilidades": "#c92a2a",
        "Tecnologia": "#5f3dc4",
    }

    def esc(s):
        return html.escape(s or "")

    parts = []
    # --- Resumen ejecutivo (destacado) ---
    if highlight_md:
        modo = "Seleccion y analisis por IA"
        hi_html = []
        for line in highlight_md.split("\n"):
            line = line.strip()
            m = re.match(r"- \*\*\[(.+?)\]\*\* (.+?)\s*$", line)
            if m:
                hi_html.append(
                    f'<li><span class="tag" style="--c:{cat_color.get(m.group(1), "#555")}">'
                    f'{esc(m.group(1))}</span> {esc(m.group(2))}'
                )
            elif line.startswith("_") and line.endswith("_"):
                hi_html.append(f'<div class="why">{esc(line.strip("_ "))}</div>')
            elif line.startswith("[Leer mas]"):
                mm = re.search(r"\((.+?)\)", line)
                if mm:
                    hi_html.append(
                        f'<a class="more" href="{esc(mm.group(1))}" '
                        f'target="_blank" rel="noopener">Leer mas &rarr;</a></li>'
                    )
        highlight_html = "<ul class='highlights'>" + "\n".join(hi_html) + "</ul>"
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
            summ = f'<p class="summary">{esc(it["summary"])}</p>' if it["summary"] else ""
            cards.append(
                f'<article class="card">'
                f'<h3><a href="{esc(it["link"])}" target="_blank" rel="noopener">{esc(it["title"])}</a></h3>'
                f'<div class="meta">{esc(it["source"])} &middot; {date_str} UTC</div>'
                f'{summ}'
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
  .summary {{ font-size: 14px; margin: 0 0 10px; color: #374151; }}
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

    # Capa LLM opcional con fallback automatico al modo simple.
    highlight_md = None
    if args.no_llm:
        print("[modo] simple (forzado por --no-llm)", file=sys.stderr)
    elif not llm_available():
        print("[modo] simple (sin ANTHROPIC_API_KEY)", file=sys.stderr)
    else:
        print("[modo] intentando destacado por IA...", file=sys.stderr)
        highlight_md = llm_highlight(items)
        if highlight_md:
            print("[modo] IA OK", file=sys.stderr)
        else:
            print("[modo] IA no disponible -> fallback a simple", file=sys.stderr)

    md = build_markdown(items, errors, highlight_md=highlight_md)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Informe escrito en {args.out}", file=sys.stderr)

    # Pagina web para GitHub Pages
    page = build_html_page(items, errors, highlight_md=highlight_md)
    with open(args.html, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Pagina web escrita en {args.html}", file=sys.stderr)

    # Version en espanol: traduce titulos y resumenes con el LLM si esta disponible.
    if not args.no_llm and llm_available():
        print("[es] Traduciendo al espanol...", file=sys.stderr)
        items_es = llm_translate_items(items)
        if items_es:
            # El highlight_md ya esta en espanol (el LLM lo genera en espanol),
            # asi que lo reutilizamos directamente.
            md_es = build_markdown(items_es, errors, highlight_md=highlight_md)
            with open(args.out_es, "w", encoding="utf-8") as f:
                f.write(md_es)
            print(f"[es] Informe en espanol escrito en {args.out_es}", file=sys.stderr)
            page_es = build_html_page(items_es, errors, highlight_md=highlight_md)
            with open(args.html_es, "w", encoding="utf-8") as f:
                f.write(page_es)
            print(f"[es] Pagina web en espanol escrita en {args.html_es}", file=sys.stderr)
        else:
            print("[es] Traduccion no disponible (fallback omitido)", file=sys.stderr)
    else:
        print("[es] Sin API key -> version en espanol omitida", file=sys.stderr)

    if args.email:
        today = dt.datetime.now().strftime("%Y-%m-%d")
        send_email(f"AI Daily Brief — {today}", md)
    else:
        print("\n" + md)


if __name__ == "__main__":
    main()
