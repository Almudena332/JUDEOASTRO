#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calculadora de Astrogematría — v3.5
- Convención de grado: (360 - (valor % 360)) % 360  (coincide con la web de ejemplo)
- Orbes estrictos: 3° (conj/opp/tri/cuad) y 2° (sextil)
- Regentes clásicos del Asc sobreponderados
- Luminarias pegan más en Importancia
- Geocoding (Nominatim) y zona horaria automática (timezonefinder + fallbacks)
- ÁNGULOS incluidos: Asc, MC, Desc, IC
  · Contribuyen a IMPORTANCIA (impacto)
  · No suman a CALIDAD (no son planetas)
"""

from flatlib.chart import Chart
from flatlib.datetime import Datetime
from flatlib.geopos import GeoPos
from flatlib import const

import unicodedata
import re
from typing import Dict, Tuple
from datetime import datetime

# ==== CONFIGURACIÓN ASTROGEMATRÍA ====

VALORES_ASTROGEMATRIA = {
    'A': 1, 'B': 2, 'C': 20, 'D': 4, 'E': 5, 'F': 80, 'G': 3, 'H': 8, 'I': 10,
    'J': 10, 'K': 20, 'L': 30, 'M': 40, 'N': 50, 'Ñ': 50, 'O': 70, 'P': 80,
    'Q': 100, 'R': 200, 'S': 300, 'T': 400, 'U': 6, 'V': 6, 'W': 6, 'X': 60,
    'Y': 10, 'Z': 7, 'Ç': 20
}

# Orbes pequeños
ASPECTOS = {
    'conjuncion': {'angulo': 0,   'orbe': 3, 'peso': +4},
    'oposicion':  {'angulo': 180, 'orbe': 3, 'peso': -2},
    'trigono':    {'angulo': 120, 'orbe': 3, 'peso': +2},
    'cuadratura': {'angulo': 90,  'orbe': 3, 'peso': -2},
    'sextil':     {'angulo': 60,  'orbe': 2, 'peso': +1}
}

PESO_PLANETA = {
    'Sun': 1.0, 'Moon': 0.9, 'Mercury': 0.7, 'Venus': 1.0, 'Mars': 1.1,
    'Jupiter': 1.0, 'Saturn': 1.15, 'Uranus': 1.0, 'Neptune': 1.0, 'Pluto': 1.0,
}

AJUSTE_SIGNO = {
    'Saturn': {'soft': 0.8, 'hard': 1.25},
    'Mars':   {'soft': 0.9, 'hard': 1.10},
}

PLANETAS_TRAD = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn']
PLANETAS_MOD  = ['Uranus', 'Neptune', 'Pluto']
ANGULOS       = ['Asc', 'MC', 'Desc', 'IC']  # añadimos Desc/IC

# Regentes clásicos del Asc (0=Aries ... 11=Piscis)
REGENTES_CLASICOS = {
    0: ['Mars'], 1: ['Venus'], 2: ['Mercury'], 3: ['Moon'],
    4: ['Sun'],  5: ['Mercury'], 6: ['Venus'], 7: ['Mars'],
    8: ['Jupiter'], 9: ['Saturn'], 10: ['Saturn'], 11: ['Jupiter']
}
RULER_MULT = 1.35

SIGNOS = ["Aries","Tauro","Géminis","Cáncer","Leo","Virgo",
          "Libra","Escorpio","Sagitario","Capricornio","Acuario","Piscis"]

# === NUEVOS PESOS PARA IMPORTANCIA Y CALIDAD ===
IMPACT_WEIGHTS = {  # Importancia (conj > doble)
    'conjuncion': 2.6,
    'trigono': 1.0,
    'sextil': 0.8,
    'cuadratura': 1.0,
    'oposicion': 1.2
}

VALENCE_WEIGHTS = {  # Calidad (firma del aspecto)
    'conjuncion': 2.0,   # signo lo da el planeta
    'trigono': 1.2,      # +
    'sextil': 0.8,       # +
    'cuadratura': 1.0,   # -
    'oposicion': 1.2     # -
}

# Naturaleza del planeta para Calidad (–1..+1)
PLANET_VALENCE = {
    'Jupiter':  +1.0, 'Venus':  +0.9, 'Sun': +0.7, 'Moon': +0.6, 'Mercury': +0.2,
    'Mars':    -0.7, 'Saturn': -0.9, 'Uranus': -0.3, 'Neptune': -0.3, 'Pluto': -0.6
}

LUMINARIES = {'Sun', 'Moon'}
LUM_IMPACT_MULT = 1.15  # luminarias pegan más en Importancia
ANGLE_IMPACT_MULT = 1.25 # los ángulos pegan fuerte en Importancia
QUALITY_SCALE = 3.0      # escalar Calidad a –10..+10

# ==== UTILIDADES ====

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def normaliza_termino(s: str) -> str:
    s = s.replace('ñ', 'Ñ').replace('ç', 'Ç')
    s = ''.join(ch for ch in unicodedata.normalize('NFKD', s)
                if not unicodedata.combining(ch))
    s = s.upper()
    return re.sub(r'[^A-Z0-9ÑÇ]', '', s)

def valor_astrogematrico(termino: str) -> int:
    return sum(VALORES_ASTROGEMATRIA.get(ch, 0) for ch in termino)

def grado_astrogematrico(val: int) -> float:
    """Convención invertida, como en la web de ejemplo."""
    return float((360 - (val % 360)) % 360)

def dist_angular(a: float, b: float) -> float:
    return abs((a - b + 540) % 360 - 180)

def atenuado_por_orbe(delta: float, orbe: float) -> float:
    return 0.0 if delta > orbe else (1.0 - delta / orbe)

def mejor_aspecto(p_alfa: float, p_beta: float):
    best = ('', 999.0, 0.0)
    d0 = dist_angular(p_alfa, p_beta)
    for nombre, cfg in ASPECTOS.items():
        delta = abs(d0 - cfg['angulo'])
        if delta <= cfg['orbe']:
            peso = cfg['peso'] * atenuado_por_orbe(delta, cfg['orbe'])
            if abs(peso) > abs(best[2]):
                best = (nombre, delta, peso)
    return best

def lon_to_sign(lon: float) -> int:
    return int((lon % 360) // 30)

# === Conversión coords decimales -> formato Flatlib 'DDnMM' / 'DDDwMM'

def dec_to_flatlib_coord(dec: float, is_lat: bool) -> str:
    hemi = ('n' if dec >= 0 else 's') if is_lat else ('e' if dec >= 0 else 'w')
    v = abs(dec)
    deg = int(v)
    minutes = int(round((v - deg) * 60))
    if minutes == 60:
        deg += 1
        minutes = 0
    return f"{deg}{hemi}{minutes:02d}"

# ==== GEOCODING ====

def geocode_city(city: str, country: str):
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="enastrologico_astrogematria/1.0")
        q = f"{city}, {country}".strip(", ")
        loc = geolocator.geocode(q, language="es", timeout=10)
        if not loc:
            return None
        lat = float(loc.latitude)
        lon = float(loc.longitude)
        lat_str = dec_to_flatlib_coord(lat, is_lat=True)
        lon_str = dec_to_flatlib_coord(lon, is_lat=False)
        return (lat_str, lon_str, lat, lon)
    except Exception as e:
        print(f"[Aviso] Geocoding falló: {e}")
        return None

def parse_geopos(user_lat: str, user_lon: str) -> Tuple[str, str, float, float]:
    def dms_to_float(s: str) -> float:
        s = s.strip()
        if re.match(r'^-?\d+(\.\d+)?$', s):
            return float(s)
        hemi = None
        if re.search(r'[NnSsEeOoWw]$', s):
            hemi = s[-1].upper()
            s = s[:-1].strip()
        parts = re.split(r'[:\s,]+', s)
        deg = float(parts[0])
        minutes = float(parts[1]) if len(parts) >= 2 else 0.0
        seconds = float(parts[2]) if len(parts) >= 3 else 0.0
        val = abs(deg) + minutes/60 + seconds/3600
        if hemi in ('S',): val = -val
        if hemi in ('W','O'): val = -val
        if str(parts[0]).startswith('-'): val = -val
        return val
    lat = dms_to_float(user_lat)
    lon = dms_to_float(user_lon)
    lat_str = dec_to_flatlib_coord(lat, is_lat=True)
    lon_str = dec_to_flatlib_coord(lon, is_lat=False)
    return (lat_str, lon_str, lat, lon)

# ==== ZONA HORARIA ====

def tz_offset_from_coords(dt_local: datetime, lat: float, lon: float) -> str:
    try:
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        tzname = tf.timezone_at(lng=lon, lat=lat)
        if not tzname:
            return None
    except Exception as e:
        print(f"[Aviso] timezonefinder falló: {e}")
        return None

    try:
        try:
            from zoneinfo import ZoneInfo
        except Exception:
            from backports.zoneinfo import ZoneInfo
        dt_with_tz = dt_local.replace(tzinfo=ZoneInfo(tzname))
    except Exception:
        try:
            import pytz
            tz = pytz.timezone(tzname)
            dt_with_tz = tz.localize(dt_local, is_dst=None)
        except Exception as e:
            print(f"[Aviso] No se pudo aplicar tz '{tzname}': {e}")
            return None

    offset = dt_with_tz.utcoffset()
    if offset is None:
        return None
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{sign}{hh:02d}:{mm:02d}"

# ==== POSICIONES CARTA ====

def obtener_posiciones(chart: Chart) -> Dict[str, float]:
    pos = {}
    for p in PLANETAS_TRAD:
        pos[p] = chart.get(p).lon
    for p in PLANETAS_MOD:
        try: pos[p] = chart.get(p).lon
        except Exception: pass
    # Ángulos
    asc = chart.get('Asc').lon
    mc  = chart.get('MC').lon
    desc = (asc + 180.0) % 360.0
    ic   = (mc  + 180.0) % 360.0
    pos['Asc']  = asc
    pos['MC']   = mc
    pos['Desc'] = desc
    pos['IC']   = ic
    return pos

# ==== EVALUACIÓN (Importancia + Calidad) ====

def evalua_termino_con_carta(term: str, posiciones: Dict[str, float]) -> Dict:
    # 1) Preparación
    tnorm = normaliza_termino(term)
    val = valor_astrogematrico(tnorm)
    grado = grado_astrogematrico(val)

    asc_lon = posiciones.get('Asc', 0.0)
    asc_sign = lon_to_sign(asc_lon)
    regentes = set(REGENTES_CLASICOS.get(asc_sign, []))

    detalles = []
    import_sum = 0.0   # Importancia (módulo)
    quality_sum = 0.0  # Calidad (con signo)
    has_aspect = False
    has_conj   = False

    # 2) Recorremos planetas y ángulos
    for cuerpo, lon in posiciones.items():
        nombre, delta, _peso_tmp = mejor_aspecto(grado, lon)
        if not nombre:
            continue

        has_aspect = True
        if nombre == 'conjuncion':
            has_conj = True

        # Orb factor (0..1)
        orbe = ASPECTOS[nombre]['orbe']
        orb_factor = atenuado_por_orbe(delta, orbe)
        if orb_factor <= 0:
            continue

        es_angulo = cuerpo in ANGULOS

        # Multiplicadores para Importancia
        if es_angulo:
            mult_imp = ANGLE_IMPACT_MULT
        else:
            mult_imp = PESO_PLANETA.get(cuerpo, 1.0)
            if cuerpo in regentes:
                mult_imp *= RULER_MULT
            if cuerpo in LUMINARIES:
                mult_imp *= LUM_IMPACT_MULT

        # 2.a) Importancia (módulo)
        imp = IMPACT_WEIGHTS[nombre] * orb_factor * mult_imp
        import_sum += abs(imp)

        # 2.b) Calidad (con signo) — solo para PLANETAS
        if not es_angulo:
            pv = PLANET_VALENCE.get(cuerpo, 0.0)
            if nombre == 'conjuncion':
                q = VALENCE_WEIGHTS[nombre] * orb_factor * pv
            elif nombre in ('trigono', 'sextil'):
                q = VALENCE_WEIGHTS[nombre] * orb_factor * abs(pv)
            else:  # cuadratura / oposición
                q = -VALENCE_WEIGHTS[nombre] * orb_factor * abs(pv)

            if cuerpo in regentes:
                q *= RULER_MULT
            q *= PESO_PLANETA.get(cuerpo, 1.0)

            quality_sum += q
            calidad_det = round(q, 3)
        else:
            calidad_det = 0.0  # los ángulos no aportan calidad

        detalles.append({
            'cuerpo': cuerpo,
            'es_angulo': es_angulo,
            'aspecto': nombre,
            'orb': round(delta, 2),
            'impacto': round(abs(imp), 3),
            'calidad': calidad_det,
            'lon_cuerpo': round(lon, 2)
        })

    # 3) Etiquetas y escalas
    if not has_aspect:
        etq_import = "impacto NO importante (sin aspectos)"
        etq_calidad = "—"
        importancia = 0.0
        calidad = 0.0
    else:
        importancia = import_sum
        if has_conj:
            importancia = max(importancia, 2.1)  # conjunción ⇒ importante por defecto

        if importancia <= 2.0:
            etq_import = "impacto menor (presente pero discreto)"
        else:
            etq_import = "impacto IMPORTANTE"

        calidad = clamp(quality_sum * QUALITY_SCALE, -10, 10)
        if calidad >= 5:
            etq_calidad = "MUY BENÉFICO"
        elif calidad >= 2:
            etq_calidad = "BENÉFICO"
        elif calidad <= -5:
            etq_calidad = "MUY MALÉFICO"
        elif calidad <= -2:
            etq_calidad = "MALÉFICO"
        else:
            etq_calidad = "MIXTO / AMBIVALENTE"

    # Ordenamos impactos por Importancia y luego por |Calidad|
    detalles = sorted(detalles, key=lambda d: (-d['impacto'], -abs(d['calidad'])))[:8]

    # Info de signo y grado dentro del signo
    signo_idx = int(grado // 30)
    grado_en_signo = round(grado % 30, 2)
    signo_nombre = SIGNOS[signo_idx]

    return {
        'termino': tnorm,
        'valor_astrogematrico': val,
        'grado_ecliptico': round(grado, 2),
        'signo': signo_nombre,
        'grado_en_signo': grado_en_signo,

        'importancia': round(importancia, 2),
        'etq_importancia': etq_import,

        'calidad': round(calidad, 1),
        'etq_calidad': etq_calidad,

        'regentes_asc': sorted(list(regentes)),
        'hits': detalles
    }

# ==== ENTRADA Y CLI ====

def pedir_datos():
    print("=== DATOS DE NACIMIENTO ===")
    fecha = input("Fecha (YYYY/MM/DD): ").strip()
    hora  = input("Hora  (HH:MM): ").strip()
    city   = input("Ciudad: ").strip()
    country= input("País  : ").strip()

    lat_str = lon_str = None
    lat_f = lon_f = None

    if city or country:
        print("[Info] Buscando coordenadas…", flush=True)
        geo = geocode_city(city, country)
        if geo:
            lat_str, lon_str, lat_f, lon_f = geo
            print(f"[OK] {city}, {country} → {lat_str}, {lon_str}")
        else:
            print("[Aviso] No se pudo geocodificar. Pasamos a coordenadas manuales.")

    if not lat_str:
        print("Introduce coordenadas manuales (decimal o DMS, ej: 40.418, -3.703):")
        u_lat = input("Latitud : ").strip()
        u_lon = input("Longitud: ").strip()
        lat_str, lon_str, lat_f, lon_f = parse_geopos(u_lat, u_lon)

    try:
        dt_local = datetime.strptime(f"{fecha} {hora}", "%Y/%m/%d %H:%M")
    except ValueError:
        raise ValueError("Formato de fecha/hora inválido. Usa YYYY/MM/DD y HH:MM.")

    print("[Info] Calculando zona horaria…", flush=True)
    zona = tz_offset_from_coords(dt_local, lat_f, lon_f)
    if zona is None:
        print("[Aviso] No se pudo determinar la zona automáticamente.")
        zona = input("Indica el offset (ej +01:00 para España): ").strip()

    print(f"[OK] Offset horario: {zona}")
    return fecha, hora, zona, lat_str, lon_str

def main():
    print("🌟 CALCULADORA DE ASTROGEMATRÍA — v3.5 🌟")
    print("=" * 60)

    fecha, hora, zona, lat_str, lon_str = pedir_datos()

    print("\nCalculando carta natal…")
    dt  = Datetime(fecha, hora, zona)
    pos = GeoPos(lat_str, lon_str)
    chart = Chart(dt, pos, hsys=const.HOUSES_PLACIDUS)
    posiciones = obtener_posiciones(chart)

    trad_names = {
        'Sun':'Sol','Moon':'Luna','Mercury':'Mercurio','Venus':'Venus','Mars':'Marte',
        'Jupiter':'Júpiter','Saturn':'Saturno','Uranus':'Urano','Neptune':'Neptuno',
        'Pluto':'Plutón','Asc':'Asc','MC':'MC','Desc':'Desc','IC':'IC'
    }

    print("\n=== CARTA NATAL (longitudes) ===")
    for k in ['Sun','Moon','Mercury','Venus','Mars','Jupiter','Saturn','Uranus','Neptune','Pluto','Asc','Desc','MC','IC']:
        if k in posiciones:
            print(f"{trad_names.get(k,k):12}: {posiciones[k]:6.2f}°")

    while True:
        print("\n" + "=" * 60)
        term = input("Palabra/frase (o 'salir'): ").strip()
        if term.lower() == 'salir':
            break
        if not term:
            continue

        res = evalua_termino_con_carta(term, posiciones)
        print("\n=== RESULTADO ===")
        print(f"Término normalizado : {res['termino']}")
        print(f"Valor astrogemátrico: {res['valor_astrogematrico']}")
        print(f"Grado eclíptico     : {res['grado_ecliptico']}°  →  {res['grado_en_signo']}° de {res['signo']}")
        print(f"Regentes Asc        : {', '.join(res['regentes_asc']) or '—'}")

        if res['importancia'] == 0:
            print("IMPORTANCIA         : 0.0 → impacto NO importante (sin aspectos)")
            print("CALIDAD             : — (no se evalúa sin aspectos)")
        else:
            print(f"IMPORTANCIA         : {res['importancia']} → {res['etq_importancia']}")
            print(f"CALIDAD             : {res['calidad']} → {res['etq_calidad']}")

        if not res['hits']:
            print("No hay aspectos dentro de orbe. (Orbes estrictos). Prueba variantes.")
        else:
            print("\nTop impactos (por importancia):")
            for h in res['hits']:
                tipo = "ángulo" if h['es_angulo'] else "planeta"
                signo = "+" if h['calidad'] > 0 else ""
                print(f"  {h['cuerpo']:8} ({tipo})  {h['aspecto']:11} (orb {h['orb']:>4.1f}°)  "
                      f"Impacto {h['impacto']:>4.2f}  |  Calidad {signo}{h['calidad']:>4.2f}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] {e}")
    finally:
        input("\nPulsa Enter para salir…")
