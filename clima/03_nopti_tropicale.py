# -*- coding: utf-8 -*-
"""
03_nopti_tropicale.py — Nopți tropicale (Tmin > 20 °C): două decenii comparate
==============================================================================
Numărul mediu anual de nopți cu Tmin > 20 °C (ETCCDI: TR) în perioada recentă, minus aceeași
mărime în perioada de comparație. COG: diferența + cele două perioade. Paletă recomandată în QGIS: Magma/Inferno.

Rulare:
  * OSGeo4W Shell:           python 03_nopti_tropicale.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\03_nopti_tropicale.py", encoding="utf-8").read())
    (în QGIS, rezultatele COG și GPKG se încarcă automat în proiect, în grupul „Zarr ANM”)

Cost estimat: 2 × 10 ani ≈ 4 GB (~6 min) pentru toată țara; mult mai puțin pentru o zonă.
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
PRAG = 20.0                       # °C (Tmin > PRAG)                               <-- MODIFICABIL
ANI_RECENTI = (2016, 2025)                                                     # <-- MODIFICABIL
ANI_COMPARATIE = (1971, 1980)                                                  # <-- MODIFICABIL
SEZON = "anual"

# Zona analizei (alegeți UNA dintre variante):
ZONA = zc.Zona.tara()                                                   # toată țara
# ZONA = zc.Zona.dreptunghi(25.5, 44.0, 27.0, 45.0)                       # lon_min, lat_min, lon_max, lat_max
# ZONA = zc.Zona.poligoane(str(DATE_VECTOR / "ro_judete_poligon.gpkg"),
#                          coloana="name", valori=["Iași", "Vaslui"])          # fiecare județ separat  # coloana: vezi 00b_inspecteaza_vector.py
# ZONA = zc.Zona.poligoane(str(DATE_VECTOR / "ro_judete_poligon.gpkg"),
#                          coloana="name", valori=["Iași", "Vaslui"], unite=True)   # cele două = o singură zonă

# Ce rezultate se scriu (True / False):
IESIRI = dict(
    cog=True,      # GeoTIFF optimizat pentru cloud (raster pentru QGIS)
    png=True,      # harta PNG gata de prezentare
    grafic=True,   # graficul PNG (seria pe ani; pe zone, dacă ZONA are mai multe poligoane)
    gpkg=True,     # GeoPackage: statistici pe poligoane (dacă ZONA are poligoane), altfel centrele pixelilor
    csv=False,     # tabel CSV (separator ;, zecimale cu virgulă)
)
IESIRI["png_perioade"] = True     # PNG pentru fiecare deceniu

# Folderul rezultatelor și numele fișierelor
OUT = FOLDER / "rezultate"                                              # <-- MODIFICABIL
NUME = "03_nopti_tropicale"                                                         # <-- MODIFICABIL

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
IND = zc.indicator("zile_peste", var="min_temp", prag=PRAG, strict=True)
zc.ruleaza_anomalie(IND, ANI_RECENTI, ANI_COMPARATIE, SEZON, ZONA, IESIRI, OUT, NUME)
