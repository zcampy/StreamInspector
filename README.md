# StreamInspector

Aplicación de escritorio para inspección y depuración **autorizada** de tráfico web y APIs.

## Inicio automático en Windows

No ejecutes directamente `src/streaminspector/main.py`, porque ese archivo presupone que las dependencias ya están instaladas.

Haz doble clic en:

```text
Iniciar StreamInspector.bat
```

El lanzador realiza automáticamente estas operaciones:

1. Comprueba Python 3.12 o superior.
2. Crea `.venv` si todavía no existe.
3. Instala o actualiza PySide6, mitmproxy, SQLAlchemy y el resto de dependencias.
4. Reinstala el proyecto cuando cambia `pyproject.toml`.
5. Inicia StreamInspector usando el Python del entorno virtual.

También puede iniciarse desde una consola:

```powershell
py -3.12 bootstrap.py
```

## Funciones actuales

- GUI PySide6 con tema oscuro.
- Proxy local basado en mitmproxy.
- Captura HTTP/HTTPS para entornos autorizados.
- Persistencia SQLite y sesiones históricas.
- Inspector de petición, respuesta, cabeceras, cuerpo y JSON.
- Filtros combinables y ordenación por columnas.
- Exportación CSV, JSON y HAR 1.2.
- Menú contextual para copiar datos de una captura.
- Compositor para editar y repetir una petición seleccionada.
- Pruebas con pytest, lint con Ruff y CI de GitHub Actions.

## Instalación de desarrollo

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Después:

```powershell
python -m streaminspector.main
```

## Primera captura

1. Inicia StreamInspector con el lanzador automático.
2. Pulsa `Proxy OFF`; cambiará a `Proxy ON` cuando el motor esté escuchando.
3. Configura temporalmente el proxy HTTP/HTTPS del navegador como `127.0.0.1:8080`.
4. Navega por un sistema propio o autorizado.
5. Las respuestas capturadas aparecerán en la tabla.

Para HTTPS será necesario instalar el certificado generado por mitmproxy. Con el proxy activo, abre `http://mitm.it` en el navegador configurado y sigue las instrucciones del sistema operativo. Instálalo únicamente en equipos y perfiles de prueba controlados.

## Repetir una petición

Selecciona una captura y usa `Peticiones > Repetir petición seleccionada…` o el menú contextual. Puedes modificar método, URL, cabeceras y cuerpo antes de enviarla. La operación se ejecuta en un hilo separado para no bloquear la interfaz.

## Configuración del proxy

```powershell
$env:STREAMINSPECTOR_PROXY__HOST = "127.0.0.1"
$env:STREAMINSPECTOR_PROXY__PORT = "8080"
```

## Pruebas y calidad

```bash
pytest
ruff check .
```

## Uso responsable

Utiliza StreamInspector únicamente sobre sistemas propios o cuando dispongas de autorización expresa para inspeccionar o repetir el tráfico.
