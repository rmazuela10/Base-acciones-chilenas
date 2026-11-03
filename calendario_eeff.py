"""Calendario de presentación de estados financieros: las "Fechas de Divulgación de EEFF" que cada empresa declara en la CMF
(pestaña 101 de https://www.cmfchile.cl/institucional/mercados/entidad.php).

Escribe data/calendario_eeff.json:
  {"actualizado": ..., "fuente": ..., "empresas": {"AGUAS-A.SN": {"nombre", "rut", "fechas": {"2026-09": "2026-11-26", "2026-12": null, ...}, "error": null}}}
La clave es el período que se informa (AAAA-MM); la fecha es el día de divulgación (el de diciembre cae en el año siguiente).

Uso: python calendario_eeff.py [--ticker A,B] [--mercado chile]
"""
import argparse
import html
import json
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent
URL = "https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut}&grupo=&tipoentidad=RVEMI&row=&vig=VI&control=svs&pestania=101"
UA = {"User-Agent": "Mozilla/5.0 (compatible; finance-macro-dashboard/1.0)"}
MESES = ("03", "06", "09", "12")
PAUSA = 1.0
REINTENTOS = 4


def celdas(pagina: str):
    out = []
    for c in re.findall(r"<td[^>]*>(.*?)</td>", pagina, flags=re.S | re.I):
        t = re.sub(r"<[^>]+>", " ", c)
        out.append(re.sub(r"\s+", " ", html.unescape(t).replace("\xa0", " ")).strip())
    return out


def leer_pagina(pagina: str) -> dict:
    """{'2026-03': '2026-05-20', ...} a partir de la tabla Año | Marzo | Junio | Septiembre | Diciembre."""
    cs = celdas(pagina)
    fechas = {}
    es_fecha = lambda x: re.fullmatch(r"\d{2}/\d{2}/\d{4}", x) is not None
    for i in range(len(cs) - 4):
        if re.fullmatch(r"20\d\d", cs[i]) and all(es_fecha(x) or x == "-" for x in cs[i + 1:i + 5]):
            for mes, x in zip(MESES, cs[i + 1:i + 5]):
                d, m, a = x.split("/") if es_fecha(x) else (None, None, None)
                fechas[f"{cs[i]}-{mes}"] = f"{a}-{m}-{d}" if d else None
    return fechas


def leer_empresa(rut: str, sesion) -> dict:
    ultimo = None
    for i in range(REINTENTOS):
        try:
            r = sesion.get(URL.format(rut=rut.split("-")[0]), headers=UA, timeout=(15, 90))
            r.raise_for_status()
            f = leer_pagina(r.text)
            if not f:
                raise ValueError("no se encontró la tabla de fechas")
            return f
        except (requests.RequestException, ValueError) as e:
            ultimo = e
            time.sleep(3 * (i + 1))
    raise ultimo


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mercado", default="chile")
    ap.add_argument("--ticker", help="uno o varios tickers separados por coma")
    a = ap.parse_args()
    uni = json.loads((RAIZ / "universe" / f"{a.mercado}.json").read_text(encoding="utf-8"))["instrumentos"]
    pedidos = set(a.ticker.split(",")) if a.ticker else None
    ruta = RAIZ / "data" / "calendario_eeff.json"
    previo = {}
    if ruta.exists():
        try:
            previo = json.loads(ruta.read_text(encoding="utf-8")).get("empresas", {})
        except ValueError:
            pass
    empresas, fallos = dict(previo), []
    s = requests.Session()
    for inst in uni:
        if inst["categoria"] != "accion" or not inst.get("rut") or (pedidos and inst["ticker"] not in pedidos):
            continue
        tk = inst["ticker"]
        if inst.get("eeff", {}).get("tipo") == "banco":   # los bancos no declaran fechas en esta pestaña de la CMF
            empresas[tk] = {"nombre": inst["nombre"], "rut": inst["rut"], "fechas": {}, "error": None}
            continue
        try:
            f = leer_empresa(inst["rut"], s)
            empresas[tk] = {"nombre": inst["nombre"], "rut": inst["rut"], "fechas": f, "error": None}
        except Exception as e:   # una empresa que falla conserva sus fechas anteriores
            fallos.append((tk, f"{type(e).__name__}: {e}"[:120]))
            empresas.setdefault(tk, {"nombre": inst["nombre"], "rut": inst["rut"], "fechas": {}, "error": None})
            empresas[tk]["error"] = fallos[-1][1]
        time.sleep(PAUSA)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    out = {"actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "fuente": "CMF, pestaña «Fechas de Divulgación de EEFF» de cada emisor", "empresas": empresas}
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)
    con_fechas = sum(1 for e in empresas.values() if any(e["fechas"].values()))
    print(f"calendario listo: {len(empresas)} empresas, {con_fechas} con fechas, {len(fallos)} con error")
    for tk, m in fallos:
        print(f"  - {tk}: {m}")
    if len(fallos) > 8:   # la CMF no responde o cambió su página: que el trabajo quede en rojo y avise
        sys.exit(f"Demasiadas empresas con error ({len(fallos)}).")


if __name__ == "__main__":
    main()
