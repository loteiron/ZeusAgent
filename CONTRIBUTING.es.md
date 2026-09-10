# Contribuir a ZeusAgent

Este es un fork independiente distribuido como código fuente. Usa los issues y
pull requests del repositorio del que obtuviste ZeusAgent; el soporte de Nous
Research no es el soporte de este fork.

La guía actual está en [CONTRIBUTING.md](CONTRIBUTING.md). Revisa también
[AGENTS.md](AGENTS.md) y las instrucciones del área que vas a modificar.

```sh
python scripts/setup_zeus.py --test-all --web
python scripts/launch_zeus.py --help
```

`--test-all` instala las dependencias Python bloqueadas de CI, incluidas las de
pruebas con proveedores simulados, sin configurar servicios reales. Para el
escritorio usa además `--desktop`. Python 3.11–3.13 es compatible; consulta
`package.json` para las versiones Node/npm.

Usa TDD como método: prueba que falla → cambio mínimo → misma prueba y regresiones
vecinas → revisión de resultados. No es una función añadida al agente. No desactives
validaciones de seguridad ni simules otro sistema operativo para obtener resultados verdes.
Las pruebas Python deben ejecutarse mediante `bash scripts/run_tests.sh`, con un
intérprete que tenga los extras de pruebas instalados. Los fallos, omisiones y
restricciones del entorno deben figurar por separado en el informe.

La única CI activa es `.github/workflows/zeus-ci.yml`. Los 32 workflows originales
están archivados e inactivos en `.github/upstream-workflows/`.
La [guía original en español](docs/UPSTREAM-CONTRIBUTING.es.md) se conserva como
referencia histórica, no como instrucciones de instalación o publicación de ZeusAgent.

No publiques credenciales, conversaciones ni diagnósticos sin revisión. Usa
[SECURITY.es.md](SECURITY.es.md) para informes privados. Ejecuta
`python scripts/github_source.py check` antes de publicar el código fuente.
