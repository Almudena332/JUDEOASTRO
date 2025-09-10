#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from flatlib.chart import Chart
from flatlib.datetime import Datetime
from flatlib.geopos import GeoPos
from flatlib import const

# Tus utilidades (dejamos igual los nombres que ya usabas)
from astrogematria import (
    geocode_city, parse_geopos, tz_offset_from_coords,
    obtener_posiciones, evalua_termino_con_carta
)

app = FastAPI(title="Astro API", version="1.0.0")

# --- CORS ---
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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# --- Modelos ---
class Birth(BaseModel):
    date: str            # "YYYY/MM/DD"
    time: str            # "HH:MM"
    city: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[str] = None   # decimal o DMS
    lon: Optional[str] = None

class EvalRequest(BaseModel):
    birth: Birth
    term: str

# --- Helpers ---
def _to360(x: float) -> float:
    v = x % 360.0
    return v + 360.0 if v < 0 else v

def _resolve_coords(b: Birth):
    lat_str = lon_str = None
    lat_f = lon_f = None
    if (b.city or b.country):
        geo = geocode_city(b.city or "", b.country or "")
        if geo:
            lat_str, lon_str, lat_f, lon_f = geo
    if not lat_str:
        if not (b.lat and b.lon):
            raise HTTPException(400, "Faltan city/country o lat/lon")
        lat_str, lon_str, lat_f, lon_f = parse_geopos(b.lat, b.lon)
    return lat_str, lon_str, lat_f, lon_f

def _resolve_tz_offset(date_str: str, time_str: str, lat_f: float, lon_f: float) -> str:
    try:
        dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
    except ValueError:
        raise HTTPException(400, "Fecha/Hora inválidas. Usa YYYY/MM/DD y HH:MM.")
    return tz_offset_from_coords(dt_local, lat_f, lon_f) or "+01:00"

def _sanitize_jsonable(obj: Any) -> Any:
    """Convierte lo que venga a tipos JSON-serializables."""
    # Tipos básicos
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    # flatlib devuelve a veces objetos con .lon; si llegan, conviértelos
    if hasattr(obj, "lon"):
        try:
            return float(obj.lon)
        except Exception:
            pass
    # dict
    if isinstance(obj, dict):
        return {str(k): _sanitize_jsonable(v) for k, v in obj.items()}
    # lista/tupla
    if isinstance(obj, (list, tuple)):
        return [_sanitize_jsonable(v) for v in obj]
    # cualquier otra cosa, string
    try:
        return json.loads(json.dumps(obj))
    except Exception:
        return str(obj)

# --- Handler global de errores (para ver el motivo real) ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log al stdout (Render lo captura)
    print("=== Unhandled Exception ===")
    print(repr(exc))
    try:
        import traceback
        traceback.print_exc()
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": str(exc)},
    )

# --- Endpoints ---
@app.api_route("/healthz", methods=["GET", "HEAD", "OPTIONS"])
def healthz():
    return {"ok": True}

@app.get("/version")
def version():
    return {"version": app.version}

@app.post("/chart")
def chart(req: Birth):
    # Coordenadas & zona
    lat_str, lon_str, lat_f, lon_f = _resolve_coords(req)
    zona = _resolve_tz_offset(req.date, req.time, lat_f, lon_f)
    # Carta (CASAS IGUALES para cuadrar con la UI)
    dt = Datetime(req.date, req.time, zona)
    pos = GeoPos(lat_str, lon_str)
    ch = Chart(dt, pos, hsys=const.HOUSES_EQUAL)

    # OJO: aseguramos que todo lo que devolvemos es primitivo
    posiciones: Dict[str, Any] = _sanitize_jsonable(obtener_posiciones(ch))

    planets_keys = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                    'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
    planets = {k: _to360(float(posiciones[k])) for k in planets_keys if k in posiciones}
    angles = {
        "ASC": _to360(float(posiciones['Asc'])),
        "MC":  _to360(float(posiciones['MC'])),
    }
    houses = [_to360(float(ch.houses[i].lon)) for i in range(1, 13)]

    return {"planets": planets, "angles": angles, "houses": houses, "zone": zona}

@app.post("/evaluate")
def evaluate(req: EvalRequest):
    lat_str, lon_str, lat_f, lon_f = _resolve_coords(req.birth)
    zona = _resolve_tz_offset(req.birth.date, req.birth.time, lat_f, lon_f)
    dt = Datetime(req.birth.date, req.birth.time, zona)
    pos = GeoPos(lat_str, lon_str)
    ch = Chart(dt, pos, hsys=const.HOUSES_EQUAL)

    posiciones = _sanitize_jsonable(obtener_posiciones(ch))
    res = _sanitize_jsonable(evalua_termino_con_carta(req.term, posiciones))

    return {
        "zone": zona,
        "lat": lat_str,
        "lon": lon_str,
        "positions": posiciones,
        "result": res
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True, log_level="debug")








