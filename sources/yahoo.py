"""Fuente Yahoo Finance: descarga una serie diaria con yfinance y limpia artefactos conocidos."""
import math
import statistics
from datetime import date, timedelta

import yfinance as yf

VENTANA = 5        # vecinos a cada lado para detectar valores espurios
UMBRAL_SPIKE = 2.5  # un cierre >2.5x (o <1/2.5) la mediana vecina se descarta


def _num(x):
    """float o None si es NaN/None."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _descargar(ticker, desde, ajustar):
    kw = {"period": "max"} if not desde else {"start": desde}
    df = yf.Ticker(ticker).history(auto_adjust=ajustar, **kw)
    filas = {}
    if df is None:
        return filas
    for ts, row in df.iterrows():
        c = _num(row.get("Close"))
        if c is None:
            continue
        v = _num(row.get("Volume"))
        d = ts.strftime("%Y-%m-%d")
        filas[d] = {"d": d, "c": round(c, 6), "v": int(v) if v else None}  # 0/NaN -> None
    return [filas[k] for k in sorted(filas)]


def _quitar_relleno(rows):
    """Yahoo rellena días sin transacción en la bolsa de Santiago repitiendo el precio con volumen 0.
    Se descartan esas filas (sin volumen y mismo cierre que la anterior)."""
    out = []
    for r in rows:
        if out and r["v"] is None and r["c"] == out[-1]["c"]:
            continue
        out.append(r)
    return out


def _quitar_spikes(rows):
    """Descarta cierres aislados absurdos (glitches de Yahoo, p. ej. x100) frente a la mediana vecina."""
    if len(rows) < 5:
        return rows
    cs = [r["c"] for r in rows]
    out = []
    for i, r in enumerate(rows):
        vec = cs[max(0, i - VENTANA):i] + cs[i + 1:i + 1 + VENTANA]
        m = statistics.median(vec)
        if m > 0 and (r["c"] / m > UMBRAL_SPIKE or r["c"] / m < 1 / UMBRAL_SPIKE):
            continue
        out.append(r)
    return out


def _ajustar_splits_etf(rows):
    """ETF: un salto diario >=45% con razón cercana a un split simple (2:1, 4:1...) que Yahoo no ajustó
    se corrige reescalando el pasado."""
    for i in range(len(rows) - 1, 0, -1):
        a, b = rows[i - 1]["c"], rows[i]["c"]
        if a <= 0 or b <= 0:
            continue
        r = b / a
        if r < 0.55 or r > 1.8:
            n = round(1 / r) if r < 1 else round(r)
            ref = (1 / n) if r < 1 else n
            if n >= 2 and abs(r / ref - 1) < 0.10:
                for k in range(i):
                    rows[k]["c"] = round(rows[k]["c"] * r, 6)
    return rows


def _completar_intradia(ticker, rows, desde):
    """El diario de Yahoo para .SN deja semanas congeladas (precio repetido, volumen 0) que
    _quitar_relleno elimina, pero el feed horario sí trae esos días. Se rellenan los huecos de los
    últimos ~730 días con el último cierre horario del día, escalado al cierre ajustado con el factor
    del día válido siguiente (los ajustes por dividendo solo cambian hacia atrás)."""
    inicio = max(date.today() - timedelta(days=725), date.fromisoformat(desde) if desde else date.min)
    try:
        df = yf.Ticker(ticker).history(start=inicio.isoformat(), interval="1h", auto_adjust=False)
    except Exception:
        return rows  # sin intradía se queda el diario tal cual
    if df is None or df.empty:
        return rows
    dia = {}
    for ts, row in df.iterrows():
        c, v = _num(row.get("Close")), _num(row.get("Volume"))
        if c is None:
            continue
        d = ts.strftime("%Y-%m-%d")
        prev = dia.get(d, {"c": None, "v": 0})
        dia[d] = {"c": c, "v": prev["v"] + (v or 0)}  # filas en orden: el último cierre gana
    por_fecha = {r["d"]: r for r in rows}
    factor = 1.0
    for d in sorted(dia, reverse=True):  # de lo más reciente hacia atrás
        if d in por_fecha:
            if dia[d]["c"] > 0:
                factor = por_fecha[d]["c"] / dia[d]["c"]
        elif dia[d]["v"] > 0:  # día con transacciones que el diario no trae
            por_fecha[d] = {"d": d, "c": round(dia[d]["c"] * factor, 6), "v": int(dia[d]["v"])}
    return [por_fecha[k] for k in sorted(por_fecha)]


def _barras_horarias(ticker, desde):
    """Un cierre por día a partir del feed horario: el último cierre del día, con el volumen del día. Los días sin
    transacciones (volumen 0) se omiten. Yahoo entrega las barras horarias solo de los últimos ~730 días."""
    inicio = max(date.today() - timedelta(days=725), date.fromisoformat(desde) if desde else date.min)
    df = yf.Ticker(ticker).history(start=inicio.isoformat(), interval="1h", auto_adjust=False)
    dia = {}
    if df is None or df.empty:
        return []
    for ts, row in df.iterrows():
        c, v = _num(row.get("Close")), _num(row.get("Volume"))
        if c is None:
            continue
        d = ts.strftime("%Y-%m-%d")
        prev = dia.get(d, {"v": 0})
        dia[d] = {"c": c, "v": prev["v"] + (v or 0)}  # filas en orden: el último cierre gana
    return [{"d": d, "c": round(x["c"], 6), "v": int(x["v"])} for d, x in sorted(dia.items()) if x["v"] > 0]


def _serie_horaria(inst, desde):
    """Serie para instrumentos con `"barras": "horarias"` en el universo (el diario de Yahoo trae semanas congeladas).
    Toda la historia que cubre el feed horario sale de él; solo lo anterior (descarga completa) sale del diario ajustado."""
    horarias = _barras_horarias(inst["ticker"], desde)
    if not horarias:
        raise ValueError("Yahoo no devolvió barras horarias")
    if desde:
        return horarias
    diario = _quitar_relleno(_descargar(inst["ticker"], None, True))
    return [r for r in diario if r["d"] < horarias[0]["d"]] + horarias


def fetch_series(inst: dict, desde: str | None) -> list[dict]:
    """Devuelve [{"d","c","v"}] ascendente. desde=None -> historial completo."""
    if inst.get("barras") == "horarias":
        rows = _quitar_spikes(_serie_horaria(inst, desde))
        return _ajustar_splits_etf(rows) if inst.get("categoria") == "etf" else rows
    rows = _descargar(inst["ticker"], desde, True)  # cierre ajustado por dividendos/splits
    if rows and min(r["c"] for r in rows) <= 0:      # ajuste corrupto en Yahoo -> cierre sin ajustar
        rows = _descargar(inst["ticker"], desde, False)
    if not rows:
        raise ValueError("Yahoo no devolvió datos")
    if inst.get("categoria") in ("accion", "etf"):
        rows = _quitar_relleno(rows)
        rows = _completar_intradia(inst["ticker"], rows, desde)
    rows = _quitar_spikes(rows)
    if inst.get("categoria") == "etf":
        rows = _ajustar_splits_etf(rows)
    if not rows:
        raise ValueError("Yahoo no devolvió cierres válidos")
    return rows
