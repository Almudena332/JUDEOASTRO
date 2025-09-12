from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from flatlib.chart import Chart
from flatlib.datetime import Datetime
from flatlib.geopos import GeoPos
from flatlib import const

from astrogematria import (
    geocode_city, parse_geopos, tz_offset_from_coords,
    obtener_posiciones, evalua_termino_con_carta
)

# En pruebas: "*". En producción: pon tu dominio
ALLOW_ORIGINS = ["*"]

app = FastAPI(title="Astrogematría API")
@app.get("/healthz")
def healthz():
    return "OK"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==== MODELOS ====

class Birth(BaseModel):
    date: str      # YYYY/MM/DD
    time: str      # HH:MM
    city: str | None = None
    country: str | None = None
    lat: str | None = None
    lon: str | None = None

class EvalRequest(BaseModel):
    birth: Birth
    term: str

# ==== ENDPOINTS ====

@app.get("/healthz")
def healthz(): 
    return {"ok": True}

@app.post("/evaluate")
def evaluate(req: EvalRequest):
    # 1. Geocoding
    lat_str = lon_str = None
    lat_f = lon_f = None

    if req.birth.city or req.birth.country:
        geo = geocode_city(req.birth.city or "", req.birth.country or "")
        if geo:
            lat_str, lon_str, lat_f, lon_f = geo

    if not lat_str:
        if not (req.birth.lat and req.birth.lon):
            raise HTTPException(400, "Faltan city/country o lat/lon")
        lat_str, lon_str, lat_f, lon_f = parse_geopos(req.birth.lat, req.birth.lon)

    # 2. Fecha y hora
    try:
        dt_local = datetime.strptime(f"{req.birth.date} {req.birth.time}", "%Y/%m/%d %H:%M")
    except ValueError:
        raise HTTPException(400, "Fecha/Hora inválidas. Usa YYYY/MM/DD y HH:MM.")

    # 3. Zona horaria
    zona = tz_offset_from_coords(dt_local, lat_f, lon_f) or "+01:00"

    # 4. Carta natal
    dt  = Datetime(req.birth.date, req.birth.time, zona)
    pos = GeoPos(lat_str, lon_str)
    chart = Chart(dt, pos, hsys=const.HOUSES_PLACIDUS)
    posiciones = obtener_posiciones(chart)

    # 5. Evaluación
    res = evalua_termino_con_carta(req.term, posiciones)

    return {
        "zone": zona,
        "lat": lat_str,
        "lon": lon_str,
        "positions": posiciones,
        "result": res
    }















