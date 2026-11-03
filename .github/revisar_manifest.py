"""Falla (código 1) si la actualización de precios dejó demasiados instrumentos con error o desactualizados."""
import json
import sys
from datetime import date
from pathlib import Path

MAX_ERRORES = 10      # de los 56 instrumentos
MAX_DIAS_ATRASO = 7   # acciones cuyo último dato es más viejo que esto, respecto de hoy

man = json.loads((Path(__file__).resolve().parent.parent / "data" / "manifest.json").read_text(encoding="utf-8"))
series = man["series"]
errores = [s for s in series if s.get("error")]
hoy = date.today()
atrasadas = [s for s in series if s["categoria"] == "accion" and s.get("ultimo_dato") and (hoy - date.fromisoformat(s["ultimo_dato"])).days > MAX_DIAS_ATRASO]
print(f"Instrumentos: {len(series)} | con error: {len(errores)} | acciones con más de {MAX_DIAS_ATRASO} días de atraso: {len(atrasadas)}")
for s in errores:
    print(f"  error  {s['ticker']}: {s['error']}")
for s in atrasadas:
    print(f"  atraso {s['ticker']}: último dato {s['ultimo_dato']}")
if len(errores) > MAX_ERRORES:
    sys.exit(f"Demasiados instrumentos con error ({len(errores)} > {MAX_ERRORES}).")
