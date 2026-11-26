# -*- coding: utf-8 -*-
"""
zarr_statistici.py — statistici per pixel pe o perioadă, calculate din TOATE zilele perioadei (scriptul 17)
==========================================================================================================
Citește cubul în blocuri de timp aliniate la chunk-uri (fiecare chunk se citește o singură dată) și acumulează,
per pixel: suma, numărul de zile valide, minimul, maximul (și suma pătratelor, pentru abaterea standard).
Memoria folosită nu depinde de lungimea perioadei: 20 de ani pe toată țara încap la fel ca o lună.
"""
import math
import time
from pathlib import Path

import numpy as np

import zarr_clima as zc

STATISTICI = {
    # cod: (descriere, unitatea: "v" = a variabilei, "zi" = a variabilei pe zi, "zile")
    "medie": "media valorilor zilnice",
    "minima": "minima absolută (cea mai mică valoare zilnică)",
    "maxima": "maxima absolută (cea mai mare valoare zilnică)",
    "suma": "suma tuturor valorilor zilnice din perioadă",
    "suma_medie_anuala": "suma medie pe an (pe sezon, dacă e ales un sezon) = media zilnică × zile pe an",
    "abatere_standard": "abaterea standard a valorilor zilnice",
    "amplitudine": "maxima − minima",
    "zile_valide": "numărul de zile cu date valide",
}

IMPLICIT = {
    "precipitation": ["suma", "suma_medie_anuala", "medie", "maxima"],
    "max_temp": ["medie", "minima", "maxima"],
    "min_temp": ["medie", "minima", "maxima"],
    "tmedie": ["medie", "minima", "maxima"],
}

PALETE = {"precipitation": "YlGnBu", "max_temp": "RdYlBu_r", "min_temp": "RdYlBu_r", "tmedie": "RdYlBu_r"}
TITLURI = {"precipitation": "Precipitații", "max_temp": "Temperatura maximă zilnică",
           "min_temp": "Temperatura minimă zilnică", "tmedie": "Temperatura medie zilnică (Tmax + Tmin)/2"}


def _masca_sezon(zile, sezon):
    """Booleană: ce zile intră în sezon. sezon: None / "anual" / nume din SEZOANE / (luna_a, luna_b) / ("MM-DD", "MM-DD")."""
    if sezon is None or sezon == "anual":
        return np.ones(len(zile), bool)
    s = zc.SEZOANE[sezon] if isinstance(sezon, str) else tuple(sezon)
    a, b = s
    luni = (zile.astype("datetime64[M]").astype(int) % 12) + 1
    if isinstance(a, str):
        md = np.array([str(z)[5:10] for z in zile])
        return (md >= a) & (md <= b) if a <= b else (md >= a) | (md <= b)
    return (luni >= a) & (luni <= b) if a <= b else (luni >= a) | (luni <= b)


def _unitate(cod, var, sezon=None):
    u = zc.UNITATI.get(var, "°C")
    if cod == "zile_valide":
        return "zile"
    if var == "precipitation":
        return {"medie": "mm/zi", "minima": "mm/zi", "maxima": "mm/zi", "abatere_standard": "mm/zi",
                "amplitudine": "mm/zi", "suma": "mm", "suma_medie_anuala": "mm/an" if sezon in (None, "anual") else "mm/sezon"}.get(cod, "mm")
    return u


def ruleaza_statistici(var, perioada, sezon, statistici, zona, decupare, iesiri, out, nume, zile_pe_bloc=None):
    """Statistici per pixel din toate zilele perioadei. Returnează {cod: ndarray 2D}."""
    out = Path(out)
    t_start = time.perf_counter()
    if var not in ("max_temp", "min_temp", "precipitation", "tmedie"):
        raise ValueError(f"PARAMETRU necunoscut: «{var}». Alegeți: max_temp, min_temp, precipitation, tmedie.")
    statistici = list(statistici or IMPLICIT[var])
    necunoscute = [s for s in statistici if s not in STATISTICI]
    if necunoscute:
        raise ValueError(f"Statistici necunoscute: {necunoscute}. Disponibile: {', '.join(STATISTICI)}")
    if decupare not in ("dreptunghi", "masca"):
        raise ValueError('DECUPARE trebuie să fie "dreptunghi" sau "masca".')
    variabile = ("max_temp", "min_temp") if var == "tmedie" else (var,)

    cub, fr = zc.deschide()
    frontiera = min(fr[v] for v in variabile)
    d0 = np.datetime64(perioada[0], "D")
    d1 = np.datetime64(perioada[1], "D") if perioada[1] else frontiera
    t_cub0 = np.datetime64(str(cub.time.values[0])[:10], "D")
    if d0 < t_cub0:
        zc.log(f"   [atenție] începutul {d0} este înaintea primei zile din cub; încep la {t_cub0}"); d0 = t_cub0
    if d1 > frontiera:
        zc.log(f"   [atenție] sfârșitul {d1} depășește frontiera datelor ({frontiera}); tai la {frontiera}")
        d1 = frontiera
    if d1 < d0:
        raise ValueError(f"Perioada {d0} → {d1} este goală (frontiera datelor: {frontiera}).")

    g = zc.grila_zonei(cub, zona)
    ny, nx = g.forma
    toate = np.arange(d0, d1 + 1)
    sel = _masca_sezon(toate, sezon)
    n_sel = int(sel.sum())
    if n_sel == 0:
        raise ValueError("Niciuna dintre zilele perioadei nu intră în sezonul ales.")
    # lungimea medie a sezonului într-un an (ciclu de 4 ani, cu un an bisect): 365,25 zile anual, 90,25 la DJF etc.
    ciclu = np.arange(np.datetime64("2001-01-01"), np.datetime64("2005-01-01"))
    zile_pe_an = _masca_sezon(ciclu, sezon).sum() / 4.0
    et_sezon = "" if sezon in (None, "anual") else f" · sezon {sezon}"
    zc.log(f"== {nume}: {TITLURI[var]} · {d0} → {d1}{et_sezon} · {n_sel} zile (≈ {n_sel / zile_pe_an:.1f} ani)"
           f" · grilă {ny} × {nx} pixeli · {zona.descriere()}")

    # blocuri de timp aliniate la chunk-urile cubului (un chunk se citește o singură dată)
    ct = cub[variabile[0]].encoding.get("chunks", (90,))[0]
    pas = zile_pe_bloc or ct
    pas = max(ct, (pas // ct) * ct)
    i_start = int((d0 - t_cub0).astype(int)); i_end = int((d1 - t_cub0).astype(int))
    limite = list(range((i_start // pas) * pas, i_end + 1, pas))
    blocuri = []
    for a in limite:
        b0 = max(a, i_start); b1 = min(a + pas - 1, i_end)
        z = t_cub0 + np.arange(b0, b1 + 1)
        m = _masca_sezon(z, sezon)
        if m.any():
            idx = np.nonzero(m)[0]
            blocuri.append((z[idx[0]], z[idx[-1]]))           # citim doar porțiunea care conține zile din sezon
    mb_total = sum(zc.estimeaza_cost(cub, v, a, b, g)[1] for a, b in blocuri for v in variabile)
    zc.log(f"   de citit: {len(blocuri)} blocuri, ~{mb_total / 1000:.1f} GB (comprimat)")

    suma = np.zeros((ny, nx), "float64"); n = np.zeros((ny, nx), "int32")
    mn = np.full((ny, nx), np.inf, "float32"); mx = np.full((ny, nx), -np.inf, "float32")
    sq = np.zeros((ny, nx), "float64") if "abatere_standard" in statistici else None
    t0 = time.perf_counter()
    for k, (a, b) in enumerate(blocuri, 1):
        d, zile = zc.citeste(cub, variabile, a, b, g)
        v = (d["max_temp"] + d["min_temp"]) / 2 if var == "tmedie" else d[var]
        del d
        m = _masca_sezon(zile, sezon)
        if not m.all():
            v = v[m]
        n += np.isfinite(v).sum(axis=0, dtype="int32")
        suma += np.nansum(v, axis=0, dtype="float64")
        if sq is not None:
            sq += np.nansum(np.square(v, dtype="float64"), axis=0)
        mn = np.fmin(mn, np.fmin.reduce(v, axis=0))        # fmin/fmax ignoră NaN
        mx = np.fmax(mx, np.fmax.reduce(v, axis=0))
        del v
        if k == 1 or k == len(blocuri) or k % 10 == 0:
            rest = (time.perf_counter() - t0) / k * (len(blocuri) - k)
            zc.log(f"   bloc {k}/{len(blocuri)}: {a} → {b}" + (f" · mai durează ~{rest / 60:.0f} min" if k < len(blocuri) else ""))

    # regula zilelor valide (aceeași ca în tot pachetul)
    valid = n >= zc.PRAG_VALID * n_sel
    teren = n > 0
    exclusi = int((teren & ~valid).sum())
    if exclusi:
        zc.log(f"   {exclusi} pixeli excluși: mai puțin de {zc.PRAG_VALID:.0%} din zile au date valide")
    with np.errstate(invalid="ignore", divide="ignore"):
        medie = np.where(valid, suma / np.maximum(n, 1), np.nan)
        rez = {
            "medie": medie,
            "minima": np.where(valid, mn, np.nan),
            "maxima": np.where(valid, mx, np.nan),
            "suma": np.where(valid, suma, np.nan),
            "suma_medie_anuala": medie * zile_pe_an,
            "amplitudine": np.where(valid, mx - mn, np.nan),
            "zile_valide": np.where(teren, n, np.nan),
        }
        if sq is not None:
            var_ = sq / np.maximum(n, 1) - (suma / np.maximum(n, 1)) ** 2
            rez["abatere_standard"] = np.where(valid & (n > 1), np.sqrt(np.maximum(var_, 0) * n / np.maximum(n - 1, 1)), np.nan)
    rez = {c: rez[c].astype("float32") for c in statistici}

    if decupare == "masca" and zona._id is not None:
        rez = {c: zc._masca_zona(h, zona) for c, h in rez.items()}
    elif zona.altitudine:
        lo, hi = zona.altitudine
        alt = zc.altitudine(g)
        masca = np.isfinite(alt)
        if lo is not None:
            masca &= alt >= lo
        if hi is not None:
            masca &= alt <= hi
        rez = {c: np.where(masca, h, np.nan) for c, h in rez.items()}

    # ------------------------------------------------------------------ ieșiri
    per = f"{d0} → {d1}{et_sezon}"
    fisiere = []
    descr = [f"{c} · {TITLURI[var]} · {per} ({_unitate(c, var, sezon)})" for c in statistici]
    if iesiri.get("cog_multibanda"):
        fisiere.append(zc.scrie_cog(out / f"{nume}.tif", [rez[c] for c in statistici], g, descr))
    if iesiri.get("tif_separate"):
        for c, ds in zip(statistici, descr):
            fisiere.append(zc.scrie_cog(out / f"{nume}_{c}.tif", rez[c], g, [ds], _unitate(c, var, sezon)))
    if iesiri.get("png"):
        for c in statistici:
            cmap = "Greys" if c == "zile_valide" else ("magma_r" if c in ("abatere_standard", "amplitudine") else PALETE[var])
            zc.png_harta(out / f"{nume}_{c}.png", rez[c], g, f"{TITLURI[var]} · {STATISTICI[c].split(' (')[0]}",
                         _unitate(c, var, sezon), cmap, zona=zona, subtitlu=f"{per} · {n_sel} zile · {zona.descriere()}")
    if iesiri.get("csv"):
        rand = []
        for c in statistici:
            h = rez[c]; vv = h[np.isfinite(h)]
            rand.append((c, _unitate(c, var, sezon), *( (float(vv.min()), float(vv.mean()), float(vv.max()), int(vv.size)) if vv.size else (math.nan,) * 3 + (0,))))
        zc.scrie_csv(out / f"{nume}_rezumat.csv", ["statistica", "unitate", "min_pe_harta", "medie_pe_harta", "max_pe_harta", "pixeli"], rand)

    # rezumat în consolă
    zc.log("   rezumat pe hartă (min · medie · max):")
    for c in statistici:
        h = rez[c]; vv = h[np.isfinite(h)]
        if vv.size:
            zc.log(f"      {c:<20} {zc.ro(vv.min())} · {zc.ro(vv.mean())} · {zc.ro(vv.max())} {_unitate(c, var, sezon)}")
    zc.incarca_in_qgis(fisiere)
    zc.log(f"== gata: {nume} în {(time.perf_counter() - t_start) / 60:.1f} min")
    return rez
