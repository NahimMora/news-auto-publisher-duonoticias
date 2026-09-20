# Reglas del proyecto

- Produccion real solo en la PC cuyo `COMPUTERNAME` sea `FERNANDO`. En otras maquinas, usar exclusivamente tests, mocks y `--dry-run`/`--verify`.
- HolaSalta es solo lectura: no modificar `C:\HolaSalta\WebApp_HolaSalta` ni `C:\HolaSalta\Ops`. Solo se permite `POST /api/auth/login` y GET de noticias/jobs.
- No exponer puertos en produccion. No guardar ni imprimir secretos; configurarlos en `.env`, que esta ignorado por Git.
- La web Node y el procesamiento de valor agregado real estan fuera de este repositorio.

