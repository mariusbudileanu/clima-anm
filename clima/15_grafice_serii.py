# -*- coding: utf-8 -*-
"""
15_grafice_serii.py — Serii de timp pe zone: grafice complexe (zilnic, anual, pe zone, dungi, lunar, hartă)
==========================================================================================================
Pentru fiecare zonă (județ, UAT, bazin, sau un punct), datele zilnice se reduc la seria zilnică medie a
zonei. Din aceste serii se construiesc:

  serie_zilnica    seria zilnică pe o fereastră + climatologia de referință (medie, p10–p90), golurile NaN,
                   frontiera last_*_time și (opțional) zilele pre-alocate 0,0 de după ea; panoul B: abaterea
                   zilnică (temperaturi) sau precipitațiile cumulate față de climatologie
  serii_anuale     toate zonele pe un grafic: zonele de detaliu colorate, totalul cu media mobilă pe 11 ani
  multiple_mici    câte un mini-grafic pe zonă, aceeași scară, cu tendința și semnificația ei
  bare_zone        3 panouri aliniate: media perioadei recente · anomalia față de referință · tendința (±ns)
  dungi_zone       „dungile încălzirii” pentru toate zonele (rânduri = zone, coloane = ani)
  dungi_detaliu    dungile clasice + barele anomaliei anuale + media mobilă, pentru fiecare zonă de detaliu
  anomalii_lunare  harta termică an × lună a anomaliilor + ciclul anual (referință vs. ultimii 10 ani)
  harta_zone       hartă coropletă pe poligoane: tendința (hașurat = nesemnificativ), media sau anomalia

Seriile zonale se păstrează în cache (rezultate/cache_serii): prima rulare citește datele (cost mai jos),
rulările următoare — alte grafice, alte zone de detaliu, alte ferestre — durează câteva secunde.

Rulare:
  * OSGeo4W Shell:           python 15_grafice_serii.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\15_grafice_serii.py", encoding="utf-8").read())

Cost la prima rulare (toată țara, o variabilă): 1961–2025 ≈ 13 GB (~20–25 min); „tmedie” ≈ dublu;
precipitațiile ≈ 5,4 GB (~8 min). Costul nu depinde de numărul de județe.
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

# Variabila: "max_temp", "min_temp", "tmedie" = (Tmax + Tmin)/2, "precipitation" (sume anuale/lunare)
VARIABILA = "max_temp"                                                         # <-- MODIFICABIL
ANI = (1961, 2025)                # seriile anuale, tendințele, dungile (doar ani compleți)   <-- MODIFICABIL
REFERINTA = (1971, 2000)          # baza anomaliilor, a dungilor și a climatologiei zilnice   <-- MODIFICABIL
PERIOADA_RECENTA = (2016, 2025)   # „media recentă” și anomalia ei, în graficul cu bare       <-- MODIFICABIL

# Zona: poligoanele (fiecare valoare a coloanei = o serie)                     # coloana: vezi 00b_inspecteaza_vector.py
ZONA = zc.Zona.poligoane(DATE_VECTOR / "ro_judete_poligon.gpkg", coloana="name")                      # <-- MODIFICABIL
# ZONA = zc.Zona.poligoane(DATE_VECTOR / "ro_judete_poligon.gpkg", coloana="name",
#                          valori=["Iași", "Vaslui", "Neamț"])                 # doar câteva județe
# ZONA = zc.Zona.punct(26.1025, 44.4268, nume="București")                  # un singur punct (fără grafice „pe zone”)
NUME_TOTAL = "România (toate zonele)"   # numele seriei care reunește toate zonele             <-- MODIFICABIL

# Zonele de detaliu (serie zilnică, dungi clasice, anomalii lunare, colorate în seriile anuale).
# Numele din coloana aleasă în ZONA (majusculele și diacriticele nu contează: „iasi” = „Iași”).
ZONE_DETALIU = ["Iași", "Constanța", "Cluj"]                                  # <-- MODIFICABIL
INCLUDE_TOTALUL_LA_DETALIU = True       # adaugă și seria NUME_TOTAL la graficele de detaliu    <-- MODIFICABIL

# Seria zilnică
FEREASTRA_ZILNICA = ("2025-01-01", None)   # (început, sfârșit); None = până la frontiera datelor <-- MODIFICABIL
ZILE_DUPA_FRONTIERA = 0                    # > 0 = arată și zilele pre-alocate (0,0): capcana 2050 <-- MODIFICABIL

# Graficele dorite (True / False)
GRAFICE = dict(
    serie_zilnica=True,
    serii_anuale=True,
    multiple_mici=True,
    bare_zone=True,
    dungi_zone=True,
    dungi_detaliu=True,
    anomalii_lunare=True,
    harta_zone=True,
)
SORTARE_DUNGI = "tendinta"     # ordinea rândurilor: "tendinta", "medie", "lat" (nord → sud), "nume"   <-- MODIFICABIL
HARTA_VALOARE = "tendinta"     # harta pe zone: "tendinta", "medie", "anomalie"                         <-- MODIFICABIL
ALFA = 0.05                    # pragul de semnificație al tendinței                                   <-- MODIFICABIL

# Tabele
IESIRI = dict(
    csv=True,      # seriile anuale (an × zone) + statisticile pe zone
    gpkg=True,     # poligoanele cu media, anomalia, tendința, p și câte un câmp pe an (a1961 … a2025)
)

# Contur pe hărțile PNG (frontiera țării; poligoanele zonei se desenează oricum)
zc.CONTUR_HARTI = str(DATE_VECTOR / "ro_frontiera_poligon.gpkg")              # None = fără contur  <-- MODIFICABIL
# zc.CONTUR_GROSIME = 0.6

# Folderul rezultatelor și numele fișierelor
OUT = FOLDER / "rezultate"                                                     # <-- MODIFICABIL
NUME = f"15_{VARIABILA}"                                                       # <-- MODIFICABIL

# Setări avansate (opțional):
# zc.PRAG_VALID = 0.90       # fracția minimă de zile valide pentru un an (la fel pentru lună: 0,8)
# zc.DPI = 200               # rezoluția imaginilor

# ================================================================================================
# RULARE
# ================================================================================================
detaliu = list(ZONE_DETALIU) + ([NUME_TOTAL] if INCLUDE_TOTALUL_LA_DETALIU else [])
zc.ruleaza_serii(VARIABILA, ANI, REFERINTA, PERIOADA_RECENTA, ZONA, GRAFICE, IESIRI, OUT, NUME,
                 detaliu=detaliu, fereastra=FEREASTRA_ZILNICA, zile_dupa=ZILE_DUPA_FRONTIERA,
                 sortare=SORTARE_DUNGI, harta_valoare=HARTA_VALOARE, total_nume=NUME_TOTAL, alfa=ALFA)
