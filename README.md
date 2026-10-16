# AutoPublicador DuoNoticias

> **Estado:** este repo ahora contiene el pipeline completo (`python -m cli.main`, ver `AGENTS.md` y `docs/ARCHITECTURE.md`). HolaSalta es una fuente mas del pipeline (`extractors/holasalta/`) y la entrega a la web es la plataforma `duo_web` (`publishers/duo_web.py`). Lo que sigue describe el **puente standalone** `duonoticias_autopublicador/`, que se mantiene como deprecado durante la transicion. `pip install -e ".[test]"` instala ahora las dependencias de `requirements.txt` completas.

Backend Python que lee noticias y links de videos de X desde HolaSalta, los guarda en SQLite, pasa cada item por un procesador extensible y los entrega mediante una outbox HTTP a DuoNoticias. El procesador actual es deliberadamente `passthrough`: no agrega ni inventa contenido.

## Instalacion

Requiere Python 3.10 o posterior.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
Copy-Item .env.example .env
```

Complete `.env` sin versionarlo. Son obligatorios `HS_API_PASSWORD`, `DUO_API_URL` y `DUO_API_TOKEN`; los demas valores tienen defaults. `SEND_MAX_ATTEMPTS` controla el maximo de intentos de entrega. La primera sincronizacion usa `INITIAL_SYNC=mark_seen`, `process_all` o `last_n` (con `INITIAL_SYNC_LAST_N`).

## Uso

```powershell
python -m duonoticias_autopublicador.main --once
python -m duonoticias_autopublicador.main --once --dry-run
python -m duonoticias_autopublicador.main --verify
pytest
```

`--dry-run` consulta HolaSalta, registra y procesa items, pero no envia. `--verify` solo abre la base y muestra conteos; no consulta APIs ni modifica datos. Sin `--once`, queda en polling. El heartbeat por defecto es `state/heartbeat.json`.

El modo que puede enviar esta bloqueado por codigo salvo que `COMPUTERNAME=FERNANDO`. No se exponen puertos. El servidor de `tools/mock_duo_server.py` es solo para desarrollo y rechaza escuchar fuera de loopback.

## Tarea programada de Windows (solo documentacion)

En la PC FERNANDO, cree manualmente una tarea en Task Scheduler que se ejecute al iniciar sesion o al arrancar el equipo, con un usuario que tenga acceso al proyecto:

- Programa: `C:\DuoNoticias\AutoPublicador_DuoNoticias\.venv\Scripts\python.exe`
- Argumentos: `-m duonoticias_autopublicador.main`
- Iniciar en: `C:\DuoNoticias\AutoPublicador_DuoNoticias`
- Activar reinicio ante fallo y evitar instancias paralelas.

No se instala ninguna tarea desde este repositorio. El contrato propuesto para la web Node esta en [docs/INGEST_CONTRACT.md](docs/INGEST_CONTRACT.md).

Los items de HolaSalta se tratan como diccionarios opacos; el codigo solo usa los campos confirmados en el contrato. Para observar campos adicionales en la practica, revise `raw_json` en la base sin registrar credenciales ni tokens.

