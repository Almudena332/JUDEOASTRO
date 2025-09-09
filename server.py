#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict

from flatlib.chart import Chart
from flatlib.datetime import Datetime
from flatlib.geopos import GeoPos
from flatlib import const

# Importa utilidades desde tu módulo existente
from astrogematria import (
    geocode_city, parse_geopos, tz_offset_from_coords,
    obtener_posiciones, evalua_termino_con_carta
)

# ---------------------------
# App + CORS
# ---------------------------
app = FastAPI(title="Astro API", version="1.0.0")

ALLOW_ORIGINS = [
    "http://almudenacuervo.local",
    "http://localhost",
    "http://localhost:3000",
    "https://enastrologico.com",
    "https://www.enastrologico.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Modelos
# ---------------------------
class Birth(BaseModel):
    date: str            # "YYYY/MM/DD"
    time: str            # "HH:MM"
    city: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[str] = None   # admite decimal o DMS con N/S/E/W
    lon: Optional[str] = None

class EvalRequest(BaseModel):
    birth: Birth
    term: str

# ---------------------------
# Helpers
# ---------------------------
def _to360(x: float) -> float:
    v = x % 360.0
    return v + 360.0 if v < 0 else v

def _resolve_tz_offset(date_str: str, time_str: str, lat_f: float, lon_f: float) -> str:
    try:
        dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
    except ValueError:
        raise HTTPException(400, "Fecha/Hora inválidas. Usa YYYY/MM/DD y HH:MM.")

    try:
        zona = tz_offset_from_coords(dt_local, lat_f, lon_f)
        if not zona:
            print("[tz] tz_offset_from_coords devolvió None; uso fallback +01:00")
            return "+01:00"
        return zona
    except Exception as e:
        print(f"[tz] ERROR resolviendo zona horaria: {e}. Fallback +01:00")
        return "+01:00"

# ---------------------------
# Endpoints
# ---------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/version")
def version():
    return {"version": app.version}

@app.post("/chart")
def chart(req: Birth):
    """
    Devuelve longitudes para la rueda del front:
    {
      "planets": {"Sun":deg, ...},
      "angles": {"ASC":deg, "MC":deg},
      "houses": [deg x12],
      "zone": "+01:00"
    }
    Grados en 0–360. Casas: Placidus.
    """
    # Coordenadas
    lat_str, lon_str, lat_f, lon_f = _resolve_coords(req)
    # Zona horaria (offset tipo +01:00)
    zona = _resolve_tz_offset(req.date, req.time, lat_f, lon_f)

    # Carta
    dt = Datetime(req.date, req.time, zona)
    pos = GeoPos(lat_str, lon_str)
    ch = Chart(dt, pos, hsys=const.HOUSES_PLACIDUS)

    # Posiciones
    posiciones: Dict[str, float] = obtener_posiciones(ch)

    planets = {
        k: _to360(v) for k, v in posiciones.items()
        if k in ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
                 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
    }
    angles = {
        "ASC": _to360(posiciones['Asc']),
        "MC":  _to360(posiciones['MC']),
    }
    houses = [_to360(ch.houses[i].lon) for i in range(1, 13)]

    return {"planets": planets, "angles": angles, "houses": houses, "zone": zona}

@app.post("/evaluate")
def evaluate(req: EvalRequest):
    """
    Mantiene tu evaluador de astrogematría:
    devuelve zona/coords/positions + resultado del término.
    """
    # Coordenadas
    lat_str, lon_str, lat_f, lon_f = _resolve_coords(req.birth)
    # Zona horaria
    zona = _resolve_tz_offset(req.birth.date, req.birth.time, lat_f, lon_f)

    # Carta
    dt = Datetime(req.birth.date, req.birth.time, zona)
    pos = GeoPos(lat_str, lon_str)
    ch = Chart(dt, pos, hsys=const.HOUSES_PLACIDUS)

    posiciones = obtener_posiciones(ch)
    res = evalua_termino_con_carta(req.term, posiciones)

    return {
        "zone": zona,
        "lat": lat_str,
        "lon": lon_str,
        "positions": posiciones,
        "result": res
    }

# ---------------------------
# Main (local)
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)




