# Source Guide

## Runtime Sources

- `paparazzi`: WordPress API direct extractor.
- `tn`: RSS/HTML extractor.
- `infobae`, `ambitofinanciero`, `ariesonline`, `elonce`, `eloncesalta`, `eltribuno`, `minutouno`, `nuevodiariodesalta`, `noticiasargentinas`: registered through the common RSS/HTML extractor and controlled by `config/sources.yaml`.
- `x`: manual URL import in `X_MODE=manual`; feed scan uses `X_MODE=browser`, `X_MODE=api` or `X_MODE=feed` when configured. `X_BEARER_TOKEN` is optional and never hardcoded; without it the scanner uses the browser/session, syndication fallback and local cache.

Only sources with `enabled: true` are scanned by the 24/7 loop. Disabled sources can remain registered without affecting production.

## Configuration

Edit `config/sources.yaml`.

Fields:
- `name`
- `enabled`
- `type`
- `scan_interval_minutes`
- `priority`
- `category`
- `base_url`
- `parser`
- `max_items_per_scan`

## Add A Source

1. Add source config in `config/sources.yaml`.
2. Reuse `extractors/news/rss_html.py` when RSS/HTML is enough, or add a dedicated extractor under `extractors/news/`.
3. Register dedicated extractors in `extractors/registry.py` only when generic RSS/HTML is not enough.
4. Add a fixture or mocked integration test.
5. Run:

```powershell
python -m cli.main test-source --source <name>
python -m pytest
```

`D:\WebApp_HolaSalta` can be inspected as reference, but production should not depend on it.
