# -*- coding: utf-8 -*-
"""
13_atlas_zonal.py — Atlas climatic pe UAT-uri sau bazine hidrografice
=====================================================================
Pentru fiecare poligon al stratului: media mai multor indicatori, scrisă în tabela de atribute.
Toți indicatorii se calculează din aceeași citire a datelor. Rezultatul (GPKG) se folosește în QGIS
cu Graduated Symbology / legendă bivariată și cu Atlas (Print Layout) pentru fișe PDF pe UAT.

Rulare:
  * OSGeo4W Shell:           python 13_atlas_zonal.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\13_atlas_zonal.py", encoding="utf-8").read())
    (în QGIS, rezultatele COG și GPKG se încarcă automat în proiect, în grupul „Zarr ANM”)

Cost estimat: depinde de zonă: un județ, un an ≈ 0,1–0,3 GB; toată țara, un an ≈ 0,6 GB.
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
ANI = (2016, 2025)                                                             # <-- MODIFICABIL
SEZON = "anual"
# Câmpurile tabelei: {nume_câmp: indicator}                                       <-- MODIFICABIL
INDICATORI = {
    "tmed_C": zc.indicator("tmedie"),
    "prec_mm_an": zc.indicator("suma", var="precipitation"),
    "zile_trop": zc.indicator("zile_peste", var="max_temp", prag=30),
    "nopti_trop": zc.indicator("zile_peste", var="min_temp", prag=20, strict=True),
}

# Stratul de poligoane (obligatoriu pentru atlas):                              <-- MODIFICABIL
ZONA = zc.Zona.poligoane(str(DATE_VECTOR / "ro_judete_poligon.gpkg"),
                         coloana="name")                                     # toate județele  # coloana: vezi 00b_inspecteaza_vector.py
# ZONA = zc.Zona.poligoane(r"C:\date\uat.gpkg", coloana="name", valori=["Iași", "Tomești", "Ciurea"])   # câteva UAT-uri

# Ce rezultate se scriu (True / False):
IESIRI = dict(
    cog=True,      # GeoTIFF optimizat pentru cloud (raster pentru QGIS)
    png=True,      # harta PNG gata de prezentare
    grafic=True,   # graficul PNG (seria pe ani; pe zone, dacă ZONA are mai multe poligoane)
    gpkg=True,     # GeoPackage: statistici pe poligoane (dacă ZONA are poligoane), altfel centrele pixelilor
    csv=False,     # tabel CSV (separator ;, zecimale cu virgulă)
)

# Folderul rezultatelor și numele fișierelor
OUT = FOLDER / "rezultate"                                              # <-- MODIFICABIL
NUME = "13_atlas"                                                         # <-- MODIFICABIL

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
# coduri unice pentru indicatorii de același tip
for camp, ind in INDICATORI.items():
    ind.cod = camp
zc.ruleaza_atlas(INDICATORI, ANI, SEZON, ZONA, IESIRI, OUT, NUME)
