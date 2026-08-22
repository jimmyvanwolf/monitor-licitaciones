# Monitor de licitaciones — Remántico

Revisa automáticamente el **Portal de Contrataciones Abiertas del Estado de Chihuahua**, detecta procedimientos nuevos que encajan con los servicios de Remántico, los puntúa y genera un reporte.

---

## Puesta en marcha (una sola vez)

1. Clic derecho en **`instalar-tarea.ps1`** → *Ejecutar con PowerShell*.
2. Si Windows lo bloquea, abre PowerShell y corre `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, luego repite el paso 1.
3. Listo. Queda revisando a las **8:00, 13:00, 18:00 y 22:00** todos los días.

Para ver el resultado, abre **`reporte.html`** con doble clic.

---

## Alertas en el celular (opcional, recomendado)

Sin esto tienes que abrir el reporte tú. Con esto te llega un mensaje cuando aparece algo nuevo.

1. En Telegram busca **@BotFather**, mándale `/newbot` y sigue los pasos.
2. Copia el token que te da.
3. Escríbele cualquier mensaje a tu bot recién creado.
4. Abre en el navegador: `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y busca el valor de `chat.id`.
5. Abre `config.json` y llena:

```json
"telegram": { "activo": true, "bot_token": "TU_TOKEN", "chat_id": "TU_CHAT_ID" }
```

---

## Uso manual

```bash
python monitor.py
```

| Comando | Qué hace |
|---|---|
| `python monitor.py` | Revisión normal: detecta nuevas, guarda estado, notifica |
| `python monitor.py --test` | Prueba sin guardar estado ni notificar |
| `python monitor.py --reset` | Borra el historial y vuelve a marcar línea base |

También puedes dar doble clic a `ejecutar.bat` para una revisión inmediata.

---

## Cómo decide qué es relevante

Consulta dos materias completas del portal (**Servicios** y **Adquisición**, solo con estatus *Vigente*) y filtra localmente. Un procedimiento entra al reporte si su categoría oficial está en las listas de `config.json`, o si su descripción contiene alguna palabra clave.

El puntaje se arma así:

| Señal | Puntos |
|---|---|
| Categoría central (diseño, publicidad, video, contenido digital) | +60 |
| Categoría compatible (capacitación, impresión, software, web) | +35 |
| Categoría periférica (eventos, cultural) | +15 |
| Palabras clave en la descripción | +8 c/u, máximo +30 |
| Abierto a concurso (licitación o invitación a 3) | +20 |

**Alta** ≥ 70 pts · **Media** ≥ 40 · **Baja** por debajo.

La coincidencia de palabras es **por palabra completa**, no por subcadena. Sin eso, la palabra "comercial" hacía match dentro de la categoría *"refrigeración industrial y comercial"* y colaba aires acondicionados al reporte.

### Adjudicaciones directas

Aparecen en el reporte pero marcadas aparte y sin los +20 puntos, porque **no se puede concursar en ellas**. Se incluyen como inteligencia de mercado: te dicen qué dependencia compra qué cosa y a quién. Eso sirve para tocar puertas antes de la siguiente compra.

---

## Ajustar la sensibilidad

Todo se edita en `config.json`, sin tocar el código:

- **Te llega demasiado ruido** → quita palabras genéricas de `palabras_clave`, o vacía `conceptos_prioridad_baja`.
- **Se te escapan cosas** → agrega categorías a las listas de prioridad, o palabras a `palabras_clave`.
- **Solo quieres lo concursable** → ignora todo lo marcado como *Adjudicación directa* en el reporte.

Los nombres de categoría deben escribirse **exactamente** como los publica el portal, con acentos incluidos.

---

## Archivos

| Archivo | Para qué |
|---|---|
| `monitor.py` | El programa |
| `config.json` | Filtros, palabras clave y Telegram |
| `reporte.html` | Resultado, se regenera en cada corrida |
| `vistos.json` | Historial de lo ya reportado (evita repetir) |
| `monitor.log` | Bitácora de corridas y errores |
| `ejecutar.bat` | Lanzador para el Programador de tareas |
| `instalar-tarea.ps1` | Instalador de la tarea programada |

---

## Detalles técnicos

El portal corre sobre Django y protege sus formularios con CSRF. El flujo es:

1. `GET` a la portada → obtiene la cookie `csrftoken`
2. `POST` a `/busqueda/` con ese token → devuelve JSON

La respuesta **no es una lista**, es un objeto con llaves numéricas (`"0"`, `"1"`, `"2"`…). El script ya lo normaliza.

Campos que devuelve cada registro: `numero_procedimiento`, `descripcion_procedimiento`, `concepto_contratacion`, `materia`, `tipo_procedimiento`, `estatus`, `unidad_compradora`, `unidad_solicitante`, `id_procedimiento`, `link_detalle`.

### Si algún día deja de funcionar

El script aborta **sin tocar el historial** cuando no obtiene registros, así que un fallo temporal no provoca que te reporte 400 licitaciones viejas como nuevas al siguiente intento. Revisa `monitor.log`.

La causa más probable de una falla permanente sería que el portal cambie los nombres de los campos del formulario. Están en la función `consulta()` — incluido `num_pricedimineto`, que trae un error de dedo del portal y **debe escribirse así**.

---

## Limitaciones honestas

**"24/7" aquí significa "cuando la PC está encendida".** La tarea está configurada con `-StartWhenAvailable`, así que si la máquina estaba apagada a la hora programada, la revisión corre en cuanto la enciendas. Para 24/7 real haría falta moverlo a un servidor o a GitHub Actions.

**Solo cubre el portal estatal de Chihuahua.** Se evaluó también CompraNet federal (hoy ComprasMX): su API exige autenticación y usa reCAPTCHA v3, así que un scraper sería frágil y se rompería seguido. El portal estatal es además más realista para una agencia local. Los portales municipales de Chihuahua y Juárez quedan pendientes como posible ampliación.

**El monitor detecta, no postula.** Participar exige estar registrado en el padrón de proveedores del estado y cubrir el costo de bases (para 2026, alrededor de $2,274 pesos por licitación, pagaderos en Secretaría de Hacienda).
