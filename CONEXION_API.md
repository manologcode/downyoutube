# Opciones de conexión con la API del Orquestador

Este documento recoge las distintas formas de conectar un cliente con el
Orquestador para **enviar tareas** y **recibir/consultar sus resultados**.

- API: FastAPI (OpenAPI generado automáticamente).
- No hay autenticación: cualquiera con acceso de red puede llamar a la API.
- Formato de creación de tareas: **siempre `multipart/form-data`**, aunque no se
  adjunte archivo.
- No existen webhooks ni push: la recepción de resultados se hace por
  **polling** de los endpoints de tareas/pipelines.

---

## 1. URL base

Elige según desde dónde te conectes:

| Contexto | URL base |
|---|---|
| Misma máquina (proceso local) | `http://127.0.0.1:8100` |
| LAN / otra máquina del laboratorio | `http://192.168.1.69:8100` |
| Dentro de la red Docker (bridge) | `http://orquestador:8100` |
| Docker con `network_mode: host` | `http://<IP-del-host>:8100` |
| Detrás de un proxy inverso | `https://<tu-dominio>` |

> El puerto se define con `API_PORT` (por defecto `8000` en `.env.example`;
> el `docker-compose.yml` actual publica `8100:8100`).

Comprobación rápida:

```bash
curl -s http://127.0.0.1:8100/health
# {"status":"ok"}
```

---

## 2. Endpoints disponibles

| Método | Ruta | Uso |
|---|---|---|
| `POST` | `/tasks` | Crear tarea o pipeline |
| `GET` | `/tasks` | Listar tareas (`?status=`, `?root_id=`) |
| `GET` | `/tasks/{id}` | Detalle de una tarea |
| `GET` | `/tasks/{id}/chain` | Todos los pasos de un pipeline |
| `POST` | `/tasks/{id}/retry` | Reintentar tarea en `error` |
| `POST` | `/tasks/{id}/cancel` | Cancelar tarea `pending`/`running` |
| `GET` | `/pipelines/{pipeline_id}` | Estado agregado del pipeline |
| `GET` | `/status/worker` | Estado del worker |
| `GET` | `/health` | Healthcheck |
| `GET` | `/` | Dashboard web |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | Documentación interactiva |

---

## 3. Esquema del payload

El campo de formulario `payload` es un JSON con esta forma:

```json
{
  "text": "texto, URL o ruta de audio",
  "actions": ["summarize", "create_audio"],
  "params": {},
  "priority": 0
}
```

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `text` | string | sí (puede ir vacío si se sube `file`) | Entrada inicial |
| `actions` | string[] | sí, no vacía | Acciones solicitadas (el orden se corrige solo) |
| `params` | object | no | Parámetros de las acciones |
| `priority` | int | no | Prioridad (reservado; el worker ordena por `created_at`) |

Archivo opcional: campo de formulario `file`. Si se envía, la entrada pasa a
ser `audio_file` y su ruta se usa como `text`.

### Acciones y parámetros

| Acción | Entrada → Salida | `params` relevantes |
|---|---|---|
| `fetch_article` | `url` → `text` | — |
| `down_audio` | `url` → `audio_file` | — |
| `transcribe` | `audio_file` → `text` | `language`, `diarize`, `input_type` |
| `summarize` | `text` → `text` | `model`, `num_ctx`, `num_predict`, `max_input_chars` |
| `translate` | `text` → `text` | `model`, `target_lang`, `num_ctx`, `num_predict` |
| `create_audio` | `text` → `audio_file` | `voice`, `lang` |

`params.input_type` permite forzar `text`, `url` o `audio_file`.

---

## 4. Opción A: `curl`

Sin archivo:

```bash
curl -s -X POST http://127.0.0.1:8100/tasks \
  -F 'payload={"text":"Hola mundo","actions":["create_audio"],"params":{"lang":"es","voice":"Xavier Hayasaka"}}' \
  | python3 -m json.tool
```

Con archivo:

```bash
curl -s -X POST http://127.0.0.1:8100/tasks \
  -F 'payload={"text":"","actions":["transcribe","summarize","create_audio"],"params":{"language":"es"}}' \
  -F 'file=@/ruta/a/audio.mp3' \
  | python3 -m json.tool
```

Respuesta:

```json
{
  "id": 42,
  "root_id": 42,
  "pipeline_id": 42,
  "text": "Hola mundo",
  "actions": ["create_audio"],
  "next_action": "create_audio",
  "status": "pending",
  "params": {"lang": "es"},
  "result": {},
  "result_type": null,
  "error": null,
  "retries": 0,
  "priority": 0,
  "created_at": "2026-10-28T12:00:00"
}
```

---

## 5. Opción B: Python (`requests`)

```python
import requests

BASE = "http://127.0.0.1:8100"

payload = {
    "text": "https://example.com/articulo",
    "actions": ["fetch_article", "summarize", "create_audio"],
    "params": {"lang": "es", "model": "qwen3:4b"},
}

r = requests.post(
    f"{BASE}/tasks",
    data={"payload": __import__("json").dumps(payload)},
    timeout=30,
)
r.raise_for_status()
task = r.json()
pipeline_id = task["pipeline_id"]
print("Pipeline:", pipeline_id)
```

Con archivo:

```python
with open("/ruta/a/audio.mp3", "rb") as fh:
    r = requests.post(
        f"{BASE}/tasks",
        data={"payload": '{"text":"","actions":["transcribe"]}'},
        files={"file": ("audio.mp3", fh, "audio/mpeg")},
        timeout=120,
    )
```

### Seguimiento por polling (síncrono)

```python
import time

def esperar_pipeline(pipeline_id, interval=3, timeout=1800):
    fin = time.time() + timeout
    while time.time() < fin:
        p = requests.get(f"{BASE}/pipelines/{pipeline_id}", timeout=10).json()
        print(p["status"], f'{p["completed_steps"]}/{p["total_steps"]}')
        if p["finished"]:
            return p
        time.sleep(interval)
    raise TimeoutError("El pipeline no terminó a tiempo")
```

---

## 6. Opción C: Python async (`httpx`)

```python
import asyncio
import json
import httpx

BASE = "http://127.0.0.1:8100"

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        payload = {"text": "Hola mundo", "actions": ["create_audio"], "params": {"lang": "es"}}
        r = await client.post("/tasks", data={"payload": json.dumps(payload)})
        r.raise_for_status()
        task = r.json()
        print("Tarea", task["id"], "pipeline", task["pipeline_id"])

asyncio.run(main())
```

---

## 7. Opción D: JavaScript / navegador (`fetch`)

```javascript
const BASE = "http://127.0.0.1:8100";

async function crearTarea(text, actions, params = {}, file = null) {
  const form = new FormData();
  form.append("payload", JSON.stringify({ text, actions, params }));
  if (file) form.append("file", file);

  const res = await fetch(`${BASE}/tasks`, { method: "POST", body: form });
  if (!res.ok) throw new Error(JSON.stringify(await res.json()));
  return res.json();
}

// Seguimiento
async function seguirPipeline(pipelineId) {
  const res = await fetch(`${BASE}/pipelines/${pipelineId}`);
  return res.json();
}

// Ejemplo
crearTarea("Hola mundo", ["create_audio"], { lang: "es" })
  .then(t => console.log("Pipeline", t.pipeline_id));
```

> Si el frontend no se sirve desde el mismo origen, el navegador aplica CORS.
> El proyecto no configura `CORSMiddleware`; para integraciones desde otro
> dominio hay que añadirlo en `app/main.py` o usar un proxy inverso.

---

## 8. Opción E: cliente Node.js

```javascript
const BASE = "http://127.0.0.1:8100";

async function main() {
  const form = new FormData();
  form.append("payload", JSON.stringify({
    text: "Hola mundo",
    actions: ["summarize", "create_audio"],
    params: { lang: "es" },
  }));

  const r = await fetch(`${BASE}/tasks`, { method: "POST", body: form });
  if (!r.ok) throw new Error(await r.text());
  const task = await r.json();
  console.log(task.id, task.pipeline_id);
}

main();
```

---

## 9. Opción F: `POST` de formulario HTML

```html
<form action="http://127.0.0.1:8100/tasks" method="post" enctype="multipart/form-data">
  <input name="payload"
         value='{"text":"Hola","actions":["create_audio"],"params":{"lang":"es"}}' />
  <input type="file" name="file" />
  <button type="submit">Enviar</button>
</form>
```

Valida que el `value` sea JSON válido. Para una experiencia completa conviene
JavaScript (Opción D).

---

## 10. Opción G: dashboard web

Abre `http://127.0.0.1:8100/` (o la IP del host). Desde ahí puedes:

- seleccionar acciones y enviar tareas;
- subir archivos;
- definir `params` en JSON;
- ver worker, cola e histórico;
- descargar resultados desde `/artifacts/<archivo>`.

Es la forma más directa de "recibir" tareas ya creadas y sus resultados.

---

## 11. Opción H: documentación interactiva (OpenAPI)

FastAPI expone:

- `http://127.0.0.1:8100/docs` — Swagger UI
- `http://127.0.0.1:8100/redoc` — ReDoc
- `http://127.0.0.1:8100/openapi.json` — esquema OpenAPI

Útil para generar clientes automáticamente (por ejemplo con
`openapi-generator` o `openapi-typescript`) y para probar `POST /tasks` sin
escribir código.

---

## 12. Cómo recibir/consumir tareas y resultados

### 12.1. Polling de una tarea

```bash
curl -s http://127.0.0.1:8100/tasks/42
```

Estados: `pending`, `running`, `done`, `error`, `cancelled`.

### 12.2. Polling de un pipeline (recomendado)

```bash
curl -s http://127.0.0.1:8100/pipelines/42
```

```json
{
  "pipeline_id": 42,
  "status": "running",
  "finished": false,
  "total_steps": 3,
  "completed_steps": 1,
  "running_steps": 1,
  "pending_steps": 1,
  "error_steps": 0,
  "cancelled_steps": 0,
  "final_result": null,
  "final_result_type": null,
  "final_task_id": null,
  "steps": []
}
```

- `finished: true` → no quedan pasos `pending`/`running`.
- `final_result` contiene el resultado del último paso completado.
- `final_result_type` es `text` o `file`.
- Si es `file`, el resultado es una ruta y el archivo se sirve en
  `/artifacts/<filename>`.

### 12.3. Listar/recibir tareas nuevas

```bash
# Todas
curl -s http://127.0.0.1:8100/tasks

# Solo pendientes
curl -s "http://127.0.0.1:8100/tasks?status=pending"

# Pasos de un pipeline concreto
curl -s http://127.0.0.1:8100/tasks/42/chain
```

### 12.4. Descargar un resultado de tipo archivo

```bash
curl -O http://127.0.0.1:8100/artifacts/a1b2c3d4.mp3
```

### 12.5. Estado del worker

```bash
curl -s http://127.0.0.1:8100/status/worker
```

---

## 13. Flujo de integración recomendado

1. `POST /tasks` con `payload` (y `file` si aplica).
2. Guardar `pipeline_id` de la respuesta.
3. Hacer polling cada 2–5 s a `GET /pipelines/{pipeline_id}`.
4. Cuando `finished == true`, leer `final_result` y `final_result_type`.
5. Si es `file`, descargar de `/artifacts/<filename>`.
6. Si hay `error`, usar `POST /tasks/{id}/retry` o mostrar el mensaje.

> No hay endpoint de notificaciones. Si necesitas eventos en tiempo real,
> implementa un webhook en tu lado y consulta el pipeline periódicamente, o
> añade un endpoint de callback al orquestador.

---

## 14. Errores habituales

| Código | Causa |
|---|---|
| `400` | `payload` no es JSON válido o `actions` vacío |
| `404` | Tarea/pipeline no encontrado |
| `422` | Cadena de acciones imposible para el tipo de entrada |

Ejemplo de cadena imposible:

```json
{
  "detail": "Cadena de acciones imposible. Tipo actual: 'text'. Acciones pendientes: ['transcribe(audio_file->text)']. Falta una acción que convierta 'text' en el tipo que espera alguna pendiente."
}
```

---

## 15. Resumen de decisión

| Necesidad | Opción |
|---|---|
| Probar rápido | `curl` u OpenAPI `/docs` |
| Script de automatización | Python `requests` + polling de `/pipelines` |
| Backend async | Python `httpx` |
| Frontend web | `fetch` + `FormData` (ojo con CORS) |
| Uso manual | Dashboard `/` |
| Cliente tipado | Generar desde `/openapi.json` |
| Descarga de audios | `/artifacts/<filename>` |
