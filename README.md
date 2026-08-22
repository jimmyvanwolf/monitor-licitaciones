# Monitor de licitaciones — Remántico

Revisa cuatro veces al día el **Portal de Contrataciones Abiertas del Estado de Chihuahua**, detecta procedimientos vigentes que encajan con los servicios de Remántico, los puntúa y publica un panel web.

Corre solo en GitHub Actions. No necesita que tu computadora esté encendida.

---

## Instalación (una sola vez, ~10 minutos)

### 1. Crear el repositorio en GitHub

Entra a [github.com/new](https://github.com/new) y crea uno:

- **Nombre:** `monitor-licitaciones`
- **Visibilidad:** Público
- **No marques** ninguna casilla de "Add a README", "Add .gitignore" ni licencia

> **Por qué público:** GitHub Pages solo funciona en repositorios privados si pagas GitHub Pro. Los datos aquí son licitaciones de gobierno, que ya son información pública, así que no hay nada sensible expuesto. Tu token de Telegram **nunca** va en el código: vive en Secrets, que sí es privado aunque el repo sea público.

### 2. Subir el código

Copia la URL que te da GitHub y corre esto en la carpeta del proyecto:

```bash
git remote add origin https://github.com/TU-USUARIO/monitor-licitaciones.git
git push -u origin main
```

Te pedirá usuario y contraseña. En la contraseña **no va tu contraseña de GitHub** sino un token: ve a [github.com/settings/tokens](https://github.com/settings/tokens) → *Generate new token (classic)* → marca el permiso `repo` → cópialo y pégalo.

### 3. Permitir que el robot escriba

En tu repositorio: **Settings → Actions → General → Workflow permissions** → selecciona **Read and write permissions** → *Save*.

Sin esto el monitor puede revisar pero no puede guardar los resultados.

### 4. Encender la página web

En tu repositorio: **Settings → Pages** → en *Source* elige **Deploy from a branch** → rama `main`, carpeta `/docs` → *Save*.

En un par de minutos tu panel queda en:

```
https://TU-USUARIO.github.io/monitor-licitaciones/
```

Esa es la dirección que puedes abrir cuando quieras, desde cualquier dispositivo.

### 5. Primera corrida

Ve a la pestaña **Actions** → *Monitor de licitaciones* → botón **Run workflow**.

---

## Alertas al celular (opcional)

Sin esto tienes que abrir la página tú. Con esto te llega un mensaje cuando aparece algo nuevo.

1. En Telegram busca **@BotFather**, mándale `/newbot` y sigue los pasos.
2. Copia el token que te da.
3. Escríbele cualquier mensaje a tu bot recién creado.
4. Abre en el navegador `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y busca el valor de `chat.id`.
5. En tu repositorio: **Settings → Secrets and variables → Actions → New repository secret**. Crea dos:

| Nombre | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el token de BotFather |
| `TELEGRAM_CHAT_ID` | el chat.id que encontraste |

**Nunca pongas el token en `config.json`.** Ese archivo sí es visible para todos. El código está hecho para leer primero las variables de entorno, así que con los Secrets basta.

---

## Horarios

Corre a las **8:00, 13:00, 18:00 y 22:00** hora de Chihuahua.

GitHub programa estas tareas con margen: cuando su infraestructura está saturada una corrida puede retrasarse algunos minutos, ocasionalmente más. Para un monitor de licitaciones eso es irrelevante — el portal publica en horario hábil y los plazos son de días.

Para revisar en el momento: **Actions → Run workflow**.

---

## Cómo leer el panel

| Sección | Qué contiene |
|---|---|
| **Nuevas desde la última revisión** | Lo que apareció desde la corrida anterior. Vacío casi siempre, y eso es normal. |
| **Abiertas a concurso ahora** | Licitaciones públicas e invitaciones a tres proveedores, vigentes. **Las únicas en las que puedes participar.** |
| **Inteligencia de mercado** | Adjudicaciones directas de prioridad alta. No puedes concursar, pero revelan qué dependencia compra servicios creativos y cada cuánto. Sirve para tocar puerta antes de la siguiente compra. |

### Los puntajes

| Señal | Puntos |
|---|---|
| Categoría central (diseño, publicidad, video, contenido digital) | +60 |
| Categoría compatible (capacitación, impresión, software, web) | +35 |
| Categoría periférica (eventos, cultural) | +15 |
| Palabras clave en la descripción | +8 c/u, máximo +30 |
| Abierto a concurso | +20 |

**Alta** ≥ 70 · **Media** ≥ 40 · **Baja** por debajo.

---

## Ajustar la sensibilidad

Todo se edita en `config.json`, sin tocar código. Después de editar, haz `git push` y el cambio aplica en la siguiente corrida.

- **Demasiado ruido** → quita palabras genéricas de `palabras_clave`, o vacía `conceptos_prioridad_baja`.
- **Se escapan cosas** → agrega categorías a las listas de prioridad, o palabras a `palabras_clave`.

Los nombres de categoría deben escribirse **exactamente** como los publica el portal, acentos incluidos.

---

## Uso local (opcional)

El script sigue funcionando en tu computadora:

```bash
pip install -r requirements.txt
python monitor.py
```

| Comando | Qué hace |
|---|---|
| `python monitor.py` | Revisión normal |
| `python monitor.py --test` | Prueba sin guardar estado ni notificar |
| `python monitor.py --reset` | Borra el historial y vuelve a marcar línea base |

También existen `ejecutar.bat` e `instalar-tarea.ps1` de la versión anterior, que programaban el monitor en Windows. Con GitHub Actions ya no hacen falta, pero se dejan por si algún día quieres correrlo sin depender de GitHub.

---

## Detalles técnicos

El portal corre sobre Django y protege sus formularios con CSRF:

1. `GET` a la portada → obtiene la cookie `csrftoken`
2. `POST` a `/busqueda/` con ese token → devuelve JSON

La respuesta **no es una lista**, es un objeto con llaves numéricas (`"0"`, `"1"`, `"2"`…). El script lo normaliza.

Campos por registro: `numero_procedimiento`, `descripcion_procedimiento`, `concepto_contratacion`, `materia`, `tipo_procedimiento`, `estatus`, `unidad_compradora`, `unidad_solicitante`, `id_procedimiento`, `link_detalle`.

### Decisiones que importan

**Coincidencia por palabra completa.** Con búsqueda por subcadena, la palabra "comercial" hacía match dentro de la categoría *"refrigeración industrial y comercial"* y colaba aires acondicionados al reporte.

**Aborta sin tocar el historial** cuando no obtiene registros. Así un fallo temporal del portal no provoca que la siguiente corrida reporte 400 licitaciones viejas como nuevas.

**No notifica en la primera corrida.** Sería un mensaje con cientos de procedimientos que llevan meses publicados.

### Si deja de funcionar

Revisa la pestaña **Actions**: cada corrida deja su bitácora completa.

La causa más probable de una falla permanente sería que el portal cambiara los nombres de los campos del formulario. Están en la función `consulta()` — incluido `num_pricedimineto`, que trae un error de dedo del portal original y **debe escribirse así**.

---

## Alcance y límites

**Solo cubre el portal estatal de Chihuahua.** Se evaluó CompraNet federal (hoy ComprasMX): su API exige autenticación y usa reCAPTCHA v3, así que un scraper sería frágil. El portal estatal es además más realista para una agencia local. Los portales municipales quedan como posible ampliación.

**El monitor detecta, no postula.** Participar exige estar registrado en el padrón de proveedores del Estado y cubrir el costo de bases — alrededor de $2,274 pesos por licitación en 2026, pagaderos en Secretaría de Hacienda.

**Es gratis.** Los repositorios públicos tienen minutos ilimitados de GitHub Actions. Cada corrida tarda menos de un minuto.
