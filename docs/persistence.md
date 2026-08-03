# Persistencia de capturas

StreamInspector guarda cada respuesta capturada en SQLite mediante SQLAlchemy.

La base de datos se crea en el directorio de datos de usuario de la aplicación con el nombre `sessions.sqlite3`.

Actualmente se almacenan:

- método, URL, host, puerto y versión HTTP;
- código y motivo de respuesta;
- cabeceras completas de petición y respuesta;
- cuerpos binarios de petición y respuesta;
- tipo, tamaño y duración.

La interfaz permite inspeccionar la petición, la respuesta, las cabeceras, el cuerpo y una vista JSON formateada.
