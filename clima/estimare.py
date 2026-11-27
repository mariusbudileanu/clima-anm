# -*- coding: utf-8 -*-
"""
estimare.py — câte date va descărca o analiză, ÎNAINTE de a o rula
==================================================================
Pentru fiecare motor: lista citirilor pe care le face nucleul (variabilă × interval de zile × fereastra zonei),
transformată în chunk-uri Zarr, GB și minute. Nu descarcă date: deschide doar metadatele cubului.

Viteza implicită (10 MB/s) e măsurată pe HTTPS, de pe un laptop (2,43 GB în ~245 s). Se poate schimba cu
variabila de mediu CLIMA_MBS. Cache-ul (serii, ferestre) nu e luat în calcul: estimarea e pentru prima rulare.
"""
from __future__ import annotations

import json
import os

import numpy as np
from pathlib import Path

import indicatori as ri
import zarr_clima as zc

MBS = float(os.environ.get("CLIMA_MBS", "10"))

# ------------------------------------------------------------------ memorie și timp de calcul (v5.1)
# Calibrate pe un calculator de referință (2 nuclee, 7 GB) cu instrumente/masoara_resurse.py și
# instrumente/calibreaza_indicatori.py; ultimul scrie clima/cost_indicatori.json (cost pe indicator).
RAM_BAZA_MB = 230            # Python + numpy, xarray, GDAL, matplotlib, cubul deschis
NS_GENERIC = 5.0             # ns / pixel-zi pentru motoarele fără indicatori (medii, statistici zonale)
NS_PRAG_ZILNIC = 80.0        # ns / pixel-zi de bază: pragurile percentile pe zi calendaristică (365 sortări)
NS_SEN = 19.0                # ns / (pixel × n_ani²): Theil–Sen + Mann–Kendall
S_FIX, S_PE_IESIRE = 1.5, 0.8
_COST = None


def _cost():
    global _COST
    if _COST is None:
        try:
            _COST = json.loads((Path(__file__).with_name("cost_indicatori.json")).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _COST = {}
    return _COST


def memorie_disponibila_mb():
    """Memoria fizică disponibilă acum (MB), fără biblioteci externe: Linux /proc, Windows GlobalMemoryStatusEx,
    macOS sysctl (memoria totală). None dacă nu se poate afla."""
    import sys
    try:
        if sys.platform.startswith("linux"):
            for l in open("/proc/meminfo", encoding="ascii"):
                if l.startswith("MemAvailable:"):
                    return int(l.split()[1]) // 1024
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return int(m.ullAvailPhys // 2**20)
        if sys.platform == "darwin":
            import subprocess
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) // 2**20
    except Exception:  # noqa: BLE001
        pass
    return None


def resurse(motor, p, grupuri):
    """Memoria de vârf (MB) și timpul de calcul (s, fără descărcare) din lista citirilor grupate:
    grupuri = [(desc, (variabile…), zile, pixeli, mb_comprimat)]. Modelul (v5.1, cu citirea pe bucăți de chunk,
    indicatorii pe benzi de rânduri și variabilele încărcate la cerere):
      RAM = bază + zile_simultane × pixeli × 4 o × variabilele celui mai „lacom” indicator + bucata de citire
            (+ pragurile percentile sau stiva tendinței, unde e cazul);
      timp = citire × s/GB + Σ indicatori pixeli × zile × ns + praguri / Theil–Sen + ieșiri."""
    c = _cost()
    ns = c.get("ns_pixel_zi", {})
    s_gb = min(c.get("citire_s_per_gb", 9.0), 9.0)          # rulările complete citesc mai repede decât un an izolat
    inds = [ri.din_dict(d) for d in (p.get("INDICATORI") or [])]
    nv_ind = max((len(i.variabile) for i in inds), default=None)
    bloc = motor in ("statistici", "zonal")                  # citesc pe blocuri de 90 de zile
    ram = calc = 0.0
    for desc, variabile, zile, px, mb in grupuri:
        calc += mb / 1000 * s_gb
        baza = desc.startswith("perioada de bază")
        z_mem = min(zile, 90) if bloc else zile
        nv = nv_ind if (nv_ind and not baza) else len(variabile)
        r = (z_mem * nv + 2 * min(zile, 90)) * px * 4 / 2**20
        if baza and any(i.functie in (zc.i_pct_zile, zc.i_wsdi, zc.i_csdi, zc.i_rnnp, zc.i_rnnptot) for i in inds):
            r = 365 * px * 4 / 2**20 + zile * min(px, 161 * 81) * 4 * 1.3 / 2**20     # pragurile + blocul de lucru
            calc += zile * px * NS_PRAG_ZILNIC / 1e9
        ram = max(ram, r)
        if inds and not baza:
            calc += zile * px * sum(ns.get(i.functie.__name__[2:], ns.get(_cod_reg(i), 8.0)) for i in inds) / 1e9
        elif not inds:
            calc += zile * px * len(variabile) * NS_GENERIC / 1e9
    if motor == "trend" and inds:
        n_ani = p["ANI"][1] - p["ANI"][0] + 1
        px = max((g[3] for g in grupuri), default=0)
        ram += n_ani * px * 4 * len(inds) * 2 / 2**20
        if p.get("METODA_TREND") == "sen":
            calc += NS_SEN * px * n_ani ** 2 * len(inds) / 1e9
    calc *= {"analiza_episod": 2.5, "zonal": 0.4}.get(motor, 1.0)   # calcul pe date atipic (măsurat, v5.1)
    calc += S_FIX + S_PE_IESIRE * max(1, len(inds))
    return RAM_BAZA_MB + ram, calc


def _cod_reg(ind):
    """Codul din registru al unui indicator construit (după funcție)."""
    for cod, d in ri.REGISTRU.items():
        if d.functie is ind.functie:
            return cod
    return ""


def _vars(v):
    return ("max_temp", "min_temp") if v == "tmedie" else (v,)


def _vars_indicatori(p):
    v = []
    for d in p.get("INDICATORI") or []:
        for x in ri.din_dict(d).variabile:
            if x not in v:
                v.append(x)
    return v


def _d(x):
    return np.datetime64(str(x)[:10], "D")


def _ani(interval, sezon, frontiera, eticheta, inceput=np.datetime64("1961-01-01", "D")):
    """Câte o citire pe an (așa citește nucleul): perioadele incomplete sunt excluse, ca în harti_anuale
    (cu „Acceptă perioade incomplete”, se citesc tăiate)."""
    citiri = []
    for an in range(int(interval[0]), int(interval[1]) + 1):
        d0, d1, _ = zc.perioada(an, sezon)
        if d0 > frontiera or d1 < inceput:
            continue
        if (d1 > frontiera or d0 < inceput) and not zc.ACCEPTA_PARTIAL:
            continue
        citiri.append((eticheta, max(d0, inceput), min(d1, frontiera)))
    return citiri


def avertismente_baza(p, cub, fr):
    """Perioada de bază a indicatorilor e acoperită complet de date? (verificat înainte de rulare)"""
    rez = []
    for d in p.get("INDICATORI") or []:
        ind = ri.din_dict(d)
        if ind.pregatire is None or "baza_de" not in ind.params:
            continue
        try:
            zc._verifica_baza(cub, fr, ind.variabile, (ind.params["baza_de"], ind.params["baza_pana"]))
        except ValueError as e:
            if str(e) not in rez:
                rez.append(f"{ind.titlu}: {e}")
    return rez


def _baza(p, sez, frontiera, inceput):
    """Indicatorii cu perioadă de bază (percentile, SPI, SPEI) citesc, la prima rulare pe o zonă, și anii de bază:
    toți anii întregi pentru pragurile zilnice / ale zilelor ploioase, sezonul ales pentru SPI / SPEI."""
    vazute, rez = set(), []
    for d in p.get("INDICATORI") or []:
        ind = ri.din_dict(d)
        if ind.pregatire is None or "baza_de" not in ind.params:
            continue
        b = (int(ind.params["baza_de"]), int(ind.params["baza_pana"]))
        sezon_b = sez if zc.e_standardizat(ind) else "anual"
        for v in ind.variabile:
            if (v, b, json.dumps(sezon_b)) in vazute:
                continue
            vazute.add((v, b, json.dumps(sezon_b)))
            rez.append((f"perioada de bază {b[0]}–{b[1]} (o singură dată, apoi din cache)", v,
                        _ani(b, sezon_b, frontiera, "", inceput)))
    return rez


def citiri(motor, p, cub, fr):
    """→ [(descriere, variabila, d0, d1, zona)]"""
    frontiera = min(fr.values())
    inceput = _d(cub.time.values[0])
    sez = p.get("SEZON", "anual")
    z = p.get("ZONA")
    rez = []

    def adauga(desc, variabile, intervale, zona):
        for v in variabile:
            for _, d0, d1 in intervale:
                rez.append((desc, v, d0, d1, zona))

    if motor in ("harta", "atlas", "trend", "anomalie", "altitudine"):
        for desc, v, iv in _baza(p, sez, frontiera, inceput):
            adauga(desc, (v,), iv, z)
    if motor in ("harta", "atlas", "trend", "altitudine"):
        adauga(f"{len(range(p['ANI'][0], p['ANI'][1] + 1))} ani × sezonul {sez}", _vars_indicatori(p),
               _ani(p["ANI"], sez, frontiera, "", inceput), z)
    elif motor == "anomalie":
        v = _vars_indicatori(p)
        adauga(f"perioada țintă {p['ANI_TINTA'][0]}–{p['ANI_TINTA'][1]}", v, _ani(p["ANI_TINTA"], sez, frontiera, "", inceput), z)
        adauga(f"referința {p['ANI_REFERINTA'][0]}–{p['ANI_REFERINTA'][1]}", v, _ani(p["ANI_REFERINTA"], sez, frontiera, "", inceput), z)
    elif motor == "episod_zilnic":
        d1 = min(_d(p["PERIOADA"][1]), frontiera) if p["PERIOADA"][1] else frontiera
        adauga("zilele episodului", _vars(p["VARIABILA"]), [("", _d(p["PERIOADA"][0]), d1)], z)
    elif motor == "climatograma":
        per = [p["PERIOADA_A"]] + ([p["PERIOADA_B"]] if p.get("COMPARA") and p.get("PERIOADA_B") else [])
        a0, a1 = min(x[0] for x in per), max(x[1] for x in per)
        adauga(f"seriile zilnice ale zonei, {a0}–{a1} (o singură dată; apoi din cache)", ("max_temp", "min_temp", "precipitation"),
               _ani((a0, a1), "anual", frontiera, "", inceput), z)
    elif motor in ("dungi", "serii"):
        # din v5.0 indicatorul seriei vine în INDICATORI (valori anuale per pixel, apoi pe zonă), ca la hărți
        v = _vars_indicatori(p) if p.get("INDICATORI") else _vars(p["VARIABILA"])
        adauga(f"valorile anuale {p['ANI'][0]}–{p['ANI'][1]}", v, _ani(p["ANI"], sez, frontiera, "", inceput), z)
    elif motor == "analiza_episod":
        a, b = p["PERIOADA"]
        a = _d(a)
        b = min(_d(b), frontiera) if b else frontiera
        n = int((b - a).astype(int)) + 1
        var = _vars(p["PARAMETRU"])
        an0, an_f = int(str(inceput)[:4]), int(str(frontiera)[:4])
        adauga(f"seria zilnică a zonei, {an0}–{an_f}", var, _ani((an0, an_f), "anual", frontiera, ""), z)
        an_luni = lambda an: (np.datetime64(f"{an}{str(a)[4:]}", "D"), np.datetime64(f"{an}{str(a)[4:]}", "D") + np.timedelta64(n - 1, "D"))  # noqa: E731
        ferestre = []
        for an in range(an0, an_f + 1):
            try:
                d0, d1 = an_luni(an)
            except ValueError:                                 # 29 februarie
                continue
            if d1 <= frontiera:
                ferestre.append(("", d0, d1))
        alte = [v for v in ("max_temp", "min_temp", "precipitation") if v not in var]
        an_c = p.get("CLIMATOLOGIE", (1991, 2020))
        ctx = [f for f in ferestre if an_c[0] <= int(str(f[1])[:4]) <= an_c[1]] + [("", a, b)]
        if (p.get("ANALIZE") or {}).get("context", True):
            adauga(f"context: alte variabile, {len(ctx)} ferestre de {n} zile", alte, ctx, z)
        an_ = p.get("ANALIZE") or {}
        if an_.get("harti", True) or an_.get("extindere", True) or an_.get("gif", True):
            adauga(f"hărți: {len(ferestre)} ferestre de {n} zile", var, ferestre, p.get("HARTI_ZONA"))
    elif motor == "integritate":
        n = int(p.get("ZILE_RECENTE") or 150)
        adauga(f"ultimele {n} zile, toată țara", ("max_temp", "min_temp", "precipitation"),
               [("", frontiera - np.timedelta64(n - 1, "D"), frontiera)], zc.Zona.tara())
    elif motor == "superlative":
        v = _vars(p["VARIABILA"])
        if p.get("MOD") == "harta":                         # pe pixel: doar zilele unității, an de an
            u = p["UNITATE"]
            sez = {"luna": [int(p.get("LUNA") or 5)] * 2, "sezon": p.get("SEZON", "anual")}.get(u, "anual")
            if u == "interval":
                a_, b_ = int(str(p.get("INTERVAL_DE"))[:2]), int(str(p.get("INTERVAL_PANA"))[:2])
                sez = [a_, b_] if a_ <= b_ else "anual"
            adauga(f"{p['ANI'][0]}–{p['ANI'][1]}, zilele unității", v, _ani(p["ANI"], sez, frontiera, "", inceput), z)
        else:                                               # clasament: seriile zilnice ale zonei (cache comun cu „serii”)
            adauga(f"seriile zilnice ale zonei {p['ANI'][0]}–{p['ANI'][1]} (o singură dată, apoi din cache)", v,
                   _ani((max(p["ANI"][0] - 1, int(str(inceput)[:4])), p["ANI"][1]), "anual", frontiera, "", inceput), z)
    elif motor == "statistici":
        a, b = p["PERIOADA"]
        b = min(_d(b), frontiera) if b else frontiera
        s = p.get("SEZON") or "anual"
        if s == "anual":
            iv = [("", _d(a), b)]
        else:
            iv = [(e, max(d0, _d(a)), min(d1, b)) for e, d0, d1 in _ani((int(str(a)[:4]), int(str(b)[:4])), s, b, "")
                  if d1 >= _d(a)]
        adauga("perioada" + ("" if s == "anual" else f", sezonul {s}"), _vars(p["PARAMETRU"]), iv, z)
    elif motor == "zonal":
        a, b = p["PERIOADA"]
        b = min(_d(b), frontiera) if b else frontiera
        var = []
        for k, x in (p.get("VARIABILE") or {}).items():
            if x:
                var += [v for v in _vars(k) if v not in var]
        zona = zc.Zona.poligoane(str(p["FISIER"]), strat=p.get("STRAT"), unite=True)
        adauga("perioada, dreptunghiul tuturor poligoanelor", var, [("", _d(a), b)], zona)
    return rez


def estimeaza(motor, p):
    """Deschide metadatele cubului și întoarce {gb, chunkuri, secunde, randuri:[(desc, var, chunk, mb)], frontiera}."""
    cub, fr = zc.deschide()
    randuri, ferestre, grupuri = {}, {}, {}
    for desc, var, d0, d1, zona in citiri(motor, p, cub, fr):
        if d1 < d0:
            continue
        if zona is None:
            zona = zc.Zona.tara()
        cheie = id(zona)
        if cheie not in ferestre:
            ferestre[cheie] = zc.grila_zonei(cub, zona)
        g = ferestre[cheie]
        n, mb = zc.estimeaza_cost(cub, var, d0, d1, g)
        r = randuri.setdefault((desc, var), [0, 0.0])
        r[0] += n
        r[1] += mb
        gr = grupuri.setdefault((desc, str(d0), str(d1), cheie),
                                [desc, [], int((d1 - d0).astype(int)) + 1, g.forma[0] * g.forma[1], 0.0])
        gr[1].append(var); gr[4] += mb
    baza_ani = {}                                     # pragurile percentile citesc toți anii de bază deodată, pe blocuri
    percentile = any(ri.din_dict(d).functie in (zc.i_pct_zile, zc.i_wsdi, zc.i_csdi, zc.i_rnnp, zc.i_rnnptot)
                     for d in p.get("INDICATORI") or [])
    for cheie_g in [k for k in grupuri if percentile and k[0].startswith("perioada de bază") and k[1].endswith("-01-01")
                    and k[2].endswith("-12-31")]:
        gr = grupuri.pop(cheie_g)
        b = baza_ani.setdefault((gr[0], cheie_g[3], tuple(gr[1])), [gr[0], gr[1], 0, gr[3], 0.0])
        b[2] += gr[2]; b[4] += gr[4]
    ram_mb, calcul_s = resurse(motor, p, list(grupuri.values()) + list(baza_ani.values()))
    total_ch = sum(r[0] for r in randuri.values())
    total_mb = sum(r[1] for r in randuri.values())
    return {"gb": total_mb / 1000, "chunkuri": total_ch, "secunde": total_mb / MBS, "mbs": MBS,
            "ram_mb": round(ram_mb), "calcul_s": round(calcul_s, 1), "ram_disponibil_mb": memorie_disponibila_mb(),
            "avertismente": avertismente_baza(p, cub, fr),
            "randuri": [(d, v, n, mb) for (d, v), (n, mb) in randuri.items()],
            "frontiera": str(min(fr.values()))}


def text_durata(s):
    if s < 60:
        return f"~{max(1, round(s))} s"
    if s < 3600:
        return f"~{round(s / 60)} min"
    return f"~{s / 3600:.1f} h".replace(".", ",")
