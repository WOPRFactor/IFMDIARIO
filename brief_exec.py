#!/usr/bin/env python3
"""
brief_exec.py — Informe ejecutivo de alto nivel que CRUZA los tres briefs del
dia (IA, Ciberseguridad, GitHub). Lee los *_items.json que exporta cada brief,
le pide a Groq una sintesis ejecutiva (con fallback si no hay IA) y escribe:

  - resumen.html  : pagina ejecutiva para la web (landing), con links a los
                    tres informes detallados.
  - <--out-md>    : version Markdown para encabezar el email unico (opcional).

Uso:
    python3 brief_exec.py --out resumen.html --out-md _exec.md \\
        brief_items.json cyber_items.json github_items.json

Robusto: si falta un JSON se omite; si no hay GROQ_API_KEY o falla, cae a un
modo simple que destaca los items ya marcados como importantes. Nunca rompe.
"""

import argparse
import datetime as dt
import html
import json
import os
import sys

import brief_ai

# Color de acento por informe (coherente con el portal).
REPORT_COLOR = {
    "IA & Gobernanza": "#e67700",
    "Ciberseguridad":  "#c92a2a",
    "GitHub Repos":    "#2b8a3e",
}


def esc(s):
    return html.escape(s or "")


def es_variant(html_name):
    """ia.html -> ia_es.html"""
    base, ext = os.path.splitext(html_name or "")
    return f"{base}_es{ext}" if base else ""


def load_reports(paths):
    reports = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("items"):
                reports.append(data)
        except (OSError, ValueError) as e:
            print(f"[exec] no se pudo leer {p} ({e}), se omite", file=sys.stderr)
    return reports


def fallback_exec(reports):
    """Sin IA: arma el 'top' con los items marcados importantes de cada informe."""
    top = []
    for rep in reports:
        for it in rep.get("items", []):
            if it.get("important"):
                top.append({"report": rep["report"], "category": it.get("category", ""),
                            "title": it.get("title", ""), "link": it.get("link", ""),
                            "porque": ""})
    return {"resumen": "", "top": top[:8]}


def render_markdown(ex, today):
    lines = [f"# Resumen ejecutivo — {today}", ""]
    if ex.get("resumen"):
        lines += [ex["resumen"], ""]
    if ex.get("top"):
        lines.append("**Lo mas importante hoy**")
        for t in ex["top"]:
            line = f"- **[{t['report']}]** {t['title']}"
            if t.get("porque"):
                line += f" — {t['porque']}"
            if t.get("link"):
                line += f" ([fuente]({t['link']}))"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def render_html(ex, reports, today_h, gen_h):
    # Bloque "lo mas importante"
    if ex.get("top"):
        lis = []
        for t in ex["top"]:
            color = REPORT_COLOR.get(t["report"], "#555")
            porque = f'<div class="why">{esc(t["porque"])}</div>' if t.get("porque") else ""
            link = (f'<a class="more" href="{esc(t["link"])}" target="_blank" '
                    f'rel="noopener">Leer mas &rarr;</a>') if t.get("link") else ""
            lis.append(
                f'<li><span class="tag" style="--c:{color}">{esc(t["report"])}</span> '
                f'{esc(t["title"])}{porque}{link}</li>'
            )
        top_html = f'<ul class="highlights">{"".join(lis)}</ul>'
    else:
        top_html = '<p class="empty">Sin destacados hoy.</p>'

    resumen_html = (f'<p class="lead">{esc(ex["resumen"])}</p>'
                    if ex.get("resumen") else "")

    # Tarjetas de navegacion a los informes detallados
    cards = []
    for rep in reports:
        color = REPORT_COLOR.get(rep["report"], "#555")
        en = rep.get("html", "")
        es = es_variant(en)
        links = ""
        if en:
            links += (f'<a class="navbtn" href="{esc(en)}">English</a>')
        if es:
            links += (f'<a class="navbtn navbtn-es" href="{esc(es)}">Español</a>')
        cards.append(
            f'<div class="navcard" style="--c:{color}"><h3>{esc(rep["report"])}</h3>'
            f'<div class="navlinks">{links}</div></div>'
        )
    nav_html = f'<div class="nav">{"".join(cards)}</div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resumen ejecutivo — {today_h}</title>
<style>
  :root {{ --ink:#1a1c23; --muted:#6b7280; --line:#e5e7eb; --bg:#fbfbfd; --card:#fff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.55; -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:48px 22px 80px; }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:18px; margin-bottom:30px; }}
  .eyebrow {{ font-size:12px; letter-spacing:.14em; text-transform:uppercase;
    color:var(--muted); font-weight:700; }}
  h1 {{ font-size:34px; margin:6px 0 4px; letter-spacing:-.02em; }}
  .sub {{ color:var(--muted); font-size:14px; }}
  .lead {{ font-size:17px; line-height:1.6; margin:0 0 30px; }}
  h2.sec {{ font-size:13px; letter-spacing:.12em; text-transform:uppercase;
    color:var(--ink); margin:0 0 14px; }}
  ul.highlights {{ list-style:none; margin:0 0 40px; padding:0; }}
  ul.highlights li {{ padding:14px 0; border-top:1px solid var(--line); font-size:15px; }}
  ul.highlights li:first-child {{ border-top:none; }}
  .tag {{ display:inline-block; font-size:11px; font-weight:700; letter-spacing:.04em;
    text-transform:uppercase; color:var(--c); border:1px solid var(--c);
    border-radius:4px; padding:1px 7px; margin-right:8px; vertical-align:middle; }}
  .why {{ color:var(--muted); font-size:14px; font-style:italic; margin:4px 0 0 2px; }}
  .more {{ font-size:13px; font-weight:600; color:#3b5bdb; text-decoration:none;
    display:inline-block; margin-top:5px; }}
  .more:hover {{ text-decoration:underline; }}
  .empty {{ color:var(--muted); }}
  .nav {{ display:grid; gap:12px; }}
  .navcard {{ background:var(--card); border:1px solid var(--line);
    border-left:4px solid var(--c); border-radius:10px; padding:16px 18px;
    display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
  .navcard h3 {{ font-size:16px; margin:0; }}
  .navlinks {{ display:flex; gap:8px; }}
  .navbtn {{ font-size:13px; font-weight:600; text-decoration:none; padding:5px 16px;
    border-radius:6px; background:#f1f3f5; color:var(--ink); }}
  .navbtn-es {{ background:#3b5bdb; color:#fff; }}
  .navbtn:hover {{ opacity:.85; }}
  footer {{ margin-top:46px; padding-top:18px; border-top:1px solid var(--line);
    font-size:12px; color:var(--muted); }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="eyebrow">Daily Briefs</div>
      <h1>Resumen ejecutivo</h1>
      <div class="sub">{today_h} &middot; generado {gen_h} &middot; sintesis de los tres informes del dia</div>
    </header>
    {resumen_html}
    <h2 class="sec">Lo mas importante hoy</h2>
    {top_html}
    <h2 class="sec">Informes detallados</h2>
    {nav_html}
    <footer>Generado automaticamente. Cada destacado enlaza a su fuente.</footer>
  </div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Informe ejecutivo cruzado")
    parser.add_argument("json_files", nargs="*", help="archivos *_items.json de cada brief")
    parser.add_argument("--out", default="resumen.html", help="pagina HTML de salida")
    parser.add_argument("--out-md", default="", help="Markdown para encabezar el email")
    parser.add_argument("--no-llm", action="store_true", help="forzar modo simple")
    args = parser.parse_args()

    reports = load_reports(args.json_files)
    if not reports:
        print("[exec] no hay informes para resumir.", file=sys.stderr)
        return

    ex = None
    if not args.no_llm and brief_ai.ai_available():
        print("[exec] generando sintesis ejecutiva con IA (Groq)...", file=sys.stderr)
        ex = brief_ai.executive_brief(reports, "un CAIO/CISO ejecutivo")
    if not ex:
        print("[exec] modo simple: destaco los items importantes", file=sys.stderr)
        ex = fallback_exec(reports)

    today = dt.datetime.now().strftime("%Y-%m-%d")
    today_h = dt.datetime.now().strftime("%d/%m/%Y")
    gen_h = dt.datetime.now().strftime("%H:%M")

    page = render_html(ex, reports, today_h, gen_h)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"[exec] pagina ejecutiva escrita en {args.out}", file=sys.stderr)

    if args.out_md:
        with open(args.out_md, "w", encoding="utf-8") as f:
            f.write(render_markdown(ex, today))
        print(f"[exec] markdown ejecutivo escrito en {args.out_md}", file=sys.stderr)


if __name__ == "__main__":
    main()
