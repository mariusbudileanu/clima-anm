# -*- coding: utf-8 -*-
"""
12_episod_extrem.py — Episod meteo extrem: sub-cub zilnic pentru QGIS Temporal Controller
=========================================================================================
Extrage zilele unui episod (val de căldură, ciclon, viscol) ca NetCDF CF (strat temporal în QGIS)
și ca animație GIF. În QGIS: Layer Properties ▸ Temporal ▸ activați, apoi Temporal Controller.

Rulare:
  * OSGeo4W Shell:           python 12_episod_extrem.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\12_episod_extrem.py", encoding="utf-8").read())
    (în QGIS, rezultatele COG și GPKG se încarcă automat în proiect, în grupul „Zarr ANM”)

Cost estimat: câteva săptămâni pe toată țara: 9–18 chunk-uri (~50–100 MB).
Modificați DOAR secțiunea PARAMETRI. Rulați întâi 00_verificare_mediu.py.
"""
import importlib
import sys
from pathlib import Path

# Folderul cu zarr_clima.py (folosit în consola QGIS, unde __file__ nu există)
FOLDER = Path(__file__).resolve().parent if "__file__" in globals() else Path(r"C:\ClimaANM\clima")   # <-- doar pentru consola QGIS: folderul clima al programului
DATE_VECTOR = FOLDER.parent / "date"     # fișierele vectoriale ale programului (date/)
try:
    FOLDER = Path(__file__).resolve().parent
except NameError:
    pass
if str(FOLDER) not in sys.path:
    sys.path.insert(0, str(FOLDER))
import zarr_clima as zc  # noqa: E402
importlib.reload(zc)     # în QGIS: preia modificările din zarr_clima.py fără repornire

# ================================================================================================
# PARAMETRI
# ================================================================================================
VARIABILA = "max_temp"                                                         # <-- MODIFICABIL
START, SFARSIT = "2024-07-10", "2024-07-31"                                    # <-- MODIFICABIL
VMIN, VMAX = None, None           # limitele paletei (None = automat)              <-- MODIFICABIL
FPS = 4                           # cadre pe secundă în GIF                        <-- MODIFICABIL

# Zona analizei (alegeți UNA dintre variante):
ZONA = zc.Zona.tara()                                                   # toată țara
# ZONA = zc.Zona.dreptunghi(25.5, 44.0, 27.0, 45.0)                       # lon_min, lat_min, lon_max, lat_max
# ZONA = zc.Zona.poligoane(str(DATE_VECTOR / "ro_judete_poligon.gpkg"),
#                          coloana="name", valori=["Iași", "Vaslui"])          # fiecare județ separat  # coloana: vezi 00b_inspecteaza_vector.py
# ZONA = zc.Zona.poligoane(str(DATE_VECTOR / "ro_judete_poligon.gpkg"),
#                          coloana="name", valori=["Iași", "Vaslui"], unite=True)   # cele două = o singură zonă

IESIRI = dict(
    netcdf=True,   # NetCDF CF (pentru QGIS Temporal Controller); necesită netCDF4 sau h5netcdf
    cog=False,     # COG cu o bandă pe zi (alternativă la NetCDF)
    gif=True,      # animație GIF
    png=True,      # prima zi ca PNG
)

# Folderul rezultatelor și numele fișierelor
OUT = FOLDER / "rezultate"                                              # <-- MODIFICABIL
NUME = "12_episod"                                                         # <-- MODIFICABIL

# Contur pe hărțile PNG (opțional; poligoanele ZONA se desenează oricum):
zc.CONTUR_HARTI = str(DATE_VECTOR / "ro_frontiera_poligon.gpkg")   # <-- MODIFICABIL
# zc.CONTUR_HARTI = None                   # fără contur
# zc.CONTUR_HARTI = str(DATE_VECTOR / "ro_judete_poligon.gpkg")   # limitele județelor
# zc.CONTUR_HARTI = (r"C:\date\limite.gpkg", "tara")              # un strat anume dintr-un GPKG
# zc.CONTUR_GROSIME = 0.6                  # grosimea liniei

# Setări avansate (opțional):
# zc.PRAG_VALID = 0.90       # fracția minimă de zile valide per pixel și perioadă
# zc.ACCEPTA_PARTIAL = False # True = acceptă perioade care depășesc frontiera datelor

# ================================================================================================
# RULARE
# ================================================================================================
zc.ruleaza_episod(VARIABILA, START, SFARSIT, ZONA, IESIRI, OUT, NUME, VMIN, VMAX, FPS)
