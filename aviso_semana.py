"""Arma el texto del aviso semanal de estados financieros a partir de data/calendario_eeff.json (no envía nada).

Imprime una línea `Asunto: ...` y después el cuerpo del correo. Lo ejecuta la rutina de Claude los domingos a las 14:00 (Chile).
Uso: python aviso_semana.py [AAAA-MM-DD]   (la fecha simula "hoy", para pruebas)
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MN = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MES = {"03": "marzo (1T)", "06": "junio (2T)", "09": "septiembre (3T)", "12": "diciembre (anual)"}
fl = lambda d: f"{DIAS[d.weekday()]} {d.day} de {MN[d.month - 1]}"


def hoy_chile() -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Santiago")).date()
    except Exception:
        return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    hoy = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else hoy_chile()
    cal = json.loads((RAIZ / "data" / "calendario_eeff.json").read_text(encoding="utf-8"))
    uni = {i["ticker"]: i for i in json.loads((RAIZ / "universe" / "chile.json").read_text(encoding="utf-8"))["instrumentos"]}
    lunes = hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)
    dom = lunes + timedelta(days=6)
    semana, sin_fecha = [], []
    for tk, e in cal["empresas"].items():
        inst = uni.get(tk, {})
        if not any(e["fechas"].values()):
            sin_fecha.append(e["nombre"])
            continue
        for per, f in e["fechas"].items():
            if f and lunes <= date.fromisoformat(f) <= dom:
                semana.append((date.fromisoformat(f), e["nombre"], bool(inst.get("ipsa")), per))
    semana.sort(key=lambda x: (x[0], x[1]))
    act = date.fromisoformat(cal["actualizado"][:10])
    print(f"Asunto: Estados financieros: semana del {lunes.day} de {MN[lunes.month - 1]} al {dom.day} de {MN[dom.month - 1]}")
    print()
    if (hoy - act).days > 8:
        print(f"Aviso: el calendario de la CMF no se actualiza desde el {act} (el flujo de GitHub falló o la CMF no respondió); las fechas pueden estar desactualizadas.\n")
    print(f"Estados financieros de la semana entrante ({fl(lunes)} al {fl(dom)})\n")
    if semana:
        print("Presentan esta semana (fecha de divulgación declarada en la CMF):")
        ant = None
        for d, n, ip, per in semana:
            if d != ant:
                print("\n  " + fl(d).capitalize())
                ant = d
            print(f"    - {n}{' (IPSA)' if ip else ''}: {MES[per[5:]]} de {per[:4]}")
    else:
        print("Ninguna empresa tiene fecha de presentación declarada para esa semana.")
    if sin_fecha:
        print("\nSin fecha declarada en la CMF (publican con otro calendario o no la informan): " + ", ".join(sin_fecha) + ".")
    errores = [e["nombre"] for tk, e in cal["empresas"].items() if e.get("error") and uni.get(tk, {}).get("eeff", {}).get("tipo") != "banco"]
    if errores:
        print("No se pudo consultar la CMF para: " + ", ".join(errores) + ". Sus fechas pueden estar desactualizadas.")
    print(f"\nLas fechas son las que cada empresa declara a la CMF como día de divulgación; el archivo en la CMF puede aparecer después. Calendario consultado el {act}. Mensaje automático.")


if __name__ == "__main__":
    main()
