#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, importlib
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Astro API", version="1.0.0")

# --- CORS (tus orígenes) ---
ALLOWED = [
    "http://localhost",
    "http://localhost:3000",
    "http://almudenacuervo.local",
    "http://almudenacuervo.local:80",
    "https://vivirenastrologico.com",
    "http://vivirenastrologico.com",
    "https://www.vivirenastrologico.com",
    "http://www.vivirenastrologico.com",
    "https://enastrologico.com",
    "http://enastrologico.com",
    "https://www.enastrologico.com",
    "http://www.enastrologico.com",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED,
    allow_credentials=True,
    allow_methods=["GET","POST","OPTIONS"],
    allow_headers=["*"],
)

# --- Modelos ---
class Birth(BaseModel):
    date: str  # "YYYY/MM/DD"
    time: str  # "HH:MM"
    city: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[str] = None
    lon: Optional[str] = None

class EvalRequest(BaseModel):
    birth: Birth
    term: str

# --- Utilidades ---
def _to360(x: float) -> float:
    v = x % 360.0
    return v + 360.0 if v < 0 else v

def _sanitize(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool,int,float,str)):
        return obj
    if hasattr(obj, "lon"):
        try: return float(obj.lon)
        except: pass
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k,v in obj.items()}
    if isinstance(obj, (list,tuple)):
        return [_sanitize(v) for v in obj]
    try:
        return json.loads(json.dumps(obj))
    except:
        return str(obj)

def _lazy_flatlib():
    try:
        chart = importlib.import_module("flatlib.chart")
        dtmod = importlib.import_module("flatlib.datetime")
        geop = importlib.import_module("flatlib.geopos")
        const = importlib.import_module("flatlib.const")
        return chart, dtmod, geop, const
    except Exception as e:
        raise HTTPException(500, f"Error importando Flatlib: {e}")

def _lazy_astro():
    try:
        astro = importlib.import_module("astrogematria")
        # deben existir estas funciones:
        for name in ["geocode_city","parse_geopos","tz_offset_from_coords",
                     "obtener_posiciones","evalua_termino_con_carta"]:
            if not hasattr(astro, name):
                raise HTTPException(500, f"astrogematria.{name} no existe")
        return astro
    except Exception as e:
        raise HTTPException(500, f"Error importando astrogematria: {e}")

def _resolve_coords(astro, b: Birth):
    lat_str = lon_str = None
    lat_f = lon_f = None
    if (b.city or b.country):
        geo = astro.geocode_city(b.city or "", b.country or "")
        if geo:
            lat_str, lon_str, lat_f, lon_f = geo
    if not lat_str:
        if not (b.lat and b.lon):
            raise HTTPException(400, "Faltan city/country o lat/lon")
        lat_str, lon_str, lat_f, lon_f = astro.parse_geopos(b.lat, b.lon)
    return lat_str, lon_str, lat_f, lon_f

def _resolve_tz(astro, date_str: str, time_str: str, lat_f: float, lon_f: float) -> str:
    try:
        dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
    except ValueError:
        raise HTTPException(400, "Fecha/Hora inválidas. Usa YYYY/MM/DD y HH:MM.")
    return astro.tz_offset_from_coords(dt_local, lat_f, lon_f) or "+01:00"

# --- Handler global para ver el stack en logs y JSON ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print("=== Unhandled Exception ===")
    print(repr(exc))
    import traceback; traceback.print_exc()
    return JSONResponse(status_code=500, content={"error":"internal_error","detail":str(exc)})

# --- Rutas básicas ---
@app.get("/")
def root():
    return {"ok": True, "service": "astro-api", "version": app.version}

@app.api_route("/healthz", methods=["GET","HEAD","OPTIONS"])
def healthz():
    return {"ok": True}

@app.get("/version")
def version():
    return {"version": app.version}

@app.get("/diag")
def diag():
    """Diagnóstico rápido para Render."""
    info = {
        "python": sys.version,
        "cwd": os.getcwd(),
        "env_PORT": os.getenv("PORT"),
        "installed": {},
    }
    for m in ["flatlib","pyswisseph","timezonefinder","tzdata","geopy"]:
        try:
            importlib.import_module(m)
            info["installed"][m] = "ok"
        except Exception as e:
            info["installed"][m] = f"missing/err: {e}"
    return info

# --- Endpoints principales (imports perezosos) ---
@app.post("/chart")
def chart(req: Birth):
    chart_mod, dtmod, geop, const = _lazy_flatlib()
    astro = _lazy_astro()

    lat_str, lon_str, lat_f, lon_f = _resolve_coords(astro, req)
    zona = _resolve_tz(astro, req.date, req.time, lat_f, lon_f)

    dt = dtmod.Datetime(req.date, req.time, zona)
    pos = geop.GeoPos(lat_str, lon_str)
    ch = chart_mod.Chart(dt, pos, hsys=const.HOUSES_EQUAL)

    posiciones: Dict[str, Any] = _sanitize(astro.obtener_posiciones(ch))
    planets_keys = ['Sun','Moon','Mercury','Venus','Mars','Jupiter','Saturn','Uranus','Neptune','Pluto']
    planets = {k: _to360(float(posiciones[k])) for k in planets_keys if k in posiciones}
    angles = {"ASC": _to360(float(posiciones['Asc'])), "MC": _to360(float(posiciones['MC']))}
    houses = [_to360(float(ch.houses[i].lon)) for i in range(1,13)]

    return {"planets": planets, "angles": angles, "houses": houses, "zone": zona}

@app.post("/evaluate")
def evaluate(req: EvalRequest):
    chart_mod, dtmod, geop, const = _lazy_flatlib()
    astro = _lazy_astro()

    lat_str, lon_str, lat_f, lon_f = _resolve_coords(astro, req.birth)
    zona = _resolve_tz(astro, req.birth.date, req.birth.time, lat_f, lon_f)

    dt = dtmod.Datetime(req.birth.date, req.birth.time, zona)
    pos = geop.GeoPos(lat_str, lon_str)
    ch = chart_mod.Chart(dt, pos, hsys=const.HOUSES_EQUAL)

    posiciones = _sanitize(astro.obtener_posiciones(ch))
    res = _sanitize(astro.evalua_termino_con_carta(req.term, posiciones))

    return {"zone": zona, "lat": lat_str, "lon": lon_str, "positions": posiciones, "result": res}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="debug")









