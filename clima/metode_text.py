# -*- coding: utf-8 -*-
"""
metode_text.py — paragraful „Date și metode” al unei rulări, în română și în engleză, plus bibliografia.

Textul e DESCRIPTIV: spune ce date, ce perioadă, ce zonă, ce indicatori și ce metodă s-au folosit, cu regulile de
validitate și golurile întâlnite. Nu conține interpretări („seceta a crescut”): concluziile le scrie autorul lucrării.
Se scrie în folderul rulării ca `metode.md` și apare în fișa vizuală (index.html), cu butoane de copiere.
"""
from __future__ import annotations

import re
from pathlib import Path

DOI_PROGRAM = "10.5281/zenodo.24564871"

# ---------------------------------------------------------------------------------------------------------- bibliografie
REF = {
    "program": "Budileanu, M. ({an}). Clima ANM: analize climatice pe cubul Zarr anm-daily-grids (EOCube.ro) "
               "(versiunea {versiune}) [Software]. Zenodo. https://doi.org/" + DOI_PROGRAM,
    "date": "Administrația Națională de Meteorologie (ANM / MeteoRomania) și Universitatea de Vest din Timișoara – "
            "EOCube.ro. anm-daily-grids: date climatice zilnice grilate pentru România, 1 km (cub Zarr). "
            "Licență CC BY 4.0. https://eocube.ro",
    "zhang2011": "Zhang, X., Alexander, L., Hegerl, G. C., Jones, P., Klein Tank, A., Peterson, T. C., Trewin, B., & "
                 "Zwiers, F. W. (2011). Indices for monitoring changes in extremes based on daily temperature and "
                 "precipitation data. WIREs Climate Change, 2(6), 851–870. https://doi.org/10.1002/wcc.147",
    "wmo1203": "WMO (2017). WMO Guidelines on the Calculation of Climate Normals (WMO-No. 1203). World Meteorological "
               "Organization, Geneva.",
    "mckee1993": "McKee, T. B., Doesken, N. J., & Kleist, J. (1993). The relationship of drought frequency and duration "
                 "to time scales. In Proceedings of the 8th Conference on Applied Climatology (pp. 179–184). American "
                 "Meteorological Society.",
    "wmo1090": "WMO (2012). Standardized Precipitation Index User Guide (WMO-No. 1090). World Meteorological "
               "Organization, Geneva.",
    "vicente2010": "Vicente-Serrano, S. M., Beguería, S., & López-Moreno, J. I. (2010). A multiscalar drought index "
                   "sensitive to global warming: The Standardized Precipitation Evapotranspiration Index. Journal of "
                   "Climate, 23(7), 1696–1718. https://doi.org/10.1175/2009JCLI2909.1",
    "beg2014": "Beguería, S., Vicente-Serrano, S. M., Reig, F., & Latorre, B. (2014). Standardized precipitation "
               "evapotranspiration index (SPEI) revisited: Parameter fitting, evapotranspiration models, tools, datasets "
               "and drought monitoring. International Journal of Climatology, 34(10), 3001–3023. "
               "https://doi.org/10.1002/joc.3887",
    "hargreaves1985": "Hargreaves, G. H., & Samani, Z. A. (1985). Reference crop evapotranspiration from temperature. "
                      "Applied Engineering in Agriculture, 1(2), 96–99.",
    "fao56": "Allen, R. G., Pereira, L. S., Raes, D., & Smith, M. (1998). Crop evapotranspiration: Guidelines for "
             "computing crop water requirements (FAO Irrigation and Drainage Paper 56). FAO, Rome.",
    "demartonne1926": "De Martonne, E. (1926). Une nouvelle fonction climatologique : l'indice d'aridité. "
                      "La Météorologie, 2, 449–458.",
    "sen1968": "Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. Journal of the "
               "American Statistical Association, 63(324), 1379–1389. https://doi.org/10.1080/01621459.1968.10480934",
    "mann1945": "Mann, H. B. (1945). Nonparametric tests against trend. Econometrica, 13(3), 245–259. "
                "https://doi.org/10.2307/1907187",
    "kendall1975": "Kendall, M. G. (1975). Rank correlation methods (4th ed.). Charles Griffin, London.",
    "walter1960": "Walter, H., & Lieth, H. (1960–1967). Klimadiagramm-Weltatlas. VEB Gustav Fischer Verlag, Jena.",
    "coumou2012": "Coumou, D., & Rahmstorf, S. (2012). A decade of weather extremes. Nature Climate Change, 2(7), "
                  "491–496. https://doi.org/10.1038/nclimate1452",
}

# citarea scurtă din text (autor, an)
SCURT = {"zhang2011": "Zhang et al., 2011", "wmo1203": "WMO, 2017", "mckee1993": "McKee et al., 1993",
         "wmo1090": "WMO, 2012", "vicente2010": "Vicente-Serrano et al., 2010", "beg2014": "Beguería et al., 2014",
         "hargreaves1985": "Hargreaves & Samani, 1985", "fao56": "Allen et al., 1998",
         "demartonne1926": "De Martonne, 1926", "sen1968": "Sen, 1968", "mann1945": "Mann, 1945",
         "kendall1975": "Kendall, 1975", "coumou2012": "Coumou & Rahmstorf, 2012", "walter1960": "Walter & Lieth, 1960"}

# indicator → referințele lui (codurile din indicatori.py)
REF_INDICATOR = {
    "zile_peste": ["zhang2011"], "zile_sub": ["zhang2011"], "amplitudine_medie": ["zhang2011"],
    "amplitudine_absoluta": ["zhang2011"], "cdd": ["zhang2011"], "cwd": ["zhang2011"], "sdii": ["zhang2011"],
    "prcptot": ["zhang2011"], "rxnday": ["zhang2011"], "pct_zile": ["zhang2011", "wmo1203"],
    "wsdi": ["zhang2011", "wmo1203"], "csdi": ["zhang2011", "wmo1203"], "rnnp": ["zhang2011", "wmo1203"],
    "rnnptot": ["zhang2011", "wmo1203"], "de_martonne": ["demartonne1926"], "pet": ["hargreaves1985", "fao56"],
    "bilant": ["hargreaves1985", "fao56"], "spi": ["mckee1993", "wmo1090"],
    "spei": ["vicente2010", "beg2014", "hargreaves1985", "fao56"],
}

NUME_VAR = {"max_temp": ("temperatura maximă zilnică", "daily maximum temperature"),
            "min_temp": ("temperatura minimă zilnică", "daily minimum temperature"),
            "precipitation": ("precipitațiile zilnice", "daily precipitation")}
SEZ = {"anual": ("anul întreg", "the whole year"), "DJF": ("iarna (decembrie–februarie)", "winter (December–February)"),
       "MAM": ("primăvara (martie–mai)", "spring (March–May)"), "JJA": ("vara (iunie–august)", "summer (June–August)"),
       "SON": ("toamna (septembrie–noiembrie)", "autumn (September–November)"),
       "vara_agricola": ("sezonul de vegetație (aprilie–septembrie)", "the growing season (April–September)"),
       "iarna_extinsa": ("iarna extinsă (noiembrie–martie)", "the extended winter (November–March)")}


def _sezon(s):
    if s in SEZ:
        return SEZ[s]
    return (f"perioada „{s}”", f"the period “{s}”") if s else (None, None)


def _zona(z):
    if not isinstance(z, dict):
        return "România", "Romania"
    t = z.get("tip")
    if t == "tara":
        return "întreaga Românie", "the whole of Romania"
    if t == "punct":
        n = z.get("nume") or f"{z.get('lon')}°E, {z.get('lat')}°N"
        return f"punctul {n} (pixelul de 1 km care îl conține)", f"the point {n} (the 1 km grid cell containing it)"
    if t == "dreptunghi":
        c = f"{z.get('lon_min')}–{z.get('lon_max')}°E, {z.get('lat_min')}–{z.get('lat_max')}°N"
        return (f"dreptunghiul {z.get('nume') or ''} ({c})".replace("  ", " "), f"the box {z.get('nume') or ''} ({c})".replace("  ", " "))
    if t == "poligoane":
        val = z.get("valori") or []
        f = Path(str(z.get("fisier", ""))).name
        if val:
            s = ", ".join(map(str, val[:6])) + (" …" if len(val) > 6 else "")
            return f"zonele {s} (din {f})", f"the zones {s} (from {f})"
        return f"toate poligoanele din {f}", f"all polygons in {f}"
    return str(z.get("nume") or t or "zona aleasă"), str(z.get("nume") or t or "the selected area")


def _ani(v):
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, int) for x in v):
        return f"{v[0]}" if v[0] == v[1] else f"{v[0]}–{v[1]}"
    return None


def _indicatori(p):
    """→ (titluri, coduri, variabile) din parametrul INDICATORI."""
    lst = p.get("INDICATORI") or []
    titluri, coduri, variabile = [], [], set()
    try:
        import indicatori as reg
        for d in lst:
            d = dict(d)
            ind = reg.construieste(d.get("cod"), **{k: v for k, v in d.items() if k != "cod"})
            titluri.append(ind.titlu); coduri.append(d.get("cod")); variabile.update(ind.variabile)
    except Exception:  # noqa: BLE001 (textul rămâne util și fără titluri)
        for d in lst:
            coduri.append(d.get("cod")); titluri.append(str(d.get("cod")))
    for k in ("VARIABILA", "PARAMETRU"):
        if p.get(k) in NUME_VAR:
            variabile.add(p[k])
    for v in p.get("VARIABILE") or []:
        if v in NUME_VAR:
            variabile.add(v)
    return titluri, coduri, variabile


def compune(fisa: dict, versiune: str = "") -> dict | None:
    """→ {"ro": text, "en": text, "referinte": [..]} sau None (rulări fără date climatice, ex. verificarea datelor)."""
    motor = fisa.get("motor")
    if motor in (None, "integritate"):
        return None
    p = fisa.get("parametri") or {}
    st = p.get("_setari") or {}
    fr = fisa.get("frontiera_datelor") or {}
    fr_min = min(fr.values()) if fr else None
    titluri, coduri, variabile = _indicatori(p)
    refs = ["date"]
    ro, en = [], []
    titlu = re.sub(r"\s*\(\+\d+\)\s*$", "", str(fisa.get("titlu", "")))      # „… (+2)”: alți doi indicatori
    if titlu != fisa.get("titlu") and fisa.get("reteta_titlu"):
        titlu = fisa["reteta_titlu"]

    vars_ro = ", ".join(NUME_VAR[v][0] for v in sorted(variabile)) or "temperatura și precipitațiile"
    vars_en = ", ".join(NUME_VAR[v][1] for v in sorted(variabile)) or "temperature and precipitation"
    ro.append(f"Analiza „{titlu}” folosește datele zilnice grilate ale Administrației Naționale de "
              f"Meteorologie (rezoluție de 1 km), distribuite de EOCube.ro ca cubul Zarr anm-daily-grids (licență CC BY 4.0): "
              f"{vars_ro}" + (f", cu date disponibile până la {fr_min}." if fr_min else "."))
    en.append(f"The analysis “{titlu}” uses the daily 1 km gridded data of the Romanian National "
              f"Meteorological Administration (ANM), distributed by EOCube.ro as the Zarr data cube anm-daily-grids "
              f"(CC BY 4.0 licence): {vars_en}" + (f", with data available up to {fr_min}." if fr_min else "."))

    # perioada, sezonul, zona
    ani = _ani(p.get("ANI")) or _ani(p.get("ANI_TINTA"))
    if motor == "climatograma":
        pa, pb = _ani(p.get("PERIOADA_A")), (_ani(p.get("PERIOADA_B")) if p.get("COMPARA") else None)
        ani = pa + (f" și {pb}" if pb else "") if pa else None
    per = p.get("PERIOADA")
    sez_ro, sez_en = _sezon(p.get("SEZON"))
    z_ro, z_en = _zona(p.get("ZONA"))
    if ani:
        ro.append(f"Perioada analizată: {ani}" + (f", {sez_ro}" if sez_ro else "") + f"; zona: {z_ro}.")
        en.append(f"Study period: {ani}" + (f", {sez_en}" if sez_en else "") + f"; area: {z_en}.")
    elif isinstance(per, (list, tuple)) and len(per) == 2:
        ro.append(f"Perioada analizată: {per[0]} – {per[1]}; zona: {z_ro}.")
        en.append(f"Study period: {per[0]} to {per[1]}; area: {z_en}.")
    else:
        ro.append(f"Zona: {z_ro}."); en.append(f"Area: {z_en}.")

    # indicatorii
    if titluri:
        lista = "; ".join(f"„{t}”" for t in titluri)
        lista_en = "; ".join(f"“{t}”" for t in titluri)
        cit = []
        for c in coduri:
            for r in REF_INDICATOR.get(c, []):
                if r not in refs:
                    refs.append(r)
                if SCURT[r] not in cit:
                    cit.append(SCURT[r])
        ro.append(f"Indicatorii calculați: {lista}" + (f" ({'; '.join(cit)})." if cit else "."))
        en.append(f"Indicators (names as in the program): {lista_en}" + (f" ({'; '.join(cit)})." if cit else "."))

    # metoda, pe motor
    un_an = isinstance(p.get("ANI"), (list, tuple)) and len(p["ANI"]) == 2 and p["ANI"][0] == p["ANI"][1]
    if motor in ("harta", "atlas", "altitudine") and un_an:
        ro.append("Indicatorii s-au calculat pentru fiecare pixel" + (", apoi s-au mediat pe zone." if motor == "atlas" else "."))
        en.append("The indicators were computed for each grid cell" + (", then averaged over each zone." if motor == "atlas" else "."))
    elif motor in ("harta", "atlas", "altitudine", "serii", "dungi"):
        ro.append("Fiecare indicator s-a calculat separat pentru fiecare an și pentru fiecare pixel; valoarea "
                  "multianuală este media valorilor anuale" + (", iar valorile pe zone sunt medii ale pixelilor zonei" if motor in ("atlas", "serii", "dungi") else "") + ".")
        en.append("Each indicator was computed separately for each year and each grid cell; the multi-year value is "
                  "the mean of the annual values" + (", and zonal values are averages of the grid cells within each zone" if motor in ("atlas", "serii", "dungi") else "") + ".")
        if motor == "dungi" or motor == "serii":
            ref = _ani(p.get("REFERINTA"))
            if ref:
                ro.append(f"Anomaliile sunt calculate față de media perioadei de referință {ref}.")
                en.append(f"Anomalies are relative to the {ref} reference-period mean.")
    elif motor == "anomalie":
        ref = _ani(p.get("ANI_REFERINTA"))
        mod = "relativă (%)" if str(p.get("MOD", "")).startswith("rel") else "absolută"
        ro.append(f"Anomalia ({mod}) compară media anilor țintă cu media perioadei de referință {ref or ''}, pixel cu pixel.".replace("  ", " "))
        en.append(f"The anomaly ({'relative, %' if mod.startswith('rel') else 'absolute'}) compares the target-period mean with the {ref or ''} reference-period mean, cell by cell.".replace("  ", " "))
    elif motor == "trend":
        alfa = p.get("ALFA", 0.05)
        alfa_ro = str(alfa).replace(".", ",")
        if p.get("METODA_TREND") == "sen_mk":
            for r in ("sen1968", "mann1945", "kendall1975"):
                if r not in refs:
                    refs.append(r)
            ro.append(f"Tendința s-a estimat pentru fiecare pixel prin panta Theil–Sen (Sen, 1968), iar semnificația prin "
                      f"testul Mann–Kendall (Mann, 1945; Kendall, 1975), cu pragul α = {alfa_ro}; tendințele nesemnificative "
                      f"sunt hașurate pe hartă.")
            en.append(f"Trends were estimated for each grid cell with the Theil–Sen slope (Sen, 1968) and tested with the "
                      f"Mann–Kendall test (Mann, 1945; Kendall, 1975) at α = {alfa}; non-significant trends are hatched.")
        else:
            ro.append(f"Tendința s-a estimat pentru fiecare pixel prin regresie liniară (metoda celor mai mici pătrate), "
                      f"iar semnificația prin testul t (distribuția Student), cu pragul α = {alfa_ro}; tendințele "
                      f"nesemnificative sunt hașurate pe hartă. Panta este exprimată pe deceniu.")
            en.append(f"Trends were estimated for each grid cell by ordinary least-squares linear regression and tested "
                      f"with Student's t test at α = {alfa}; non-significant trends are hatched. Slopes are per decade.")
    elif motor == "superlative":
        refs.append("coumou2012")
        ro.append("Recordurile s-au determinat prin compararea tuturor perioadelor candidate din anii analizați "
                  "(ferestre care nu se suprapun), fiecare candidat fiind acceptat doar cu cel puțin 90 % zile valide.")
        en.append("Records were identified by ranking all candidate periods in the study years (non-overlapping "
                  "windows), each accepted only with at least 90 % valid days.")
    elif motor == "climatograma":
        refs.append("walter1960")
        ro.append("Climatograma urmează convențiile Walter–Lieth (Walter & Lieth, 1960): temperatura medie lunară, "
                  "(Tmax + Tmin)/2, și precipitațiile medii lunare, la scara 10 °C ↔ 20 mm (perioadă aridă: P < 2T), "
                  "calculate din seria zilnică medie a zonei; o lună intră într-o perioadă doar dacă are date în cel "
                  "puțin 80 % din ani. Îngheț sigur: media minimelor lunii < 0 °C; probabil: minima absolută < 0 °C.")
        en.append("The climate diagram follows the Walter–Lieth conventions (Walter & Lieth, 1960): mean monthly "
                  "temperature, (Tmax + Tmin)/2, and mean monthly precipitation, scaled 10 °C ↔ 20 mm (arid period: "
                  "P < 2T), computed from the zone's mean daily series; a month enters a period only if it has data in "
                  "at least 80 % of the years. Certain frost: mean monthly minimum < 0 °C; probable: absolute minimum < 0 °C.")
    elif motor in ("statistici", "zonal"):
        ro.append("Statisticile s-au calculat din valorile zilnice, pe pixel" + (" și pe zone." if motor == "zonal" else "."))
        en.append("Statistics were computed from the daily values, per grid cell" + (" and per zone." if motor == "zonal" else "."))
    elif motor in ("episod_zilnic", "analiza_episod"):
        clim = _ani(p.get("CLIMATOLOGIE")) or _ani(p.get("REFERINTA"))
        ro.append("Episodul a fost analizat pe valorile zilnice" + (f", comparat cu climatologia {clim}." if clim else "."))
        en.append("The episode was analysed from the daily values" + (f", compared with the {clim} climatology." if clim else "."))

    # perioada de bază a indicatorilor pe percentile / SPI / SPEI
    pct, std = set(), set()
    for d in p.get("INDICATORI") or []:
        b = f"{d.get('baza_de', 1991)}–{d.get('baza_pana', 2020)}"
        if d.get("cod") in ("pct_zile", "wsdi", "csdi", "rnnp", "rnnptot"):
            pct.add(b)
        elif d.get("cod") in ("spi", "spei"):
            std.add(b)
    if pct:
        b = ", ".join(sorted(pct))
        ro.append(f"Pragurile pe percentile s-au calculat pe perioada de bază {b} (pentru fiecare zi a anului, pe o "
                  f"fereastră centrată).")
        en.append(f"Percentile thresholds were computed over the {b} base period (for each calendar day, on a centred window).")
    if std:
        b = ", ".join(sorted(std))
        ro.append(f"Distribuțiile SPI (gamma) și SPEI (log-logistică, prin L-momente) s-au ajustat pe pixel, pe perioada "
                  f"de bază {b}, pentru aceeași perioadă a anului.")
        en.append(f"The SPI (gamma) and SPEI (log-logistic, L-moments) distributions were fitted per grid cell over the "
                  f"{b} base period, for the same part of the year.")

    # validitatea și golurile
    prag = int(round(100 * float(st.get("PRAG_VALID", 0.9))))
    ro.append(f"O valoare anuală (sau sezonieră) s-a calculat pentru un pixel doar dacă perioada avea cel puțin {prag} % "
              f"zile cu date; sumele s-au corectat proporțional pentru zilele lipsă, iar perioadele incomplete "
              + ("au fost acceptate (setare explicită)." if st.get("ACCEPTA_PARTIAL") else "au fost excluse."))
    en.append(f"An annual (or seasonal) value was computed for a grid cell only if at least {prag} % of the days had "
              f"data; sums were scaled for missing days, and incomplete periods were "
              + ("accepted (explicit setting)." if st.get("ACCEPTA_PARTIAL") else "excluded."))
    if fisa.get("avertisment_date"):
        m = re.search(r"Zile afectate: ([^.]*)\.", fisa["avertisment_date"])
        ro.append("Golurile din cub (fragmente lipsă sau nescrise) au fost tratate ca date lipsă"
                  + (f"; zile afectate: {m.group(1)}." if m else "."))
        en.append("Gaps in the data cube (missing or unwritten chunks) were treated as missing data"
                  + (f"; affected days: {m.group(1)}." if m else "."))
    an = (fisa.get("pornit") or "2026")[:4]
    ro.append(f"Calculele au fost făcute cu Clima ANM {versiune} (Budileanu, {an}).".replace("  ", " "))
    en.append(f"Computations used Clima ANM {versiune} (Budileanu, {an}).".replace("  ", " "))
    refs.insert(0, "program")
    referinte = sorted((REF[r].format(an=an, versiune=versiune or "–") for r in dict.fromkeys(refs)), key=str.lower)
    return {"ro": " ".join(ro), "en": " ".join(en), "referinte": referinte}


def scrie_md(out: Path, m: dict) -> Path:
    t = ["# Date și metode", "", m["ro"], "", "## Data and methods", "", m["en"], "", "## Bibliografie / References", ""]
    t += [f"- {r}" for r in m["referinte"]]
    f = Path(out) / "metode.md"
    f.write_text("\n".join(t) + "\n", encoding="utf-8")
    return f
