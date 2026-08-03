# StreamInspector

Aplicación de escritorio para inspección y depuración **autorizada** de tráfico web y APIs.

## Estado

`0.1.0-alpha.2` — primera versión funcional del motor de captura:

- GUI PySide6 con tema oscuro.
- EventBus tipado y thread-safe.
- Configuración mediante Pydantic Settings.
- Logs rotativos.
- Proxy local basado en mitmproxy ejecutado en un hilo dedicado.
- Inicio y parada del proxy desde la barra de herramientas.
- Historial HTTP actualizado en tiempo real.
- Árbol de dominios de la sesión actual.
- Integración segura entre el hilo del proxy y el hilo de Qt.
- Pruebas con pytest, lint con Ruff y CI de GitHub Actions.

## Requisitos

- Python 3.12 o superior.
- Windows, Linux o macOS.

## Instalación de desarrollo

```bash
python -m venv .venv
```

En Windows:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Ejecución

```bash
streaminspector
```

También puede iniciarse con:

```bash
python -m streaminspector.main
```

## Primera captura

1. Inicia StreamInspector.
2. Pulsa `Proxy OFF`; cambiará a `Proxy ON` cuando el motor esté escuchando.
3. Configura temporalmente el proxy HTTP/HTTPS del navegador como `127.0.0.1:8080`.
4. Navega por un sistema propio o autorizado.
5. Las respuestas capturadas aparecerán en la tabla.

Para HTTPS será necesario instalar el certificado generado por mitmproxy. Con el proxy activo, abre `http://mitm.it` en el navegador configurado y sigue las instrucciones del sistema operativo. Instálalo únicamente en equipos y perfiles de prueba controlados.

El host y puerto pueden cambiarse con variables de entorno:

```powershell
$env:STREAMINSPECTOR_PROXY__HOST = "127.0.0.1"
$env:STREAMINSPECTOR_PROXY__PORT = "8080"
```

## Pruebas y calidad

```bash
pytest
ruff check .
```

## Próxima fase

Persistencia SQLite de sesiones y cuerpos, selección de filas y visor real de petición/respuesta.

## Uso responsable

Utiliza StreamInspector únicamente sobre sistemas propios o cuando dispongas de autorización expresa para inspeccionar el tráfico.
