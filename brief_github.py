#!/usr/bin/env python3
"""
GitHub Repos Brief — Informe diario de repositorios nuevos y en tendencia
sobre IA, Agentes y Ciberseguridad.

Usa la API publica de GitHub Search (sin autenticacion).
Limite: 10 requests/hora sin token — una corrida diaria usa ~9 requests.

Uso:
    python brief_github.py                  # genera github_brief.md
    python brief_github.py --email          # ademas lo envia por email

Configuracion por variables de entorno (para email):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM, MAIL_TO
    GITHUB_TOKEN  (opcional — sube el limite a 5000 req/hora)
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
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

# ----------------------------------------------------------------------------
# BUSQUEDAS
# Cada entrada: (categoria, etiqueta, query GitHub Search)
# Documentacion: https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories
# ----------------------------------------------------------------------------
SEARCHES = [
    # --- Inteligencia Artificial / LLMs ---
    ("IA & LLMs", "Nuevos LLMs y modelos",
     "llm OR \"language model\" OR \"foundation model\" stars:>50"),
    ("IA & LLMs", "RAG y retrieval",
     "rag OR \"retrieval augmented\" OR \"vector store\" stars:>30"),
    ("IA & LLMs", "Fine-tuning y entrenamiento",
     "\"fine-tuning\" OR \"fine tuning\" OR qlora OR lora stars:>30"),

    # --- Agentes IA ---
    ("Agentes", "Frameworks de agentes",
     "\"ai agent\" OR \"autonomous agent\" OR langgraph OR crewai OR autogen stars:>50"),
    ("Agentes", "Herramientas MCP y tool use",
     "\"model context protocol\" OR mcp OR \"tool use\" OR \"function calling\" stars:>20"),
    ("Agentes", "Automatizacion y workflows",
     "\"agentic\" OR \"multi-agent\" OR \"agent workflow\" stars:>30"),

    # --- Ciberseguridad ---
    ("Ciberseguridad", "Exploits y vulnerabilidades",
     "exploit OR \"proof of concept\" OR poc OR cve stars:>20"),
    ("Ciberseguridad", "Red team y pentest",
     "\"red team\" OR pentest OR \"penetration testing\" OR c2 stars:>30"),
    ("Ciberseguridad", "Malware y analisis",
     "malware OR ransomware OR \"reverse engineering\" OR \"threat intel\" stars:>20"),
]

LOOKBACK_DAYS = 7       # ventana: repos creados o actualizados en los ultimos N dias
MAX_PER_SEARCH = 5      # tope de repos por busqueda
DELAY_BETWEEN_REQUESTS = 7  # segundos entre requests para respetar rate limit
USER_AGENT = "Mozilla/5.0 (GitHub-Repos-Brief/1.0)"

IMPORTANT_KEYWORDS = [
    "exploit", "vulnerability", "zero-day", "cve", "malware", "ransomware",
    "breakthrough", "release", "new model", "state of the art", "sota",
    "autonomous", "agent framework", "production", "open source",
]

LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_MAX_OUTPUT_TOKENS = 1500


# ----------------------------------------------------------------------------
# GITHUB API
# ----------------------------------------------------------------------------

def github_search(query, pushed_since):
    """Busca repos en GitHub creados o con push reciente, ordenados por estrellas."""
    date_filter = pushed_since.strftime("%Y-%m-%d")
    full_query = f"{query} pushed:>{date_filter}"
    params = urlencode({
        "q": full_query,
        "sort": "stars",
        "order": "desc",
        "per_page": MAX_PER_SEARCH * 2,
    })
    url = f"https://api.github.com/search/repositories?{params}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers)
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def score_repo(repo):
    score = {"Ciberseguridad": 3, "Agentes": 2, "IA & LLMs": 1}.get(repo["category"], 0)
    blob = f"{repo['name']} {repo['description']} {' '.join(repo['topics'])}".lower()
    score += sum(1 for kw in IMPORTANT_KEYWORDS if kw in blob)
    score += min(repo["stars"] // 500, 3)  # bonus por estrellas (max 3 pts)
    return score


def mark_important(repos, top_n=5):
    scored = sorted(enumerate(repos), key=lambda x: score_repo(x[1]), reverse=True)
    top = {i for i, _ in scored[:top_n]}
    for i, r in enumerate(repos):
        r["important"] = i in top
    return repos


def add_translations(repos):
    texts = [r["description"] for r in repos]
    translated = translate_batch(texts)
    for r, es in zip(repos, translated):
        r["description_es"] = es if es and es.strip() != r["description"].strip() else ""
    return repos


def collect():
    """Recorre todas las busquedas y devuelve repos relevantes."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)
    results = []
    errors = []

    for i, (category, label, query) in enumerate(SEARCHES):
        if i > 0:
            time.sleep(DELAY_BETWEEN_REQUESTS)
        try:
            data = github_search(query, since)
            repos = data.get("items", [])[:MAX_PER_SEARCH]
            for r in repos:
                pushed = r.get("pushed_at") or r.get("created_at")
                results.append({
                    "category": category,
                    "label": label,
                    "name": r.get("full_name", ""),
                    "description": (r.get("description") or "")[:200],
                    "url": r.get("html_url", ""),
                    "stars": r.get("stargazers_count", 0),
                    "language": r.get("language") or "",
                    "topics": r.get("topics", [])[:6],
                    "pushed_at": pushed,
                    "created_at": r.get("created_at"),
                })
        except HTTPError as e:
            if e.code == 403:
                errors.append(f"{label}: rate limit alcanzado (HTTP 403)")
            else:
                errors.append(f"{label}: HTTP {e.code}")
        except (URLError, TimeoutError) as e:
            errors.append(f"{label}: {e}")
        except Exception as e:
            errors.append(f"{label}: {type(e).__name__}: {e}")

    # Deduplica por URL (un repo puede aparecer en varias busquedas)
    seen = set()
    unique = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    return unique, errors


# ----------------------------------------------------------------------------
# CAPA LLM OPCIONAL
# ----------------------------------------------------------------------------

def llm_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def llm_highlight(repos):
    """Pide a Claude que destaque los repos mas interesantes."""
    from urllib.request import Request as _Req, urlopen as _open
    from urllib.error import URLError as _URLErr, HTTPError as _HTTPErr

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not repos:
        return None

    catalog = []
    for i, r in enumerate(repos[:60]):
        topics = ", ".join(r["topics"]) if r["topics"] else ""
        catalog.append(
            f"[{i}] ({r['category']}) {r['name']} ★{r['stars']} "
            f"— {r['description']} [{topics}]"
        )

    system = (
        "Sos analista tecnico para un CAIO/CISO. Te paso una lista de repositorios "
        "GitHub recientes sobre IA, agentes y ciberseguridad. "
        "Elegi los 5 a 7 MAS RELEVANTES para un ejecutivo tecnico "
        "(priorizando herramientas practicas, exploits activos, frameworks nuevos "
        "con traccion, o proyectos que cambian el estado del arte). "
        "Para cada uno escribi UNA frase explicando por que es importante, "
        "en espanol, concreta. "
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
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
        parsed = json.loads(text)
        destacados = parsed.get("destacados", [])
    except (ValueError, KeyError, AttributeError) as e:
        print(f"[llm] no parseable ({e}): modo simple", file=sys.stderr)
        return None

    if not destacados:
        return None

    out = []
    for d in destacados:
        try:
            r = repos[int(d["idx"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        porque = str(d.get("porque", ""))[:300]
        stars = f"★{r['stars']:,}"
        out.append(f"- **[{r['category']}]** [{r['name']}]({r['url']}) {stars}  ")
        if porque:
            out.append(f"  _{porque}_")
    return "\n".join(out) if out else None


def llm_translate_repos(repos):
    """Traduce descripciones al espanol via Claude."""
    from urllib.request import Request as _Req, urlopen as _open

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not repos:
        return None

    catalog = [{"i": i, "d": r["description"]}
               for i, r in enumerate(repos[:60]) if r["description"]]

    system = (
        "Traducí cada 'd' (description) al español rioplatense, tecnico y preciso. "
        "Mantené nombres propios, siglas tecnicas y nombres de proyectos sin traducir. "
        "Devolve SOLO JSON valido: "
        '{"items": [{"i": <numero>, "d": "<descripcion traducida>"}]}'
    )

    payload = json.dumps({
        "model": LLM_MODEL,
        "max_tokens": 3000,
        "system": system,
        "messages": [{"role": "user", "content": json.dumps(catalog, ensure_ascii=False)}],
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
    except Exception as e:
        print(f"[translate] error ({e}): omitido", file=sys.stderr)
        return None

    try:
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
        translations = {entry["i"]: entry["d"] for entry in json.loads(text).get("items", [])}
    except Exception as e:
        print(f"[translate] no parseable ({e}): omitido", file=sys.stderr)
        return None

    translated = copy.deepcopy(repos)
    for i, r in enumerate(translated[:60]):
        if i in translations:
            r["description"] = translations[i]
    return translated


# ----------------------------------------------------------------------------
# GENERACION DEL INFORME
# ----------------------------------------------------------------------------

ORDER = ["IA & LLMs", "Agentes", "Ciberseguridad"]
CAT_COLOR = {
    "IA & LLMs":      "#3b5bdb",
    "Agentes":        "#0c8599",
    "Ciberseguridad": "#c92a2a",
}


def fmt_date(iso):
    if not iso:
        return "s/f"
    try:
        d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%d/%m/%Y")
    except ValueError:
        return iso[:10]


def build_markdown(repos, errors, highlight_md=None):
    today = dt.datetime.now().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"# GitHub Repos Brief — {today}")
    lines.append("")
    lines.append(f"_Ventana: ultimos {LOOKBACK_DAYS} dias · {len(repos)} repositorios · "
                 f"generado automaticamente_")
    lines.append("")
    lines.append("## Destacados")

    if highlight_md:
        lines.append("_Seleccion y analisis por IA (Claude)_")
        lines.append("")
        lines.append(highlight_md)
    else:
        top = sorted(repos, key=lambda r: r["stars"], reverse=True)[:6]
        for r in top:
            lines.append(f"- **[{r['category']}]** [{r['name']}]({r['url']}) "
                         f"★{r['stars']:,} — {r['description']}")
    lines.append("")

    for cat in ORDER:
        cat_repos = [r for r in repos if r["category"] == cat]
        if not cat_repos:
            continue
        lines.append(f"## {cat}")
        # agrupa por label dentro de la categoria
        labels_seen = []
        for r in cat_repos:
            if r["label"] not in labels_seen:
                labels_seen.append(r["label"])
        for label in labels_seen:
            label_repos = [r for r in cat_repos if r["label"] == label]
            lines.append(f"### {label}")
            for r in label_repos:
                topics_str = " · ".join(r["topics"]) if r["topics"] else ""
                marker = "**[IMPORTANTE]** " if r.get("important") else ""
                lines.append(f"#### {marker}[{r['name']}]({r['url']}) ★{r['stars']:,}")
                if r["language"]:
                    lines.append(f"_{r['language']} · actualizado {fmt_date(r['pushed_at'])}_")
                if r["description"]:
                    lines.append("")
                    lines.append(r["description"])
                if r.get("description_es"):
                    lines.append("")
                    lines.append(f"> **ES:** {r['description_es']}")
                if topics_str:
                    lines.append("")
                    lines.append(f"`{topics_str}`")
                lines.append("")
    lines.append("---")
    lines.append("## Accion recomendada")
    lines.append("- Evaluar repos de **Agentes** para adopcion en proyectos internos.")
    lines.append("- Revisar **Ciberseguridad**: nuevos exploits pueden afectar tu stack.")
    lines.append("- Compartir destacados de **IA & LLMs** con el equipo tecnico.")
    lines.append("")

    if errors:
        lines.append("<details><summary>Busquedas con error</summary>")
        lines.append("")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("</details>")

    return "\n".join(lines)


def build_html_page(repos, errors, highlight_md=None):
    today_h = dt.datetime.now().strftime("%d/%m/%Y")
    gen_h = dt.datetime.now().strftime("%H:%M")

    def esc(s):
        return html.escape(s or "")

    if highlight_md:
        modo = "Seleccion y analisis por IA"
        hi_html = []
        for line in highlight_md.split("\n"):
            line = line.strip()
            m = re.match(r"- \*\*\[(.+?)\]\*\* \[(.+?)\]\((.+?)\) (★[\d,]+)\s*$", line)
            if m:
                color = CAT_COLOR.get(m.group(1), "#555")
                hi_html.append(
                    f'<li><span class="tag" style="--c:{color}">{esc(m.group(1))}</span> '
                    f'<a href="{esc(m.group(3))}" target="_blank" rel="noopener">{esc(m.group(2))}</a> '
                    f'<span class="stars">{esc(m.group(4))}</span>'
                )
            elif line.startswith("_") and line.endswith("_"):
                hi_html.append(f'<div class="why">{esc(line.strip("_ "))}</div></li>')
        highlight_html = "<ul class='highlights'>" + "\n".join(hi_html) + "</ul>"
    else:
        modo = "Top repos por estrellas"
        top = sorted(repos, key=lambda r: r["stars"], reverse=True)[:6]
        lis = [
            f'<li><span class="tag" style="--c:{CAT_COLOR.get(r["category"], "#555")}">'
            f'{esc(r["category"])}</span> '
            f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["name"])}</a> '
            f'<span class="stars">★{r["stars"]:,}</span> — {esc(r["description"])}</li>'
            for r in top
        ]
        highlight_html = "<ul class='highlights'>" + "\n".join(lis) + "</ul>"

    sections = []
    for cat in ORDER:
        cat_repos = [r for r in repos if r["category"] == cat]
        if not cat_repos:
            continue
        cards = []
        for r in cat_repos:
            topics_html = "".join(
                f'<span class="topic">{esc(t)}</span>' for t in r["topics"]
            )
            important_badge = '<span class="badge-imp">IMPORTANTE</span>' if r.get("important") else ""
            desc_en = f'<p class="summary">{esc(r["description"])}</p>' if r["description"] else ""
            desc_es = (f'<p class="summary-es"><span class="es-label">ES</span> {esc(r["description_es"])}</p>'
                       if r.get("description_es") else "")
            lang = f'<span class="lang">{esc(r["language"])}</span>' if r["language"] else ""
            cards.append(
                f'<article class="card{"  card-imp" if r.get("important") else ""}">'
                f'<h3>{important_badge}<a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["name"])}</a>'
                f' <span class="stars">★{r["stars"]:,}</span></h3>'
                f'<div class="meta">{lang} · actualizado {fmt_date(r["pushed_at"])}</div>'
                f'{desc_en}{desc_es}'
                f'<div class="topics">{topics_html}</div>'
                f'</article>'
            )
        color = CAT_COLOR.get(cat, "#555")
        sections.append(
            f'<section><h2 style="--c:{color}">{esc(cat)}'
            f'<span class="count">{len(cat_repos)}</span></h2>'
            f'<div class="cards">{"".join(cards)}</div></section>'
        )

    errors_html = ""
    if errors:
        err_items = "".join(f"<li>{esc(e)}</li>" for e in errors)
        errors_html = (
            f'<details class="errors"><summary>Busquedas con error ({len(errors)})</summary>'
            f'<ul>{err_items}</ul></details>'
        )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GitHub Repos Brief — {today_h}</title>
<style>
  :root {{
    --ink: #1a1c23; --muted: #6b7280; --line: #e5e7eb;
    --bg: #f6f8fa; --card: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.55; -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 48px 22px 80px; }}
  header {{ border-bottom: 2px solid #24292f; padding-bottom: 18px; margin-bottom: 32px; }}
  .eyebrow {{ font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
    color: var(--muted); font-weight: 700; }}
  h1 {{ font-size: 34px; margin: 6px 0 4px; letter-spacing: -.02em; }}
  .sub {{ color: var(--muted); font-size: 14px; }}
  .exec {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 22px 24px; margin-bottom: 40px; box-shadow: 0 1px 3px rgba(0,0,0,.04); }}
  .exec h2 {{ font-size: 13px; letter-spacing: .12em; text-transform: uppercase;
    margin: 0 0 4px; }}
  .exec .mode {{ font-size: 12px; color: var(--muted); margin-bottom: 14px; }}
  ul.highlights {{ list-style: none; margin: 0; padding: 0; }}
  ul.highlights li {{ padding: 12px 0; border-top: 1px solid var(--line); }}
  ul.highlights li:first-child {{ border-top: none; }}
  .tag {{ display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: var(--c); border: 1px solid var(--c);
    border-radius: 4px; padding: 1px 7px; margin-right: 6px; vertical-align: middle; }}
  .stars {{ font-size: 13px; color: #b08800; font-weight: 600; margin-left: 4px; }}
  .why {{ color: var(--muted); font-size: 14px; font-style: italic; margin: 4px 0 0 2px; }}
  section {{ margin-bottom: 38px; }}
  section h2 {{ font-size: 20px; border-left: 4px solid var(--c); padding-left: 12px;
    margin: 0 0 16px; display: flex; align-items: center; gap: 10px; }}
  .count {{ font-size: 12px; font-weight: 600; color: var(--muted); background: var(--line);
    border-radius: 20px; padding: 2px 9px; }}
  .cards {{ display: grid; gap: 14px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 16px 18px; }}
  .card h3 {{ font-size: 15px; margin: 0 0 4px; display: flex; align-items: baseline; gap: 6px; }}
  .card h3 a {{ color: var(--ink); text-decoration: none; font-weight: 600; }}
  .card h3 a:hover {{ text-decoration: underline; }}
  .meta {{ font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
  .lang {{ font-weight: 600; }}
  .summary {{ font-size: 14px; margin: 0 0 6px; color: #374151; }}
  .summary-es {{ font-size: 14px; margin: 0 0 8px; color: #0a3b1e;
    background: #f0fff4; border-left: 3px solid #2b8a3e;
    padding: 6px 10px; border-radius: 0 6px 6px 0; }}
  .es-label {{ font-size: 10px; font-weight: 700; letter-spacing: .08em;
    color: #2b8a3e; text-transform: uppercase; margin-right: 6px; }}
  .badge-imp {{ display: inline-block; font-size: 10px; font-weight: 700;
    letter-spacing: .06em; text-transform: uppercase; background: #fff3bf;
    color: #835400; border: 1px solid #f0c040; border-radius: 4px;
    padding: 1px 7px; margin-right: 8px; vertical-align: middle; }}
  .card-imp {{ border-left: 3px solid #f0c040 !important; }}
  .topics {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }}
  .topic {{ font-size: 11px; background: #f1f3f5; color: #3b5bdb; border-radius: 20px;
    padding: 2px 9px; }}
  .errors {{ margin-top: 30px; font-size: 13px; color: var(--muted); }}
  footer {{ margin-top: 50px; padding-top: 18px; border-top: 1px solid var(--line);
    font-size: 12px; color: var(--muted); }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="eyebrow">GitHub Repos Brief</div>
      <h1>Repositorios en tendencia</h1>
      <div class="sub">{today_h} &middot; generado {gen_h} &middot; ultimos {LOOKBACK_DAYS} dias &middot; {len(repos)} repos</div>
    </header>
    <div class="exec">
      <h2>Destacados</h2>
      <div class="mode">{modo}</div>
      {highlight_html}
    </div>
    {"".join(sections) if sections else "<p>Sin resultados.</p>"}
    {errors_html}
    <footer>Generado automaticamente via GitHub Search API. Cada repo enlaza a GitHub.</footer>
  </div>
</body>
</html>"""


# ----------------------------------------------------------------------------
# EMAIL
# ----------------------------------------------------------------------------

def md_to_basic_html(md):
    out = []
    for line in md.split("\n"):
        if line.startswith("#### "):
            out.append(f"<h4>{line[5:]}</h4>")
        elif line.startswith("### "):
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
    parser = argparse.ArgumentParser(description="GitHub Repos Brief")
    parser.add_argument("--email", action="store_true", help="enviar por email")
    parser.add_argument("--out", default="github_brief.md",
                        help="archivo Markdown de salida")
    parser.add_argument("--out-es", default="github_brief_es.md",
                        help="archivo Markdown en espanol")
    parser.add_argument("--html", default="github_index.html",
                        help="archivo HTML para GitHub Pages")
    parser.add_argument("--html-es", default="github_index_es.html",
                        help="archivo HTML en espanol")
    parser.add_argument("--no-llm", action="store_true",
                        help="modo simple sin IA")
    args = parser.parse_args()

    print("Buscando repositorios en GitHub...", file=sys.stderr)
    repos, errors = collect()
    print(f"  {len(repos)} repos unicos, {len(errors)} busquedas con error", file=sys.stderr)

    mark_important(repos)
    print("[traduccion] Traduciendo descripciones al espanol...", file=sys.stderr)
    add_translations(repos)

    highlight_md = None
    if args.no_llm:
        print("[modo] simple (forzado por --no-llm)", file=sys.stderr)
    elif not llm_available():
        print("[modo] simple (sin ANTHROPIC_API_KEY)", file=sys.stderr)
    else:
        print("[modo] intentando destacado por IA...", file=sys.stderr)
        highlight_md = llm_highlight(repos)
        if highlight_md:
            print("[modo] IA OK", file=sys.stderr)
        else:
            print("[modo] IA no disponible -> fallback simple", file=sys.stderr)

    md = build_markdown(repos, errors, highlight_md=highlight_md)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Informe escrito en {args.out}", file=sys.stderr)

    page = build_html_page(repos, errors, highlight_md=highlight_md)
    with open(args.html, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Pagina web escrita en {args.html}", file=sys.stderr)

    if not args.no_llm and llm_available():
        print("[es] Traduciendo descripciones al espanol...", file=sys.stderr)
        repos_es = llm_translate_repos(repos)
        if repos_es:
            md_es = build_markdown(repos_es, errors, highlight_md=highlight_md)
            with open(args.out_es, "w", encoding="utf-8") as f:
                f.write(md_es)
            print(f"[es] Informe en espanol escrito en {args.out_es}", file=sys.stderr)
            page_es = build_html_page(repos_es, errors, highlight_md=highlight_md)
            with open(args.html_es, "w", encoding="utf-8") as f:
                f.write(page_es)
            print(f"[es] Pagina web en espanol escrita en {args.html_es}", file=sys.stderr)
        else:
            print("[es] Traduccion no disponible", file=sys.stderr)
    else:
        print("[es] Sin API key -> version en espanol omitida", file=sys.stderr)

    if args.email:
        today = dt.datetime.now().strftime("%Y-%m-%d")
        send_email(f"GitHub Repos Brief — {today}", md)
    else:
        print("\n" + md)


if __name__ == "__main__":
    main()
