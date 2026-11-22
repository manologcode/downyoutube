# downyoutube

Interfaz web autohospedada para descargar de YouTube **vídeo**, **solo audio** o
**solo texto** (subtítulos), usando `yt-dlp` y `ffmpeg`.

## Uso con Docker

```bash
docker run --rm --name downyoutube -p 8080:8080 manologcode/downyoutube:latest
```

Abre `http://localhost:8080`. Los archivos se guardan en `/downloads` dentro del
contenedor.

Para conservarlos en el host:

```bash
docker run -d --name downyoutube \
  -p 8080:8080 \
  -v "$PWD/downloads:/downloads" \
  --restart unless-stopped \
  manologcode/downyoutube:latest
```

## Uso con Docker Compose

```bash
./downyoutube.sh
# o
docker compose up -d --build
```

## Qué permite

- **Vídeo**: descarga hasta la calidad elegida y lo fusiona en MP4/MKV.
- **Audio**: extrae el audio en mp3, m4a, wav, opus o el formato original.
- **Texto**: descarga los subtítulos y los convierte a `.txt`.
- Acepta varias URLs a la vez y playlists completas.

## Configuración

| Variable | Por defecto | Descripción |
|---|---|---|
| `PORT` | `8080` | Puerto interno de la interfaz |
| `WEB_PORT` | `8080` | Puerto del host (solo Compose) |
| `DOWNLOAD_DIR` | `/downloads` | Carpeta de descargas en el contenedor |
| `PUID` / `PGID` | `1000` | UID/GID propietario de los archivos |

## Cookies

Si YouTube pide verificación, el vídeo es privado o aparece un error 429, coloca
un `cookies.txt` en formato Netscape dentro de `downloads/`. La interfaz lo
detecta automáticamente.

## Comandos útiles

```bash
docker logs -f downyoutube                    # ver logs
docker stop downyoutube                       # detener
docker rm downyoutube                         # eliminar
docker pull manologcode/downyoutube:latest    # actualizar
```
