# -*- coding: utf-8 -*-
"""
motoare.py — MOTOARELE de analiză (ce se face cu indicatorii)
=============================================================
Un motor = un tip de analiză (hartă medie, anomalie, tendință…), cu:
  * câmpurile lui de formular (cele comune — zonă, ieșiri, contur, prag de validitate — sunt definite o singură dată aici);
  * funcția de rulare (apelează nucleul zarr_clima);
  * exportul într-un script Python echivalent (pentru cine vrea codul, sau pentru curs).

Rețetele din retete/*.json aleg un motor, indicatorii și valorile implicite. O analiză nouă = o rețetă nouă,
nu un script nou.
"""
from __future__ import annotations

import json
from pathlib import Path

import indicatori as ri
import zarr_clima as zc

# =====================================================================================
# Câmpuri comune (definite o singură dată)
# =====================================================================================
IESIRI_HARTA = {"cog": "GeoTIFF (COG)", "png": "hartă PNG", "grafic": "grafic PNG (seria pe ani)",
                "gpkg": "GeoPackage", "csv": "tabel CSV"}


def camp_zona(nume="ZONA", eticheta="Zona analizei", forme=("tara", "dreptunghi", "poligoane"), implicit=None):
    return {"nume": nume, "tip": "zona", "eticheta": eticheta, "forme": list(forme),
            "implicit": implicit or {"tip": forme[0]}}


def camp_iesiri(optiuni=None, implicit=None):
    optiuni = optiuni or IESIRI_HARTA
    return {"nume": "IESIRI", "tip": "bife", "eticheta": "Rezultate", "optiuni": optiuni,
            "implicit": implicit or {k: k != "csv" for k in optiuni}}


def camp_indicatori(nume="INDICATORI", eticheta="Indicatori", maxim=None):
    return {"nume": nume, "tip": "indicatori", "eticheta": eticheta, "maxim": maxim}


CAMP_SEZON = {"nume": "SEZON", "tip": "sezon", "eticheta": "Sezonul", "implicit": "anual"}
SETARI_AVANSATE = [
    {"nume": "CONTUR_HARTI", "tip": "vector_optional", "setare": True, "eticheta": "Contur pe hărțile PNG",
     "implicit": "date/ro_frontiera_poligon.gpkg", "sectiune": "avansat"},
    {"nume": "RELIEF_HARTI", "tip": "bifa", "setare": True, "eticheta": "Relieful (umbrire) sub hărțile PNG",
     "implicit": True, "sectiune": "avansat", "ajutor": "din DEM-ul coregistrat (date/dem_grila_zarr.tif), dacă există"},
    {"nume": "PRAG_VALID", "tip": "numar", "setare": True, "eticheta": "Fracția minimă de zile valide per pixel",
     "implicit": 0.9, "min": 0.5, "max": 1, "pas": 0.05, "sectiune": "avansat",
     "ajutor": "un pixel cu mai puține zile valide în perioadă devine NoData (ex. golul de date din aprilie–mai 2026)"},
    {"nume": "ACCEPTA_PARTIAL", "tip": "bifa", "setare": True, "eticheta": "Acceptă perioade incomplete",
     "implicit": False, "sectiune": "avansat",
     "ajutor": "implicit, un an / sezon care depășește frontiera datelor e exclus (media ar fi falsă)"},
]

# =====================================================================================
# Registrul motoarelor
# =====================================================================================
MOTOARE: dict[str, dict] = {}


def motor(cod, titlu, descriere, campuri, exporta, nume=None, setari=None, titlu_rulare=None):
    """nume: funcție(parametri) → prefixul fișierelor (implicit: id-ul rețetei); setari: setările avansate ale motorului;
    titlu_rulare: funcție(parametri JSON) → titlul a ceea ce calculează efectiv rularea (folder, istoric, fișe)."""
    def dec(f):
        MOTOARE[cod] = {"cod": cod, "titlu": titlu, "descriere": descriere,
                        "campuri": campuri + (SETARI_AVANSATE if setari is None else setari),
                        "ruleaza": f, "exporta": exporta, "nume": nume, "titlu_rulare": titlu_rulare}
        return f
    return dec


def _sufix_sezon(sez):
    if sez in (None, "anual"):
        return ""
    if isinstance(sez, str):
        return f"_{sez}"
    a, b = sez
    return f"_l{a}-{b}" if isinstance(a, int) else f"_{a}_{b}".replace("-", "")


def _nume_ani(p, rid, cheie_ani="ANI"):
    """Prefixul fișierelor: rețeta + (indicatorul, dacă e unul singur) + anii + sezonul.
    Două rulări cu parametri diferiți nu se mai suprascriu (auditul 3.2); aceeași rulare repetată, da."""
    ind = p.get("INDICATORI") or []
    cod = f"_{ri.din_dict(ind[0]).cod}" if len(ind) == 1 else ""
    if cod and cod[1:] in rid:                           # „08_ariditate_de_martonne” + „de_martonne”: fără repetiție
        cod = ""
    a = p[cheie_ani]
    return f"{rid}{cod}_{a[0]}-{a[1]}{_sufix_sezon(p.get('SEZON'))}"


def _indicatori(p, cheie="INDICATORI", unul=False):
    lista = p.get(cheie) or []
    if isinstance(lista, dict):
        lista = [lista]
    if not lista:
        raise ValueError("Alegeți cel puțin un indicator.")
    if unul and len(lista) > 1:
        raise ValueError("Acest motor folosește un singur indicator.")
    ind = ri.coduri_unice([ri.din_dict(d) for d in lista])
    sezon = p.get("SEZON", "anual")
    for d in lista:
        if ri.REGISTRU[d["cod"]].sezon_anual and sezon != "anual":
            raise ValueError(f"Indicatorul „{ri.REGISTRU[d['cod']].titlu}” cere sezonul „anual” (are {sezon!r}).")
    return ind[0] if unul else ind


# ---------------------------------------------------------------------- export în Python
_RADACINA_EXPORT = None      # setată de _antet_py: căile din interiorul programului devin RADACINA / "…"


def _py_cale(v):
    """O cale: relativă la RADACINA dacă e în folderul programului (scriptul rămâne portabil), altfel absolută."""
    if v is None:
        return "None"
    p = Path(str(v))
    if _RADACINA_EXPORT is not None:
        try:
            rel = p.resolve().relative_to(Path(_RADACINA_EXPORT).resolve())
            return "RADACINA / " + repr(rel.as_posix())
        except ValueError:
            pass
    return repr(str(v))


def _py(v):
    """Valoare Python lizibilă (tupluri pentru perioade, r"…" pentru căi Windows)."""
    if isinstance(v, (list, tuple)):
        return "(" + ", ".join(_py(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    return repr(v)


def _py_zona(z: dict):
    alt = z.get("altitudine") or [None, None]
    _n = lambda v: None if v in (None, "") else float(v)  # noqa: E731
    sufix = (f".cu_altitudine({_n(alt[0])}, {_n(alt[1])})"
             if z.get("tip") != "punct" and (_n(alt[0]) is not None or _n(alt[1]) is not None) else "")
    return _py_zona_baza(z) + sufix


def _py_zona_baza(z: dict):
    t = z.get("tip", "tara")
    nume = f", nume={z['nume']!r}" if z.get("nume") else ""
    if t == "tara":
        return f"zc.Zona.tara({nume[2:]})"
    if t == "dreptunghi":
        limite = [float(z[k]) for k in ("lon_min", "lat_min", "lon_max", "lat_max")]
        return f"zc.Zona.dreptunghi({', '.join(map(repr, limite))}{nume})"
    if t == "punct":
        return f"zc.Zona.punct({float(z['lon'])!r}, {float(z['lat'])!r}{nume})"
    extra = "".join(f", {k}={_py(z[k])}" for k in ("coloana", "valori", "strat") if z.get(k))
    extra += ", unite=True" if z.get("unite") else ""
    return f"zc.Zona.poligoane({_py_cale(z['fisier'])}{extra}{nume})"


def _py_indicator(d: dict):
    d = dict(d); cod = d.pop("cod")
    return f"zc.indicator({cod!r}, **{d!r})"


def _antet_py(job, setari):
    global _RADACINA_EXPORT
    _RADACINA_EXPORT = job.get("_radacina")
    linii = [
        "# -*- coding: utf-8 -*-",
        repr(str(job.get("titlu", job["motor"])) + " — script generat de Clima ANM."),
        "# Rulare, din folderul programului:  instrumente\\pixi.exe run python <calea acestui fișier>",
        "# Dacă mutați programul în alt folder, schimbați doar RADACINA de mai jos.",
        "import sys",
        "from pathlib import Path",
        "",
        f"RADACINA = Path({_RADACINA_EXPORT!r})",
        'sys.path.insert(0, str(RADACINA / "clima"))',
        "import zarr_clima as zc  # noqa: E402",
        "",
    ]
    for k, v in setari.items():
        linii.append(f"zc.{k} = {_py_cale(v) if k == 'CONTUR_HARTI' else _py(v)}")
    return linii


# =====================================================================================
# Motorul HARTĂ — media pe ani a unuia sau mai multor indicatori
# =====================================================================================
def _exporta_harta(job, p, setari):
    l = _antet_py(job, setari)
    l += ["", "INDICATORI = ["] + [f"    {_py_indicator(d)}," for d in p["INDICATORI"]] + ["]"]
    l += [f"ZONA = {_py_zona(p['ZONA'])}",
          f"zc.ruleaza_harta(INDICATORI, {_py(p['ANI'])}, {_py(p['SEZON'])}, ZONA, {_py(p['IESIRI'])},",
          f"                 {_py_cale(p['OUT'])}, {p['NUME']!r}" +
          (f", clase={_py(p['CLASE'])}" if p.get("CLASE") else "") + ")"]
    return "\n".join(l) + "\n"


@motor("harta", "Hartă — media pe ani", "Media anuală a unuia sau mai multor indicatori, per pixel, pe un interval de ani.",
       [camp_indicatori(),
        {"nume": "ANI", "tip": "interval_ani", "eticheta": "Anii (media)", "implicit": [2016, 2025]},
        CAMP_SEZON, camp_zona(), camp_iesiri({**IESIRI_HARTA, "ani": "GeoTIFF pe ani (animația din Hartă)"}),
        {"nume": "CLASE", "tip": "lista_numere", "eticheta": "Limitele claselor pe harta PNG", "implicit": [],
         "ajutor": "gol = scară continuă; ex. 10; 20; 24; 28; 35", "sectiune": "avansat"}],
       _exporta_harta, nume=_nume_ani)
def _harta(p):
    return zc.ruleaza_harta(_indicatori(p), p["ANI"], p["SEZON"], p["ZONA"], p["IESIRI"], p["OUT"], p["NUME"],
                            clase=list(p["CLASE"]) or None if p.get("CLASE") else None)


# =====================================================================================
# Motorul ANOMALIE — perioada țintă față de perioada de referință
# =====================================================================================
def _exporta_anomalie(job, p, setari):
    l = _antet_py(job, setari)
    l += ["", f"INDICATOR = {_py_indicator(p['INDICATORI'][0])}",
          f"ZONA = {_py_zona(p['ZONA'])}",
          f"zc.ruleaza_anomalie(INDICATOR, {_py(p['ANI_TINTA'])}, {_py(p['ANI_REFERINTA'])}, {_py(p['SEZON'])}, ZONA,",
          f"                    {_py(p['IESIRI'])}, {_py_cale(p['OUT'])}, {p['NUME']!r}, mod={p['MOD']!r})"]
    return "\n".join(l) + "\n"


@motor("anomalie", "Anomalie față de o perioadă de referință",
       "Diferența (sau raportul în %) dintre media indicatorului pe perioada țintă și pe perioada de referință.",
       [camp_indicatori(eticheta="Indicatorul", maxim=1),
        {"nume": "ANI_TINTA", "tip": "interval_ani", "eticheta": "Perioada țintă", "implicit": [2025, 2025]},
        {"nume": "ANI_REFERINTA", "tip": "interval_ani", "eticheta": "Perioada de referință (normala)",
         "implicit": [1991, 2020], "ajutor": "normala climatologică OMM: 1991–2020"},
        {"nume": "MOD", "tip": "alegere", "eticheta": "Tipul anomaliei", "implicit": "diferenta",
         "optiuni": [["diferenta", "diferență (țintă − referință)"], ["procent", "% din normală (țintă / referință)"]]},
        CAMP_SEZON, camp_zona(),
        camp_iesiri(dict(IESIRI_HARTA, png_perioade="hărțile celor două perioade (PNG)"),
                    {"cog": True, "png": True, "grafic": True, "gpkg": True, "csv": False, "png_perioade": False})],
       _exporta_anomalie,
       nume=lambda p, rid: f"{_nume_ani(p, rid, 'ANI_TINTA')}_vs_{p['ANI_REFERINTA'][0]}-{p['ANI_REFERINTA'][1]}"
                           + ("_procent" if p.get("MOD") == "procent" else ""))
def _anomalie(p):
    return zc.ruleaza_anomalie(_indicatori(p, unul=True), p["ANI_TINTA"], p["ANI_REFERINTA"], p["SEZON"], p["ZONA"],
                               p["IESIRI"], p["OUT"], p["NUME"], mod=p.get("MOD", "diferenta"))


# =====================================================================================
# Motorul TENDINȚĂ — panta per pixel (unitate / deceniu), cu semnificația
# =====================================================================================
CAMP_METODA_TREND = {"nume": "METODA_TREND", "tip": "alegere", "eticheta": "Metoda tendinței", "implicit": "ols",
                     "optiuni": [["ols", "regresie liniară (OLS) + test t"], ["sen", "Theil–Sen + test Mann–Kendall (robustă)"]],
                     "ajutor": "Theil–Sen = mediana pantelor tuturor perechilor de ani: un an excepțional nu o trage după el. "
                               "Mann–Kendall testează doar dacă seria crește / scade constant, fără să presupună o dreaptă."}


def _exporta_trend(job, p, setari):
    l = _antet_py(job, setari)
    l += ["", f"INDICATOR = {_py_indicator(p['INDICATORI'][0])}",
          f"ZONA = {_py_zona(p['ZONA'])}",
          f"zc.ruleaza_trend(INDICATOR, {_py(p['ANI'])}, {_py(p['SEZON'])}, ZONA, {_py(p['IESIRI'])},",
          f"                 {_py_cale(p['OUT'])}, {p['NUME']!r}, alfa={p['ALFA']!r}, metoda={p.get('METODA_TREND', 'ols')!r})"]
    return "\n".join(l) + "\n"


@motor("trend", "Tendință pe ani (°C / deceniu etc.)",
       "Panta indicatorului an de an, per pixel (regresie liniară sau Theil–Sen); hașurat = nesemnificativ statistic.",
       [camp_indicatori(eticheta="Indicatorul", maxim=1),
        {"nume": "ANI", "tip": "interval_ani", "eticheta": "Anii", "implicit": [1961, 2025],
         "ajutor": "doar ani compleți; o tendință robustă cere cel puțin ~30 de ani"},
        CAMP_SEZON,
        CAMP_METODA_TREND,
        {"nume": "ALFA", "tip": "numar", "eticheta": "Pragul de semnificație (α)", "implicit": 0.05,
         "min": 0.001, "max": 0.5, "pas": 0.01},
        camp_zona(), camp_iesiri()],
       _exporta_trend, nume=_nume_ani)
def _trend(p):
    return zc.ruleaza_trend(_indicatori(p, unul=True), p["ANI"], p["SEZON"], p["ZONA"], p["IESIRI"], p["OUT"], p["NUME"],
                            alfa=float(p.get("ALFA", 0.05)), metoda=p.get("METODA_TREND", "ols"))


# =====================================================================================
# Motorul ALTITUDINE — indicatorul față de altitudine (DEM coregistrat pe grila cubului)
# =====================================================================================
IESIRI_ALTITUDINE = {"grafic": "grafic: indicatorul față de altitudine (PNG)", "csv": "tabel pe trepte + regresia (CSV)",
                     "cog": "harta reziduului (GeoTIFF)", "png": "harta reziduului (PNG)",
                     "csv_pixeli": "toți pixelii: lon, lat, altitudine, valoare (CSV mare)"}


def _exporta_altitudine(job, p, setari):
    l = _antet_py(job, setari)
    l += ["", "INDICATORI = ["] + [f"    {_py_indicator(d)}," for d in p["INDICATORI"]] + ["]"]
    l += [f"ZONA = {_py_zona(p['ZONA'])}",
          f"zc.ruleaza_altitudine(INDICATORI, {_py(p['ANI'])}, {_py(p['SEZON'])}, ZONA, {_py(p['IESIRI'])},",
          f"                      {_py_cale(p['OUT'])}, {p['NUME']!r}, treapta={float(p.get('TREAPTA', 200))!r})"]
    return "\n".join(l) + "\n"


@motor("altitudine", "Indicatorul față de altitudine",
       "Fiecare pixel e un punct (altitudine, valoare): gradientul pe 100 m din regresie, media pe trepte de altitudine "
       "și harta abaterii față de valoarea prezisă de dreaptă. Cauzele abaterii cer observații independente.",
       [camp_indicatori(maxim=3),
        {"nume": "ANI", "tip": "interval_ani", "eticheta": "Anii (media)", "implicit": [1991, 2020]},
        CAMP_SEZON, camp_zona(),
        {"nume": "TREAPTA", "tip": "numar", "eticheta": "Treapta de altitudine (m)", "implicit": 200,
         "min": 50, "max": 1000, "pas": 50, "ajutor": "lățimea claselor din tabel și a punctelor de pe grafic"},
        camp_iesiri(IESIRI_ALTITUDINE, {"grafic": True, "csv": True, "cog": True, "png": True, "csv_pixeli": False})],
       _exporta_altitudine, nume=_nume_ani)
def _altitudine(p):
    return zc.ruleaza_altitudine(_indicatori(p), p["ANI"], p["SEZON"], p["ZONA"], p["IESIRI"], p["OUT"], p["NUME"],
                                 treapta=float(p.get("TREAPTA", 200)))


# =====================================================================================
# Câmpuri folosite de motoarele 12–18
# =====================================================================================
VAR4 = [["max_temp", "Tmax (temperatura maximă)"], ["min_temp", "Tmin (temperatura minimă)"],
        ["tmedie", "Tmed = (Tmax + Tmin) / 2"], ["precipitation", "P (precipitații)"]]
VAR3_T = VAR4[:3]
CAMP_CONTUR = SETARI_AVANSATE[0]


def _ind_din_variabila(v):
    """Rețetele salvate înainte de v4 aveau VARIABILA; o transformăm în indicatorul echivalent."""
    if v == "tmedie":
        return {"cod": "tmedie"}
    if v == "precipitation":
        return {"cod": "suma", "var": "precipitation"}
    return {"cod": "medie", "var": v}


def _ind_serie(p):
    """Indicatorul motoarelor 14 / 15: din INDICATORI (v4) sau din VARIABILA (rețete vechi)."""
    if p.get("VARIABILA"):
        p = dict(p, INDICATORI=[_ind_din_variabila(p["VARIABILA"])])
    return _indicatori(p, unul=True)


def _nume_serie(p, rid, prefix=None):
    d = ([_ind_din_variabila(p["VARIABILA"])] if p.get("VARIABILA") else p.get("INDICATORI")) or [{"cod": "medie", "var": "max_temp"}]
    return f"{prefix or rid}_{ri.din_dict(d[0]).cod}{_sufix_sezon(p.get('SEZON'))}"


CAMP_IND_SERIE = dict(camp_indicatori(eticheta="Indicatorul", maxim=1), implicit=[{"cod": "medie", "var": "max_temp"}],
                      ajutor="orice indicator: media Tmax, suma P, zile tropicale, zile de îngheț, CDD, GDD…; "
                             "se calculează per pixel și per an, apoi se mediază pe zonă")


def _apel(functie, *poz, **kw):
    """Textul unui apel Python, pe rânduri, pentru export."""
    arg = [x for x in poz] + [f"{k}={v}" for k, v in kw.items()]
    return f"{functie}(\n    " + ",\n    ".join(arg) + ",\n)"


def _per(v):
    return tuple(v) if v else v


# =====================================================================================
# 12 — EPISOD ZILNIC: sub-cub pentru QGIS Temporal Controller + animație
# =====================================================================================
def _exporta_episod_zilnic(job, p, setari):
    l = _antet_py(job, setari)
    l += ["", f"ZONA = {_py_zona(p['ZONA'])}",
          _apel("zc.ruleaza_episod", repr(p["VARIABILA"]), repr(p["PERIOADA"][0]), repr(p["PERIOADA"][1]), "ZONA",
                _py(p["IESIRI"]), _py_cale(p["OUT"]), repr(p["NUME"]), repr(p.get("VMIN")), repr(p.get("VMAX")),
                repr(p.get("FPS", 4)))]
    return "\n".join(l) + "\n"


@motor("episod_zilnic", "Episod zilnic (animație, NetCDF pentru QGIS)",
       "Hărțile zi cu zi ale unei perioade scurte: NetCDF CF pentru QGIS Temporal Controller, COG multi-bandă, GIF.",
       [{"nume": "VARIABILA", "tip": "alegere", "eticheta": "Variabila", "optiuni": VAR4[:2] + VAR4[3:], "implicit": "max_temp"},
        {"nume": "PERIOADA", "tip": "perioada", "eticheta": "Perioada (zi cu zi)", "implicit": ["2024-07-10", "2024-07-31"],
         "ajutor": "sfârșit gol = până la frontiera datelor; perioade lungi = fișiere mari"},
        camp_zona(), {"nume": "IESIRI", "tip": "bife", "eticheta": "Rezultate",
                      "optiuni": {"netcdf": "NetCDF (QGIS Temporal Controller)", "cog": "COG, o bandă pe zi",
                                  "gif": "animație GIF", "png": "prima zi (PNG)"},
                      "implicit": {"netcdf": True, "cog": False, "gif": True, "png": True}},
        {"nume": "VMIN", "tip": "numar", "eticheta": "Paleta: minimul", "pas": 0.5, "ajutor": "gol = automat", "sectiune": "avansat"},
        {"nume": "VMAX", "tip": "numar", "eticheta": "Paleta: maximul", "pas": 0.5, "ajutor": "gol = automat", "sectiune": "avansat"},
        {"nume": "FPS", "tip": "numar", "eticheta": "Cadre pe secundă (GIF)", "implicit": 4, "min": 1, "max": 30, "sectiune": "avansat"}],
       _exporta_episod_zilnic,
       nume=lambda p, rid=None: f"{rid or '12'}_{p['VARIABILA']}_{p['PERIOADA'][0]}")
def _episod_zilnic(p):
    per = p["PERIOADA"]
    return zc.ruleaza_episod(p["VARIABILA"], per[0], per[1] or "2100-01-01", p["ZONA"], p["IESIRI"], p["OUT"], p["NUME"],
                             p.get("VMIN"), p.get("VMAX"), int(p.get("FPS") or 4))


# =====================================================================================
# 13 — ATLAS: tabel de indicatori pe poligoane (UAT, județe, bazine)
# =====================================================================================
def _exporta_atlas(job, p, setari):
    l = _antet_py(job, setari)
    l += ["", "INDICATORI = ["] + [f"    {_py_indicator(d)}," for d in p["INDICATORI"]] + ["]",
          "INDICATORI = {ind.cod: ind for ind in INDICATORI}      # câmpurile tabelei = codurile indicatorilor",
          f"ZONA = {_py_zona(p['ZONA'])}",
          f"zc.ruleaza_atlas(INDICATORI, {_py(p['ANI'])}, {_py(p['SEZON'])}, ZONA, {_py(p['IESIRI'])},",
          f"                 {_py_cale(p['OUT'])}, {p['NUME']!r})"]
    return "\n".join(l) + "\n"


@motor("atlas", "Atlas pe poligoane (UAT, județe, bazine)",
       "Pentru fiecare poligon, media pe ani a mai multor indicatori: un tabel (GPKG / CSV) și câte o hartă pe indicator.",
       [camp_indicatori(eticheta="Indicatorii (câte o coloană în tabel)"),
        {"nume": "ANI", "tip": "interval_ani", "eticheta": "Anii (media)", "implicit": [2016, 2025]},
        CAMP_SEZON,
        camp_zona(eticheta="Poligoanele atlasului", forme=("poligoane",), implicit={"tip": "poligoane", "fisier": "date/ro_judete_poligon.gpkg", "coloana": "name"}),
        camp_iesiri()],
       _exporta_atlas, nume=_nume_ani)
def _atlas(p):
    ind = _indicatori(p)
    return zc.ruleaza_atlas({i.cod: i for i in ind}, p["ANI"], p["SEZON"], p["ZONA"], p["IESIRI"], p["OUT"], p["NUME"])


# =====================================================================================
# 14 — DUNGILE ÎNCĂLZIRII
# =====================================================================================
def _exporta_dungi(job, p, setari):
    l = _antet_py(job, setari)
    d = _ind_din_variabila(p["VARIABILA"]) if p.get("VARIABILA") else p["INDICATORI"][0]
    l += ["", f"INDICATOR = {_py_indicator(d)}", f"ZONA = {_py_zona(p['ZONA'])}",
          f"zc.ruleaza_dungi(INDICATOR, {_py(p['ANI'])}, ZONA, {_py(p['IESIRI'])}, {_py_cale(p['OUT'])}, "
          f"{p['NUME']!r}, ref={_py(p['REFERINTA'])}, sezon={_py(p.get('SEZON', 'anual'))})"]
    return "\n".join(l) + "\n"


@motor("dungi", "Dungile încălzirii (warming stripes)",
       "Câte o dungă colorată pe an, după abaterea față de o perioadă de referință; pentru un punct sau pentru fiecare poligon.",
       [CAMP_IND_SERIE,
        {"nume": "ANI", "tip": "interval_ani", "eticheta": "Anii", "implicit": [1961, 2025]},
        CAMP_SEZON,
        {"nume": "REFERINTA", "tip": "interval_ani", "eticheta": "Referința culorilor", "implicit": [1971, 2000]},
        camp_zona(forme=("punct", "poligoane"), implicit={"tip": "punct", "lon": 26.1025, "lat": 44.4268, "nume": "București"}),
        {"nume": "IESIRI", "tip": "bife", "eticheta": "Rezultate",
         "optiuni": {"png": "dungile (PNG)", "grafic": "seria cu tendința", "gpkg": "GeoPackage (poligoane: un câmp pe an)",
                     "csv": "tabelul seriei"}, "implicit": {"png": True, "grafic": True, "gpkg": True, "csv": True}}],
       _exporta_dungi, nume=_nume_serie)
def _dungi(p):
    return zc.ruleaza_dungi(_ind_serie(p), p["ANI"], p["ZONA"], p["IESIRI"], p["OUT"], p["NUME"], ref=p["REFERINTA"],
                            sezon=p.get("SEZON", "anual"))


# =====================================================================================
# 15 — SERII DE TIMP PE ZONE (grafice complexe)
# =====================================================================================
GRAFICE_SERII = {"serie_zilnica": "seria zilnică", "serii_anuale": "seriile anuale", "multiple_mici": "multiple mici",
                 "bare_zone": "bare pe zone (medie / anomalie)", "dungi_zone": "dungi pe zone", "dungi_detaliu": "dungi clasice (detaliu)",
                 "anomalii_lunare": "anomalii lunare", "harta_zone": "harta pe zone",
                 "sensibilitate": "sensibilitatea la un singur an (zonele de detaliu)"}


def _exporta_serii(job, p, setari):
    l = _antet_py(job, setari)
    det = list(p.get("ZONE_DETALIU") or []) + ([p["NUME_TOTAL"]] if p.get("INCLUDE_TOTALUL_LA_DETALIU") else [])
    l += ["", f"ZONA = {_py_zona(p['ZONA'])}",
          f"INDICATOR = {_py_indicator(_ind_din_variabila(p['VARIABILA']) if p.get('VARIABILA') else p['INDICATORI'][0])}",
          _apel("zc.ruleaza_serii", "INDICATOR", _py(p["ANI"]), _py(p["REFERINTA"]), _py(p["PERIOADA_RECENTA"]),
                "ZONA", _py(p["GRAFICE"]), _py(p["IESIRI"]), _py_cale(p["OUT"]), repr(p["NUME"]),
                detaliu=_py(det), fereastra=_py(p["FEREASTRA_ZILNICA"]), zile_dupa=repr(int(p.get("ZILE_DUPA_FRONTIERA") or 0)),
                sortare=repr(p["SORTARE_DUNGI"]), harta_valoare=repr(p["HARTA_VALOARE"]), total_nume=repr(p["NUME_TOTAL"]),
                alfa=repr(p["ALFA"]), sezon=_py(p.get("SEZON", "anual")), metoda_trend=repr(p.get("METODA_TREND", "ols")))]
    return "\n".join(l) + "\n"


@motor("serii", "Serii de timp pe zone (grafice)",
       "Seria zilnică, seriile anuale cu tendință, multiple mici, bare, dungi pe zone, anomalii lunare și harta pe zone.",
       [CAMP_IND_SERIE,
        {"nume": "ANI", "tip": "interval_ani", "eticheta": "Anii (serii, tendințe, dungi)", "implicit": [1961, 2025]},
        dict(CAMP_SEZON, ajutor="seria zilnică și anomaliile lunare: doar pentru media Tmax / Tmin / Tmed și suma P, pe tot anul"),
        {"nume": "REFERINTA", "tip": "interval_ani", "eticheta": "Referința anomaliilor", "implicit": [1971, 2000]},
        {"nume": "PERIOADA_RECENTA", "tip": "interval_ani", "eticheta": "Media recentă (graficul cu bare)", "implicit": [2016, 2025]},
        camp_zona(eticheta="Zonele (fiecare poligon = o serie)", forme=("poligoane", "punct"),
                  implicit={"tip": "poligoane", "fisier": "date/ro_judete_poligon.gpkg", "coloana": "name"}),
        {"nume": "NUME_TOTAL", "tip": "text", "eticheta": "Numele seriei care reunește toate zonele (media tuturor pixelilor lor: zonele mari cântăresc mai mult)", "implicit": "România (toate zonele)"},
        {"nume": "ZONE_DETALIU", "tip": "lista_text", "eticheta": "Zonele de detaliu", "implicit": ["Iași", "Constanța", "Cluj"],
         "ajutor": "nume din coloana zonei, separate prin ; (majusculele și diacriticele nu contează)"},
        {"nume": "INCLUDE_TOTALUL_LA_DETALIU", "tip": "bifa", "eticheta": "Seria totală", "text": "adaugă și seria totală la detaliu", "implicit": True},
        {"nume": "GRAFICE", "tip": "bife", "eticheta": "Graficele", "optiuni": GRAFICE_SERII, "implicit": {k: True for k in GRAFICE_SERII}},
        {"nume": "IESIRI", "tip": "bife", "eticheta": "Tabele", "optiuni": {"csv": "CSV (an × zone, statistici)",
                                                                      "gpkg": "GeoPackage (poligoane cu medie, tendință, câte un câmp pe an)"},
         "implicit": {"csv": True, "gpkg": True}},
        {"nume": "FEREASTRA_ZILNICA", "tip": "perioada", "eticheta": "Fereastra seriei zilnice", "implicit": ["2025-01-01", None],
         "sectiune": "avansat", "ajutor": "sfârșit gol = până la frontiera datelor"},
        {"nume": "ZILE_DUPA_FRONTIERA", "tip": "numar", "eticheta": "Zile arătate după frontieră (capcana 2050)", "implicit": 0,
         "min": 0, "max": 365, "sectiune": "avansat", "ajutor": "> 0 = arată zilele pre-alocate, citite ca 0,0"},
        {"nume": "SORTARE_DUNGI", "tip": "alegere", "eticheta": "Ordinea dungilor pe zone", "implicit": "tendinta", "sectiune": "avansat",
         "optiuni": [["tendinta", "după tendință"], ["medie", "după medie"], ["lat", "nord → sud"], ["nume", "alfabetic"]]},
        {"nume": "HARTA_VALOARE", "tip": "alegere", "eticheta": "Valoarea hărții pe zone", "implicit": "tendinta", "sectiune": "avansat",
         "optiuni": [["tendinta", "tendința"], ["medie", "media"], ["anomalie", "anomalia recentă"]]},
        dict(CAMP_METODA_TREND, sectiune="avansat"),
        {"nume": "ALFA", "tip": "numar", "eticheta": "Pragul de semnificație (α)", "implicit": 0.05, "min": 0.001, "max": 0.5,
         "pas": 0.01, "sectiune": "avansat"}],
       _exporta_serii,
       nume=lambda p, rid=None: _nume_serie(p, rid or "15"),
       setari=SETARI_AVANSATE)
def _serii(p):
    det = list(p.get("ZONE_DETALIU") or []) + ([p["NUME_TOTAL"]] if p.get("INCLUDE_TOTALUL_LA_DETALIU") else [])
    return zc.ruleaza_serii(_ind_serie(p), p["ANI"], p["REFERINTA"], p["PERIOADA_RECENTA"], p["ZONA"], p["GRAFICE"],
                            p["IESIRI"], p["OUT"], p["NUME"], detaliu=det, fereastra=_per(p["FEREASTRA_ZILNICA"]),
                            zile_dupa=int(p.get("ZILE_DUPA_FRONTIERA") or 0), sortare=p["SORTARE_DUNGI"],
                            harta_valoare=p["HARTA_VALOARE"], total_nume=p["NUME_TOTAL"], alfa=float(p["ALFA"]),
                            sezon=p.get("SEZON", "anual"), metoda_trend=p.get("METODA_TREND", "ols"))


# =====================================================================================
# 16 — ANALIZA UNUI EPISOD (statistici, raritate, context, hărți, fișa HTML)
# =====================================================================================
ANALIZE_EPISOD = {"rang_fereastra": "(1) rang pe fereastră", "top_episoade": "(2) top episoade",
                  "gumbel": "(3) perioada de revenire", "siruri": "(4) șiruri", "zile_episod": "(5) zilele episodului",
                  "context_anterior": "(7) context anterior", "harti": "(8) hărți", "extindere": "(9) extindere",
                  "context": "(10) alte variabile", "calendar": "(11) calendar", "gif": "(12) animație GIF",
                  "comparatii": "(13) comparații", "frecventa": "(14) frecvență"}


def _exporta_analiza_episod(job, p, setari):
    l = _antet_py(job, setari)
    l += ["import zarr_episod as ze  # noqa: E402", "",
          f"ZONA = {_py_zona(p['ZONA'])}", f"HARTI_ZONA = {_py_zona(p['HARTI_ZONA'])}",
          _apel("ze.analizeaza", repr(p["PARAMETRU"]), _py(p["PERIOADA"]), _py(p["REFERINTA"]), _py(p["CLIMATOLOGIE"]),
                "ZONA", repr(p.get("ZONA_ANALIZA")), "HARTI_ZONA", _py(p["IESIRI"]), _py(p["ANALIZE"]), _py_cale(p["OUT"]),
                repr(p["NUME"]), PRAG_ZI_PLOIOASA=repr(p["PRAG_ZI_PLOIOASA"]), SENS=repr(p["SENS"]),
                ZILE_ANTERIOARE=_py(p["ZILE_ANTERIOARE"]), EPISOADE_COMPARATIE=_py([tuple(x) for x in p.get("EPISOADE_COMPARATIE") or []]),
                MIN_ZILE_SIR=repr(p["MIN_ZILE_SIR"]), PRAGURI_EXTINDERE=_py(p.get("PRAGURI_EXTINDERE") or None),
                TOP_N=repr(p["TOP_N"]), FPS_GIF=repr(p["FPS_GIF"]), HTML_FACTOR=repr(p["HTML_REZOLUTIE"]))]
    return "\n".join(l) + "\n"


@motor("analiza_episod", "Analiza unui episod (raritate, context, fișă HTML)",
       "Statistici, anomalie, raritate (rang, top episoade, Gumbel, șiruri), context, hărți, GIF și fișa interactivă HTML.",
       [{"nume": "PARAMETRU", "tip": "alegere", "eticheta": "Parametrul", "implicit": "precipitation",
         "optiuni": [["precipitation", "Precipitații"], ["max_temp", "Temperatura maximă"],
                     ["min_temp", "Temperatura minimă"], ["tmedie", "Temperatura medie (Tmax+Tmin)/2"]]},
        {"nume": "PERIOADA", "tip": "perioada", "eticheta": "Perioada episodului", "implicit": ["2026-10-26", "2026-11-18"],
         "ajutor": "sfârșit gol = până la frontiera datelor"},
        {"nume": "REFERINTA", "tip": "referinta", "eticheta": "Referința anomaliei", "implicit": ["climatologie", 1991, 2020]},
        {"nume": "CLIMATOLOGIE", "tip": "interval_ani", "eticheta": "Climatologia (percentile, normale)", "implicit": [1991, 2020]},
        camp_zona(eticheta="Zona de analiză", forme=("punct", "dreptunghi", "poligoane"),
                  implicit={"tip": "punct", "lon": 26.1025, "lat": 44.4268, "nume": "București"}),
        {"nume": "ZONA_ANALIZA", "tip": "text", "eticheta": "Zona analizată în detaliu (mai multe poligoane)",
         "ajutor": "gol = media tuturor", "gol_none": True},
        camp_zona("HARTI_ZONA", "Zona hărților", forme=("tara", "dreptunghi")),
        {"nume": "ANALIZE", "tip": "bife", "eticheta": "Analize", "optiuni": ANALIZE_EPISOD,
         "implicit": {k: True for k in ANALIZE_EPISOD}},
        {"nume": "IESIRI", "tip": "bife", "eticheta": "Exporturi",
         "optiuni": {"csv": "tabele CSV", "cog": "GeoTIFF multi-bandă", "gpkg": "GeoPackage",
                     "raport": "raport .md + .json", "html": "fișa interactivă .html"},
         "implicit": {"csv": True, "cog": True, "gpkg": True, "raport": True, "html": True}},
        {"nume": "HTML_REZOLUTIE", "tip": "alegere", "eticheta": "Rezoluția hărților din fișă", "implicit": 1,
         "optiuni": [[1, "0,01° (≈ 6–15 MB)"], [2, "0,02° (≈ 4× mai mic)"], [3, "0,03°"]]},
        {"nume": "SENS", "tip": "alegere", "eticheta": "Sensul episodului (temperaturi)", "sectiune": "avansat", "implicit": "auto",
         "optiuni": [["auto", "automat (după anomalie)"], ["mare", "cald"], ["mic", "rece"]]},
        {"nume": "PRAG_ZI_PLOIOASA", "tip": "numar", "eticheta": "Prag zi ploioasă (mm)", "pas": 0.1, "implicit": 1.0, "sectiune": "avansat"},
        {"nume": "ZILE_ANTERIOARE", "tip": "lista_numere", "eticheta": "Contextul anterior (zile)", "implicit": [30, 60, 90], "sectiune": "avansat"},
        {"nume": "MIN_ZILE_SIR", "tip": "numar", "eticheta": "Lungimea minimă a unui șir lung (zile)", "implicit": 5, "sectiune": "avansat"},
        {"nume": "PRAGURI_EXTINDERE", "tip": "lista_numere", "eticheta": "Pragurile extinderii (9)", "implicit": [], "sectiune": "avansat",
         "ajutor": "gol = implicit: 150; 200; 300 % (precipitații), ±2; 4; 6 °C (temperaturi)"},
        {"nume": "TOP_N", "tip": "numar", "eticheta": "Câte episoade în clasamente", "implicit": 10, "sectiune": "avansat"},
        {"nume": "FPS_GIF", "tip": "numar", "eticheta": "Cadre pe secundă (GIF)", "implicit": 2, "sectiune": "avansat"},
        {"nume": "EPISOADE_COMPARATIE", "tip": "lista_episoade", "eticheta": "Episoade de comparat", "implicit": [],
         "ajutor": "câte unul pe rând: eticheta; data de început (AAAA-LL-ZZ)", "sectiune": "avansat"}],
       _exporta_analiza_episod,
       nume=lambda p, rid=None: f"{rid or '16'}_{p['PARAMETRU']}_{p['PERIOADA'][0]}",
       setari=[CAMP_CONTUR])
def _analiza_episod(p):
    import zarr_episod as ze
    return ze.analizeaza(p["PARAMETRU"], p["PERIOADA"], p["REFERINTA"], p["CLIMATOLOGIE"], p["ZONA"], p.get("ZONA_ANALIZA"),
                         p["HARTI_ZONA"], p["IESIRI"], p["ANALIZE"], p["OUT"], p["NUME"],
                         PRAG_ZI_PLOIOASA=float(p["PRAG_ZI_PLOIOASA"]), SENS=p["SENS"], ZILE_ANTERIOARE=tuple(p["ZILE_ANTERIOARE"]),
                         EPISOADE_COMPARATIE=[tuple(x) for x in p.get("EPISOADE_COMPARATIE") or []],
                         MIN_ZILE_SIR=int(p["MIN_ZILE_SIR"]), PRAGURI_EXTINDERE=tuple(p.get("PRAGURI_EXTINDERE") or ()) or None,
                         TOP_N=int(p["TOP_N"]), FPS_GIF=float(p["FPS_GIF"]), HTML_FACTOR=int(p["HTML_REZOLUTIE"]))


# =====================================================================================
# 17 — STATISTICI PE PERIOADĂ, PER PIXEL (medie, minimă, maximă, sumă …) → GeoTIFF
# =====================================================================================
STATISTICI_17 = {"medie": "media", "minima": "minima", "maxima": "maxima", "suma": "suma", "suma_medie_anuala": "suma medie anuală",
                 "abatere_standard": "abaterea standard", "amplitudine": "amplitudinea", "zile_valide": "zilele valide"}


def _sezon_17(v):
    return None if v in (None, "anual") else v


def _statistici_17(p):
    alese = [k for k, x in (p.get("STATISTICI") or {}).items() if x]
    return alese or None


def _exporta_statistici(job, p, setari):
    l = _antet_py(job, setari)
    l += ["import zarr_statistici as zs  # noqa: E402", "", f"ZONA = {_py_zona(p['ZONA'])}",
          _apel("zs.ruleaza_statistici", repr(p["PARAMETRU"]), _py(p["PERIOADA"]), _py(_sezon_17(p["SEZON"])),
                _py(_statistici_17(p)), "ZONA", repr(p["DECUPARE"]), _py(p["IESIRI"]), _py_cale(p["OUT"]), repr(p["NUME"]))]
    return "\n".join(l) + "\n"


def _nume_17(p, rid=None):
    sez = p.get("SEZON")
    s = "" if sez in (None, "anual") else "_" + (sez if isinstance(sez, str) else "-".join(map(str, sez)))
    return f"17_{p['PARAMETRU']}_{p['PERIOADA'][0][:4]}_{(p['PERIOADA'][1] or 'frontiera')[:4]}{s}"


@motor("statistici", "Statistici pe perioadă, per pixel (GeoTIFF)",
       "Media, minima, maxima, suma (și altele) ale valorilor zilnice dintr-o perioadă, pixel cu pixel.",
       [{"nume": "PARAMETRU", "tip": "alegere", "eticheta": "Parametrul", "optiuni": VAR4, "implicit": "max_temp"},
        {"nume": "PERIOADA", "tip": "perioada", "eticheta": "Perioada", "implicit": ["2006-01-01", "2025-12-31"],
         "ajutor": "sfârșit gol = până la frontiera datelor"},
        dict(CAMP_SEZON, ajutor="„anual” = toate zilele perioadei"),
        {"nume": "STATISTICI", "tip": "bife", "eticheta": "Statisticile", "optiuni": STATISTICI_17,
         "implicit": {k: False for k in STATISTICI_17},
         "ajutor": "nimic bifat = implicit: medie, minima, maxima (temperaturi); suma, suma medie anuală, medie, maxima (precipitații)"},
        camp_zona(),
        {"nume": "DECUPARE", "tip": "alegere", "eticheta": "Decuparea (zona cu poligoane)", "implicit": "masca",
         "optiuni": [["masca", "NoData în afara poligoanelor"], ["dreptunghi", "tot dreptunghiul poligoanelor"]]},
        {"nume": "IESIRI", "tip": "bife", "eticheta": "Exporturi",
         "optiuni": {"cog_multibanda": "un COG cu o bandă pe statistică", "tif_separate": "câte un GeoTIFF pe statistică",
                     "png": "hărți de control (PNG)", "csv": "rezumat CSV"},
         "implicit": {"cog_multibanda": True, "tif_separate": True, "png": True, "csv": True}}],
       _exporta_statistici, nume=_nume_17, setari=[CAMP_CONTUR, SETARI_AVANSATE[1]])
def _statistici(p):
    import zarr_statistici as zs
    return zs.ruleaza_statistici(p["PARAMETRU"], p["PERIOADA"], _sezon_17(p["SEZON"]), _statistici_17(p), p["ZONA"],
                                 p["DECUPARE"], p["IESIRI"], p["OUT"], p["NUME"])


# =====================================================================================
# 18 — STATISTICI ZONALE ZILNICE (+ lunare, sezoniere) pe județe / regiuni → CSV
# =====================================================================================
def _zonari(p):
    z = []
    for r in p.get("ZONARI") or []:
        d = {k: r[k] for k in ("prefix", "eticheta", "coloana") if r.get(k)}
        import re
        if not re.fullmatch(r"[\w -]*", str(d.get("prefix", ""))):
            raise ValueError("Prefixul zonării trebuie să fie un nume simplu.")
        if r.get("altitudine") is not None:
            d["altitudine"] = [None if x in ("", None) else float(x) for x in r["altitudine"]]
        if r.get("valori"):
            d["valori"] = list(r["valori"])
        z.append(d)
    if not z:
        raise ValueError("Adăugați cel puțin o zonare (prefix, etichetă, coloană).")
    return z


def _out_18(p):
    return Path(p["OUT"]) / p["NUME"]


def _exporta_zonal(job, p, setari):
    l = _antet_py(job, setari)
    l += ["import zarr_statistici_zonale as zz  # noqa: E402", "",
          _apel("zz.ruleaza_statistici_zonale", _py_cale(p["FISIER"]), repr(p.get("STRAT")), _py(_zonari(p)),
                _py([k for k, x in p["VARIABILE"].items() if x]), _py(p["PERIOADA"]), _py(p["IESIRI"]),
                _py_cale(_out_18(p)), repr(p["FORMAT_CSV"]))]
    return "\n".join(l) + "\n"


@motor("zonal", "Statistici zonale zilnice (CSV pe județe / regiuni)",
       "Valorile zilnice mediate pe poligoane, pentru una sau mai multe zonări, plus agregări lunare și sezoniere.",
       [{"nume": "PERIOADA", "tip": "perioada", "eticheta": "Perioada", "implicit": ["2020-01-01", "2025-12-31"],
         "ajutor": "sfârșit gol = până la frontiera datelor"},
        {"nume": "VARIABILE", "tip": "bife", "eticheta": "Variabilele",
         "optiuni": {"precipitation": "precipitații (precip)", "max_temp": "Tmax (tmax)", "min_temp": "Tmin (tmin)",
                     "tmedie": "Tmed (tmed)"},
         "implicit": {"precipitation": True, "max_temp": True, "min_temp": True, "tmedie": False}},
        {"nume": "FISIER", "tip": "vector", "eticheta": "Fișierul cu poligoane", "implicit": "date/ro_judete_poligon.gpkg"},
        {"nume": "STRAT", "tip": "text", "eticheta": "Stratul", "gol_none": True, "ajutor": "gol = singurul strat cu geometrie"},
        {"nume": "ZONARI", "tip": "zonari", "eticheta": "Zonările (câte una pe rând)",
         "implicit": [{"prefix": "judete", "eticheta": "judet", "coloana": "name", "valori": []}],
         "ajutor": "prefix = în numele fișierelor; etichetă = numele coloanei de entitate în CSV; coloană = din fișier; valori: gol = toate"},
        {"nume": "IESIRI", "tip": "bife", "eticheta": "Exporturi",
         "optiuni": {"zilnic_total": "zilnic, toate variabilele", "zilnic_pe_variabila": "zilnic, câte un fișier pe variabilă",
                     "lunar_anual": "lunar, pe ani", "lunar_multianual": "lunar, multianual",
                     "sezonier_anual": "sezonier, pe ani", "sezonier_multianual": "sezonier, multianual"},
         "implicit": {"zilnic_total": True, "zilnic_pe_variabila": True, "lunar_anual": True, "lunar_multianual": True,
                      "sezonier_anual": True, "sezonier_multianual": True}},
        {"nume": "FORMAT_CSV", "tip": "alegere", "eticheta": "Formatul CSV", "implicit": "standard",
         "optiuni": [["standard", "virgulă + punct zecimal (standard)"], ["ro", "; + virgulă zecimală (Excel RO)"]]}],
       _exporta_zonal, nume=lambda p, rid: f"{rid or '18'}_{p['PERIOADA'][0]}_{p['PERIOADA'][1] or 'frontiera'}", setari=[])
def _zonal(p):
    import zarr_statistici_zonale as zz
    var = [k for k, x in p["VARIABILE"].items() if x]
    if not var:
        raise ValueError("Bifați cel puțin o variabilă.")
    return zz.ruleaza_statistici_zonale(str(p["FISIER"]), p.get("STRAT"), _zonari(p), var, p["PERIOADA"], p["IESIRI"],
                                        _out_18(p), p["FORMAT_CSV"])


# =====================================================================================
# INTEGRITATEA DATELOR — butonul „Verifică datele”
# =====================================================================================
def _exporta_integritate(job, p, setari):
    l = _antet_py(job, setari)
    l += ["import integritate  # noqa: E402", "",
          _apel("integritate.ruleaza_integritate", _py_cale(p["OUT"]), repr(p["NUME"]),
                zile_recente=repr(int(p["ZILE_RECENTE"])), istoric=repr(bool(p["ISTORIC"])), iesiri=_py(p["IESIRI"]))]
    return "\n".join(l) + "\n"


@motor("integritate", "Verificarea datelor",
       "Chunk-uri lipsă și blocuri nescrise (valori exact 0) în cub: pe tot istoricul (fără descărcare) și în zilele "
       "recente (citire efectivă). Rezultatul: ultima zi sigură pe variabile, harta disponibilității, lista problemelor.",
       [{"nume": "ZILE_RECENTE", "tip": "numar", "eticheta": "Câte zile recente se citesc", "implicit": 150, "min": 30, "max": 365,
         "ajutor": "~0,35 GB pentru 150 de zile, toate cele trei variabile"},
        {"nume": "ISTORIC", "tip": "bifa", "eticheta": "Verifică și existența chunk-urilor pe tot istoricul",
         "implicit": True, "ajutor": "fără descărcare: câte o cerere scurtă pe chunk (~7 000), cam un minut"},
        {"nume": "IESIRI", "tip": "bife", "eticheta": "Rezultate",
         "optiuni": {"png": "graficele disponibilității", "csv": "lista problemelor (CSV)"},
         "implicit": {"png": True, "csv": True}}],
       _exporta_integritate, setari=[])
def _integritate(p):
    import integritate
    return integritate.ruleaza_integritate(p["OUT"], p["NUME"], zile_recente=int(p["ZILE_RECENTE"]),
                                           istoric=bool(p["ISTORIC"]), iesiri=p["IESIRI"])


# =====================================================================================
# SUPERLATIVE — cel mai ploios mai, cea mai caldă zi, cele mai ploioase 3 zile consecutive…
# =====================================================================================
UNITATI_SUP = [["zi", "o zi"], ["fereastra", "N zile consecutive"], ["luna", "o lună anume (de-a lungul anilor)"],
               ["luni", "oricare lună din serie"], ["sezon", "un sezon (de-a lungul anilor)"], ["an", "anul întreg"],
               ["interval", "un interval fix din fiecare an (de ex. 1–15 august)"]]
_LUNI_OPT = [[i + 1, n] for i, n in enumerate(["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie",
                                                "august", "septembrie", "octombrie", "noiembrie", "decembrie"])]


def _arg_superlative(p):
    return dict(n=int(p.get("N_ZILE") or 3), luna=int(p.get("LUNA") or 5), sezon=p.get("SEZON", "anual"),
                restrange=p.get("RESTRANGE", "anual") if p["UNITATE"] in ("zi", "fereastra") else None,
                interval=[p.get("INTERVAL_DE"), p.get("INTERVAL_PANA")] if p["UNITATE"] == "interval" else None,
                an_evidentiat=int(p["AN_EVIDENTIAT"]) if p.get("AN_EVIDENTIAT") not in (None, "") else None,
                top=int(p.get("TOP") or 10))


def _exporta_superlative(job, p, setari):
    l = _antet_py(job, setari)
    a = _arg_superlative(p)
    l += ["import zarr_superlative as zsup  # noqa: E402", "", f"ZONA = {_py_zona(p['ZONA'])}",
          _apel("zsup.ruleaza_superlative", repr(p["VARIABILA"]), repr(p["SENS"]), repr(p["UNITATE"]), _py(p["ANI"]),
                "ZONA", repr(p["MOD"]), _py(p["IESIRI"]), _py_cale(p["OUT"]), repr(p["NUME"]),
                **{k: _py(v) if isinstance(v, (list, tuple, dict)) else repr(v) for k, v in a.items()})]
    return "\n".join(l) + "\n"


def nume_zona_scurt(z):
    """„București”, „România”, „județe (ro_judete_poligon)”, „Câmpia Română centrală”."""
    if not isinstance(z, dict):
        return ""
    if z.get("tip") == "tara":
        return "România"
    if z.get("tip") == "poligoane":
        val = z.get("valori") or []
        baza = Path(str(z.get("fisier", ""))).stem
        return ", ".join(map(str, val[:3])) + (" …" if len(val) > 3 else "") if val else f"zonele din {baza}"
    return z.get("nume") or {"punct": "un punct", "dreptunghi": "un dreptunghi"}.get(z.get("tip"), "")


def _titlu_superlative(p):
    import zarr_superlative as zsup
    a = _arg_superlative(p)
    interval = a["interval"]
    if p["UNITATE"] == "interval":
        interval = zsup.valideaza(p["VARIABILA"], p["SENS"], "interval", interval=interval)
    t = zsup.titlu_superlativ(p["VARIABILA"], p["SENS"], p["UNITATE"], a["n"], a["luna"], a["sezon"], interval, a["restrange"])
    z = nume_zona_scurt(p.get("ZONA"))
    return f"{t} · {z}" if z else t


def _nume_superlative(p, rid=None):
    if rid:                                               # titlul rulării e deja în id (vezi ruleaza.titlu_rulare)
        return rid
    u = p["UNITATE"]
    det = {"fereastra": f"{p.get('N_ZILE') or 3}z", "luna": f"l{p.get('LUNA') or 5}"}.get(u, "")
    return f"{rid or 'superlative'}_{p['VARIABILA']}_{p['SENS']}_{u}{det}{_sufix_sezon(p.get('SEZON')) if u == 'sezon' else ''}"


@motor("superlative", "Superlative: recorduri și clasamente",
       "Cel mai ploios mai, cea mai caldă zi, cele mai ploioase 3 zile consecutive, cea mai rece iarnă…: clasamentul "
       "pe o zonă (media zonei) sau hărțile recordului pe pixel (valoarea, anul și data recordului).",
       [{"nume": "VARIABILA", "tip": "alegere", "eticheta": "Variabila", "optiuni": VAR4, "implicit": "precipitation"},
        {"nume": "SENS", "tip": "alegere", "eticheta": "Ce căutăm",
         "optiuni": [["max", "maximul: cel mai cald / cel mai ploios"], ["min", "minimul: cel mai rece / cel mai secetos"]],
         "implicit": "max"},
        {"nume": "UNITATE", "tip": "alegere", "eticheta": "Unitatea de timp", "optiuni": UNITATI_SUP, "implicit": "luna",
         "ajutor": "precipitațiile se adună, temperaturile se mediază pe unitate"},
        {"nume": "N_ZILE", "tip": "numar", "eticheta": "Câte zile consecutive", "implicit": 3, "min": 2, "max": 366,
         "doar_daca": {"camp": "UNITATE", "valori": ["fereastra"]}},
        {"nume": "RESTRANGE", "tip": "sezon", "eticheta": "Doar în această parte a anului", "implicit": "anual",
         "ajutor": "ex. „luni alese: noiembrie” → cea mai geroasă săptămână din noiembrie; „anual” = oricând",
         "doar_daca": {"camp": "UNITATE", "valori": ["zi", "fereastra"]}},
        {"nume": "LUNA", "tip": "alegere", "eticheta": "Luna", "optiuni": _LUNI_OPT, "implicit": 5,
         "doar_daca": {"camp": "UNITATE", "valori": ["luna"]}},
        dict(CAMP_SEZON, implicit="JJA", doar_daca={"camp": "UNITATE", "valori": ["sezon"]}),
        {"nume": "INTERVAL_DE", "tip": "text", "eticheta": "Intervalul: de la (LL-ZZ)", "implicit": "08-01",
         "doar_daca": {"camp": "UNITATE", "valori": ["interval"]}},
        {"nume": "INTERVAL_PANA", "tip": "text", "eticheta": "până la (LL-ZZ)", "implicit": "08-15",
         "ajutor": "peste Anul Nou (de ex. 12-15 → 01-15) se socotește în anul în care se termină",
         "doar_daca": {"camp": "UNITATE", "valori": ["interval"]}},
        {"nume": "ANI", "tip": "interval_ani", "eticheta": "Anii comparați", "implicit": [1961, 2025]},
        {"nume": "MOD", "tip": "alegere", "eticheta": "Rezultatul",
         "optiuni": [["clasament", "clasamentul pe zonă (media zonei): top, record, locul unui an"],
                     ["harta", "hărți pe pixel: valoarea, anul și data recordului"]], "implicit": "clasament"},
        camp_zona(forme=("punct", "dreptunghi", "poligoane", "tara"),
                  implicit={"tip": "punct", "lon": 26.1025, "lat": 44.4268, "nume": "București"}),
        {"nume": "TOP", "tip": "numar", "eticheta": "Câte locuri în clasament", "implicit": 10, "min": 3, "max": 50,
         "doar_daca": {"camp": "MOD", "valori": ["clasament"]}},
        {"nume": "AN_EVIDENTIAT", "tip": "numar", "eticheta": "Un an de evidențiat", "ajutor": "gol = niciunul; ex. 2024: pe ce loc e?"},
        {"nume": "IESIRI", "tip": "bife", "eticheta": "Rezultate",
         "optiuni": {"png": "grafice / hărți PNG", "csv": "tabele CSV", "cog": "GeoTIFF (hărțile pe pixel)",
                     "gpkg": "GeoPackage (recordul fiecărui poligon)"},
         "implicit": {"png": True, "csv": True, "cog": True, "gpkg": True}}],
       _exporta_superlative, nume=_nume_superlative, titlu_rulare=_titlu_superlative)
def _superlative(p):
    import zarr_superlative as zsup
    return zsup.ruleaza_superlative(p["VARIABILA"], p["SENS"], p["UNITATE"], p["ANI"], p["ZONA"], p["MOD"], p["IESIRI"],
                                    p["OUT"], p["NUME"], **_arg_superlative(p))


# =====================================================================================
# Rețetele
# =====================================================================================
def foldere_retete(radacina: Path):
    return [radacina / "retete", radacina / "retete" / "utilizator"]


def citeste_retete(radacina: Path):
    """[(rețetă, eroare)] din retete/*.json și retete/utilizator/*.json, cu câmpurile motorului completate."""
    rez, erori = [], []
    for folder in foldere_retete(radacina):
        for f in sorted(folder.glob("*.json")):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
                r["id"] = ("utilizator/" if folder.name == "utilizator" else "") + f.stem
                r["utilizator"] = folder.name == "utilizator"
                if r.get("motor") not in MOTOARE:
                    raise ValueError(f"motor necunoscut {r.get('motor')!r} (disponibile: {', '.join(MOTOARE)})")
                rez.append(completeaza_reteta(r))
            except Exception as e:  # noqa: BLE001
                erori.append(f"{folder.name}/{f.name}: {e}")
    return rez, erori


def completeaza_reteta(r):
    """Câmpurile motorului, cu valorile implicite ale rețetei; ascunse / fixate după cum cere rețeta."""
    m = MOTOARE[r["motor"]]
    val = dict(r.get("parametri", {}))
    if r["motor"] in ("dungi", "serii") and "VARIABILA" in val:       # rețetă salvată înainte de v4
        val.setdefault("INDICATORI", [_ind_din_variabila(val.pop("VARIABILA"))])
        val.pop("VARIABILA", None)
    ascunse = set(r.get("ascunse", []))
    campuri = []
    for c in m["campuri"]:
        if c["nume"] in ascunse:
            continue
        c = dict(c)
        if c["nume"] in val:
            c["implicit"] = val[c["nume"]]
        if c["tip"] == "indicatori":
            c["mod"] = r.get("mod_indicatori", "liber")      # liber · acelasi · blocat
            if r.get("grupuri_indicatori"):
                c["grupuri"] = r["grupuri_indicatori"]
        campuri.append(c)
    fixe = {c["nume"]: val.get(c["nume"], c.get("implicit")) for c in m["campuri"] if c["nume"] in ascunse}
    return {"id": r["id"], "titlu": r["titlu"], "grup": r.get("grup", "Altele"), "descriere": r.get("descriere", ""),
            "cost": r.get("cost", ""), "etichete": r.get("etichete", []), "motor": r["motor"],
            "rapida": bool(r.get("rapida")),
            "motor_titlu": m["titlu"], "campuri": campuri, "fixe": fixe, "utilizator": r.get("utilizator", False),
            "tip": "reteta"}
