# -*- coding: utf-8 -*-
"""
indicatori.py — REGISTRUL indicatorilor climatici
=================================================
Un indicator = o funcție (date zilnice pe o perioadă → o hartă 2D) + descrierea ei: parametri, variabile, unitate,
titlu, paletă. Odată înregistrat, indicatorul apare AUTOMAT în toate motoarele (hartă, anomalie, tendință, atlas…)
și în interfață, cu formularul parametrilor lui.

Un indicator nou = o funcție în zarr_clima.py (sau aici) + un apel `inregistreaza(...)`. Exemplu:

    inregistreaza(
        "zile_vara", "Zile de vară (Tmax > 25 °C)", zc.i_zile_peste, grup="Temperatură",
        variabile=("max_temp",), unitate="zile", cmap="YlOrRd",
        fixati={"var": "max_temp", "prag": 25.0, "strict": True},
        descriere="SU25 (ETCCDI): numărul de zile cu Tmax > 25 °C.")

Parametrii unui indicator se descriu cu aceleași tipuri de câmpuri ca formularele interfeței
(„alegere”, „numar”, „bifa”), deci interfața îi poate afișa fără cod suplimentar.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import zarr_clima as zc

VAR_NUME = {"max_temp": "Tmax", "min_temp": "Tmin", "precipitation": "P"}
VAR_FISIER = {"max_temp": "tmax", "min_temp": "tmin", "precipitation": "p"}
VAR_OPTIUNI = [["max_temp", "Tmax (temperatura maximă)"], ["min_temp", "Tmin (temperatura minimă)"],
               ["precipitation", "P (precipitații)"]]
TEMP_OPTIUNI = VAR_OPTIUNI[:2]

P_VAR = {"nume": "var", "tip": "alegere", "eticheta": "Variabila", "optiuni": VAR_OPTIUNI, "implicit": "max_temp"}
P_VAR_T = {"nume": "var", "tip": "alegere", "eticheta": "Variabila", "optiuni": TEMP_OPTIUNI, "implicit": "max_temp"}


def _g(x):
    """30.0 → „30”, 0.5 → „0,5” (titluri); în numele fișierelor punctul devine „p”."""
    return f"{x:g}".replace(".", ",")


def _gf(x):
    return f"{x:g}".replace(".", "p").replace("-", "m")


@dataclass
class DefIndicator:
    cod: str
    titlu: object                    # str sau funcție(params) → str
    functie: object                  # f(d, zile, **params) → ndarray 2D
    grup: str = "Altele"
    variabile: object = ()           # tuple sau funcție(params) → tuple
    unitate: object = ""             # str sau funcție(params) → str
    cmap: object = "viridis"         # str sau funcție(params) → str
    parametri: list = field(default_factory=list)
    fixati: dict = field(default_factory=dict)      # parametri impuși (nu apar în formular)
    descriere: str = ""
    cod_fisier: object = None        # funcție(params) → sufixul fișierelor; implicit = cod
    sezon_anual: bool = False        # indicatorul cere SEZON = "anual" (ex. înghețuri)
    nume: str = ""                   # numele generic, în formular (titlul depinde de parametri)
    pregatire: object = None         # f(cub, fr, g, sezon, ind) → context din perioada de bază (vezi zarr_clima)

    def _v(self, x, p):
        return x(p) if callable(x) else x

    def implicite(self):
        p = {c["nume"]: c.get("implicit") for c in self.parametri}
        p.update(self.fixati)
        return p

    def construieste(self, **params) -> zc.Indicator:
        p = self.implicite()
        necunoscuti = set(params) - set(p) - {"cod"}
        if necunoscuti:
            raise ValueError(f"Indicatorul „{self.cod}” nu are parametrii {sorted(necunoscuti)}; "
                             f"are: {sorted(c['nume'] for c in self.parametri) or 'niciunul'}")
        p.update({k: v for k, v in params.items() if k != "cod" and k not in self.fixati})
        for c in self.parametri:                       # conversii și validări simple
            v = p.get(c["nume"])
            if c["tip"] == "numar":
                if v is None:
                    raise ValueError(f"{self.cod}: parametrul „{c['eticheta']}” lipsește")
                if self.cod == "rxnday" and c["nume"] == "n":
                    if not float(v).is_integer():
                        raise ValueError("RxNday cere un număr întreg de zile.")
                    v = int(v)
                else:
                    v = float(v) if c.get("pas", 1) != 1 or isinstance(v, float) else int(v)
                if "min" in c and v < c["min"] or "max" in c and v > c["max"]:
                    raise ValueError(f"{self.cod}: „{c['eticheta']}” = {v} în afara intervalului "
                                     f"[{c.get('min', '-∞')}, {c.get('max', '∞')}]")
            elif c["tip"] == "alegere" and v not in [o[0] for o in c["optiuni"]]:
                raise ValueError(f"{self.cod}: „{c['eticheta']}” = {v!r} nu este o opțiune validă")
            elif c["tip"] == "bifa":
                v = bool(v)
            p[c["nume"]] = v
        if "baza_de" in p and "baza_pana" in p and p["baza_pana"] - p["baza_de"] + 1 < 10:
            raise ValueError(f"{self.cod}: perioada de bază {p['baza_de']}–{p['baza_pana']} are sub 10 ani "
                             f"(OMM recomandă 30: normala actuală 1991–2020).")
        cod_f = self.cod_fisier(p) if self.cod_fisier else self.cod
        argumente = {k: v for k, v in p.items() if k in _argumente(self.functie)}
        return zc.Indicator(cod_f, self._v(self.titlu, p), self.functie, tuple(self._v(self.variabile, p)),
                            self._v(self.unitate, p), self._v(self.cmap, p), argumente, pregatire=self.pregatire)

    def descriere_json(self):
        return {"cod": self.cod, "titlu": self.nume or (self.titlu if isinstance(self.titlu, str) else self.titlu(self.implicite())),
                "grup": self.grup, "descriere": self.descriere, "parametri": self.parametri,
                "sezon_anual": self.sezon_anual,
                "variabile": list(self._v(self.variabile, self.implicite()))}


def _argumente(f):
    import inspect
    return set(list(inspect.signature(f).parameters)[2:])


REGISTRU: dict[str, DefIndicator] = {}


def inregistreaza(cod, titlu, functie, **kw):
    if cod in REGISTRU:
        raise ValueError(f"Indicatorul „{cod}” este deja înregistrat.")
    REGISTRU[cod] = DefIndicator(cod, titlu, functie, **kw)
    return REGISTRU[cod]


def construieste(cod, **params) -> zc.Indicator:
    if cod not in REGISTRU:
        import difflib
        sug = difflib.get_close_matches(cod, REGISTRU, n=3)
        raise KeyError(f"Indicator necunoscut: „{cod}”" + (f" — poate: {', '.join(sug)}" if sug else "") +
                       f". Disponibili: {', '.join(REGISTRU)}")
    return REGISTRU[cod].construieste(**params)


def din_dict(d: dict) -> zc.Indicator:
    """{"cod": "zile_peste", "var": "max_temp", "prag": 30} → Indicator"""
    d = dict(d)
    return construieste(d.pop("cod"), **d)


def coduri_unice(indicatori):
    """Două rânduri cu același sufix de fișier (ex. același prag de două ori) ar suprascrie fișierele."""
    vazute = {}
    for ind in indicatori:
        if ind.cod in vazute:
            vazute[ind.cod] += 1
            ind.cod = f"{ind.cod}_{vazute[ind.cod]}"
        else:
            vazute[ind.cod] = 1
    return indicatori


# =====================================================================================
# Indicatorii (funcțiile de calcul sunt în zarr_clima.py: i_…)
# =====================================================================================
_U = lambda p: zc.UNITATI.get(p["var"], "")                                   # noqa: E731
_semn = lambda p, mare: (">" if p.get("strict") else "≥") if mare else ("<" if p.get("strict", True) else "≤")  # noqa: E731

inregistreaza(
    "medie", lambda p: f"{VAR_NUME[p['var']]} medie", zc.i_medie, nume="Media zilnică", grup="Medii și sume",
    variabile=lambda p: (p["var"],), unitate=lambda p: "mm/zi" if p["var"] == "precipitation" else _U(p),
    cmap=lambda p: "Blues" if p["var"] == "precipitation" else "RdYlBu_r",
    parametri=[P_VAR], cod_fisier=lambda p: f"medie_{VAR_FISIER[p['var']]}",
    descriere="Media valorilor zilnice pe perioadă (la precipitații: mm/zi).")

inregistreaza(
    "tmedie", "Temperatura medie (Tmax + Tmin) / 2", zc.i_tmedie, grup="Medii și sume",
    variabile=("max_temp", "min_temp"), unitate="°C", cmap="RdYlBu_r",
    descriere="Temperatura medie zilnică aproximată ca (Tmax + Tmin) / 2, mediată pe perioadă.")

inregistreaza(
    "suma", lambda p: f"{VAR_NUME[p['var']]} — suma pe perioadă", zc.i_suma, nume="Suma pe perioadă", grup="Medii și sume",
    variabile=lambda p: (p["var"],), unitate=_U, cmap="YlGnBu",
    parametri=[dict(P_VAR, implicit="precipitation")], cod_fisier=lambda p: f"suma_{VAR_FISIER[p['var']]}",
    descriere="Suma valorilor zilnice pe perioadă (precipitații totale, mm). Include toate zilele, nu doar ≥ 1 mm.")

inregistreaza(
    "zile_peste", lambda p: f"Zile cu {VAR_NUME[p['var']]} {_semn(p, True)} {_g(p['prag'])} {_U(p)}",
    zc.i_zile_peste, nume="Zile peste prag", grup="Praguri și extreme",
    variabile=lambda p: (p["var"],), unitate="zile",
    cmap=lambda p: "PuBuGn" if p["var"] == "precipitation" else "YlOrRd",
    parametri=[P_VAR, {"nume": "prag", "tip": "numar", "eticheta": "Prag", "implicit": 30.0, "pas": 0.1},
               {"nume": "strict", "tip": "bifa", "eticheta": "strict (> în loc de ≥)", "implicit": False}],
    cod_fisier=lambda p: f"{VAR_FISIER[p['var']]}_{'gt' if p['strict'] else 'ge'}_{_gf(p['prag'])}",
    descriere="Numărul de zile peste prag. Tmax ≥ 30 °C = zi tropicală, ≥ 35 °C = zi caniculară (ANM); "
              "Tmax > 25 °C = zi de vară (SU25); Tmin > 20 °C = noapte tropicală (TR); P ≥ 10 mm = R10mm (ETCCDI).")

inregistreaza(
    "zile_sub", lambda p: f"Zile cu {VAR_NUME[p['var']]} {_semn(p, False)} {_g(p['prag'])} {_U(p)}",
    zc.i_zile_sub, nume="Zile sub prag", grup="Praguri și extreme",
    variabile=lambda p: (p["var"],), unitate="zile", cmap="PuBu",
    parametri=[dict(P_VAR, implicit="min_temp"),
               {"nume": "prag", "tip": "numar", "eticheta": "Prag", "implicit": 0.0, "pas": 0.1},
               {"nume": "strict", "tip": "bifa", "eticheta": "strict (< în loc de ≤)", "implicit": True}],
    cod_fisier=lambda p: f"{VAR_FISIER[p['var']]}_{'lt' if p['strict'] else 'le'}_{_gf(p['prag'])}",
    descriere="Numărul de zile sub prag. Tmin < 0 °C = zi de îngheț (FD); Tmax < 0 °C = zi de iarnă (ID); "
              "Tmin ≤ −10 °C = zi geroasă.")

inregistreaza(
    "amplitudine_medie", "Amplitudinea termică diurnă medie (Tmax − Tmin)", zc.i_amplitudine_medie,
    grup="Temperatură", variabile=("max_temp", "min_temp"), unitate="°C", cmap="magma_r",
    descriere="DTR (ETCCDI): media diferenței zilnice Tmax − Tmin.")

inregistreaza(
    "amplitudine_absoluta", "Amplitudinea termică extremă max(Tmax) − min(Tmin)", zc.i_amplitudine_absoluta,
    grup="Temperatură", variabile=("max_temp", "min_temp"), unitate="°C", cmap="magma_r",
    descriere="Diferența dintre cea mai mare Tmax și cea mai mică Tmin a perioadei (TXx − TNn).")

inregistreaza(
    "gdd", lambda p: f"Grade-zile de creștere (bază {_g(p['baza'])} °C)", zc.i_gdd, nume="Grade-zile de creștere (GDD)", grup="Agroclimatic",
    variabile=("max_temp", "min_temp"), unitate="°C·zile", cmap="YlGn",
    parametri=[{"nume": "baza", "tip": "numar", "eticheta": "Temperatura de bază (°C)", "implicit": 10.0, "pas": 0.5}],
    cod_fisier=lambda p: f"gdd_{_gf(p['baza'])}",
    descriere="Σ max((Tmax + Tmin)/2 − bază, 0). Baza 10 °C: porumb, vița-de-vie; 5 °C: cereale păioase.")

_P_INGHET = [{"nume": "prag", "tip": "numar", "eticheta": "Prag Tmin (°C)", "implicit": 0.0, "pas": 0.5}]
_sufix_prag = lambda p: "" if p["prag"] == 0 else f"_{_gf(p['prag'])}"   # noqa: E731

inregistreaza(
    "ultimul_inghet", "Ultimul îngheț de primăvară (ziua din an)", zc.i_ultimul_inghet, grup="Agroclimatic",
    variabile=("min_temp",), unitate="ziua din an", cmap="viridis_r", parametri=_P_INGHET, sezon_anual=True,
    cod_fisier=lambda p: "ultimul_inghet" + _sufix_prag(p),
    descriere="Ultima zi cu Tmin < prag între 1 ianuarie și 30 iunie. Cere sezonul „anual”.")

inregistreaza(
    "primul_inghet", "Primul îngheț de toamnă (ziua din an)", zc.i_primul_inghet, grup="Agroclimatic",
    variabile=("min_temp",), unitate="ziua din an", cmap="viridis", parametri=_P_INGHET, sezon_anual=True,
    cod_fisier=lambda p: "primul_inghet" + _sufix_prag(p),
    descriere="Prima zi cu Tmin < prag între 1 iulie și 31 decembrie. Cere sezonul „anual”.")

inregistreaza(
    "sezon_fara_inghet", "Durata sezonului fără îngheț", zc.i_sezon_fara_inghet, grup="Agroclimatic",
    variabile=("min_temp",), unitate="zile", cmap="YlGn", parametri=_P_INGHET, sezon_anual=True,
    cod_fisier=lambda p: "sezon_fara_inghet" + _sufix_prag(p),
    descriere="Primul îngheț de toamnă − ultimul îngheț de primăvară (zile). Cere sezonul „anual”.")

inregistreaza(
    "cdd", lambda p: f"Cel mai lung șir de zile cu P < {_g(p['prag'])} mm (CDD)", zc.i_cdd, nume="Cel mai lung șir de zile uscate (CDD)", grup="Precipitații",
    variabile=("precipitation",), unitate="zile", cmap="YlOrBr",
    parametri=[{"nume": "prag", "tip": "numar", "eticheta": "Prag zi uscată (mm)", "implicit": 1.0, "pas": 0.1}],
    cod_fisier=lambda p: "cdd" if p["prag"] == 1 else f"cdd_{_gf(p['prag'])}",
    descriere="CDD (ETCCDI): cel mai lung șir de zile consecutive cu precipitații sub prag.")

P_ZI_UDA = {"nume": "prag", "tip": "numar", "eticheta": "Prag zi ploioasă (mm)", "implicit": 1.0, "pas": 0.1, "min": 0.1}

inregistreaza(
    "cwd", lambda p: f"Cel mai lung șir de zile cu P ≥ {_g(p['prag'])} mm (CWD)", zc.i_cwd,
    nume="Cel mai lung șir de zile ploioase (CWD)", grup="Precipitații",
    variabile=("precipitation",), unitate="zile", cmap="GnBu", parametri=[P_ZI_UDA],
    cod_fisier=lambda p: "cwd" if p["prag"] == 1 else f"cwd_{_gf(p['prag'])}",
    descriere="CWD (ETCCDI): cel mai lung șir de zile consecutive cu precipitații de cel puțin 1 mm.")

inregistreaza(
    "sdii", lambda p: f"Intensitatea medie a zilelor cu P ≥ {_g(p['prag'])} mm (SDII)", zc.i_sdii,
    nume="Intensitatea zilnică a precipitațiilor (SDII)", grup="Precipitații",
    variabile=("precipitation",), unitate="mm/zi", cmap="GnBu", parametri=[P_ZI_UDA],
    cod_fisier=lambda p: "sdii" if p["prag"] == 1 else f"sdii_{_gf(p['prag'])}",
    descriere="SDII (ETCCDI): cât plouă, în medie, într-o zi ploioasă (suma zilelor ≥ 1 mm / numărul lor).")

inregistreaza(
    "prcptot", lambda p: f"Precipitațiile din zilele cu P ≥ {_g(p['prag'])} mm (PRCPTOT)", zc.i_prcptot,
    nume="Precipitațiile zilelor ploioase (PRCPTOT)", grup="Precipitații",
    variabile=("precipitation",), unitate="mm", cmap="Blues", parametri=[P_ZI_UDA],
    cod_fisier=lambda p: "prcptot" if p["prag"] == 1 else f"prcptot_{_gf(p['prag'])}",
    descriere="PRCPTOT (ETCCDI): suma precipitațiilor din zilele cu cel puțin 1 mm (urmele nu intră).")

inregistreaza(
    "rxnday", lambda p: f"Rx{p['n']}day: maximul precipitațiilor în {p['n']} " + ("zi" if p["n"] == 1 else "zile consecutive"),
    zc.i_rxnday, nume="Maximul precipitațiilor în n zile (RxNday)", grup="Precipitații", variabile=("precipitation",), unitate="mm", cmap="GnBu",
    parametri=[{"nume": "n", "tip": "numar", "eticheta": "Numărul de zile", "implicit": 1, "min": 1, "max": 30}],
    cod_fisier=lambda p: f"rx{p['n']}day",
    descriere="Rx1day / Rx5day (ETCCDI): cantitatea maximă căzută în n zile consecutive.")

inregistreaza(
    "de_martonne", "Indicele de ariditate De Martonne", zc.i_de_martonne, grup="Precipitații",
    variabile=("precipitation", "max_temp", "min_temp"), unitate="", cmap="BrBG",
    descriere="I = P_an / (T + 10). Clase: < 10 arid · 10–20 semiarid · 20–24 mediteranean · 24–28 semiumed · "
              "28–35 umed · > 35 foarte umed.")


def catalog(cu_teorie=True):
    rez = {c: d.descriere_json() for c, d in REGISTRU.items()}
    if cu_teorie:
        import inspect
        try:
            import teorie_indicatori as ti
        except ImportError:
            ti = None
        for c, d in REGISTRU.items():
            try:
                rez[c]["cod_sursa"] = inspect.getsource(d.functie)
            except (OSError, TypeError):
                rez[c]["cod_sursa"] = ""
            rez[c]["teorie"] = (ti.TEORIE.get(c) if ti else None)
    return rez


def metode():
    """Fișele metodelor statistice (tendințe, sensibilitate, agregarea pe zone), cu codul exact al funcțiilor."""
    import inspect
    try:
        import teorie_indicatori as ti
        import zarr_clima as zc
    except ImportError:
        return {}
    rez = {}
    for cod, d in getattr(ti, "METODE", {}).items():
        d = dict(d)
        surse = []
        for f in d.pop("functii", []):
            try:
                if "." in f:                                   # „modul.functie” (ex. zarr_superlative.candidati)
                    import importlib
                    mod, nume_f = f.rsplit(".", 1)
                    surse.append(inspect.getsource(getattr(importlib.import_module(mod), nume_f)))
                else:
                    surse.append(inspect.getsource(getattr(zc, f)))
            except (AttributeError, OSError, TypeError, ImportError):
                pass
        rez[cod] = dict(titlu=d.pop("titlu"), grup="Metode statistice", teorie=d, cod_sursa="\n\n".join(surse))
    return rez


def pasi_comuni():
    try:
        import teorie_indicatori as ti
        return ti.PASI_COMUNI
    except ImportError:
        return []


# =====================================================================================
# Indicatori cu perioadă de bază (v5.0 livrarea B): percentile ETCCDI, bilanț hidric, SPI, SPEI
# Perioada de bază implicită: normala climatologică OMM actuală, 1991–2020 (modificabilă în formular).
# =====================================================================================
P_BAZA = [{"nume": "baza_de", "tip": "numar", "eticheta": "Perioada de bază: de la anul", "implicit": 1991, "min": 1961, "max": 2100},
          {"nume": "baza_pana", "tip": "numar", "eticheta": "până la anul", "implicit": 2020, "min": 1961, "max": 2100}]
_b = lambda p: f"{p['baza_de']}–{p['baza_pana']}"                                       # noqa: E731
_bf = lambda p: "" if (p["baza_de"], p["baza_pana"]) == (1991, 2020) else f"_b{p['baza_de']}{p['baza_pana']}"  # noqa: E731
_PCT_TEXT = {"tx90p": ("TX90p", "Tmax > p90"), "tx10p": ("TX10p", "Tmax < p10"),
             "tn90p": ("TN90p", "Tmin > p90"), "tn10p": ("TN10p", "Tmin < p10")}

inregistreaza(
    "pct_zile", lambda p: f"{_PCT_TEXT[p['indice']][0]}: % zile cu {_PCT_TEXT[p['indice']][1]} al zilei (bază {_b(p)})",
    zc.i_pct_zile, nume="Zile calde / reci după percentile (TX90p, TN90p, TX10p, TN10p)", grup="Percentile (ETCCDI)",
    variabile=lambda p: (zc.INDICI_PCT[p["indice"]][0],), unitate="% din zile",
    cmap=lambda p: "YlOrRd" if p["indice"].endswith("90p") else "PuBu",
    parametri=[{"nume": "indice", "tip": "alegere", "eticheta": "Indicele",
                "optiuni": [["tx90p", "TX90p — zile calde (Tmax > p90)"], ["tn90p", "TN90p — nopți calde (Tmin > p90)"],
                            ["tx10p", "TX10p — zile reci (Tmax < p10)"], ["tn10p", "TN10p — nopți reci (Tmin < p10)"]],
                "implicit": "tx90p"}] + P_BAZA,
    cod_fisier=lambda p: p["indice"] + _bf(p), pregatire=zc._preg_pct,
    descriere="Procentul zilelor mai calde (reci) decât percentila 90 (10) a aceleiași zile calendaristice în perioada "
              "de bază. Prin construcție ≈ 10 % în anii de bază; peste 10 % = mai multe extreme decât în normală.")

_P_DURATA = {"nume": "durata", "tip": "numar", "eticheta": "Durata minimă a șirului (zile)", "implicit": 6, "min": 2, "max": 30}

inregistreaza(
    "wsdi", lambda p: f"WSDI: zile în șiruri de ≥ {p['durata']} zile cu Tmax > p90 (bază {_b(p)})", zc.i_wsdi,
    nume="Durata valurilor de căldură (WSDI)", grup="Percentile (ETCCDI)", variabile=("max_temp",), unitate="zile",
    cmap="YlOrRd", parametri=[_P_DURATA] + P_BAZA, pregatire=zc._preg_pct,
    cod_fisier=lambda p: ("wsdi" if p["durata"] == 6 else f"wsdi{p['durata']}") + _bf(p),
    descriere="WSDI (ETCCDI): numărul de zile care fac parte din șiruri de cel puțin 6 zile consecutive cu Tmax peste "
              "percentila 90 a zilei calendaristice. Un indicator al valurilor de căldură relativ la clima locului.")

inregistreaza(
    "csdi", lambda p: f"CSDI: zile în șiruri de ≥ {p['durata']} zile cu Tmin < p10 (bază {_b(p)})", zc.i_csdi,
    nume="Durata valurilor de frig (CSDI)", grup="Percentile (ETCCDI)", variabile=("min_temp",), unitate="zile",
    cmap="PuBu", parametri=[_P_DURATA] + P_BAZA, pregatire=zc._preg_pct,
    cod_fisier=lambda p: ("csdi" if p["durata"] == 6 else f"csdi{p['durata']}") + _bf(p),
    descriere="CSDI (ETCCDI): numărul de zile care fac parte din șiruri de cel puțin 6 zile consecutive cu Tmin sub "
              "percentila 10 a zilei calendaristice.")

_P_PCT_P = {"nume": "percentila", "tip": "alegere", "eticheta": "Percentila zilelor ploioase",
            "optiuni": [["95", "p95 (R95p)"], ["99", "p99 (R99p)"]], "implicit": "95"}

inregistreaza(
    "rnnp", lambda p: f"R{p['percentila']}p: precipitațiile zilelor cu P > p{p['percentila']} (bază {_b(p)})", zc.i_rnnp,
    nume="Precipitații din zilele foarte ploioase (R95p, R99p)", grup="Percentile (ETCCDI)",
    variabile=("precipitation",), unitate="mm", cmap="GnBu", parametri=[_P_PCT_P] + P_BAZA, pregatire=zc._preg_umed,
    cod_fisier=lambda p: f"r{p['percentila']}p" + _bf(p),
    descriere="R95p (ETCCDI): suma precipitațiilor din zilele mai ploioase decât percentila 95 a zilelor cu P ≥ 1 mm "
              "din perioada de bază (R99p: percentila 99).")

inregistreaza(
    "rnnptot", lambda p: f"R{p['percentila']}pTOT: % din precipitații căzute în zilele cu P > p{p['percentila']} (bază {_b(p)})",
    zc.i_rnnptot, nume="Ponderea zilelor foarte ploioase (R95pTOT, R99pTOT)", grup="Percentile (ETCCDI)",
    variabile=("precipitation",), unitate="% din PRCPTOT", cmap="GnBu", parametri=[_P_PCT_P] + P_BAZA, pregatire=zc._preg_umed,
    cod_fisier=lambda p: f"r{p['percentila']}ptot" + _bf(p),
    descriere="R95pTOT (ETCCDI): ce procent din precipitațiile zilelor ploioase (PRCPTOT) a căzut în zilele "
              "mai ploioase decât percentila 95 a perioadei de bază. Crește când ploaia se concentrează în episoade intense.")

inregistreaza(
    "pet", "Evapotranspirația potențială (Hargreaves)", zc.i_pet, grup="Secetă și bilanț hidric",
    variabile=("max_temp", "min_temp"), unitate="mm", cmap="YlOrBr", pregatire=zc._preg_lat,
    descriere="PET Hargreaves–Samani (FAO-56): cât ar evapora și transpira o suprafață bine aprovizionată cu apă, "
              "estimat din temperaturi și radiația extraterestră. Suma pe perioadă.")

inregistreaza(
    "bilant", "Bilanțul climatic al apei P − PET", zc.i_bilant, grup="Secetă și bilanț hidric",
    variabile=("precipitation", "max_temp", "min_temp"), unitate="mm", cmap="BrBG", pregatire=zc._preg_lat,
    descriere="Σ (P − PET Hargreaves) pe perioadă. Negativ = atmosfera „cere” mai multă apă decât cade. Baza SPEI.")

inregistreaza(
    "spi", lambda p: f"SPI: indicele standardizat al precipitațiilor (bază {_b(p)})", zc.i_spi,
    nume="SPI — indicele standardizat al precipitațiilor", grup="Secetă și bilanț hidric",
    variabile=("precipitation",), unitate="", cmap="BrBG", parametri=list(P_BAZA), pregatire=zc._preg_standardizat,
    cod_fisier=lambda p: "spi" + _bf(p),
    descriere="SPI (OMM, 2012): precipitațiile perioadei alese, exprimate ca abatere standardizată față de aceeași "
              "perioadă din anii de bază (distribuția gamma). Scara = durata sezonului ales (anual = SPI-12, "
              "iunie–august = SPI-3). Sub −1 secetă moderată, sub −1,5 severă, sub −2 extremă.")

inregistreaza(
    "spei", lambda p: f"SPEI: indicele standardizat al bilanțului P − PET (bază {_b(p)})", zc.i_spei,
    nume="SPEI — indicele standardizat precipitații–evapotranspirație", grup="Secetă și bilanț hidric",
    variabile=("precipitation", "max_temp", "min_temp"), unitate="", cmap="BrBG", parametri=list(P_BAZA),
    pregatire=zc._preg_standardizat, cod_fisier=lambda p: "spei" + _bf(p),
    descriere="SPEI (Vicente-Serrano et al., 2010): ca SPI, dar pe bilanțul P − PET (Hargreaves), cu distribuția "
              "log-logistică. Ține cont și de căldură: aceeași ploaie într-o vară mai caldă înseamnă secetă mai mare.")
