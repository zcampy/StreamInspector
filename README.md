# StreamInspector

Aplicación de escritorio para inspección y depuración **autorizada** de tráfico web y APIs.

## Estado

`0.1.0-alpha.1` — base ejecutable del proyecto:

- GUI inicial con PySide6 y tema oscuro.
- EventBus tipado y thread-safe.
- Configuración mediante Pydantic Settings.
- Logs rotativos.
- Estructura `src/` y pruebas con pytest.
- Punto de extensión preparado para integrar mitmproxy en la siguiente fase.

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

## Pruebas y calidad

```bash
pytest
ruff check .
```

## Próxima fase

Integración del motor proxy local con mitmproxy, emisión de eventos HTTP hacia la GUI y captura de metadatos de peticiones y respuestas.

## Uso responsable

Utiliza StreamInspector únicamente sobre sistemas propios o cuando dispongas de autorización expresa para inspeccionar el tráfico.
