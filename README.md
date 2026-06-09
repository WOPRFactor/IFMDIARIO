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

3. Listo. El informe se envia todos los dias a las **08:00 de Argentina**.
   Para cambiar el horario, edita la linea `cron` en
   `.github/workflows/daily-brief.yml` (esta en UTC).
4. Para probarlo ya mismo: pestana **Actions -> AI Daily Brief -> Run workflow**.

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

## Modo IA opcional (destacar y resumir lo mas importante)

El script funciona en dos modos dentro de la **misma ejecucion**:

- **Modo simple** (por defecto): agrupa por categoria y prioriza Regulacion y
  Vulnerabilidades. No requiere ninguna cuenta ni gasto.
- **Modo IA**: si detecta una API key de Anthropic, usa Claude (Haiku) para
  elegir y resumir las 5-7 noticias mas importantes del dia, con una linea de
  "por que importa" en cada una.

**La gracia:** no hay que elegir uno. Si la key esta presente y hay credito, usa
IA; si no hay key, si la llamada falla, o si se acabo el credito, **cae solo al
modo simple** y genera el informe igual. Nunca se rompe ni te deja sin informe.

### Activarlo
1. Crea una cuenta en https://console.anthropic.com (es gratis crearla).
   Ojo: **es una cuenta separada del plan Pro/Max de claude.ai** — el plan de
   chat no incluye acceso a la API.
2. Carga un poco de credito (con 5 USD te alcanza para cientos de informes) y
   genera una API key.
3. En GitHub: **Settings -> Secrets and variables -> Actions** y agrega el
   secret `ANTHROPIC_API_KEY` con tu key. Listo, el script lo detecta solo.

### Control de gasto (importante)
- El costo real es de **centavos al mes** (cada informe procesa pocos titulares).
- En la Console de Anthropic podes fijar un **limite de gasto mensual** (tope
  duro): si se alcanza, la API deja de responder y el script vuelve al modo
  simple, sin cargos extra.
- El credito es **prepago**: sin auto-recarga activada, nunca podes gastar mas
  de lo que cargaste.
- El script tiene un **tope de tokens por corrida** incorporado
  (`LLM_MAX_OUTPUT_TOKENS`), asi una sola ejecucion no puede dispararse.

### Forzar modo simple puntualmente
```bash
python3 brief.py --no-llm        # ignora la key y usa modo simple
```
