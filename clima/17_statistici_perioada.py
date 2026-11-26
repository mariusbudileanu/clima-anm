# -*- coding: utf-8 -*-
"""
17_statistici_perioada.py — Media, minima, maxima (și suma) unui parametru pe o perioadă, per pixel → GeoTIFF
=============================================================================================================
Statisticile se calculează din TOATE zilele perioadei alese, pixel cu pixel. Exemple:
  * PERIOADA 2006–2025, temperatura maximă:  „medie” = media celor ~7300 de valori zilnice ale fiecărui pixel;
    „minima” = cea mai mică Tmax zilnică din cei 20 de ani; „maxima” = cea mai mare Tmax zilnică din cei 20 de ani.
  * PERIOADA 2006–2025, precipitații:  „suma” = totalul celor 20 de ani (mm); „suma_medie_anuala” = mm pe an,
    în medie; „medie” = mm pe zi; „maxima” = cea mai ploioasă zi (mm în 24 h).
  * cu SEZON = "JJA": doar zilele de vară din perioadă (iar „suma_medie_anuala” devine „suma medie pe vară”).

Implicit rulează pe TOATĂ grila cubului (483 × 972 pixeli, 0,01°); pixelii din afara țării rămân NoData.
Un pixel primește valoare doar dacă are date valide în cel puțin 90 % din zilele perioadei (zc.PRAG_VALID).

Rezultate (în OUT):
  * {NUME}.tif              COG cu câte o bandă pe statistică (numele benzilor: în proprietățile stratului)
  * {NUME}_{statistica}.tif câte un COG pe statistică
  * {NUME}_{statistica}.png hărți de control; {NUME}_rezumat.csv = min / medie / max pe hartă

Rulare:
  * OSGeo4W Shell:           python 17_statistici_perioada.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\17_statistici_perioada.py", encoding="utf-8").read())
    (în QGIS, tif-urile se încarcă automat în proiect, în grupul „Zarr ANM”)

Cost (toată țara): ≈ 0,2 GB pe an pentru o temperatură, ≈ 0,1 GB pe an pentru precipitații
(„tmedie” citește ambele temperaturi: dublu). 20 de ani de Tmax ≈ 4 GB, de ordinul 10–20 min, în funcție de rețea.
Memoria folosită nu crește cu lungimea perioadei (datele se citesc pe blocuri de ~90 de zile).
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
import zarr_clima as zc        # noqa: E402
import zarr_statistici as zs   # noqa: E402
importlib.reload(zc)
importlib.reload(zs)           # în QGIS: preia modificările fără repornire

# ================================================================================================
# PARAMETRI
# ================================================================================================

# 1. PARAMETRUL — lăsați necomentată O SINGURĂ linie
PARAMETRU = "max_temp"           # temperatura maximă zilnică                                     <-- MODIFICABIL
# PARAMETRU = "min_temp"         # temperatura minimă zilnică
# PARAMETRU = "tmedie"           # temperatura medie zilnică = (Tmax + Tmin) / 2
# PARAMETRU = "precipitation"    # precipitații

# 2. PERIOADA (început, sfârșit), inclusiv. Sfârșitul None = până la frontiera datelor.
PERIOADA = ("2006-01-01", "2025-12-31")                                        # <-- MODIFICABIL

# 3. SEZONUL: None = toate zilele perioadei; sau doar anumite zile din fiecare an:
SEZON = None               # "DJF", "MAM", "JJA", "SON", (4, 9) = aprilie–septembrie, ("06-15", "08-15")   <-- MODIFICABIL

# 4. STATISTICILE — None = implicit: medie, minima, maxima (temperaturi);
#                                    suma, suma_medie_anuala, medie, maxima (precipitații)
STATISTICI = None                                                              # <-- MODIFICABIL
# STATISTICI = ["medie", "minima", "maxima"]
# Disponibile: "medie", "minima", "maxima", "suma", "suma_medie_anuala", "abatere_standard", "amplitudine", "zile_valide"

# 5. ZONA — implicit toată grila cubului
ZONA = zc.Zona.tara()                                                          # <-- MODIFICABIL
# ZONA = zc.Zona.dreptunghi(25.5, 44.0, 27.0, 45.0)                           # lon_min, lat_min, lon_max, lat_max
# ZONA = zc.Zona.poligoane(DATE_VECTOR / "ro_judete_poligon.gpkg", coloana="name", valori=["Iași"])
# ZONA = zc.Zona.poligoane(DATE_VECTOR / "ro_judete_poligon.gpkg", coloana="name",
#                          valori=["Iași", "Vaslui"], unite=True)             # două județe = o singură zonă
DECUPARE = "masca"         # cu poligoane: "masca" = NoData în afara poligoanelor; "dreptunghi" = tot dreptunghiul lor   <-- MODIFICABIL

# 6. EXPORTURI
IESIRI = dict(
    cog_multibanda=True,   # un singur tif, câte o bandă pe statistică
    tif_separate=True,     # câte un tif pe statistică
    png=True,              # hărți de control
    csv=True,              # rezumatul: min / medie / max pe hartă, pentru fiecare statistică
)

# Folderul rezultatelor și numele fișierelor
OUT = FOLDER / "rezultate"                                                     # <-- MODIFICABIL
_sez = "" if SEZON in (None, "anual") else "_" + (SEZON if isinstance(SEZON, str) else "-".join(map(str, SEZON)))
NUME = f"17_{PARAMETRU}_{PERIOADA[0][:4]}_{(PERIOADA[1] or 'frontiera')[:4]}{_sez}"   # <-- MODIFICABIL

# Setări avansate (opțional):
# zc.PRAG_VALID = 0.90     # fracția minimă de zile valide per pixel
zc.CONTUR_HARTI = str(DATE_VECTOR / "ro_frontiera_poligon.gpkg")               # None = fără contur  <-- MODIFICABIL

# ================================================================================================
# RULARE
# ================================================================================================
rezultat = zs.ruleaza_statistici(PARAMETRU, PERIOADA, SEZON, STATISTICI, ZONA, DECUPARE, IESIRI, OUT, NUME)
