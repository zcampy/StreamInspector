# StreamInspector

StreamInspector es una aplicación de escritorio para inspeccionar tráfico HTTP/HTTPS autorizado, organizar capturas, analizar contenido multimedia y exportar sesiones.

## Inicio rápido

1. Ejecuta `Iniciar StreamInspector.bat` en Windows.
2. Pulsa `Proxy ON`.
3. Abre el navegador dedicado desde el menú `Proxy`.
4. Navega por la web que quieras analizar.
5. Revisa las solicitudes y respuestas capturadas.

## Enlaces multimedia

El panel **Streams de vídeo** detecta HLS, DASH, MP4, WebM, MPEG-TS y otros formatos por URL, tipo MIME o firma del cuerpo.

### Obtener enlace reproducible

Selecciona un stream y pulsa **Obtener enlace reproducible**.

La acción:

- descomprime respuestas `gzip`, `deflate` y Brotli;
- analiza la playlist M3U8;
- si es una playlist maestra, selecciona automáticamente la variante con mayor ancho de banda y resolución;
- copia la URL seleccionada al portapapeles;
- genera un comando ffmpeg con `User-Agent`, `Referer` y `Origin` cuando estén presentes;
- indica si la captura contiene `Cookie` o `Authorization`, sin incluirlas automáticamente;
- avisa cuando la URL parece firmada o temporal y puede caducar.

Las cookies y cabeceras de autorización solo deben añadirse mediante la opción explícita del diálogo HLS y únicamente para depuración autorizada.

## Exportaciones

JSON, HAR y CSV se exportan saneados por defecto. Se ocultan cabeceras sensibles, firmas y tokens habituales en URLs, además de campos sensibles en cuerpos JSON y formularios. Los cuerpos binarios se conservan en Base64 para evitar pérdida de datos.

## HTTPS

Para inspeccionar HTTPS, instala el certificado local de mitmproxy desde `http://mitm.it` usando el navegador que está conectado al proxy.

## Pruebas

```powershell
pytest
ruff check .
```
