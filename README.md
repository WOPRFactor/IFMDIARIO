# AI Daily Brief

Informe diario automatico de novedades en **IA, gobierno de IA, vulnerabilidades
y regulacion**, pensado para un rol de CAIO / liderazgo de IA.

Recolecta de fuentes RSS/Atom publicas, filtra por relevancia y por las ultimas
48 horas, agrupa en secciones (Regulacion, Gobierno de IA, Vulnerabilidades,
Tecnologia) y genera un informe en Markdown que ademas puede llegarte por email.

No tiene dependencias externas: usa solo la libreria estandar de Python 3.

---

## Opcion A — Correr en la nube con GitHub Actions (recomendado)

Corre solo cada dia sin tener la PC prendida. Es gratis.

1. Crea un repositorio nuevo en GitHub y subi estos archivos
   (`brief.py`, la carpeta `.github/`, este README).
2. En el repo, anda a **Settings -> Secrets and variables -> Actions** y agrega
   estos *secrets* (para el envio por email):

   | Secret      | Ejemplo                        | Que es |
   |-------------|--------------------------------|--------|
   | `SMTP_HOST` | `smtp.gmail.com`               | Servidor de correo saliente |
   | `SMTP_PORT` | `587`                          | Puerto (587 con STARTTLS) |
   | `SMTP_USER` | `tucuenta@gmail.com`           | Usuario SMTP |
   | `SMTP_PASS` | `xxxx xxxx xxxx xxxx`          | Contrasena de aplicacion (ver abajo) |
   | `MAIL_FROM` | `tucuenta@gmail.com`           | Remitente |
   | `MAIL_TO`   | `vos@empresa.com,otro@emp.com` | Destinatarios (coma para varios) |

3. Listo. Cada dia a las **08:00 de Argentina** se generan los tres informes
   (IA, Ciberseguridad y GitHub) y llegan **juntos en un solo email**
   (`send_digest.py` los combina). Para cambiar el horario, edita la linea
   `cron` en `.github/workflows/daily-brief.yml` (esta en UTC).
4. Para probarlo ya mismo: pestana **Actions -> Daily Briefs -> Run workflow**.

### Contrasena de aplicacion (Gmail)
Gmail no acepta tu clave normal por SMTP. Activa la verificacion en 2 pasos y
genera una *App Password* en https://myaccount.google.com/apppasswords. Usa esos
16 caracteres como `SMTP_PASS`. Outlook/Office365 y otros proveedores tienen un
mecanismo equivalente.

---

## Opcion B — Correr en tu PC

```bash
# Genera el informe y lo muestra en pantalla (guarda brief.md)
python3 brief.py

# Genera y ademas lo envia por email (exporta antes las variables SMTP_*)
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 \
       SMTP_USER=tucuenta@gmail.com SMTP_PASS="app password" \
       MAIL_FROM=tucuenta@gmail.com MAIL_TO=vos@empresa.com
python3 brief.py --email
```

Para que corra solo en tu PC podes usar `cron` (Linux/Mac) o el Programador de
tareas (Windows), pero la PC tiene que estar encendida a esa hora. Por eso la
Opcion A suele ser mas comoda.

---

## Personalizar

Todo se edita en `brief.py`, arriba de todo:

- **`SOURCES`**: agrega o quita feeds. Formato `(categoria, nombre, url, tipo)`
  donde tipo es `"rss"` o `"atom"`. Para sumar, por ejemplo, fuentes de tu
  jurisdiccion (boletines oficiales con RSS, blogs sectoriales, etc.), agregalas
  aca.
- **`KEYWORDS`**: terminos que marcan una noticia como relevante. Sumá los
  propios de tu industria (salud, fintech, etc.) para afinar el filtro.
- **`LOOKBACK_HOURS`**: ventana de tiempo (48h por defecto; usa 24 si lo querés
  mas acotado).
- **`MAX_PER_SOURCE`**: tope de items por fuente.

### Nota sobre fuentes
Algunas fuentes oficiales (NIST, IAPP, etc.) a veces cambian o protegen sus
feeds. Si una falla, aparece listada al final del informe en "Fuentes con error"
y el resto sigue funcionando igual. Revisa esa lista cada tanto y reemplaza las
que queden caidas.

### Ideas para mejorar
- Enviar a **Slack** via webhook (en vez de o ademas del email).
- Deduplicar noticias que aparecen en varias fuentes.

---

## Modo IA con Groq (analisis, tendencias y traduccion)

Los tres informes comparten una capa de IA (`brief_ai.py`) que usa **Groq**
(API compatible con OpenAI, muy rapida y con tier gratuito). Funciona en dos
modos dentro de la **misma ejecucion**:

- **Modo simple** (por defecto, sin key): agrupa por categoria y prioriza lo mas
  relevante. No requiere ninguna cuenta ni gasto.
- **Modo IA** (si hay `GROQ_API_KEY`): en **un solo llamado** por informe genera
  - un **resumen ejecutivo analitico** que conecta las noticias del dia,
  - **deteccion de tendencias** (agrupa titulares relacionados),
  - **priorizacion con propuesta de accion** concreta en cada destacada, y
  - ademas hace una **traduccion real al espanol** (titulo + cuerpo) para las
    paginas `*_es.html`.

**La gracia:** no hay que elegir uno. Si la key esta presente, usa IA; si no hay
key, si la llamada falla, o si la respuesta no es valida, **cae solo al modo
simple** y genera el informe igual. Nunca se rompe ni te deja sin informe.

### Activarlo
1. Crea una cuenta gratis en https://console.groq.com y genera una API key en
   https://console.groq.com/keys.
2. En GitHub: **Settings -> Secrets and variables -> Actions** y agrega el
   secret `GROQ_API_KEY` con tu key. Listo, el script lo detecta solo.
3. *(Opcional)* Para cambiar de modelo sin tocar codigo, agrega una **variable**
   (no secret) `LLM_MODEL` en esa misma pantalla. Por defecto usa
   `llama-3.3-70b-versatile`. Otras opciones en Groq: `openai/gpt-oss-120b`
   (mas potente), `llama-3.1-8b-instant` (mas barato/rapido), `qwen/qwen3-32b`.

### Costo
- El tier gratuito de Groq suele alcanzar de sobra para una corrida diaria de
  los tres informes. Si sumas volumen, su pricing por token es de los mas bajos.
- Cada corrida procesa pocos titulares y tiene topes de tokens incorporados, asi
  una ejecucion no se dispara.

### Forzar modo simple puntualmente
```bash
python3 brief.py --no-llm        # ignora la key y usa modo simple
```

### Localmente
```bash
export GROQ_API_KEY="gsk_..."        # opcional: activa el modo IA
export LLM_MODEL="openai/gpt-oss-120b"  # opcional: cambia el modelo
python3 brief.py
```
