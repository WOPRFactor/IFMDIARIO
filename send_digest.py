#!/usr/bin/env python3
"""
send_digest.py — Combina los informes diarios (IA, Cyber, GitHub) en UN solo
email y lo envia via SMTP. Pensado para correr en el workflow despues de que los
tres briefs generaron sus .md.

Uso:
    python3 send_digest.py brief.md cyber_brief.md github_brief.md

Config por variables de entorno:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM, MAIL_TO

Robusto: si falta algun .md se omite esa seccion (no rompe); si faltan las
variables SMTP, no envia y termina sin error.
"""

import datetime as dt
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def extract_meta(md):
    """Saca (titulo corto, cantidad, unidad) de un informe en Markdown.

    Lee el primer encabezado '# ...' (recortando la fecha) y el numero de la
    linea '_Ventana ... N novedades/repositorios ..._'.
    """
    title = "Informe"
    for line in md.split("\n"):
        if line.startswith("# "):
            title = line[2:].split("—")[0].strip()
            break
    m = re.search(r"(\d+)\s+(novedades|repositorios|repos)", md)
    count = int(m.group(1)) if m else None
    unit = m.group(2) if m else "items"
    return title, count, unit


def build_index(parts):
    """Arma el indice de cobertura (inventario) que va al tope del email."""
    today = dt.datetime.now().strftime("%Y-%m-%d")
    lines = [f"# Daily Briefs — {today}", "", "## Cobertura de hoy", ""]
    total = 0
    for md in parts:
        title, count, unit = extract_meta(md)
        if count is not None:
            lines.append(f"- **{title}** — {count} {unit}")
            total += count
        else:
            lines.append(f"- **{title}**")
    lines.append("")
    lines.append(f"_Inventario completo: {total} items en total. "
                 f"Cada informe lista todo lo encontrado, agrupado por categoria._")
    return "\n".join(lines), total


def md_to_basic_html(md):
    """Conversion minima Markdown -> HTML para el cuerpo del email."""
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
    return body


def main():
    files = sys.argv[1:]
    if not files:
        print("[digest] uso: send_digest.py <archivo.md> [...]", file=sys.stderr)
        return

    parts = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                parts.append(f.read().strip())
        except OSError:
            print(f"[digest] no se encontro {path}, se omite", file=sys.stderr)

    if not parts:
        print("[digest] no hay informes para enviar.", file=sys.stderr)
        return

    index_md, total = build_index(parts)
    combined_md = index_md + "\n\n---\n\n" + "\n\n---\n\n".join(parts)

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    mail_from = os.environ.get("MAIL_FROM", user)
    mail_to = os.environ.get("MAIL_TO")

    if not all([host, user, password, mail_to]):
        print("[digest] faltan variables SMTP. No se envia.", file=sys.stderr)
        return

    today = dt.datetime.now().strftime("%Y-%m-%d")
    html_body = (
        "<html><body style='font-family:sans-serif;max-width:720px;margin:0 auto'>"
        + md_to_basic_html(combined_md)
        + "</body></html>"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Daily Briefs — {today} · {total} novedades (IA · Cyber · GitHub)"
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.attach(MIMEText(combined_md, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(mail_from, [a.strip() for a in mail_to.split(",")],
                        msg.as_string())
    print(f"[digest] enviado a {mail_to} ({len(parts)} informes)")


if __name__ == "__main__":
    main()
