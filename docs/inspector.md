# Inspector HTTP

Selecciona una fila del historial para abrir sus detalles.

Pestañas disponibles:

- **Petición:** línea de petición, cabeceras y cuerpo.
- **Respuesta:** estado, cabeceras y cuerpo.
- **Headers:** comparación directa de ambas cabeceras.
- **Body:** cuerpo de la respuesta decodificado como UTF-8 con sustitución segura.
- **JSON:** representación formateada cuando el cuerpo contiene JSON válido.

Los cuerpos originales se conservan como bytes en SQLite para no perder información binaria.
