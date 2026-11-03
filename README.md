# Base acciones chilenas

Precios diarios de acciones y ETF de la bolsa de Santiago, tomados de Yahoo Finance. Este repositorio es público y contiene **solo precios**.

- `data/prices/<TICKER>.json`: una serie por instrumento, `[{"d": "2026-11-02", "c": 123.4, "v": 1000}, ...]`. Una sola fila por fecha; `c` es el cierre ajustado por dividendos y splits (el valor de hoy es el último precio disponible hasta que cierra la rueda) y `v` el volumen. Historia de 15 años.
- `data/manifest.json`: catálogo con la fecha de actualización y el último dato de cada serie.
- `universe/chile.json`: instrumentos que se descargan.
- Un flujo de GitHub Actions (`.github/workflows/precios.yml`) actualiza todo de lunes a viernes cada 30 minutos durante la rueda y una vez después del cierre.

Los datos vienen de Yahoo Finance y se publican solo para consulta personal; no son una recomendación de inversión.

Lectura desde una página: `https://raw.githubusercontent.com/rmazuela10/Base-acciones-chilenas/main/data/manifest.json` y `.../data/prices/<TICKER>.json`.
