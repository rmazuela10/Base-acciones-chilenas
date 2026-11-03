"""Precios: lee universe/<mercado>.json y escribe data/manifest.json + data/prices/*.json (un cierre por día, 15 años de historia)."""
import argparse
import importlib
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
MERCADO_DEFECTO = "chile"   # un manifest por mercado
ANIOS_HISTORIA = 15         # la historia nunca se baja ni se guarda más atrás que esto
SOLAPE_DIAS = 5             # días hacia atrás en la descarga incremental
PAUSA = 0.4                 # pausa corta entre peticiones a Yahoo


def inicio_historia() -> str:
    hoy = date.today()
    return hoy.replace(year=hoy.year - ANIOS_HISTORIA, day=min(hoy.day, 28) if hoy.month == 2 else hoy.day).isoformat()


def nombre_archivo(ticker: str) -> str:
    for ch in "^=/":
        ticker = ticker.replace(ch, "_")
    return ticker


def leer_json(p: Path, defecto):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _linea(x):
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def texto_json(obj) -> str:
    """JSON legible hacia abajo: una fila (un dia, una serie) por linea y cada fila compacta; asi pesa casi lo mismo que
    el JSON en una sola linea y los cambios de cada corrida se ven linea a linea en GitHub."""
    nl = chr(10)
    if isinstance(obj, list):
        return "[" + nl + ("," + nl).join(_linea(x) for x in obj) + nl + "]" + nl
    partes = []
    for k, v in obj.items():
        if isinstance(v, list):
            partes.append(_linea(k) + ":[" + nl + ("," + nl).join(_linea(x) for x in v) + nl + "]")
        else:
            partes.append(_linea(k) + ":" + _linea(v))
    return "{" + nl + ("," + nl).join(partes) + nl + "}" + nl


def escribir_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto_json(obj), encoding="utf-8", newline=chr(10))


def cargar_fetcher(fuente: str):
    """Devuelve fetch_series de la fuente, o None (csv) / lanza error si no existe."""
    if fuente == "yahoo":
        from sources import yahoo
        return yahoo.fetch_series
    if fuente == "fondos":
        if not (RAIZ / "sources" / "fondos.py").exists():
            raise RuntimeError("fuente fondos no disponible")
        return importlib.import_module("sources.fondos").fetch_series
    if fuente == "csv":
        return None
    raise RuntimeError(f"fuente desconocida: {fuente}")


def _historia_cambio(previo, nuevo, tol=0.005):
    """True si el cierre en fechas solapadas difiere >0.5% (Yahoo reajustó el historial)."""
    ant = {r["d"]: r["c"] for r in previo}
    return any(r["d"] in ant and ant[r["d"]] > 0 and abs(r["c"] / ant[r["d"]] - 1) > tol for r in nuevo)


def fila_manifest(inst, archivo, datos, error):
    return {
        "ticker": inst["ticker"], "nombre": inst["nombre"], "categoria": inst["categoria"],
        "moneda": inst.get("moneda"), "sector": inst.get("sector"),
        "archivo": archivo if datos else None,
        "primer_dato": datos[0]["d"] if datos else None,
        "ultimo_dato": datos[-1]["d"] if datos else None,
        "n": len(datos), "ultimo": datos[-1]["c"] if datos else None,
        "error": error,
    }


MIN_PUNTOS = 30  # una serie previa con menos puntos se considera sospechosa -> descarga completa


def procesar(inst, completo: bool, ignorar_previo: bool):
    ticker = inst["ticker"]
    rel = "prices/" + nombre_archivo(ticker) + ".json"
    ruta = RAIZ / "data" / rel
    previo = [] if ignorar_previo or not ruta.exists() else leer_json(ruta, [])
    if ignorar_previo and ruta.exists() and inst.get("fuente") != "csv":
        ruta.unlink()  # archivo de muestra: se descarta
    error = None
    try:
        fetch = cargar_fetcher(inst.get("fuente", "yahoo"))
        if fetch is not None:
            desde = None
            falta_s = inst.get("categoria") == "accion" and previo and "s" not in previo[0]  # serie sin cierre sin ajustar: se baja completa
            if len(previo) >= MIN_PUNTOS and not completo and not falta_s:
                ult = date.fromisoformat(previo[-1]["d"])
                desde = (ult - timedelta(days=SOLAPE_DIAS)).isoformat()
            nuevo = fetch(inst, desde or inicio_historia())
            if desde and _historia_cambio(previo, nuevo):  # dividendo/split reajustó el pasado
                desde, nuevo = None, fetch(inst, inicio_historia())
            if desde is None:
                previo = []  # descarga completa: reemplaza todo lo previo
            fusion = {r["d"]: r for r in previo}
            for r in nuevo:
                if r.get("s") is None and (fusion.get(r["d"]) or {}).get("s") is not None:
                    r["s"] = fusion[r["d"]]["s"]  # no perder el cierre sin ajustar ya guardado
            fusion.update({r["d"]: r for r in nuevo})  # lo nuevo pisa lo previo
            previo = [fusion[k] for k in sorted(fusion) if k >= inicio_historia()]
            if inst.get("fuente", "yahoo") == "yahoo" and inst.get("categoria") in ("accion", "etf"):
                from sources.yahoo import _quitar_relleno
                previo = _quitar_relleno(previo)  # el borde del solape también puede ser relleno
            escribir_json(ruta, previo)
        elif not previo:
            error = "csv: archivo no encontrado en data/prices/"
    except Exception as e:  # un fallo no aborta el resto; se conservan datos previos
        error = (str(e) or e.__class__.__name__)[:120]
    return fila_manifest(inst, rel, previo, error)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument("--mercado", default=MERCADO_DEFECTO)
    ap.add_argument("--completo", action="store_true", help="ignora lo existente y baja todo el historial")
    ap.add_argument("--solo", help="tickers separados por coma (el resto conserva su fila previa)")
    args = ap.parse_args()

    uni_path = RAIZ / "universe" / f"{args.mercado}.json"
    if not uni_path.exists():
        sys.exit(f"No existe {uni_path}")
    insts = json.loads(uni_path.read_text(encoding="utf-8"))["instrumentos"]
    solo = set(args.solo.split(",")) if args.solo else None
    man_path = RAIZ / "data" / ("manifest.json" if args.mercado == "chile" else f"manifest_{args.mercado}.json")
    man_previo = leer_json(man_path, {})
    previas = {s["ticker"]: s for s in man_previo.get("series", [])}
    muestra = bool(man_previo.get("_muestra"))  # manifest de muestra: ignorar archivos previos

    filas, ok, err = [], 0, []
    for i, inst in enumerate(insts, 1):
        if solo and inst["ticker"] not in solo and inst["ticker"] in previas:
            filas.append(previas[inst["ticker"]])
            continue
        fila = procesar(inst, args.completo, muestra)
        filas.append(fila)
        if fila["error"]:
            err.append((inst["ticker"], fila["error"]))
        else:
            ok += 1
        print(f"[{i}/{len(insts)}] {inst['ticker']}: " + (f"ERROR {fila['error']}" if fila["error"] else f"ok n={fila['n']} ultimo={fila['ultimo_dato']}"), flush=True)
        if inst.get("fuente") == "yahoo":
            time.sleep(PAUSA)

    escribir_json(man_path, {"mercado": args.mercado,
                             "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "series": filas})
    print(f"\nResumen: {ok} ok, {len(err)} con error")
    for t, e in err:
        print(f"  - {t}: {e}")


if __name__ == "__main__":
    main()
