# Contrato propuesto de ingesta (v1)

Endpoint: `POST {DUO_API_URL}/api/ingest/articles`

Headers:

- `Authorization: Bearer <DUO_API_TOKEN>`
- `Idempotency-Key: <sha256 hexadecimal de la clave interna del item>`
- `Content-Type: application/json`

Body:

```json
{
  "schemaVersion": 1,
  "idempotencyKey": "string",
  "kind": "news | video_link",
  "source": {
    "name": "HolaSalta",
    "url": "URL original o source_url",
    "publishedUrl": "web_url/url_wordpress o null"
  },
  "title": "string",
  "raw": {},
  "processed": {},
  "ingestedAt": "ISO-8601 UTC"
}
```

La web debe imponer unicidad sobre `idempotencyKey`. `201` significa creado; `200` o `409` significan que el mismo item ya existia y tambien cuentan como exito. Los demas `4xx` son definitivos. `5xx`, timeout y errores de red son transitorios.

La clave interna para noticias es `source:<url>`, en su defecto `web:<web_url|url_wordpress>`, y en su defecto `title:<titulo normalizado>`. Para videos es la `source_url` normalizada. El hash enviado nunca contiene secretos.

