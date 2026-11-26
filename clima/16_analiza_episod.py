# -*- coding: utf-8 -*-
"""
16_analiza_episod.py — Analiza generică a unei perioade sau a unui episod excepțional
===================================================================================
Alegeți parametrul (temperatura maximă / minimă / medie sau precipitațiile), perioada, referința
anomaliei și zona (un punct, un poligon sau mai multe). Scriptul produce:

  STATISTICI     min, max, medie (temperaturi) sau suma, media zilnică, zilele ploioase (precipitații),
                 anomalia față de referința aleasă: climatologie, un an, o lună sau o perioadă oarecare
  RARITATE       (1) rangul pe aceeași fereastră calendaristică în toți anii din 1961
                 (2) locul între TOATE episoadele de aceeași lungime, oricând în an
                 (3) perioada de revenire (Gumbel, orientativ)
                 (4) cel mai lung șir de zile ploioase / zile peste p90 (temperaturi), față de recorduri
                 (5) ziua extremă față de recordul absolut și al lunii; zile peste p95 / p99
                 (6) echivalențe: % din normala lunii și a anului, „câte zile normale de ploaie”
  CONTEXT        (7) cele 30 / 60 / 90 de zile dinainte (sol deja saturat? perioadă deja caldă?)
                 (10) celelalte variabile în episod (ex. ploaie rece sau caldă? amplitudinea diurnă)
                 (13) comparația cu alte episoade (automat: top 3 istoric; plus cele alese de voi)
                 (14) cât de des apar episoade similare: număr pe an, mediile pe decenii, tendința
  SPAȚIAL        (8) hărți: suma / media, minima, maxima, normala, anomalia, %, zile ploioase,
                     rangul istoric PER PIXEL (unde a fost record), cu punctul marcat
                 (9) extinderea: ce fracție din teritoriu a depășit pragurile / a avut record
                 (12) animația GIF zi cu zi (ziua + cumulul)
                 (11) calendarul zi × an (tot istoricul), cu episodul încadrat
  EXPORTURI      PNG, GIF, CSV, COG multi-bandă, GPKG (punct sau poligoane), raport .md + .json,
                 FIȘA INTERACTIVĂ .html (un singur fișier: hărți cu glisor pe zile, grafice, tabel pe zone, raport)

Rulare:
  * OSGeo4W Shell:           python 16_analiza_episod.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\16_analiza_episod.py", encoding="utf-8").read())

Cost la prima rulare (o variabilă):
  * seria zonei pe tot istoricul: ca scriptul 15 (≈ 13 GB temperaturi / ≈ 5,4 GB precipitații pentru toată
    țara; pentru un punct ≈ 1,6 GB) — se păstrează în rezultate/cache_serii, comun cu scriptul 15;
  * hărțile: fereastra episodului în fiecare an (~65 de ferestre scurte, ≈ 0,2–2 GB) — în rezultate/cache_episod;
  * contextul (alte variabile): ferestrele anilor climatologici (≈ 0,1–1 GB).
Rulările următoare (alte grafice, altă referință, aceeași fereastră) durează câteva secunde.
Modificați DOAR secțiunea PARAMETRI. Rulați întâi 00_verificare_mediu.py.
"""
import importlib
import sys
from pathlib import Path

# Folderul cu zarr_clima.py și zarr_episod.py (folosit în consola QGIS, unde __file__ nu există)
FOLDER = Path(__file__).resolve().parent if "__file__" in globals() else Path(r"C:\ClimaANM\clima")   # <-- doar pentru consola QGIS: folderul clima al programului
DATE_VECTOR = FOLDER.parent / "date"     # fișierele vectoriale ale programului (date/)
try:
    FOLDER = Path(__file__).resolve().parent
except NameError:
    pass
if str(FOLDER) not in sys.path:
    sys.path.insert(0, str(FOLDER))
import zarr_clima as zc    # noqa: E402
import zarr_episod as ze   # noqa: E402
importlib.reload(zc)
importlib.reload(ze)       # în QGIS: preia modificările fără repornire

# ================================================================================================
# PARAMETRI
# ================================================================================================

# 1. PARAMETRUL — lăsați necomentată O SINGURĂ linie
PARAMETRU = "precipitation"      # precipitații: suma, media zilnică, min, max, zile ploioase   <-- MODIFICABIL
# PARAMETRU = "max_temp"         # temperatura maximă zilnică
# PARAMETRU = "min_temp"         # temperatura minimă zilnică
# PARAMETRU = "tmedie"           # temperatura medie = (Tmax + Tmin) / 2

# 2. PERIOADA analizată (început, sfârșit). Sfârșitul None = până la frontiera datelor.
#    Dacă depășește frontiera last_*_time, se taie automat (cu avertisment).
PERIOADA = ("2026-10-09", "2026-10-15")                                        # <-- MODIFICABIL

# 3. REFERINȚA anomaliei — lăsați necomentată O SINGURĂ linie
REFERINTA = ("climatologie", 1991, 2020)     # media aceleiași ferestre calendaristice în 1991–2020   <-- MODIFICABIL
# REFERINTA = ("an", 2005)                   # aceeași fereastră într-un an anume
# REFERINTA = ("luna", "2025-10")            # o lună (precipitațiile se aduc la lungimea episodului)
# REFERINTA = ("perioada", "2025-10-01", "2025-10-20")   # o perioadă oarecare (idem)

# Climatologia folosită pentru percentile, praguri, normale și ranguri relative (nu se schimbă des)
CLIMATOLOGIE = (1991, 2020)                                                    # <-- MODIFICABIL

# 4. ZONA DE ANALIZĂ (serii, raritate, context) — lăsați necomentată O SINGURĂ variantă
ZONA = zc.Zona.punct(26.1025, 44.4268, nume="București")                     # un punct (pixelul cel mai apropiat) <-- MODIFICABIL
# ZONA = zc.Zona.dreptunghi(25.95, 44.33, 26.25, 44.54, nume="București (dreptunghi)")
# ZONA = zc.Zona.poligoane(DATE_VECTOR / "ro_judete_poligon.gpkg", coloana="name", valori=["Ilfov"])   # un județ
# ZONA = zc.Zona.poligoane(DATE_VECTOR / "ro_judete_poligon.gpkg", coloana="name",
#                          valori=["Ilfov", "Giurgiu"], unite=True)           # două județe = o singură zonă
# ZONA = zc.Zona.poligoane(DATE_VECTOR / "ro_judete_poligon.gpkg", coloana="name")   # toate județele: tabel + GPKG pe județe
#   coloana = coloana cu numele zonelor (vezi 00b_inspecteaza_vector.py); majusculele și diacriticele nu contează
ZONA_ANALIZA = None    # cu mai multe poligoane: numele zonei analizate în detaliu; None = media tuturor   <-- MODIFICABIL

# Zona HĂRȚILOR (8, 9, 12) — de obicei toată țara; punctul de analiză apare marcat cu o stea
HARTI_ZONA = zc.Zona.tara()                                                    # <-- MODIFICABIL
# HARTI_ZONA = zc.Zona.dreptunghi(24.5, 43.6, 28.0, 45.6)   # doar sudul țării (mai rapid)

# 5. Opțiuni ale analizei
SENS = "auto"              # temperaturi: "auto" (după semnul anomaliei), "mare" (episod cald), "mic" (episod rece) <-- MODIFICABIL
PRAG_ZI_PLOIOASA = 1.0     # mm: zi ploioasă (șiruri, zile ploioase, percentile pe zilele ploioase)          <-- MODIFICABIL
ZILE_ANTERIOARE = (30, 60, 90)   # contextul anterior episodului                                               <-- MODIFICABIL
MIN_ZILE_SIR = 5           # (14) un „șir lung” are cel puțin atâtea zile                                      <-- MODIFICABIL
PRAGURI_EXTINDERE = None   # (9) None = implicit: (150, 200, 300) % precipitații; ±(2, 4, 6) °C temperaturi    <-- MODIFICABIL
TOP_N = 10                 # câte episoade / șiruri istorice în clasamente                                    <-- MODIFICABIL
FPS_GIF = 2                # cadre pe secundă în animație                                                     <-- MODIFICABIL

# (13) Episoade de comparat: (eticheta, data de început); lungimea = lungimea episodului analizat
EPISOADE_COMPARATIE = [
    # ("Inundațiile din 2005", "2005-08-20"),
    # ("Septembrie 2023", "2023-09-04"),
]                                                                              # <-- MODIFICABIL

# 6. ANALIZELE dorite (True / False)
ANALIZE = dict(
    rang_fereastra=True,     # (1)
    top_episoade=True,       # (2)
    gumbel=True,             # (3)
    siruri=True,             # (4)
    zile_episod=True,        # (5) graficul zilnic al episodului + pragurile p95 / p99
    context_anterior=True,   # (7)
    harti=True,              # (8)
    extindere=True,          # (9)
    context=True,            # (10) citește și celelalte variabile
    calendar=True,           # (11)
    gif=True,                # (12)
    comparatii=True,         # (13)
    frecventa=True,          # (14)
)

# 7. EXPORTURI
IESIRI = dict(
    csv=True,       # tabelele fiecărei analize + seria zilnică a episodului
    cog=True,       # GeoTIFF multi-bandă: statistica, min, max, normala, anomalia, %, zile ploioase, rangul
    gpkg=True,      # punctul (cu rezultatele în atribute) sau poligoanele (episod, normală, anomalie, %, rang)
    raport=True,    # raport .md (frazele-cheie gata de folosit) + .json (toate cifrele)
    html=True,      # FIȘA INTERACTIVĂ: un singur fișier .html (hărți, glisor pe zile, grafice, tabel pe zone, raport)
)
HTML_REZOLUTIE = 1   # 1 = hărțile din fișă la 0,01° (≈ 6–15 MB); 2 = la 0,02° (≈ 4× mai mic); 3 = la 0,03°   <-- MODIFICABIL

# Contur pe hărțile PNG
zc.CONTUR_HARTI = str(DATE_VECTOR / "ro_frontiera_poligon.gpkg")              # None = fără contur  <-- MODIFICABIL

# Folderul rezultatelor și prefixul fișierelor
OUT = FOLDER / "rezultate"                                                     # <-- MODIFICABIL
NUME = None     # None = automat: 16_<parametru>_<data de început>                         # <-- MODIFICABIL

# Setări avansate (opțional):
# zc.DPI = 200

zc.parametri_externi(globals())   # pornit din interfață: parametrii vin din formular

# ================================================================================================
# RULARE
NUME = NUME or f"16_{PARAMETRU}_{PERIOADA[0]}"
# ================================================================================================
rezultat = ze.analizeaza(PARAMETRU, PERIOADA, REFERINTA, CLIMATOLOGIE, ZONA, ZONA_ANALIZA, HARTI_ZONA, IESIRI, ANALIZE,
                         OUT, NUME, PRAG_ZI_PLOIOASA=PRAG_ZI_PLOIOASA, SENS=SENS, ZILE_ANTERIOARE=ZILE_ANTERIOARE,
                         EPISOADE_COMPARATIE=EPISOADE_COMPARATIE, MIN_ZILE_SIR=MIN_ZILE_SIR,
                         PRAGURI_EXTINDERE=PRAGURI_EXTINDERE, TOP_N=TOP_N, FPS_GIF=FPS_GIF, HTML_FACTOR=HTML_REZOLUTIE)
