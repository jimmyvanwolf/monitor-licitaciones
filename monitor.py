#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Monitor de licitaciones para Remantico.

Consulta el Portal de Contrataciones Abiertas del Estado de Chihuahua
(contrataciones.chihuahua.gob.mx), detecta procedimientos NUEVOS relevantes
para una agencia creativa, los puntua, y genera un reporte HTML.

Uso:
    python monitor.py              # corrida normal
    python monitor.py --test       # no guarda estado, no notifica (para probar)
    python monitor.py --reset      # borra el historial de vistos y arranca de cero

El portal usa Django con CSRF. El flujo es:
    1. GET a la portada  -> obtiene cookie csrftoken + token del formulario
    2. POST a /busqueda/ -> devuelve JSON con los procedimientos
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import requests

TZ_CHIHUAHUA = timezone(timedelta(hours=-6))

BASE = "https://contrataciones.chihuahua.gob.mx"
BUSQUEDA_URL = f"{BASE}/busqueda/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
TIMEOUT = 45

RAIZ = Path(__file__).resolve().parent
CONFIG_PATH = RAIZ / "config.json"
ESTADO_PATH = RAIZ / "vistos.json"
# El reporte vive en docs/ porque GitHub Pages publica esa carpeta tal cual.
# Corriendo en local funciona igual: es solo un archivo HTML.
REPORTE_PATH = RAIZ / "docs" / "index.html"
LOG_PATH = RAIZ / "monitor.log"

# En GitHub Actions no hay disco persistente para el log ni tiene caso:
# la bitacora de cada corrida queda en la pestaña Actions del repositorio.
EN_CI = os.environ.get("GITHUB_ACTIONS") == "true"


# ---------------------------------------------------------------- utilidades

def ahora_local():
    """Hora de Chihuahua (UTC-6 todo el año desde que México eliminó el horario
    de verano en 2022). En GitHub Actions el reloj del runner es UTC, así que
    hay que convertir a mano o el reporte mostraría horas equivocadas."""
    return datetime.now(timezone.utc).astimezone(TZ_CHIHUAHUA)


def log(msg):
    linea = f"[{ahora_local():%Y-%m-%d %H:%M:%S}] {msg}"
    print(linea)
    if EN_CI:
        return  # en CI la bitácora es la salida del propio job
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def normaliza(texto):
    """Minusculas sin acentos, para comparar sin que estorben las tildes."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower().strip()


_CACHE_KW = {}


def contiene_palabra(texto_norm, palabra):
    """Coincidencia por palabra completa, no por subcadena.

    Sin esto, la palabra clave 'comercial' hace match dentro de la categoria
    'refrigeracion industrial y comercial' y mete aires acondicionados al
    reporte. El limite de palabra evita esa clase de falso positivo.
    """
    pat = _CACHE_KW.get(palabra)
    if pat is None:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(normaliza(palabra)) + r"(?![a-z0-9])")
        _CACHE_KW[palabra] = pat
    return bool(pat.search(texto_norm))


def carga_config():
    if not CONFIG_PATH.exists():
        log(f"ERROR: no existe {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def carga_vistos():
    if not ESTADO_PATH.exists():
        return {}
    try:
        with open(ESTADO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        log("AVISO: vistos.json ilegible, se reinicia el historial.")
        return {}


def guarda_vistos(vistos):
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(vistos, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- descarga

def abre_sesion():
    """Obtiene una sesion con cookie CSRF y el token del formulario."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    r = s.get(BASE + "/", timeout=TIMEOUT)
    r.raise_for_status()

    token = s.cookies.get("csrftoken")
    if not token:
        m = re.search(r"name=['\"]csrfmiddlewaretoken['\"]\s+value=['\"]([^'\"]+)", r.text)
        if m:
            token = m.group(1)
    if not token:
        raise RuntimeError("No se pudo obtener el token CSRF del portal.")
    return s, token


def consulta(sesion, token, tipo_proc, estatus="0"):
    """Consulta el portal. estatus 0 = Vigente. tipo_proc: 5=Servicios, 2=Adquisicion."""
    datos = {
        "csrfmiddlewaretoken": token,
        "num_pricedimineto": "",   # el typo es del portal, no nuestro
        "num_contrato": "",
        "Unidades_Responsables": "",
        "Tipo_de_Licitaci_n": "-1",
        "Estatus": estatus,
        "TipoProc": str(tipo_proc),
        "rdFechas": "1",
        "fechainicio": "",
        "fechafin": "",
        "nom_proveedor": "",
        "concepto_contratacion": "",
        "desc_procedimiento": "",
        "proyecto_esp": "",
    }
    r = sesion.post(
        BUSQUEDA_URL,
        data=datos,
        headers={"Referer": BASE + "/", "X-CSRFToken": token,
                 "X-Requested-With": "XMLHttpRequest"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()

    # El portal devuelve un objeto con llaves numericas "0","1","2"... no una lista.
    if isinstance(payload, dict):
        registros = [v for k, v in sorted(payload.items(), key=lambda kv: int(kv[0]))
                     if isinstance(v, dict)]
    elif isinstance(payload, list):
        registros = [v for v in payload if isinstance(v, dict)]
    else:
        registros = []
    return registros


# ---------------------------------------------------------------- scoring

def evalua(reg, cfg):
    """Devuelve (puntaje, prioridad, motivos) para un procedimiento."""
    concepto = reg.get("concepto_contratacion") or ""
    descripcion = reg.get("descripcion_procedimiento") or ""
    tipo = reg.get("tipo_procedimiento") or ""

    concepto_n = normaliza(concepto)
    texto_n = normaliza(f"{descripcion} {concepto}")

    puntaje = 0
    motivos = []

    altos = {normaliza(c) for c in cfg["conceptos_prioridad_alta"]}
    medios = {normaliza(c) for c in cfg["conceptos_prioridad_media"]}
    bajos = {normaliza(c) for c in cfg["conceptos_prioridad_baja"]}

    if concepto_n in altos:
        puntaje += 60
        motivos.append("Categoria central de Remantico")
    elif concepto_n in medios:
        puntaje += 35
        motivos.append("Categoria compatible")
    elif concepto_n in bajos:
        puntaje += 15
        motivos.append("Categoria periferica")

    # El config lleva variantes con y sin acento ("difusion" y "difusión").
    # Ambas coinciden tras normalizar, asi que se agrupan por su forma
    # normalizada para no contarlas ni mostrarlas dos veces.
    encontradas = {}
    for kw in cfg["palabras_clave"]:
        if contiene_palabra(texto_n, kw):
            encontradas.setdefault(normaliza(kw), kw)
    if encontradas:
        puntaje += min(30, 8 * len(encontradas))
        etiquetas = sorted(encontradas.values(), key=str.lower)
        motivos.append("Palabras clave: " + ", ".join(etiquetas[:6]))

    # Se puede concursar realmente?
    concursable = tipo in cfg["tipos_procedimiento_interes"]
    if concursable:
        puntaje += 20
        motivos.append("Abierto a concurso")
    else:
        motivos.append("Adjudicacion directa (solo inteligencia de mercado)")

    if descripcion.strip().upper() in ("N/A", "", "NA"):
        motivos.append("Sin descripcion publicada: revisar el detalle")

    if puntaje >= 70:
        prioridad = "alta"
    elif puntaje >= 40:
        prioridad = "media"
    else:
        prioridad = "baja"

    return puntaje, prioridad, motivos, concursable


def es_relevante(reg, cfg):
    concepto_n = normaliza(reg.get("concepto_contratacion"))
    texto_n = normaliza(f"{reg.get('descripcion_procedimiento')} {reg.get('concepto_contratacion')}")

    todos = set()
    for llave in ("conceptos_prioridad_alta", "conceptos_prioridad_media", "conceptos_prioridad_baja"):
        todos |= {normaliza(c) for c in cfg[llave]}

    if concepto_n in todos:
        return True
    return any(contiene_palabra(texto_n, kw) for kw in cfg["palabras_clave"])


# ---------------------------------------------------------------- reporte

CSS = """
:root{--bg:#faf9f7;--card:#fff;--tx:#1a1a1a;--mut:#666;--bd:#e3e0da;
--alta:#a32d2d;--altab:#fcebeb;--media:#854f0b;--mediab:#faeeda;--baja:#5f5e5a;--bajab:#f1efe8;--acc:#2b055e;--mag:#ea36c8}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px;background:var(--bg);color:var(--tx);
font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:24px;font-weight:600;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:24px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:28px}
.stat{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 18px;min-width:110px}
.stat b{display:block;font-size:26px;font-weight:600;line-height:1.2}
.stat span{font-size:12px;color:var(--mut)}
h2{font-size:16px;font-weight:600;margin:28px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--bd)}
.item{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:16px 18px;margin-bottom:10px}
.item.alta{border-left:3px solid var(--alta)}
.item.media{border-left:3px solid var(--media)}
.item.baja{border-left:3px solid var(--baja)}
.top{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.badge{font-size:11px;padding:2px 8px;border-radius:4px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.b-alta{background:var(--altab);color:var(--alta)}
.b-media{background:var(--mediab);color:var(--media)}
.b-baja{background:var(--bajab);color:var(--baja)}
.b-nuevo{background:var(--acc);color:#fff}
.cnt{font-weight:400;font-size:13px;color:var(--mut);background:var(--bajab);
padding:1px 8px;border-radius:10px;margin-left:6px}
.nota{font-size:13px;color:var(--mut);margin:0 0 12px}
.num{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--mut)}
.score{margin-left:auto;font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--mut)}
.desc{font-weight:500;margin-bottom:4px}
.meta{font-size:13px;color:var(--mut);margin-bottom:8px}
.motivos{font-size:12px;color:var(--mut)}
.motivos li{margin:2px 0}
ul{margin:4px 0;padding-left:18px}
a.det{display:inline-block;margin-top:8px;font-size:13px;color:var(--acc);text-decoration:none;border-bottom:1px solid var(--mag)}
.vacio{background:var(--card);border:1px dashed var(--bd);border-radius:10px;padding:28px;text-align:center;color:var(--mut)}
footer{margin-top:36px;font-size:12px;color:var(--mut);border-top:1px solid var(--bd);padding-top:14px}
@media(prefers-color-scheme:dark){
:root{--bg:#141414;--card:#1d1d1d;--tx:#eee;--mut:#999;--bd:#2f2f2f;
--altab:#3a1414;--mediab:#3a2a08;--bajab:#262626;--alta:#f09595;--media:#fac775;--baja:#b4b2a9;--acc:#cfc4ff}}
"""


def render_item(reg, ev, nuevo=False):
    puntaje, prioridad, motivos, _ = ev
    desc = reg.get("descripcion_procedimiento") or ""
    if desc.strip().upper() in ("N/A", "", "NA"):
        desc = "(sin descripción publicada)"
    motivos_html = "".join(f"<li>{escape(m)}</li>" for m in motivos)
    marca_nuevo = '<span class="badge b-nuevo">nuevo</span>' if nuevo else ""
    return f"""
<div class="item {prioridad}">
  <div class="top">
    <span class="badge b-{prioridad}">{prioridad}</span>{marca_nuevo}
    <span class="num">{escape(reg.get('numero_procedimiento') or '')}</span>
    <span class="score">{puntaje} pts</span>
  </div>
  <div class="desc">{escape(desc)}</div>
  <div class="meta">{escape(reg.get('concepto_contratacion') or '')} &middot;
    {escape(reg.get('tipo_procedimiento') or '')}<br>
    {escape(reg.get('unidad_compradora') or '')}</div>
  <div class="motivos"><ul>{motivos_html}</ul></div>
  <a class="det" href="{BASE}{escape(reg.get('link_detalle') or '')}" target="_blank">Ver convocatoria completa</a>
</div>"""


def genera_reporte(nuevos, evaluados, total_revisados, historico_relevantes):
    """Arma el panel HTML.

    `nuevos` es lo que aparecio desde la corrida anterior; `evaluados` es la
    foto completa de lo vigente hoy. Se muestran ambos: si solo pintaramos lo
    nuevo, la pagina estaria vacia casi siempre y no serviria para consultarla
    cuando uno quiera.
    """
    ahora = f"{ahora_local():%d/%m/%Y %H:%M}"
    claves_nuevas = {id(r) for r, _ev in nuevos}

    concursables = sorted([x for x in evaluados if x[1][3]], key=lambda x: -x[1][0])
    altas_directas = sorted(
        [x for x in evaluados if x[1][1] == "alta" and not x[1][3]],
        key=lambda x: -x[1][0])

    partes = []

    if nuevos:
        orden = sorted(nuevos, key=lambda n: -n[1][0])
        partes.append(
            f'<h2>Nuevas desde la última revisión <span class="cnt">{len(orden)}</span></h2>')
        partes.append("".join(render_item(r, ev, nuevo=True) for r, ev in orden))
    else:
        partes.append('<h2>Nuevas desde la última revisión</h2>')
        partes.append('<div class="vacio">Sin novedades. El portal no publicó '
                      'procedimientos nuevos que encajen con Remántico.</div>')

    partes.append(
        f'<h2>Abiertas a concurso ahora <span class="cnt">{len(concursables)}</span></h2>')
    if concursables:
        partes.append('<p class="nota">Licitaciones públicas e invitaciones a cuando menos '
                      'tres proveedores con estatus vigente. Son las únicas en las que se '
                      'puede participar.</p>')
        partes.append("".join(
            render_item(r, ev, nuevo=(id(r) in claves_nuevas)) for r, ev in concursables))
    else:
        partes.append('<div class="vacio">Ninguna convocatoria abierta en este momento.</div>')

    if altas_directas:
        partes.append(
            f'<h2>Inteligencia de mercado <span class="cnt">{len(altas_directas)}</span></h2>')
        partes.append('<p class="nota">Adjudicaciones directas de prioridad alta. '
                      'No se puede concursar en ellas, pero revelan qué dependencia '
                      'compra servicios creativos y con qué frecuencia. Sirven para '
                      'tocar puerta antes de la siguiente compra.</p>')
        partes.append("".join(render_item(r, ev) for r, ev in altas_directas[:40]))

    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor de licitaciones &middot; Remántico</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>Monitor de licitaciones</h1>
<div class="sub">Portal de Contrataciones Abiertas del Estado de Chihuahua &middot;
última revisión {ahora} (hora de Chihuahua)</div>
<div class="stats">
  <div class="stat"><b>{len(nuevos)}</b><span>nuevas</span></div>
  <div class="stat"><b>{len(concursables)}</b><span>abiertas a concurso</span></div>
  <div class="stat"><b>{len(evaluados)}</b><span>relevantes vigentes</span></div>
  <div class="stat"><b>{total_revisados}</b><span>revisadas hoy</span></div>
  <div class="stat"><b>{historico_relevantes}</b><span>en historial</span></div>
</div>
{"".join(partes)}
<footer>Fuente: contrataciones.chihuahua.gob.mx &middot; Solo procedimientos con estatus Vigente.
Participar requiere estar en el padrón de proveedores del Estado y cubrir el costo de bases.
&middot; Página generada automáticamente por GitHub Actions.</footer>
</div></body></html>"""

    REPORTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORTE_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    return REPORTE_PATH


# ---------------------------------------------------------------- telegram

def credenciales_telegram(cfg):
    """Las variables de entorno ganan sobre config.json.

    Así los secretos viven en GitHub Secrets y nunca se suben al repositorio,
    mientras que en local se sigue pudiendo usar config.json.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        return token, chat

    tg = cfg.get("telegram", {})
    if tg.get("activo"):
        return tg.get("bot_token", "").strip(), tg.get("chat_id", "").strip()
    return "", ""


def notifica_telegram(cfg, nuevos):
    token, chat_id = credenciales_telegram(cfg)
    if not token or not chat_id:
        return False
    if not nuevos:
        return False

    orden = sorted(nuevos, key=lambda n: -n[1][0])[:8]
    lineas = [f"*{len(nuevos)} oportunidad(es) nueva(s)* en licitaciones de Chihuahua", ""]
    for reg, (puntaje, prioridad, _m, concursable) in orden:
        desc = (reg.get("descripcion_procedimiento") or "").strip()
        if desc.upper() in ("N/A", "", "NA"):
            desc = reg.get("concepto_contratacion") or "sin descripcion"
        desc = desc[:110]
        marca = "CONCURSABLE" if concursable else "directa"
        lineas.append(f"[{prioridad.upper()} {puntaje}pts | {marca}]")
        lineas.append(desc)
        lineas.append(f"{reg.get('unidad_compradora','')}")
        lineas.append(f"{BASE}{reg.get('link_detalle','')}")
        lineas.append("")
    if len(nuevos) > 8:
        lineas.append(f"...y {len(nuevos)-8} mas en el reporte.")

    texto = "\n".join(lineas)[:4000]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat_id, "text": texto,
                                     "disable_web_page_preview": True}, timeout=30)
        if r.status_code == 200:
            log("Notificacion enviada a Telegram.")
            return True
        log(f"Telegram respondio {r.status_code}: {r.text[:200]}")
    except requests.RequestException as e:
        log(f"Error enviando a Telegram: {e}")
    return False


# ---------------------------------------------------------------- principal

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="no guarda estado ni notifica")
    ap.add_argument("--reset", action="store_true", help="borra el historial de vistos")
    args = ap.parse_args()

    if args.reset and ESTADO_PATH.exists():
        ESTADO_PATH.unlink()
        log("Historial borrado.")

    cfg = carga_config()
    vistos = {} if args.test and args.reset else carga_vistos()
    primera_corrida = not vistos

    try:
        sesion, token = abre_sesion()
    except (requests.RequestException, RuntimeError) as e:
        log(f"ERROR conectando al portal: {e}")
        sys.exit(2)

    registros = []
    for tipo_proc in cfg["materias"]:
        try:
            lote = consulta(sesion, token, tipo_proc)
            log(f"Materia {tipo_proc} ({cfg['materias'][tipo_proc]}): {len(lote)} vigentes.")
            registros.extend(lote)
        except (requests.RequestException, ValueError) as e:
            log(f"AVISO: fallo la consulta de materia {tipo_proc}: {e}")

    if not registros:
        log("No se obtuvo ningun registro. Se aborta sin tocar el historial.")
        sys.exit(3)

    relevantes = [r for r in registros if es_relevante(r, cfg)]
    log(f"Total revisados: {len(registros)} | relevantes: {len(relevantes)}")

    evaluados = []
    nuevos = []
    for reg in relevantes:
        clave = str(reg.get("id_procedimiento") or reg.get("numero_procedimiento"))
        ev = evalua(reg, cfg)
        evaluados.append((reg, ev))
        if clave in vistos:
            continue
        nuevos.append((reg, ev))
        vistos[clave] = {
            "visto": f"{ahora_local():%Y-%m-%d}",
            "num": reg.get("numero_procedimiento"),
            "concepto": reg.get("concepto_contratacion"),
            "puntaje": ev[0],
        }

    if primera_corrida:
        log(f"PRIMERA CORRIDA: se marcan {len(nuevos)} procedimientos como linea base.")

    ruta = genera_reporte(nuevos, evaluados, len(registros), len(vistos))
    log(f"Reporte: {ruta}")

    if nuevos:
        altas = sum(1 for _r, ev in nuevos if ev[1] == "alta")
        concursables = sum(1 for _r, ev in nuevos if ev[3])
        log(f"NUEVAS: {len(nuevos)} (alta: {altas}, concursables: {concursables})")
    else:
        log("Sin novedades.")

    if not args.test:
        guarda_vistos(vistos)
        if not primera_corrida:
            notifica_telegram(cfg, nuevos)
        else:
            log("No se notifica en la primera corrida (seria ruido).")
    else:
        log("Modo --test: no se guardo estado ni se notifico.")


if __name__ == "__main__":
    main()
