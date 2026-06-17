#!/usr/bin/env python3
"""
brief_ai.py — Capa de IA compartida por los tres briefs (IA, Cyber, GitHub).

Usa Groq (API compatible con OpenAI, rapida y barata) para, en un solo modulo:
  - analyze():   resumen ejecutivo + deteccion de tendencias + priorizacion
                 + propuestas de accion, todo en un unico llamado.
  - translate(): traduccion real al espanol (titulo + resumen) de cada item.
  - analysis_to_markdown() / analysis_to_html(): render del bloque ejecutivo.

Filosofia (igual que el resto del proyecto): si no hay GROQ_API_KEY, si la
llamada falla, o si la respuesta no es parseable, TODAS las funciones devuelven
None / dato vacio y el script que llama cae limpiamente al modo simple. Nunca
rompe la generacion del informe.

Config por variables de entorno:
    GROQ_API_KEY   (obligatoria para activar la IA)
    LLM_MODEL      (opcional; default 'llama-3.3-70b-versatile')
                   otras opciones en Groq: 'openai/gpt-oss-120b',
                   'llama-3.1-8b-instant' (mas barato), 'qwen/qwen3-32b'.

Conseguir una API key gratis: https://console.groq.com/keys
"""

import html as _html
import json
import os
import re
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_INPUT_ITEMS = 60  # tope de items que se mandan al modelo por corrida


def ai_available():
    """True si hay API key configurada para intentar el modo IA."""
    return bool(os.environ.get("GROQ_API_KEY"))


def provider_label():
    """Etiqueta legible del proveedor/modelo, para mostrar en el informe."""
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    return f"Groq · {model}"


def _strip_fences(text):
    """Quita posibles cercos ```json ... ``` alrededor de la respuesta."""
    return re.sub(r"^```(?:json)?|```$", "", (text or "").strip()).strip()


def _groq_json(system, user, max_tokens=1500, temperature=0.3):
    """Llama a Groq pidiendo JSON y devuelve el objeto parseado, o None.

    Cualquier fallo (sin key, red, HTTP, JSON invalido) devuelve None para que
    el llamador caiga al modo simple sin romperse.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODEL

    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # Fuerza salida JSON. Requiere mencionar "JSON" en el prompt (lo hacemos).
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")

    req = Request(
        GROQ_URL,
        data=payload,
        headers={
            "content-type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        print(f"[ai] HTTP {e.code}: modo simple {detail}", file=sys.stderr)
        return None
    except (URLError, TimeoutError, ValueError) as e:
        print(f"[ai] error ({e}): modo simple", file=sys.stderr)
        return None

    try:
        text = data["choices"][0]["message"]["content"]
        return json.loads(_strip_fences(text))
    except (KeyError, IndexError, ValueError, TypeError) as e:
        print(f"[ai] respuesta no parseable ({e}): modo simple", file=sys.stderr)
        return None


def analyze(norm, audience):
    """Analisis ejecutivo completo en UN solo llamado.

    norm:     lista de dicts {idx, category, title, summary}.
    audience: descripcion del rol destino (ej. 'un CAIO (Chief AI Officer)').

    Devuelve dict {resumen, tendencias[], destacadas[], orden[]} o None.
    """
    if not norm:
        return None
    catalog = "\n".join(
        f"[{it['idx']}] ({it['category']}) {it['title']} — {it['summary'][:200]}"
        for it in norm[:MAX_INPUT_ITEMS]
    )
    system = (
        f"Sos analista senior para {audience}. Te paso titulares numerados de "
        "novedades del dia. Analizalos y devolve SOLO un JSON valido (sin texto "
        "extra), redactado en espanol rioplatense, con esta forma EXACTA:\n"
        "{\n"
        '  "resumen": "<2 a 4 frases conectando lo mas importante del dia y que '
        'implica para la organizacion>",\n'
        '  "tendencias": [{"tema": "<patron/tendencia>", "detalle": "<1 frase>", '
        '"refs": [<idx>, ...]}],\n'
        '  "destacadas": [{"idx": <numero>, "porque": "<por que importa, 1 frase>", '
        '"accion": "<que hacer o escalar concretamente, 1 frase>"}],\n'
        '  "orden": [<idx en orden de prioridad ejecutiva>]\n'
        "}\n"
        "Elegi 5 a 7 destacadas priorizando riesgo, regulacion e impacto de "
        "negocio. Detecta 2 a 4 tendencias agrupando titulares relacionados. "
        "Usa solo indices que existan en la lista."
    )
    user = f"Titulares:\n{catalog}"
    parsed = _groq_json(system, user, max_tokens=2200)
    if not isinstance(parsed, dict):
        return None
    if not parsed.get("destacadas") and not parsed.get("resumen"):
        return None
    return parsed


def translate(norm):
    """Traduce title+summary al espanol. Devuelve {idx: {title, summary}} o None."""
    if not norm:
        return None
    catalog = [{"i": it["idx"], "t": it["title"], "s": (it["summary"] or "")[:220]}
               for it in norm[:MAX_INPUT_ITEMS]]
    system = (
        "Sos traductor tecnico EN->ES (espanol rioplatense, claro y preciso). "
        "Traduci cada 't' (titulo) y 's' (resumen) al espanol. Mante SIN traducir "
        "nombres propios, marcas, siglas tecnicas, identificadores CVE y nombres "
        "de productos o proyectos. Devolve SOLO un JSON valido con esta forma: "
        '{"items": [{"i": <numero>, "t": "<titulo ES>", "s": "<resumen ES>"}]}'
    )
    user = json.dumps(catalog, ensure_ascii=False)
    parsed = _groq_json(system, user, max_tokens=4000, temperature=0.2)
    if not isinstance(parsed, dict):
        return None
    out = {}
    for entry in parsed.get("items", []):
        try:
            out[int(entry["i"])] = {
                "title": (entry.get("t") or "").strip(),
                "summary": (entry.get("s") or "").strip(),
            }
        except (KeyError, ValueError, TypeError):
            continue
    return out or None


# ----------------------------------------------------------------------------
# RENDER DEL BLOQUE EJECUTIVO (compartido por los tres informes)
# ----------------------------------------------------------------------------

def _esc(s):
    return _html.escape(s or "")


def analysis_to_markdown(analysis, norm):
    """Convierte el dict de analisis en Markdown para el resumen ejecutivo."""
    if not analysis:
        return None
    by_idx = {it["idx"]: it for it in norm}
    out = []

    resumen = (analysis.get("resumen") or "").strip()
    if resumen:
        out.append(resumen)
        out.append("")

    tendencias = analysis.get("tendencias") or []
    trend_lines = []
    for t in tendencias:
        tema = (t.get("tema") or "").strip()
        if not tema:
            continue
        detalle = (t.get("detalle") or "").strip()
        trend_lines.append(f"- **{tema}**" + (f" — {detalle}" if detalle else ""))
    if trend_lines:
        out.append("**Tendencias del dia**")
        out.extend(trend_lines)
        out.append("")

    destacadas = analysis.get("destacadas") or []
    dest_lines = []
    for d in destacadas:
        try:
            it = by_idx[int(d["idx"])]
        except (KeyError, ValueError, TypeError):
            continue
        dest_lines.append(f"- **[{it['category']}]** {it['title']}  ")
        porque = (str(d.get("porque", "")) or "").strip()
        accion = (str(d.get("accion", "")) or "").strip()
        if porque:
            dest_lines.append(f"  _{porque}_  ")
        if accion:
            dest_lines.append(f"  -> **Accion:** {accion}  ")
        if it.get("link"):
            dest_lines.append(f"  [Leer mas]({it['link']})")
    if dest_lines:
        out.append("**Destacadas**")
        out.extend(dest_lines)

    text = "\n".join(out).strip()
    return text or None


def analysis_to_html(analysis, norm, cat_color):
    """Convierte el dict de analisis en HTML para el bloque ejecutivo.

    Usa las clases CSS existentes (.highlights, .tag, .why, .more) y estilos
    inline para los elementos nuevos (resumen y tendencias), asi no hace falta
    tocar el <style> de cada pagina.
    """
    if not analysis:
        return None
    by_idx = {it["idx"]: it for it in norm}
    parts = []

    resumen = (analysis.get("resumen") or "").strip()
    if resumen:
        parts.append(
            '<p style="font-size:15px;line-height:1.6;margin:0 0 18px;color:#1a1c23">'
            f'{_esc(resumen)}</p>'
        )

    tendencias = analysis.get("tendencias") or []
    trend_lis = []
    for t in tendencias:
        tema = (t.get("tema") or "").strip()
        if not tema:
            continue
        detalle = (t.get("detalle") or "").strip()
        suffix = f' &mdash; {_esc(detalle)}' if detalle else ""
        trend_lis.append(
            f'<li style="margin:0 0 5px;font-size:14px">'
            f'<strong>{_esc(tema)}</strong>{suffix}</li>'
        )
    if trend_lis:
        parts.append(
            '<div style="margin:0 0 18px">'
            '<div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;'
            'color:#6b7280;font-weight:700;margin-bottom:7px">Tendencias del dia</div>'
            f'<ul style="margin:0;padding-left:18px">{"".join(trend_lis)}</ul></div>'
        )

    destacadas = analysis.get("destacadas") or []
    dest_lis = []
    for d in destacadas:
        try:
            it = by_idx[int(d["idx"])]
        except (KeyError, ValueError, TypeError):
            continue
        color = cat_color.get(it["category"], "#555")
        porque = (d.get("porque") or "").strip()
        accion = (d.get("accion") or "").strip()
        why = f'<div class="why">{_esc(porque)}</div>' if porque else ""
        act = (
            '<div style="font-size:13px;color:#0c5a2e;margin:3px 0 0 2px">'
            f'<strong>Accion:</strong> {_esc(accion)}</div>'
        ) if accion else ""
        more = (
            f'<a class="more" href="{_esc(it.get("link"))}" target="_blank" '
            f'rel="noopener">Leer mas &rarr;</a>'
        ) if it.get("link") else ""
        dest_lis.append(
            f'<li><span class="tag" style="--c:{color}">{_esc(it["category"])}</span> '
            f'{_esc(it["title"])}{why}{act}{more}</li>'
        )
    if dest_lis:
        parts.append(f'<ul class="highlights">{"".join(dest_lis)}</ul>')

    return "\n".join(parts) if parts else None


# ----------------------------------------------------------------------------
# FILTROS INTERACTIVOS (client-side) — compartidos por las tres paginas
# Las tarjetas llevan data-cat / data-imp / data-src / data-text; estas dos
# funciones inyectan la barra de controles y el JS que filtra en el navegador.
# ----------------------------------------------------------------------------

def card_data_attrs(category, source, text, important):
    """Devuelve los atributos data-* (ya escapados) para una tarjeta .card."""
    blob = _esc((text or "").lower())
    return (
        f'data-cat="{_esc(category)}" '
        f'data-src="{_esc(source) or "—"}" '
        f'data-imp="{"1" if important else "0"}" '
        f'data-text="{blob}"'
    )


def filter_bar_html(source_label="Fuente"):
    """HTML + estilos de la barra de filtros. Categorias y fuentes se completan
    solas via JS (filter_script) leyendo los data-* de las tarjetas."""
    return (
        "<style>"
        ".filters{background:#fff;border:1px solid #e5e7eb;border-radius:12px;"
        "padding:14px 16px;margin:0 0 26px}"
        ".fchips{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:10px}"
        ".fchip{font:600 12px/1 inherit;cursor:pointer;border:1px solid #cbd2dc;"
        "background:#f8f9fb;color:#374151;border-radius:20px;padding:6px 13px}"
        ".fchip.on{background:#1a1c23;color:#fff;border-color:#1a1c23}"
        ".frow{display:flex;flex-wrap:wrap;align-items:center;gap:10px}"
        ".filters input[type=search]{flex:1;min-width:150px;font-size:14px;"
        "padding:7px 11px;border:1px solid #cbd2dc;border-radius:8px}"
        ".filters select{font-size:13px;padding:7px 9px;border:1px solid #cbd2dc;"
        "border-radius:8px;background:#fff;max-width:200px}"
        ".ftoggle{font-size:13px;color:#374151;display:flex;align-items:center;"
        "gap:5px;cursor:pointer;white-space:nowrap}"
        ".fcount{font-size:12px;color:#6b7280;margin-left:auto}"
        "</style>"
        '<div class="filters">'
        '<div class="fchips" id="f-cats"></div>'
        '<div class="frow">'
        '<input type="search" id="f-q" placeholder="Buscar en titulo y resumen...">'
        f'<select id="f-src"><option value="">{_esc(source_label)} (todas)</option></select>'
        '<label class="ftoggle"><input type="checkbox" id="f-imp"> Solo importantes</label>'
        '<span class="fcount" id="f-count"></span>'
        "</div></div>"
    )


def filter_script():
    """JS vanilla: filtra por categoria, fuente, importantes y texto; oculta las
    secciones que quedan vacias. Auto-descubre categorias y fuentes del DOM."""
    return """<script>
(function(){
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var sections=[].slice.call(document.querySelectorAll('section'));
  var catBox=document.getElementById('f-cats');
  var srcSel=document.getElementById('f-src');
  var impChk=document.getElementById('f-imp');
  var q=document.getElementById('f-q');
  var countEl=document.getElementById('f-count');
  if(!catBox) return;
  var active={}, cats=[], srcs=[];
  cards.forEach(function(c){
    var cat=c.getAttribute('data-cat')||'', src=c.getAttribute('data-src')||'';
    if(cat&&cats.indexOf(cat)<0)cats.push(cat);
    if(src&&src!=='\\u2014'&&srcs.indexOf(src)<0)srcs.push(src);
  });
  cats.forEach(function(cat){
    var b=document.createElement('button');
    b.type='button'; b.className='fchip'; b.textContent=cat;
    b.addEventListener('click',function(){
      if(active[cat]){delete active[cat];b.classList.remove('on');}
      else{active[cat]=1;b.classList.add('on');}
      apply();
    });
    catBox.appendChild(b);
  });
  srcs.sort().forEach(function(s){
    var o=document.createElement('option'); o.value=s; o.textContent=s; srcSel.appendChild(o);
  });
  function apply(){
    var anyCat=Object.keys(active).length>0, src=srcSel.value,
        imp=impChk.checked, t=(q.value||'').trim().toLowerCase(), vis=0;
    cards.forEach(function(c){
      var ok=(!anyCat||active[c.getAttribute('data-cat')])
        &&(!src||c.getAttribute('data-src')===src)
        &&(!imp||c.getAttribute('data-imp')==='1')
        &&(!t||(c.getAttribute('data-text')||'').indexOf(t)>=0);
      c.style.display=ok?'':'none'; if(ok)vis++;
    });
    sections.forEach(function(sec){
      var has=[].some.call(sec.querySelectorAll('.card'),function(c){return c.style.display!=='none';});
      sec.style.display=has?'':'none';
    });
    if(countEl)countEl.textContent=vis+' visibles';
  }
  srcSel.addEventListener('change',apply);
  impChk.addEventListener('change',apply);
  q.addEventListener('input',apply);
  apply();
})();
</script>"""
