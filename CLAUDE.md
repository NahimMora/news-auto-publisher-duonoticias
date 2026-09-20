# Reglas del proyecto

- Produccion real solo en la PC cuyo `COMPUTERNAME` sea `FERNANDO`. En otras maquinas, usar exclusivamente tests, mocks y `--dry-run`/`--verify`.
- HolaSalta es solo lectura: no modificar `C:\HolaSalta\WebApp_HolaSalta` ni `C:\HolaSalta\Ops`. Solo se permite `POST /api/auth/login` y GET de noticias/jobs.
- No exponer puertos en produccion. No guardar ni imprimir secretos; configurarlos en `.env`, que esta ignorado por Git.
- La web Node y el procesamiento de valor agregado real estan fuera de este repositorio.

## Segundo Cerebro (gestión de conocimiento personal)

Este repo está trackeado por el "Segundo Cerebro" personal
(`AutoPublicadores/2doCerebro`, https://ops.moraapps.com) bajo el proyecto
**DUO** (Duo Noticias), módulo **Web**.

Si el usuario pregunta algo como "¿qué bugs/ideas/incidentes anoté acá?" (o
equivalente), consultá antes de responder; no asumas que no hay nada
pendiente sin chequear:

```bash
curl -s https://ops.moraapps.com/api/shortcuts \
  -H "Authorization: Bearer $SEGUNDO_CEREBRO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"list_items","projectCode":"DUO","moduleSlug":"web"}'
```

- Si resolviste algo que ya estaba anotado ahí (id visible en la respuesta
  anterior, formato `DUO-BUG-0007`, o porque el usuario te lo dijo), marcalo
  resuelto en vez de dejarlo como pendiente fantasma, y referencialo en el
  commit (`fix: ... [DUO-BUG-0007]`):

  ```bash
  curl -s https://ops.moraapps.com/api/shortcuts \
    -H "Authorization: Bearer $SEGUNDO_CEREBRO_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action":"resolve_item","publicId":"DUO-BUG-0007"}'
  ```

- Si encontraste un bug real que no vas a arreglar ahora, o una idea/mejora
  para más adelante, anotala en vez de perderla en la conversación:

  ```bash
  curl -s https://ops.moraapps.com/api/shortcuts \
    -H "Authorization: Bearer $SEGUNDO_CEREBRO_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action":"capture","content":"texto libre describiendo el bug/idea","mode":"interpret","projectCode":"DUO","moduleSlug":"web"}'
  ```

`SEGUNDO_CEREBRO_TOKEN` vive en `.env` (gitignored; nunca commitear su
valor ni imprimirlo). Si no está seteado, avisá que esta integración no
está disponible en vez de fallar en silencio.
