# StreamInspector

Aplicación de escritorio para inspeccionar, analizar y repetir tráfico HTTP/HTTPS en sistemas propios o expresamente autorizados.

## Inicio rápido en Windows

1. Descarga o clona el repositorio.
2. Abre la carpeta del proyecto.
3. Haz doble clic en:

```text
Iniciar StreamInspector.bat
```

El lanzador busca un Python compatible, puede instalar Python 3.12 mediante `winget`, crea o repara `.venv`, instala PySide6 y el resto de dependencias, y finalmente inicia la aplicación.

No ejecutes directamente `src/streaminspector/main.py` salvo que hayas preparado previamente el entorno de desarrollo.

## Primera captura paso a paso

1. Inicia StreamInspector con `Iniciar StreamInspector.bat`.
2. Pulsa el botón `Proxy OFF`.
3. Cuando el motor esté preparado, el botón cambiará a `Proxy ON`.
4. De forma predeterminada el proxy escucha en `127.0.0.1:8080`.
5. En Windows, deja marcada `Proxy > Configurar automáticamente el proxy de Windows` para que StreamInspector aplique y restaure la configuración del sistema.
6. Abre una web o API propia. Las solicitudes aparecerán en la tabla principal.
7. Selecciona una fila para revisar petición, respuesta, cabeceras, cuerpo y contenido JSON.
8. Para detenerlo, pulsa `Proxy ON`; volverá a `Proxy OFF` y se restaurará el proxy anterior de Windows.

No es necesario definir manualmente `STREAMINSPECTOR_PROXY__HOST` ni `STREAMINSPECTOR_PROXY__PORT`.

## Capturar HTTPS

1. Activa el proxy.
2. Abre `Proxy > Configurar navegador y HTTPS…`.
3. Pulsa `Abrir mitm.it`.
4. Descarga el certificado correspondiente al sistema operativo.
5. Instálalo como entidad de certificación raíz únicamente en un equipo o perfil de prueba autorizado.
6. Abre una web HTTPS y comprueba que aparece en StreamInspector.

La aplicación también permite abrir la carpeta de certificados de mitmproxy y comprobar si ya existen.

## Configurar host y puerto

Abre:

```text
Proxy > Configurar host y puerto…
```

El valor predeterminado es `127.0.0.1:8080`. Detén el proxy antes de cambiarlo. Usa `Proxy > Diagnosticar configuración…` para comprobar si el puerto está disponible.

## Captura selectiva

En el menú `Captura` puedes:

- pausar y reanudar la captura sin detener el proxy;
- omitir imágenes, CSS, JavaScript, fuentes, audio y vídeo;
- excluir dominios y todos sus subdominios;
- consultar la política de captura activa.

El tráfico omitido no se muestra ni se guarda en SQLite.

## Buscar y filtrar

La barra superior permite combinar:

- texto libre;
- dominio;
- método HTTP;
- familia de estado;
- tipo de contenido.

La tabla puede ordenarse pulsando las cabeceras. Las exportaciones y análisis trabajan con las filas visibles.

## Inspeccionar, copiar y repetir

Selecciona una captura para ver sus detalles. Con el botón derecho puedes copiar la URL, cabeceras, cuerpos o la petición completa.

Desde `Peticiones` puedes:

- editar y repetir una solicitud;
- comparar dos capturas y revisar sus diferencias.

Repite solicitudes únicamente contra sistemas autorizados.

## Sesiones e historial

Cada ejecución crea una sesión. El panel lateral permite abrir, renombrar y eliminar sesiones históricas. Las capturas se guardan localmente en SQLite.

## Importar archivos HAR

Abre `Importar > Archivo HAR…` para analizar archivos generados por Chrome, Edge, Firefox, DevTools, Postman u otras herramientas compatibles.

El HAR se abre como una vista temporal y no se mezcla automáticamente con la sesión activa ni con SQLite. Puede filtrarse, compararse, analizarse y exportarse desde StreamInspector.

## Organizar capturas

El menú `Organizar` permite:

- marcar o desmarcar una captura como favorita;
- añadir etiquetas separadas por comas;
- guardar una nota de análisis;
- consultar la anotación completa;
- mostrar únicamente las capturas favoritas.

Las anotaciones de capturas guardadas se conservan en SQLite y reaparecen al abrir sesiones históricas. Las capturas favoritas se identifican con una estrella en la tabla.

## Prueba de concepto automática

Después de preparar el entorno, ejecuta:

```powershell
.\.venv\Scripts\python.exe -m streaminspector.poc
```

Hay una segunda POC que sí hace una petición HTTP real para validar todo el
pipeline (persistencia, anotación, export/import HAR, búsqueda profunda y
métricas) contra una web concreta:

```powershell
.\.venv\Scripts\python.exe -m streaminspector.poc_web
```

La POC realiza sin conectarse a servicios externos:

1. genera un HAR de ejemplo;
2. lo convierte en una captura;
3. guarda la captura en una base SQLite temporal;
4. añade favorito, etiquetas y nota;
5. cierra y vuelve a abrir la base;
6. comprueba que la captura y sus anotaciones persisten.

El resultado correcto termina con:

```text
[POC] CORRECTO
[POC] HAR importado: 1 captura
[POC] Persistencia SQLite: correcta
[POC] Favorito, etiquetas y nota: correctos
```

Esta misma POC se ejecuta en GitHub Actions mediante `tests/test_poc.py`.

## Exportar y analizar

El menú `Exportar` genera:

- CSV;
- JSON;
- HAR 1.2.

El menú `Análisis` muestra métricas de rendimiento, errores, tiempos de respuesta, tamaños, dominios y familias de estado.

## Obtener un enlace reproducible

En el panel `Streams de vídeo`, selecciona una captura y pulsa `Obtener enlace reproducible`.

La acción descomprime respuestas gzip, deflate y Brotli, analiza la playlist HLS y, si es una playlist maestra, selecciona automáticamente la variante con mayor ancho de banda, resolución y frecuencia de imagen. También copia la URL seleccionada, genera un comando ffmpeg con User-Agent, Referer y Origin, indica si existen Cookie o Authorization y avisa cuando la URL parece firmada o temporal.

Las credenciales sensibles no se incluyen automáticamente en el comando.

## Asistente integrado

En la primera ejecución se abre una guía. También puede abrirse desde:

```text
Ayuda > Primeros pasos y diagnóstico…
```

Incluye instrucciones y un informe local con Python, sistema operativo, proxy, certificados y directorio de datos.

## Actualizar una copia existente

```powershell
git switch main
git pull
```

Después vuelve a ejecutar `Iniciar StreamInspector.bat`; el lanzador actualizará las dependencias cuando sea necesario.

## Instalación de desarrollo

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m streaminspector.main
```

Pruebas y lint:

```powershell
pytest
ruff check .
```

## Problemas frecuentes

### `ModuleNotFoundError: No module named 'PySide6'`

Estás usando un Python sin las dependencias. Ejecuta `Iniciar StreamInspector.bat`.

### `No pyvenv.cfg file`

El entorno virtual quedó incompleto. El lanzador actual lo detecta, elimina y reconstruye automáticamente.

### El puerto 8080 está ocupado

Detén el programa que lo utiliza o cambia el puerto desde `Proxy > Configurar host y puerto…`.

### No aparece tráfico HTTPS

Comprueba que el proxy está activo, que el navegador usa el proxy y que el certificado de mitmproxy está instalado en el perfil de prueba.

### Internet queda sin conexión al cerrar

Abre de nuevo StreamInspector y apaga el proxy correctamente. La aplicación restaura automáticamente la configuración anterior de Windows al detenerse o cerrarse.

## Uso responsable

StreamInspector puede mostrar credenciales, cookies, tokens y otros datos sensibles presentes en el tráfico. Utilízalo únicamente con autorización expresa, protege las exportaciones y elimina las sesiones cuando ya no sean necesarias.
