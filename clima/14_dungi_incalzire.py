# -*- coding: utf-8 -*-
"""
14_dungi_incalzire.py — „Dungile încălzirii” (warming stripes) pe localitate sau pe județe
==========================================================================================
Seria mediilor anuale 1961–prezent pentru un punct sau pentru fiecare poligon + graficul de tip
Ed Hawkins (anomalia față de 1971–2000). GPKG: câte un câmp pe an (a1961 … a2025), pentru HTML Map Tip.

Rulare:
  * OSGeo4W Shell:           python 14_dungi_incalzire.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\14_dungi_incalzire.py", encoding="utf-8").read())
    (în QGIS, rezultatele COG și GPKG se încarcă automat în proiect, în grupul „Zarr ANM”)

Cost estimat: un punct sau un județ, 65 de ani ≈ 1,5–3 GB (~2,5–5 min).
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
VARIABILA = "max_temp"            # "max_temp", "min_temp", "tmedie"                <-- MODIFICABIL
ANI = (1961, 2025)                                                             # <-- MODIFICABIL
REFERINTA = (1971, 2000)          # baza culorilor                                  <-- MODIFICABIL

# Un punct SAU poligoane:                                                       <-- MODIFICABIL
ZONA = zc.Zona.punct(26.1025, 44.4268, nume="București")
# ZONA = zc.Zona.poligoane(str(DATE_VECTOR / "ro_judete_poligon.gpkg"), coloana="name")   # toate județele  # coloana: vezi 00b_inspecteaza_vector.py

IESIRI = dict(
    png=True,      # dungile încălzirii
    grafic=True,   # seria cu tendința
    gpkg=True,     # doar pentru poligoane: câte un câmp pe an
    csv=True,      # tabelul seriei
)

# Folderul rezultatelor și numele fișierelor
OUT = FOLDER / "rezultate"                                              # <-- MODIFICABIL
NUME = "14_dungi"                                                         # <-- MODIFICABIL

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
zc.ruleaza_dungi(VARIABILA, ANI, ZONA, IESIRI, OUT, NUME, ref=REFERINTA)
