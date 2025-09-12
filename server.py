
# server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional, Tuple
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

# ===================== CORS =====================
# En pruebas: "*". En producción: pon tus dominios.
ALLOW_ORIGINS = ["*"]

app = FastAPI(title="Astrogematría API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== MODELOS =====================

class Birth(BaseModel):
    # Permitimos varios formatos de entrada y normalizamos
    date: str            # "YYYY/MM/DD" (aceptamos también "YYYY-MM-DD" o "DD/MM/YYYY")
    time: str            # "HH:MM"
    city: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[str] = None
    lon: Optional[str] = None

    @field_validator("date")
    @classmethod
    def norm_date(cls, v: str) -> str:
        """Normaliza a YYYY/MM/DD aceptando YYYY-MM-DD o DD/MM/YYYY."""
        v = v.strip().replace("-", "/")
        # Intentos de parseo comunes
        fmts = ["%Y/%m/%d", "%d/%m/%Y"]
        for f in fmts:
            try:
                dt = datetime.strptime(v, f)
                return dt.strftime("%Y/%m/%d")
            except ValueError:
                continue
        # Si no cuadra con nada, devolvemos tal cual para que el handler levante 400 con mensaje claro
        return v

    @field_validator("time")
    @classmethod
    def norm_time(cls, v: str) -> str:
        return v.strip()

class EvalRequest(BaseModel):
    birth: Birth
    term: str

# ===================== HELPERS =====================

def parse_date_time_or_400(date_str: str, time_str: str) -> datetime:
    """Parses date/time robustamente y devuelve datetime (local).
    Levanta HTTP 400 con mensaje claro si no cuadra."""
    # Ya viene normalizada a YYYY/MM/DD por el validador; intentamos parsear la hora.
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha/Hora inválidas. Usa YYYY/MM/DD y HH:MM.")

def resolve_coords_or_400(b: Birth) -> Tuple[str, str, float, float]:
    """Devuelve (lat_str, lon_str, lat_float, lon_float) resolviendo si hace falta por city+country."""
    lat_str = lon_str = None
    lat_f = lon_f = None

    # Prioridad: si faltan lat/lon pero hay city/country, geocodificamos en el servidor
    if (not b.lat or not b.lon) and (b.city and b.country):
        geo = geocode_city(b.city or "", b.country or "")
        if geo:
            lat_str, lon_str, lat_f, lon_f = geo

    # Si no tenemos aún, intentamos parsear lo que venga en lat/lon
    if not lat_str:
        if not (b.lat and b.lon):
            # Mensaje acorde al que te devolvía antes el backend
            raise HTTPException(status_code=400, detail="Faltan city/country o lat/lon")
        lat_str, lon_str, lat_f, lon_f = parse_geopos(b.lat, b.lon)

    return lat_str, lon_str, lat_f, lon_f

# ===================== ENDPOINTS =====================

@app.get("/")
def root():
    return {"status": "ok", "service": "judeoastro", "msg": "API viva 🚀"}

@app.get("/healthz")
def healthz():
    return "OK"

@app.post("/evaluate")
def evaluate(req: EvalRequest):
    # 1) Fecha/Hora robustas
    dt_local = parse_date_time_or_400(req.birth.date, req.birth.time)

    # 2) Coordenadas (server-side geocoding si hace falta)
    lat_str, lon_str, lat_f, lon_f = resolve_coords_or_400(req.birth)

    # 3) Zona horaria desde coords (fallback +01:00)
    zona = tz_offset_from_coords(dt_local, lat_f, lon_f) or "+01:00"

    # 4) Carta natal (mantengo PLACIDUS; cambia a EQUAL si lo deseas)
    dt  = Datetime(req.birth.date, req.birth.time, zona)
    pos = GeoPos(lat_str, lon_str)
    chart = Chart(dt, pos, hsys=const.HOUSES_PLACIDUS)

    # 5) Posiciones + evaluación
    posiciones = obtener_posiciones(chart)
    res = evalua_termino_con_carta(req.term, posiciones)

    return {
        "zone": zona,
        "lat": lat_str,
        "lon": lon_str,
        "positions": posiciones,
        "result": res
    }













