# -*- coding: utf-8 -*-
"""
18_statistici_zonale.py — Statistici zilnice pe județe / regiuni + agregări lunare și sezoniere, pe perioada aleasă
=================================================================================================================
Înlocuiește într-un singur script cele două scripturi vechi (statistici_nc.py + statistici_anotimpuale.py), cu
datele luate direct din cubul Zarr (nu mai sunt necesare fișierele NetCDF anuale).

(1) SERIA ZILNICĂ pe fiecare zonă: pentru fiecare zi, minima, maxima și media pixelilor din poligon
      stats_{prefix}.csv  (toate variabilele)  și  stats_{prefix}_{variabila}.csv
(2) AGREGĂRILE seriei zilnice:
      stats_{prefix}_lunar_anual.csv          fiecare lună din fiecare an
      stats_{prefix}_lunar_multianual.csv     cele 12 luni, pe toată perioada
      stats_{prefix}_sezonier_anual.csv       DJF, MAM, JJA, SON pe fiecare an climatic (decembrie → iarna anului următor)
      stats_{prefix}_sezonier_multianual.csv  cele 4 anotimpuri, pe toată perioada
    min_absolut = cea mai mică valoare a unui pixel într-o zi; max_absolut = cea mai mare;
    media = media mediilor zilnice ale zonei; precip_cumulat = suma mediilor zilnice (doar precipitații, mm).

Zonele: un pixel aparține poligonului dacă centrul lui e în poligon; poligoanele mai mici decât un pixel se
rasterizează cu ALL_TOUCHED (ca în statistici_nc.py). Entitățile cu aceeași valoare în coloană se unesc
(ex. toate județele unei regiuni → o singură zonă „regiune”).

Rulare:
  * OSGeo4W Shell:           python 18_statistici_zonale.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\18_statistici_zonale.py", encoding="utf-8").read())

Cost: se citește toată țara, o singură dată pentru toate zonările: ≈ 0,2 GB pe an pentru o temperatură,
≈ 0,1 GB pe an pentru precipitații. 2020–2025 cu cele trei variabile ≈ 3 GB, de ordinul 10 min.
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
import zarr_clima as zc                 # noqa: E402
import zarr_statistici_zonale as zz     # noqa: E402
importlib.reload(zc)
importlib.reload(zz)                    # în QGIS: preia modificările fără repornire

# ================================================================================================
# PARAMETRI
# ================================================================================================
# 1. PERIOADA din care se extrag statisticile (început, sfârșit), inclusiv. Sfârșitul None = până la frontiera datelor.
PERIOADA = ("2020-01-01", "2025-12-31")                                        # <-- MODIFICABIL

# 2. VARIABILELE — oricare dintre: "precipitation", "max_temp", "min_temp", "tmedie" (= (Tmax + Tmin) / 2)
#    În CSV apar ca: precip, tmax, tmin, tmed (aceleași nume ca în scripturile vechi)
VARIABILE = ["precipitation", "max_temp", "min_temp"]                          # <-- MODIFICABIL

# 3. FIȘIERUL CU POLIGOANE și ZONĂRILE (fiecare zonare = o coloană din fișier)
FISIER = str(DATE_VECTOR / "ro_judete_poligon.gpkg")      # <-- MODIFICABIL
STRAT = None               # None dacă fișierul are un singur strat cu geometrie; altfel numele stratului   <-- MODIFICABIL
ZONARI = [
    #  prefix = în numele fișierelor;  eticheta = numele coloanei de entitate în CSV;  coloana = coloana din fișier
    dict(prefix="judete", eticheta="judet", coloana="name"),
    dict(prefix="regiuni", eticheta="regiune", coloana="region"),
    # dict(prefix="sud", eticheta="judet", coloana="name", valori=["Ilfov", "Giurgiu", "Călărași"]),   # doar câteva
]                                                                              # <-- MODIFICABIL

# 4. EXPORTURI
IESIRI = dict(
    zilnic_total=True,          # stats_{prefix}.csv            (toate variabilele, zi cu zi)
    zilnic_pe_variabila=True,   # stats_{prefix}_{variabila}.csv
    lunar_anual=True,
    lunar_multianual=True,
    sezonier_anual=True,
    sezonier_multianual=True,
)
FORMAT_CSV = "standard"    # "standard" = virgulă + punct zecimal (ca scripturile vechi); "ro" = ; + virgulă zecimală (Excel RO)   <-- MODIFICABIL

# Folderul rezultatelor (câte un subfolder pe perioadă)
OUT = FOLDER / "rezultate" / f"18_stats_{PERIOADA[0]}_{PERIOADA[1] or 'frontiera'}"   # <-- MODIFICABIL

# ================================================================================================
# RULARE
# ================================================================================================
fisiere = zz.ruleaza_statistici_zonale(FISIER, STRAT, ZONARI, VARIABILE, PERIOADA, IESIRI, OUT, FORMAT_CSV)
