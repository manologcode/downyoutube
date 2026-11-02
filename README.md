# downyoutube

Descarga vídeos, solo audio o solo texto (subtítulos) de YouTube desde una interfaz web.

## Uso

```bash
docker run -d --name downyoutube \
  -p 8080:8080 \
  -e PUID="$(id -u)" -e PGID="$(id -g)" \
  -v "$PWD/downloads:/downloads" \
  --restart unless-stopped \
  manologcode/downyoutube:latest
```

Abre `http://localhost:8080` (o `http://IP-DEL-HOST:8080`).

Los archivos se guardan en `./downloads`.

## Comandos útiles

```bash
docker logs -f downyoutube      # ver logs
docker stop downyoutube         # detener
docker rm downyoutube           # eliminar el contenedor
docker pull manologcode/downyoutube:latest   # actualizar
```

Si el puerto 8080 está ocupado, cambia `-p 8080:8080` por otro, por ejemplo `-p 9090:8080`.

## Orquestador

Al terminar una descarga en modo **audio** o **texto**, el archivo se envía
automáticamente al orquestador mediante `POST /tasks` (sin esperar el
resultado). El envío se hace en segundo plano, así que no bloquea la descarga.

Configuración por variables de entorno:

| Variable | Por defecto | Descripción |
|---|---|---|
| `ORCHESTRATOR_URL` | `http://192.168.1.69:8100` | URL base del orquestador |
| `ORCHESTRATOR_ENABLED` | `1` | `0`/`false` desactiva el envío |
| `ORCHESTRATOR_TEXT_ACTIONS` | `["summarize"]` | Acciones para textos (JSON) |
| `ORCHESTRATOR_AUDIO_ACTIONS` | `["transcribe","summarize"]` | Acciones para audios (JSON) |
| `ORCHESTRATOR_TEXT_PARAMS` | `{}` | Parámetros para textos (JSON) |
| `ORCHESTRATOR_AUDIO_PARAMS` | `{}` | Parámetros para audios (JSON) |
| `ORCHESTRATOR_TIMEOUT` | `120` | Timeout de la petición en segundos |

Ejemplo con `docker run`:

```bash
docker run -d --name downyoutube \
  -p 8080:8080 \
  -e ORCHESTRATOR_URL="http://192.168.1.69:8100" \
  -e ORCHESTRATOR_AUDIO_ACTIONS='["transcribe"]' \
  -e ORCHESTRATOR_AUDIO_PARAMS='{"language":"es"}' \
  -v "$PWD/downloads:/downloads" \
  --restart unless-stopped \
  manologcode/downyoutube:latest
```

## Cookies

Si YouTube pide verificación o el vídeo es privado, coloca un `cookies.txt` en
formato Netscape dentro de `./downloads`. La interfaz lo detecta automáticamente.
