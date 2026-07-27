#!/usr/bin/env python3
"""
Productos AI Brief — Informe diario de novedades, lanzamientos y updates
del ecosistema de herramientas de IA: nuevas funciones, apps, integraciones,
frameworks, providers y herramientas satelite.

Uso:
    python brief_productos.py                  # genera productos_brief.md
    python brief_productos.py --email          # ademas lo envia por email

Configuracion por variables de entorno (para email):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM, MAIL_TO
"""

import argparse
import copy
import datetime as dt
import html
import json
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
# FUENTES
# ----------------------------------------------------------------------------
SOURCES = [
    # --- Labs principales ---
    ("Labs", "Anthropic News", "https://www.anthropic.com/rss.xml", "rss"),
    ("Labs", "OpenAI News", "https://openai.com/news/rss.xml", "rss"),
    ("Labs", "Google DeepMind", "https://deepmind.google/blog/rss.xml", "rss"),
    ("Labs", "Google AI Blog", "https://blog.google/technology/ai/rss/", "rss"),
    ("Labs", "Meta AI Blog", "https://ai.meta.com/blog/rss/", "rss"),
    ("Labs", "Microsoft AI Blog", "https://blogs.microsoft.com/ai/feed/", "rss"),
    ("Labs", "Mistral AI", "https://mistral.ai/news/rss", "rss"),
    ("Labs", "xAI / Grok", "https://x.ai/blog/rss.xml", "rss"),

    # --- Productos de consumo / apps ---
    ("Productos", "Perplexity Blog", "https://blog.perplexity.ai/rss", "rss"),
    ("Productos", "Notion AI Blog", "https://www.notion.so/blog/rss.xml", "rss"),
    ("Productos", "Midjourney Updates", "https://updates.midjourney.com/rss", "rss"),
    ("Productos", "Runway Blog", "https://runwayml.com/blog/rss.xml", "rss"),
    ("Productos", "ElevenLabs Blog", "https://elevenlabs.io/blog/rss.xml", "rss"),

    # --- Automatizacion / agentes / workflows ---
    ("Automatizacion", "n8n Blog", "https://blog.n8n.io/rss.xml", "rss"),
    ("Automatizacion", "Zapier Blog AI", "https://zapier.com/blog/ai/feed/", "rss"),
    ("Automatizacion", "LangChain Blog", "https://blog.langchain.dev/rss/", "rss"),
    ("Automatizacion", "LlamaIndex Blog", "https://www.llamaindex.ai/blog/rss.xml", "rss"),
    ("Automatizacion", "Crew AI Blog", "https://www.crewai.com/blog/rss.xml", "rss"),

    # --- Coding / dev tools ---
    ("Dev Tools", "GitHub Blog AI", "https://github.blog/ai-and-ml/feed/", "rss"),
    ("Dev Tools", "Cursor Changelog", "https://cursor.com/changelog/rss.xml", "rss"),
    ("Dev Tools", "Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "atom"),
    ("Dev Tools", "Replicate Blog", "https://replicate.com/blog/rss", "rss"),

    # --- Infraestructura / providers ---
    ("Infraestructura", "Groq Blog", "https://wow.groq.com/feed/", "rss"),
    ("Infraestructura", "Together AI Blog", "https://www.together.ai/blog/rss.xml", "rss"),
    ("Infraestructura", "Vercel AI Blog", "https://vercel.com/blog/rss.xml", "rss"),

    # --- Agregadores / newsletters ---
    ("Novedades", "Ben's Bites", "https://www.bensbites.com/feed", "rss"),
    ("Novedades", "The Rundown AI", "https://www.therundown.ai/feed", "rss"),
    ("Novedades", "TLDR AI", "https://tldr.tech/ai/rss", "rss"),
    ("Novedades", "Product Hunt AI", "https://www.producthunt.com/feed?category=artificial-intelligence", "rss"),
]

KEYWORDS = [
    # lanzamientos
    "launch", "release", "announce", "introducing", "new feature", "update",
    "now available", "shipped", "just released", "v2", "v3", "beta", "ga",
    "generally available", "api", "plugin", "integration", "extension",
    # productos y herramientas
    "ai", "llm", "agent", "copilot", "assistant", "tool", "app", "model",
    "workflow", "automation", "no-code", "low-code",
    # marcas satelite clave
    "n8n", "zapier", "make", "langchain", "llamaindex", "crewai", "autogen",
    "cursor", "windsurf", "copilot", "midjourney", "runway", "elevenlabs",
    "perplexity", "notion", "replicate", "groq", "hugging face", "vercel",
    "openai", "anthropic", "gemini", "claude", "gpt", "grok", "mistral",
]

IMPORTANT_KEYWORDS = [
    "launch", "introducing", "new model", "new feature", "major update",
    "api", "now available", "generally available", "breakthrough",
    "free", "open source", "open-source", "multimodal", "real-time",
    "voice", "vision", "code", "agent",
]

LOOKBACK_HOURS = 48
MAX_PER_SOURCE = 4
USER_AGENT = "Mozilla/5.0 (Productos-AI-Brief/1.0)"

LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_MAX_OUTPUT_TOKENS = 1500

ORDER = ["Labs", "Productos", "Automatizacion", "Dev Tools", "Infraestructura", "Novedades"]
TITLES = {
    "Labs":           "Labs y modelos",
    "Productos":      "Productos y apps",
    "Automatizacion": "Automatizacion y agentes",
    "Dev Tools":      "Herramientas para developers",
    "Infraestructura": "Infraestructura y providers",
    "Novedades":      "Agregadores y novedades",
}
CAT_COLOR = {
    "Labs":           "#3b5bdb",
    "Productos":      "#0c8599",
    "Automatizacion": "#862e9c",
    "Dev Tools":      "#2b8a3e",
    "Infraestructura": "#e67700",
    "Novedades":      "#c92a2a",
}


# ----------------------------------------------------------------------------
# UTILIDADES
# ----------------------------------------------------------------------------

def fetch(url):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=25) as resp:
        return resp.read()


def parse_date(text):
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
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_relevant(title, summary):
    blob = f"{title} {summary}".lower()
    return any(kw in blob for kw in KEYWORDS)


def translate_batch(texts):
    if not texts:
        return texts
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        return texts
    translator = GoogleTranslator(source="en", target="es")
    results = []
    for i in range(0, len(texts), 20):
        chunk = texts[i:i + 20]
        try:
            results.extend(translator.translate_batch(chunk))
        except Exception:
            results.extend(chunk)
    return results


def score_item(item):
    score = {"Labs": 4, "Productos": 3, "Automatizacion": 2,
             "Dev Tools": 2, "Infraestructura": 1, "Novedades": 1}.get(item["category"], 0)
    blob = f"{item['title']} {item['summary']}".lower()
    score += sum(1 for kw in IMPORTANT_KEYWORDS if kw in blob)
    if item["date"]:
        age_h = (dt.datetime.now(dt.timezone.utc) - item["date"]).total_seconds() / 3600
        score += 2 if age_h < 12 else (1 if age_h < 24 else 0)
    return score


def mark_important(items, top_n=5):
    scored = sorted(enumerate(items), key=lambda x: score_item(x[1]), reverse=True)
    top = {i for i, _ in scored[:top_n]}
    for i, it in enumerate(items):
        it["important"] = i in top
    return items


def add_translations(items):
    texts = [it["summary"] for it in items]
    translated = translate_batch(texts)
    for it, es in zip(items, translated):
        it["summary_es"] = es if es and es.strip() != it["summary"].strip() else ""
    return items


# ----------------------------------------------------------------------------
# PARSEO DE FEEDS
# ----------------------------------------------------------------------------

def parse_feed(category, name, raw):
    items = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return items

    nodes = root.findall(".//item")
    is_atom = False
    if not nodes:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        nodes = root.findall(".//a:entry", ns)
        is_atom = True

    for node in nodes[:MAX_PER_SOURCE * 2]:
        if is_atom:
            ns = {"a": "http://www.w3.org/2005/Atom"}
            title = node.findtext("a:title", default="", namespaces=ns)
            link_el = node.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            summary = (node.findtext("a:summary", default="", namespaces=ns) or
                       node.findtext("a:content", default="", namespaces=ns))
            date_txt = (node.findtext("a:updated", default="", namespaces=ns) or
                        node.findtext("a:published", default="", namespaces=ns))
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
        if not is_relevant(title, summary):
            continue

        items.append({
            "category": category,
            "source": name,
            "title": title,
            "link": link.strip(),
            "summary": summary[:300],
            "summary_es": "",
            "date": pub,
            "important": False,
        })
    return items


def collect():
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=LOOKBACK_HOURS)
    all_items = []
    errors = []

    for category, name, url, kind in SOURCES:
        try:
            raw = fetch(url)
            feed_items = parse_feed(category, name, raw)
            recent = [it for it in feed_items
                      if it["date"] is None or it["date"] >= cutoff]
            all_items.extend(recent[:MAX_PER_SOURCE])
        except (URLError, HTTPError, TimeoutError) as e:
            errors.append(f"{name}: {e}")
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")

    return all_items, errors


# ----------------------------------------------------------------------------
# CAPA LLM OPCIONAL
# ----------------------------------------------------------------------------

def llm_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def llm_highlight(items):
    """Selecciona los lanzamientos mas importantes para testear/adoptar."""
    from urllib.request import Request as _Req, urlopen as _open
    from urllib.error import URLError as _URLErr, HTTPError as _HTTPErr

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not items:
        return None

    catalog = []
    for i, it in enumerate(items[:60]):
        catalog.append(f"[{i}] ({it['category']}) {it['title']} — {it['summary'][:200]}")

    system = (
        "Sos analista de herramientas de IA para un profesional que necesita testear "
        "novedades del ecosistema. Te paso lanzamientos y updates de productos de IA. "
        "Elegi los 5 a 7 MAS RELEVANTES para adoptar o testear hoy "
        "(priorizando nuevas funciones practicas, integraciones utiles, "
        "herramientas de automatizacion y lanzamientos de modelos usables). "
        "Para cada uno escribi UNA frase de por que vale la pena probarlo, "
        "en espanol, concreta y practica. "
        "Devolve SOLO JSON valido: "
        '{"destacados": [{"idx": <numero>, "porque": "<una frase>"}]}'
    )

    payload = json.dumps({
        "model": LLM_MODEL,
        "max_tokens": LLM_MAX_OUTPUT_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": "\n".join(catalog)}],
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
    except (_HTTPErr, _URLErr, TimeoutError, ValueError) as e:
        print(f"[llm] error ({e}): modo simple", file=sys.stderr)
        return None

    try:
        text = "".join(
            block.get("text", "") for block in data.get("content", [])
            if block.get("type") == "text"
        ).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
        destacados = json.loads(text).get("destacados", [])
    except Exception as e:
        print(f"[llm] no parseable ({e}): modo simple", file=sys.stderr)
        return None

    out = []
    for d in destacados:
        try:
            it = items[int(d["idx"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        porque = clean_text(str(d.get("porque", "")))[:300]
        out.append(f"- **[{it['category']}]** {it['title']}  ")
        if porque:
            out.append(f"  _{porque}_  ")
        out.append(f"  [Ver]({it['link']})")
    return "\n".join(out) if out else None


# ----------------------------------------------------------------------------
# GENERACION DEL INFORME
# ----------------------------------------------------------------------------

def build_markdown(items, errors, highlight_md=None):
    today = dt.datetime.now().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"# Productos AI Brief — {today}")
    lines.append("")
    lines.append(f"_Ventana: ultimas {LOOKBACK_HOURS}h · {len(items)} novedades · "
                 f"generado automaticamente_")
    lines.append("")
    lines.append("## Lo que vale la pena testear hoy")

    if highlight_md:
        lines.append("_Seleccion por IA (Claude)_")
        lines.append("")
        lines.append(highlight_md)
    else:
        top = sorted(items, key=score_item, reverse=True)[:6]
        for it in top:
            lines.append(f"- **[{it['category']}]** {it['title']} ([ver]({it['link']}))")
    lines.append("")

    for cat in ORDER:
        cat_items = [it for it in items if it["category"] == cat]
        if not cat_items:
            continue
        lines.append(f"## {TITLES[cat]}")
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
            lines.append(f"[Ver]({it['link']})")
            lines.append("")

    lines.append("---")
    lines.append("## Accion recomendada")
    lines.append("- Testear los items marcados como **IMPORTANTE** primero.")
    lines.append("- Evaluar integraciones de **Automatizacion** para flujos internos.")
    lines.append("- Revisar **Dev Tools** para incorporar al stack.")
    lines.append("")

    if errors:
        lines.append("<details><summary>Fuentes con error</summary>")
        lines.append("")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("</details>")

    return "\n".join(lines)


def build_html_page(items, errors, highlight_md=None):
    today_h = dt.datetime.now().strftime("%d/%m/%Y")
    gen_h = dt.datetime.now().strftime("%H:%M")

    def esc(s):
        return html.escape(s or "")

    if highlight_md:
        modo = "Seleccion por IA — que vale la pena testear hoy"
        hi_html = []
        for line in highlight_md.split("\n"):
            line = line.strip()
            m = re.match(r"- \*\*\[(.+?)\]\*\* (.+?)\s*$", line)
            if m:
                hi_html.append(
                    f'<li><span class="tag" style="--c:{CAT_COLOR.get(m.group(1), "#555")}">'
                    f'{esc(m.group(1))}</span> {esc(m.group(2))}'
                )
            elif line.startswith("_") and line.endswith("_"):
                hi_html.append(f'<div class="why">{esc(line.strip("_ "))}</div>')
            elif line.startswith("[Ver]"):
                mm = re.search(r"\((.+?)\)", line)
                if mm:
                    hi_html.append(
                        f'<a class="more" href="{esc(mm.group(1))}" '
                        f'target="_blank" rel="noopener">Ver &rarr;</a></li>'
                    )
        highlight_html = "<ul class='highlights'>" + "\n".join(hi_html) + "</ul>"
    else:
        modo = "Seleccion automatica por score"
        top = sorted(items, key=score_item, reverse=True)[:6]
        lis = [
            f'<li><span class="tag" style="--c:{CAT_COLOR.get(it["category"], "#555")}">'
            f'{esc(it["category"])}</span> {esc(it["title"])} '
            f'<a class="more" href="{esc(it["link"])}" target="_blank" rel="noopener">'
            f'Ver &rarr;</a></li>'
            for it in top
        ]
        highlight_html = "<ul class='highlights'>" + "\n".join(lis) + "</ul>"

    sections = []
    for cat in ORDER:
        cat_items = [it for it in items if it["category"] == cat]
        if not cat_items:
            continue
        cards = []
        for it in cat_items:
            date_str = it["date"].strftime("%d/%m %H:%M") if it["date"] else "s/f"
            badge = '<span class="badge-imp">IMPORTANTE</span>' if it.get("important") else ""
            summ_en = f'<p class="summary">{esc(it["summary"])}</p>' if it["summary"] else ""
            summ_es = (f'<p class="summary-es"><span class="es-label">ES</span> {esc(it["summary_es"])}</p>'
                       if it.get("summary_es") else "")
            cards.append(
                f'<article class="card{"  card-imp" if it.get("important") else ""}">'
                f'<h3>{badge}<a href="{esc(it["link"])}" target="_blank" rel="noopener">{esc(it["title"])}</a></h3>'
                f'<div class="meta">{esc(it["source"])} &middot; {date_str} UTC</div>'
                f'{summ_en}{summ_es}'
                f'<a class="more" href="{esc(it["link"])}" target="_blank" rel="noopener">Ver &rarr;</a>'
                f'</article>'
            )
        sections.append(
            f'<section><h2 style="--c:{CAT_COLOR.get(cat, "#555")}">{esc(TITLES[cat])}'
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
<title>Productos AI Brief — {today_h}</title>
<style>
  :root {{
    --ink: #1a1c23; --muted: #6b7280; --line: #e5e7eb;
    --bg: #f8f9ff; --card: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.55; -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 48px 22px 80px; }}
  header {{ border-bottom: 3px solid #3b5bdb; padding-bottom: 18px; margin-bottom: 32px; }}
  .eyebrow {{ font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
    color: #3b5bdb; font-weight: 700; }}
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
  .errors {{ margin-top: 30px; font-size: 13px; color: var(--muted); }}
  footer {{ margin-top: 50px; padding-top: 18px; border-top: 1px solid var(--line);
    font-size: 12px; color: var(--muted); }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="eyebrow">Productos AI Brief</div>
      <h1>Novedades del ecosistema IA</h1>
      <div class="sub">{today_h} &middot; generado {gen_h} &middot; ultimas {LOOKBACK_HOURS}h &middot; {len(items)} novedades</div>
    </header>
    <div class="exec">
      <h2>Lo que vale la pena testear hoy</h2>
      <div class="mode">{modo}</div>
      {highlight_html}
    </div>
    {"".join(sections) if sections else "<p>Sin novedades relevantes hoy.</p>"}
    {errors_html}
    <footer>Generado automaticamente. Cada titulo enlaza a la fuente original.</footer>
  </div>
</body>
</html>"""


# ----------------------------------------------------------------------------
# EMAIL
# ----------------------------------------------------------------------------

def md_to_basic_html(md):
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
    body = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', body)
    body = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", body)
    return f"<html><body style='font-family:sans-serif;max-width:700px'>{body}</body></html>"


def send_email(subject, md_body):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    mail_from = os.environ.get("MAIL_FROM", user)
    mail_to = os.environ.get("MAIL_TO")

    if not all([host, user, password, mail_to]):
        print("[email] Faltan variables SMTP. No se envia.", file=sys.stderr)
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


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Productos AI Brief")
    parser.add_argument("--email", action="store_true", help="enviar por email")
    parser.add_argument("--out", default="productos_brief.md", help="Markdown de salida")
    parser.add_argument("--out-es", default="productos_brief_es.md", help="Markdown en espanol")
    parser.add_argument("--html", default="productos.html", help="HTML para GitHub Pages")
    parser.add_argument("--html-es", default="productos_es.html", help="HTML en espanol")
    parser.add_argument("--no-llm", action="store_true", help="modo simple sin IA")
    parser.add_argument("--json", default=None, help="JSON de items de salida")
    args = parser.parse_args()

    print("Recolectando novedades del ecosistema IA...", file=sys.stderr)
    items, errors = collect()
    print(f"  {len(items)} items, {len(errors)} fuentes con error", file=sys.stderr)

    mark_important(items)
    print("[traduccion] Traduciendo al espanol...", file=sys.stderr)
    add_translations(items)

    highlight_md = None
    if args.no_llm:
        print("[modo] simple (forzado por --no-llm)", file=sys.stderr)
    elif not llm_available():
        print("[modo] simple (sin ANTHROPIC_API_KEY)", file=sys.stderr)
    else:
        print("[modo] intentando seleccion por IA...", file=sys.stderr)
        highlight_md = llm_highlight(items)
        if highlight_md:
            print("[modo] IA OK", file=sys.stderr)
        else:
            print("[modo] IA no disponible -> fallback simple", file=sys.stderr)

    md = build_markdown(items, errors, highlight_md=highlight_md)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Informe escrito en {args.out}", file=sys.stderr)

    page = build_html_page(items, errors, highlight_md=highlight_md)
    with open(args.html, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Pagina web escrita en {args.html}", file=sys.stderr)

    md_es = build_markdown(items, errors, highlight_md=highlight_md)
    with open(args.out_es, "w", encoding="utf-8") as f:
        f.write(md_es)
    print(f"[es] Informe en espanol escrito en {args.out_es}", file=sys.stderr)

    page_es = build_html_page(items, errors, highlight_md=highlight_md)
    with open(args.html_es, "w", encoding="utf-8") as f:
        f.write(page_es)
    print(f"[es] Pagina web en espanol escrita en {args.html_es}", file=sys.stderr)

    if args.json:
        import json as _json
        with open(args.json, "w", encoding="utf-8") as f:
            _json.dump([{
                "title": i.get("title", ""),
                "url": i.get("url", ""),
                "category": i.get("category", ""),
                "score": i.get("score", 0),
                "important": i.get("important", False),
                "summary": i.get("summary", ""),
            } for i in items], f, ensure_ascii=False, indent=2)
        print(f"JSON escrito en {args.json}", file=sys.stderr)

    if args.email:
        today = dt.datetime.now().strftime("%Y-%m-%d")
        send_email(f"Productos AI Brief — {today}", md)
    else:
        print("\n" + md)


if __name__ == "__main__":
    main()
