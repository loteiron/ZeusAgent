# ZeusAgent

Agente personal independiente derivado de Nous Research / Hermes Agent. La licencia MIT y los avisos originales se conservan en [LICENSE](LICENSE) y [NOTICE.md](NOTICE.md).

Este paquete es una distribución de código fuente en desarrollo. Consulta [README.md](README.md) para la instalación y el uso.

## Instalación desde este paquete

Extrae todo el archivo. Necesitas Python 3.11–3.13 y, para las interfaces, una versión de Node.js/npm compatible con `package.json`.

```sh
python scripts/setup_zeus.py --web
python scripts/launch_zeus.py setup
python scripts/launch_zeus.py
```

En Linux/macOS puedes usar `python3`. En Windows puedes abrir `KUR-ZEUS.bat` y después `BASLAT-ZEUS.bat`.

Para el escritorio:

```sh
python scripts/setup_zeus.py --desktop
python scripts/launch_zeus.py --desktop
```

El escritorio abre la compilación local. Para desarrollar con recarga en vivo, usa `--desktop-dev`. Para el panel web, ejecuta `python scripts/launch_zeus.py dashboard`.

Los proveedores de modelos y Telegram se configuran por separado. Los datos de Hermes no se migran automáticamente. ZeusAgent todavía no tiene un canal de actualizaciones remoto propio; las direcciones de instalación de Hermes instalan el producto original.

La traducción heredada queda como referencia histórica en [docs/UPSTREAM-README.es.md](docs/UPSTREAM-README.es.md).
