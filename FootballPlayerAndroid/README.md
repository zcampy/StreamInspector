# Football Player Android

Aplicación Android independiente con la parte de partidos de StreamInspector.

## Funciones de esta primera versión

- Carga la página de fútbol directamente desde Android.
- Localiza el prefijo dinámico de la API.
- Descarga y decodifica el calendario protobuf.
- Muestra hora local, competición y equipos.
- Busca en segundo plano hasta 20 enlaces HLS directos.
- Reproduce HLS dentro de la APK mediante AndroidX Media3.
- No utiliza mitmproxy, navegador externo, FFplay, Cookie ni Authorization.

## Abrir

1. Abre Android Studio.
2. Selecciona **Open**.
3. Elige la carpeta `FootballPlayerAndroid`.
4. Deja que Gradle sincronice el proyecto.
5. Ejecuta `app` en un dispositivo Android 8.0 o superior.

## Generar APK

En Android Studio usa **Build > Build APK(s)**. La APK de depuración se genera normalmente en:

`app/build/outputs/apk/debug/app-debug.apk`

## Limitación

La aplicación solo acepta URLs `.m3u8` presentes directamente en las respuestas públicas. Los eventos que necesiten JavaScript, descifrado, autenticación o DRM aparecen como `No directo`.
