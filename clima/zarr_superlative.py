# -*- coding: utf-8 -*-
"""
zarr_superlative.py — SUPERLATIVE: cel mai ploios mai, cea mai caldă zi, cele mai ploioase 3 zile consecutive…
==============================================================================================================
Pentru o variabilă (Tmax, Tmin, Tmed, P) și o unitate de timp, găsește valorile extreme din toată seria:

  unitate       candidații unui an                          agregare
  ----------    ----------------------------------------    -------------------------------------------
  zi            fiecare zi                                  valoarea zilei
  fereastra     fiecare șir de N zile consecutive           suma (P) / media (T) pe cele N zile
  luna          luna aleasă (ex. mai)                       suma / media lunii
  luni          fiecare dintre cele 12 luni                 suma / media lunii
  sezon         sezonul ales (ex. iunie–august)             suma / media sezonului
  an            anul calendaristic                          suma / media anului
  interval      un interval calendaristic fix (ex. 1–15 aug) suma / media intervalului

Un candidat e valid dacă are date în cel puțin PRAG_VALID (90 %) din zilele lui, ca la orice altă analiză, și se
află în întregime în datele cubului (excepție: zilele și ferestrele anului curent, până la frontieră).

Două moduri:
  * „clasament” — pe zonă (punct, dreptunghi, țară sau fiecare poligon): seria zilnică MEDIATĂ PE ZONĂ (aceeași ca
    la graficele de serii, cu cache), apoi clasamentul candidaților: top N, recordul, locul unui an ales.
  * „harta” — pe pixel: pentru fiecare pixel, recordul, anul și data recordului, marja față de recordul anterior
    și locul unui an ales; plus în câți pixeli fiecare an deține recordul.

Atenție la diferența dintre ele: recordul unei zone (media zonei) nu e recordul celui mai extrem pixel din zonă.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import zarr_clima as zc

UNITATI = {"zi": "ziua", "fereastra": "N zile consecutive", "luna": "o lună anume, de-a lungul anilor",
           "luni": "toate lunile din serie", "sezon": "sezonul ales", "an": "anul", "interval": "un interval fix din fiecare an"}
LUNI = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie",
        "noiembrie", "decembrie"]
LUNI_SCURT = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi", "dec"]
SEZOANE = {"DJF": "iarna", "MAM": "primăvara", "JJA": "vara", "SON": "toamna", "anual": "anul"}
SEZOANE_NEART = {"DJF": "iarnă", "MAM": "primăvară", "JJA": "vară", "SON": "toamnă"}
VAR_TITLU = {"max_temp": "Tmax", "min_temp": "Tmin", "tmedie": "Tmed", "precipitation": "precipitații"}
ZI = np.timedelta64(1, "D")


# =====================================================================================
# Texte
# =====================================================================================
def _adj(var, sens, forma):
    """forma: m (masculin sg), f (feminin sg), p (plural feminin)."""
    if var == "precipitation":
        b = {"max": ("ploios", "ploioasă", "ploioase"), "min": ("secetos", "secetoasă", "secetoase")}[sens]
    else:
        b = {"max": ("cald", "caldă", "calde"), "min": ("rece", "rece", "reci")}[sens]
    return b["mfp".index(forma)]


def text_perioada(sez):
    """„din noiembrie”, „din vară”, „din iunie–august”, „din 1 august – 15 august”."""
    if not _restrans(sez):
        return ""
    if isinstance(sez, str):
        return f" din {SEZOANE_NEART.get(sez, sez)}"
    a, b = sez
    if isinstance(a, (int, np.integer)):
        return f" din {LUNI[a - 1]}" if a == b else f" din {LUNI[a - 1]}–{LUNI[b - 1]}"
    return f" din {_zi_luna(a)} – {_zi_luna(b)}"


def titlu_superlativ(var, sens, unitate, n=3, luna=5, sezon="anual", interval=None, restrange=None):
    """Ex. „Cea mai ploioasă lună mai”, „Cele mai reci 7 zile consecutive din noiembrie (după Tmin)”."""
    calif = "" if var in ("precipitation", "tmedie") else f" (după {VAR_TITLU[var]})"
    if unitate == "zi":
        return f"Cea mai {_adj(var, sens, 'f')} zi{text_perioada(restrange)}{calif}"
    if unitate == "fereastra":
        return f"Cele mai {_adj(var, sens, 'p')} {n} zile consecutive{text_perioada(restrange)}{calif}"
    if unitate == "luna":
        return f"Cea mai {_adj(var, sens, 'f')} lună {LUNI[luna - 1]}{calif}"
    if unitate == "luni":
        return f"Cea mai {_adj(var, sens, 'f')} lună din serie{calif}"
    if unitate == "sezon":
        if sezon == "anual":
            return f"Cel mai {_adj(var, sens, 'm')} an{calif}"
        nume = SEZOANE_NEART.get(sezon) if isinstance(sezon, str) else None
        if nume:
            return f"Cea mai {_adj(var, sens, 'f')} {nume}{calif}"
        a, b = sezon
        per = (f"{LUNI[a - 1]}–{LUNI[b - 1]}" if a != b else LUNI[a - 1]) if isinstance(a, int) else f"{a} → {b}"
        return f"Cea mai {_adj(var, sens, 'f')} perioadă {per}{calif}"
    if unitate == "an":
        return f"Cel mai {_adj(var, sens, 'm')} an{calif}"
    if unitate == "interval":
        return f"Cel mai {_adj(var, sens, 'm')} interval {_text_interval(interval)}{calif}"
    raise ValueError(f"Unitate necunoscută: {unitate}")


def _zi_luna(md):
    m, z = int(md[:2]), int(md[3:5])
    return f"{z} {LUNI[m - 1]}"


def _text_interval(interval):
    a, b = interval
    return f"{_zi_luna(a)} – {_zi_luna(b)}"


def eticheta(d0, d1, unitate, sezon=None):
    """Textul unui candidat: „24 iulie 2024”, „24–26 iulie 2024”, „mai 2010”, „vara 2024”, „2024”."""
    a, b = str(d0), str(d1)
    if unitate == "sezon" and isinstance(sezon, str) and sezon in SEZOANE:
        return f"{SEZOANE[sezon]} {b[:4]}"
    ya, ma, za = int(a[:4]), int(a[5:7]), int(a[8:10])
    yb, mb, zb = int(b[:4]), int(b[5:7]), int(b[8:10])
    if unitate == "zi":
        return f"{za} {LUNI[ma - 1]} {ya}"
    if unitate in ("luna", "luni"):
        return f"{LUNI[ma - 1]} {ya}"
    if unitate == "an":
        return str(ya)
    if ya == yb and ma == mb:
        return f"{za}–{zb} {LUNI[ma - 1]} {ya}"
    if ya == yb:
        return f"{za} {LUNI[ma - 1]} – {zb} {LUNI[mb - 1]} {ya}"
    return f"{za} {LUNI[ma - 1]} {ya} – {zb} {LUNI[mb - 1]} {yb}"


# =====================================================================================
# Candidații unui an
# =====================================================================================
def _parse_md(s, nume):
    s = str(s).strip()
    try:
        m, z = int(s[:2]), int(s[3:5])
        np.datetime64(f"2001-{m:02d}-{z:02d}") if not (m == 2 and z == 29) else None
    except (ValueError, IndexError):
        raise ValueError(f"{nume}: scrieți luna și ziua ca LL-ZZ (de exemplu 08-01), nu „{s}”.") from None
    if not (s[2] in "-./" and len(s) == 5):
        raise ValueError(f"{nume}: scrieți luna și ziua ca LL-ZZ (de exemplu 08-01), nu „{s}”.")
    return f"{m:02d}-{z:02d}"


def valideaza(var, sens, unitate, n=3, luna=5, interval=None):
    if unitate not in UNITATI:
        raise ValueError(f"Unitatea „{unitate}” nu există; alegeți una dintre: {', '.join(UNITATI)}.")
    if var == "precipitation" and sens == "min" and unitate == "zi":
        raise ValueError("Ziua cu cele mai puține precipitații are aproape mereu 0 mm (mii de zile la egalitate). "
                         "Alegeți „maxim”, sau o perioadă mai lungă (de exemplu cele mai secetoase 30 de zile).")
    if unitate == "fereastra" and not (isinstance(n, (int, np.integer)) and 2 <= n <= 366):
        raise ValueError("Numărul de zile consecutive trebuie să fie un întreg între 2 și 366.")
    if unitate == "luna" and not (isinstance(luna, (int, np.integer)) and 1 <= luna <= 12):
        raise ValueError("Luna trebuie să fie între 1 (ianuarie) și 12 (decembrie).")
    if unitate == "interval":
        if not interval or len(interval) != 2:
            raise ValueError("Intervalul fix cere un început și un sfârșit (LL-ZZ), de exemplu 08-01 și 08-15.")
        return [_parse_md(interval[0], "Începutul intervalului"), _parse_md(interval[1], "Sfârșitul intervalului")]
    return interval


def _data(an, md):
    if md == "02-29" and not (an % 4 == 0 and (an % 100 != 0 or an % 400 == 0)):
        md = "02-28"
    return np.datetime64(f"{an}-{md}")


def _restrans(restrange):
    return restrange not in (None, "", "anual")


def intervale_an(an, unitate, n=3, luna=5, sezon="anual", interval=None, restrange=None):
    """Candidații anului `an` ca intervale [d0, d1] (zile incluse). Ferestrele: toate cele care ÎNCEP în an.
    Cu `restrange` (o lună, un sezon, un interval — ca SEZON), zilele / ferestrele trebuie să stea în întregime în
    acea parte a anului (de ex. „cele mai reci 7 zile din noiembrie”); iarna (DJF) e cea care se termină în `an`."""
    if unitate in ("zi", "fereastra"):
        lung = 1 if unitate == "zi" else n
        if _restrans(restrange):
            d0, d1, _ = zc.perioada(an, restrange)
            if int((d1 - d0).astype(int)) + 1 < lung:
                raise ValueError(f"Perioada aleasă are doar {int((d1 - d0).astype(int)) + 1} zile: nu încap {lung} zile consecutive.")
            return [(d, d + (lung - 1) * ZI) for d in np.arange(d0, d1 - (lung - 2) * ZI)]
        z = np.arange(np.datetime64(f"{an}-01-01"), np.datetime64(f"{an + 1}-01-01"))
        return [(d, d + (lung - 1) * ZI) for d in z]
    if unitate == "luna":
        d0 = np.datetime64(f"{an}-{luna:02d}-01")
        return [(d0, (d0.astype("datetime64[M]") + 1).astype("datetime64[D]") - ZI)]
    if unitate == "luni":
        return [(np.datetime64(f"{an}-{m:02d}-01"),
                 (np.datetime64(f"{an}-{m:02d}") + 1).astype("datetime64[D]") - ZI) for m in range(1, 13)]
    if unitate == "sezon":
        d0, d1, _ = zc.perioada(an, sezon)
        return [(d0, d1)]
    if unitate == "an":
        return [(np.datetime64(f"{an}-01-01"), np.datetime64(f"{an}-12-31"))]
    if unitate == "interval":
        a, b = interval
        d1 = _data(an, b)
        d0 = _data(an if a <= b else an - 1, a)        # peste Anul Nou (ex. 12-15 → 01-15): se termină în anul `an`
        return [(d0, d1)]
    raise ValueError(unitate)


def candidati(D, zile, iv, agregare, inceput, frontiera, unitate):
    """D (t, …) valorile zilnice pe zilele `zile` (consecutive); iv = [(d0, d1)] intervalele candidaților.
    → (valori (k, …) float64 cu NaN pentru candidații invalizi, intervalele valide în date)."""
    D = np.asarray(D)
    if not len(zile):
        return np.full((0,) + D.shape[1:], np.nan), []
    z0 = zile[0]
    rest = D.shape[1:]
    # candidații care ies din date (înainte de cub sau după frontieră) nu se pot compara: se exclud;
    # excepție: zilele și ferestrele anului curent, până la frontieră
    iv = [(a, b) for a, b in iv if a >= max(z0, inceput) and b <= min(zile[-1], frontiera)]
    if not iv:
        return np.full((0,) + rest, np.nan), []
    lung = np.array([int((b - a).astype(int)) + 1 for a, b in iv])
    i0 = np.array([int((a - z0).astype(int)) for a, _ in iv])
    ok = np.isfinite(D)
    if unitate == "zi":
        return np.where(ok[i0], D[i0], np.nan).astype("float64"), iv
    Dz = np.where(ok, D, 0.0).astype("float64")
    cs = np.concatenate([np.zeros((1,) + rest), np.cumsum(Dz, axis=0)]); del Dz
    cn = np.concatenate([np.zeros((1,) + rest, dtype="int32"), np.cumsum(ok, axis=0, dtype="int32")])
    idx_b = i0 + lung
    s = cs[idx_b] - cs[i0]
    nv = cn[idx_b] - cn[i0]
    lung_b = lung.reshape((-1,) + (1,) * len(rest))
    valid = nv >= zc.PRAG_VALID * lung_b
    with np.errstate(invalid="ignore", divide="ignore"):
        val = s if agregare == "suma" else s / np.maximum(nv, 1)
    return np.where(valid & (nv > 0), val, np.nan), iv


def fereastra_citire(an, unitate, n=3, sezon="anual", interval=None, luna=5, restrange=None):
    """Zilele de citit pentru candidații anului `an` (ferestrele care încep în decembrie continuă în anul următor)."""
    iv = intervale_an(an, unitate, n=n, luna=luna, sezon=sezon, interval=interval, restrange=restrange)
    return min(a for a, _ in iv), max(b for _, b in iv)


def an_candidat(d0, d1, unitate, restrange=None):
    """Anul căruia îi aparține un candidat: anul începutului; la sezoane / intervale peste Anul Nou, anul sfârșitului
    (aceeași convenție ca restul programului: iarna 2026 = decembrie 2025 – februarie 2026). Zilele și ferestrele
    restrânse la o perioadă peste Anul Nou (ex. DJF) aparțin anului în care se termină perioada."""
    if unitate in ("zi", "fereastra") and _restrans(restrange):
        a0, _, _ = zc.perioada(int(str(d0)[:4]) + 1, restrange)
        if d0 >= a0:                                  # începe în decembrie, într-o iarnă care se termină anul următor
            return int(str(d0)[:4]) + 1
    return int(str(d1 if unitate in ("sezon", "interval") else d0)[:4])


def _agregare(var):
    return "suma" if var == "precipitation" else "medie"


def _unitate_masura(var):
    return "mm" if var == "precipitation" else "°C"


def _mai_bun(sens):
    return (lambda a, b: a > b) if sens == "max" else (lambda a, b: a < b)


# =====================================================================================
# Clasament pe zone (din seriile zilnice mediate pe zonă)
# =====================================================================================
def clasament_zona(vals, iv, sens, top, unitate):
    """vals (K,), iv [(d0, d1)] → lista celor mai bune `top` candidați [(loc, valoare, d0, d1)], fără suprapuneri
    pentru ferestre (cele 3 zile din 24–26 iulie și cele din 25–27 iulie sunt același episod: rămâne doar cel mai bun)."""
    vals = np.asarray(vals, dtype="float64")
    ok = np.isfinite(vals)
    ordine = np.argsort(-vals if sens == "max" else vals, kind="stable")
    ordine = ordine[ok[ordine]]
    ales, ocupate = [], []
    for k in ordine:
        a, b = iv[k]
        if unitate == "fereastra" and any(a <= y and x <= b for x, y in ocupate):
            continue
        ales.append(k); ocupate.append((a, b))
        if len(ales) >= top:
            break
    return [(i + 1, float(vals[k]), iv[k][0], iv[k][1]) for i, k in enumerate(ales)]


def _rang(vals, v, sens):
    """Locul valorii v între toate valorile (1 = record; egalitățile împart locul)."""
    vals = np.asarray(vals, dtype="float64")
    vals = vals[np.isfinite(vals)]
    return int(1 + ((vals > v) if sens == "max" else (vals < v)).sum()) if np.isfinite(v) else None


def ruleaza_superlative(var, sens, unitate, ani, zona: zc.Zona, mod, iesiri: dict, out, nume, n=3, luna=5,
                        sezon="anual", interval=None, an_evidentiat=None, top=10, total_nume=None, restrange=None):
    """Punctul de intrare (motorul „superlative”)."""
    out = Path(out)
    interval = valideaza(var, sens, unitate, n, luna, interval)
    if sens not in ("max", "min"):
        raise ValueError("Sensul trebuie să fie „max” sau „min”.")
    if mod == "harta" and zona.punct is not None:
        raise ValueError("Hărțile pe pixel cer o suprafață (dreptunghi, poligoane sau toată țara); pentru un punct "
                         "alegeți „clasamentul pe zonă”.")
    if not (unitate in ("zi", "fereastra")):
        restrange = None
    titlu = titlu_superlativ(var, sens, unitate, n, luna, sezon, interval, restrange)
    zc.log(f"== {nume}: {titlu} · {ani[0]}–{ani[1]} · {zona.descriere()} · mod: {mod}")
    if total_nume is None:                       # zonele fără poligoane au o singură serie: numele zonei
        total_nume = "Toate zonele" if zona.poligoane else (zona.nume or zona.descriere())
    if mod == "harta":
        return _pe_pixeli(var, sens, unitate, ani, zona, iesiri, out, nume, n, luna, sezon, interval, an_evidentiat, titlu,
                          restrange)
    return _pe_zone(var, sens, unitate, ani, zona, iesiri, out, nume, n, luna, sezon, interval, an_evidentiat, top,
                    titlu, total_nume, restrange)


def _pe_zone(var, sens, unitate, ani, zona, iesiri, out, nume, n, luna, sezon, interval, an_ev, top, titlu, total_nume,
             restrange=None):
    cub, fr = zc.deschide()
    g = zc.grila_zonei(cub, zona)
    inceput = np.datetime64(str(cub.time.values[0])[:10], "D")
    ani_cititi = range(max(ani[0] - 1, int(str(inceput)[:4])), ani[1] + 2)        # vecinii: ferestre / intervale
    etichete, serii, frontiera = zc.serii_zonale(cub, fr, var, ani_cititi, zona, g, total_nume, zc.dir_cache("serii"))
    # seria completă (zone, zile) cu NaN pentru anii lipsă
    z_start = np.datetime64(f"{min(serii)}-01-01") if serii else inceput
    z_end = frontiera
    zile = np.arange(z_start, z_end + ZI)
    S = np.full((len(zile), len(etichete)), np.nan)
    for an, a in serii.items():
        i = int((np.datetime64(f"{an}-01-01") - z_start).astype(int))
        S[i:i + a.shape[1]] = a.T
    vals, ivs = [], []
    for an in range(ani[0], ani[1] + 1):
        iv = intervale_an(an, unitate, n=n, luna=luna, sezon=sezon, interval=interval, restrange=restrange)
        v, ivv = candidati(S, zile, iv, _agregare(var), inceput, frontiera, unitate)
        vals.append(v); ivs += ivv
    V = np.concatenate(vals, axis=0) if vals else np.zeros((0, len(etichete)))
    um = _unitate_masura(var)
    unul_pe_an = unitate not in ("zi", "fereastra", "luni")
    an_cand = np.array([an_candidat(a, b, unitate, restrange) for a, b in ivs])
    rand_clas, rand_rec, rezumat = [], [], {"titlu": titlu, "variabila": var, "sens": sens, "unitate": unitate,
                                            "ani": list(ani), "unitate_masura": um, "zone": []}
    fis = []
    out.mkdir(parents=True, exist_ok=True)
    for k, et in enumerate(etichete):
        v = V[:, k]
        lista = clasament_zona(v, ivs, sens, top, unitate)
        if not lista:
            zc.log(f"   [atenție] {et}: niciun candidat valid în {ani[0]}–{ani[1]}"); continue
        media = float(np.nanmean(v)) if unul_pe_an else None
        for loc, val, d0, d1 in lista:
            rand_clas.append([et, loc, round(val, 2), um, str(d0), str(d1), eticheta(d0, d1, unitate, sezon), an_candidat(d0, d1, unitate, restrange),
                              round(val - media, 2) if media is not None else ""])
        rec = lista[0]
        doi = lista[1] if len(lista) > 1 else None
        info = {"k": k, "zona": et, "record": round(rec[1], 2), "eticheta": eticheta(rec[2], rec[3], unitate, sezon), "an": an_candidat(rec[2], rec[3], unitate, restrange),
                "al_doilea": round(doi[1], 2) if doi else None, "eticheta_al_doilea": eticheta(doi[2], doi[3], unitate, sezon) if doi else None,
                "media": round(media, 2) if media is not None else None, "candidati": int(np.isfinite(v).sum())}
        if an_ev:
            m = an_cand == int(an_ev)
            if m.any() and np.isfinite(v[m]).any():
                best = np.nanmax(v[m]) if sens == "max" else np.nanmin(v[m])
                i_best = np.flatnonzero(m)[np.nanargmax(v[m]) if sens == "max" else np.nanargmin(v[m])]
                # rangul se face mereu între ANI (cel mai bun candidat al fiecărui an), și la unitatea „zi”:
                # „locul 3 din 65” înseamnă al treilea an, nu a treia zi din toate cele ~23 700
                comp = v if unul_pe_an else _cele_mai_bune_pe_an(v, an_cand, sens)
                info.update(an_evidentiat=int(an_ev), valoare_an=round(float(best), 2),
                            eticheta_an=eticheta(ivs[i_best][0], ivs[i_best][1], unitate, sezon),
                            loc_an=_rang(comp, best, sens), din=int(np.isfinite(comp).sum()))
        rezumat["zone"].append(info)
        rand_rec.append([et, info["record"], info["eticheta"], info["an"], info["al_doilea"] if doi else "",
                         round(rec[1] - doi[1], 2) if doi else "", info.get("loc_an", ""), info.get("din", "")])
        zc.log(f"   {et}: {titlu[0].lower() + titlu[1:]} = {zc.ro(rec[1], 1)} {um}, {info['eticheta']}"
               + (f" (al doilea: {zc.ro(doi[1], 1)} {um}, {info['eticheta_al_doilea']})" if doi else "")
               + (f" · media: {zc.ro(media, 1)} {um}" if media is not None else "")
               + (f" · {an_ev}: locul {info['loc_an']} din {info['din']} ani" if info.get("loc_an") else ""))
        if iesiri.get("png") and (len(etichete) <= 9 or et == etichete[-1]):
            sl = _slug(et) if len(etichete) > 1 else ""
            f = png_clasament(out / f"{nume}{'_' + sl if sl else ''}_clasament.png", lista, titlu, et, um, unitate,
                              int(an_ev) if an_ev else None, media, sens, sezon, restrange=restrange,
                              nota_an=(f"{an_ev}: locul {info['loc_an']} din {info['din']} ani" if info.get("loc_an") else
                                       (f"{an_ev}: fără date complete" if an_ev else None)))
            fis.append(f)
            if unul_pe_an:
                ani_v = [an_candidat(a, b, unitate, restrange) for a, b in ivs]
                fis.append(png_serie_superlativ(out / f"{nume}{'_' + sl if sl else ''}_serie.png", ani_v, v, lista, titlu,
                                                et, um, int(an_ev) if an_ev else None, sens))
    if not rezumat["zone"]:
        raise ValueError(f"Niciun candidat valid în {ani[0]}–{ani[1]} (datele: {inceput} … {frontiera}).")
    if iesiri.get("csv", True):
        fis.append(zc.scrie_csv(out / f"{nume}_clasament.csv",
                                ["zona", "loc", "valoare", "unitate", "inceput", "sfarsit", "eticheta", "an",
                                 "abatere_fata_de_medie"], rand_clas))
        if len(etichete) > 1:
            fis.append(zc.scrie_csv(out / f"{nume}_recorduri_zone.csv",
                                    ["zona", "record", "eticheta", "an", "al_doilea", "marja", f"loc_{an_ev or 'an'}", "din"],
                                    rand_rec))
    if len(etichete) > 1 and iesiri.get("png"):
        fis.append(png_recorduri_zone(out / f"{nume}_recorduri_zone.png", rezumat["zone"], titlu, um, sens))
    if iesiri.get("gpkg") and zona.poligoane:
        # după indicele poligonului, nu după poziția în listă: o zonă fără candidați e sărită în rezumat și ar
        # decala toate valorile pe poligonul vecin (audit 1.1, 2.4)
        dupa_k = {z["k"]: z for z in rezumat["zone"]}
        z_pol = [dupa_k.get(k) for k in range(len(zona.poligoane))]
        fis.append(zc.scrie_gpkg_zone(out / f"{nume}_recorduri.gpkg", zona, {
            "record": [z["record"] if z else None for z in z_pol], "an_record": [z["an"] if z else None for z in z_pol],
            "data_record": [z["eticheta"] if z else None for z in z_pol]}))
    (out / f"{nume}_rezumat.json").write_text(json.dumps(rezumat, ensure_ascii=False, indent=1), encoding="utf-8")
    zc.log(f"== gata: {nume}")
    return fis


def _cele_mai_bune_pe_an(v, an_cand, sens):
    """Cel mai bun candidat al fiecărui an (pentru locul unui an la zile / ferestre / luni)."""
    rez = []
    for a in np.unique(an_cand):
        x = v[an_cand == a]
        if np.isfinite(x).any():
            rez.append(np.nanmax(x) if sens == "max" else np.nanmin(x))
    return np.array(rez)


def _slug(s):
    return "".join(c if c.isalnum() else "_" for c in s)[:40]


# =====================================================================================
# Hărți pe pixel
# =====================================================================================
BANDA = 64
# luna recordului: anotimpurile se recunosc (iarnă albastru, primăvară verde, vară galben–roșu, toamnă violet),
# lunile aceluiași anotimp se deosebesc prin luminozitate
CULORI_LUNI = ["#3182bd", "#9ecae1", "#c7e9c0", "#74c476", "#238b45", "#fed976", "#fd8d3c", "#bd0026",
               "#d4b9da", "#9e7bb5", "#6a51a3", "#08519c"]


def _paleta_luni():
    import matplotlib
    from matplotlib.colors import ListedColormap
    if "clima_luni" not in matplotlib.colormaps:
        # +2 culori de capăt: legenda în trepte are și capetele „extend”, deci 14 regiuni pentru 12 luni
        matplotlib.colormaps.register(ListedColormap(CULORI_LUNI[:1] + CULORI_LUNI + CULORI_LUNI[-1:], name="clima_luni"))
    return "clima_luni"


def _pe_pixeli(var, sens, unitate, ani, zona, iesiri, out, nume, n, luna, sezon, interval, an_ev, titlu, restrange=None):
    cub, fr = zc.deschide()
    g = zc.grila_zonei(cub, zona)
    variabile = zc._variabile_pentru(var)
    frontiera = min(fr[v] for v in variabile)
    inceput = np.datetime64(str(cub.time.values[0])[:10], "D")
    agr = _agregare(var)
    ny, nx = g.forma
    best_v, best_d, ani_ok = [], [], []
    import time
    for k, an in enumerate(range(ani[0], ani[1] + 1), 1):
        iv = intervale_an(an, unitate, n=n, luna=luna, sezon=sezon, interval=interval, restrange=restrange)
        a, b = min(x for x, _ in iv), max(y for _, y in iv)
        a, b = max(a, inceput), min(b, frontiera)
        if a > b:
            continue
        t0 = time.perf_counter()
        d, zile = zc.citeste(cub, variabile, a, b, g)
        D = zc._valoare_zilnica(d, var); del d
        bv = np.full((ny, nx), np.nan, "float32"); bd = np.zeros((ny, nx), "int32")
        gasit = False
        for r0 in range(0, ny, BANDA):                    # pe benzi de rânduri: temporarele rămân mici
            v, ivv = candidati(D[:, r0:r0 + BANDA], zile, iv, agr, inceput, frontiera, unitate)
            if not ivv:
                break
            gasit = True
            tot_nan = ~np.isfinite(v).any(axis=0)
            vv = np.where(np.isfinite(v), v, -np.inf if sens == "max" else np.inf)
            i = np.argmax(vv, axis=0) if sens == "max" else np.argmin(vv, axis=0)
            bv[r0:r0 + BANDA] = np.where(tot_nan, np.nan, np.take_along_axis(v, i[None], 0)[0])
            starts = np.array([int(x.astype("datetime64[D]").astype(int)) for x, _ in ivv])
            bd[r0:r0 + BANDA] = starts[i]
        del D
        if not gasit:
            zc.log(f"   {an}: niciun candidat complet în date (exclus)"); continue
        best_v.append(bv); best_d.append(bd); ani_ok.append(an)
        zc.log(f"   {an}: {len(zile)} zile în {time.perf_counter() - t0:.1f} s ({k}/{ani[1] - ani[0] + 1})")
    if len(ani_ok) < 2:
        raise ValueError(f"Prea puțini ani cu date complete în {ani[0]}–{ani[1]} (datele: {inceput} … {frontiera}).")
    V = np.stack(best_v); Dd = np.stack(best_d); del best_v, best_d
    fin = np.isfinite(V)
    vv = np.where(fin, V, -np.inf if sens == "max" else np.inf)
    idx = np.argmax(vv, axis=0) if sens == "max" else np.argmin(vv, axis=0)
    are = fin.any(axis=0)
    rec = np.where(are, np.take_along_axis(V, idx[None], 0)[0], np.nan)
    ani_arr = np.array(ani_ok)
    an_rec = np.where(are, ani_arr[idx], np.nan).astype("float32")
    data_rec = np.take_along_axis(Dd, idx[None], 0)[0]
    # al doilea (recordul anterior, oricare an) → marja
    vv2 = vv.copy(); np.put_along_axis(vv2, idx[None], -np.inf if sens == "max" else np.inf, 0)
    doi = np.max(vv2, axis=0) if sens == "max" else np.min(vv2, axis=0)
    marja = np.where(are & np.isfinite(doi), np.abs(rec - doi), np.nan).astype("float32")
    del vv, vv2
    um = _unitate_masura(var)
    rec = zc._masca_zona(rec.astype("float32"), zona); an_rec = zc._masca_zona(an_rec, zona)
    marja = zc._masca_zona(marja, zona)
    out.mkdir(parents=True, exist_ok=True)
    sub = f"{zona.descriere()} · {ani_ok[0]}–{ani_ok[-1]} ({len(ani_ok)} ani)"
    fis = []
    cm_val = ("Blues" if sens == "max" else "YlOrBr") if var == "precipitation" else ("YlOrRd" if sens == "max" else "PuBu")
    fis += zc._iesiri_harta(out, f"{nume}_valoare", rec, g, zona, SimpleNamespace(unitate=um, cmap=cm_val),
                            f"{titlu}: valoarea recordului", sub, _iesiri_doar(iesiri))
    # anul recordului: harta-vedetă
    pas = 5 if len(ani_ok) > 25 else 1
    clase = [ani_ok[0] - 0.5] + [a + 0.5 for a in range(ani_ok[0] + pas - 1, ani_ok[-1], pas)] + [ani_ok[-1] + 0.5]
    if iesiri.get("png"):
        et_cl = [f"{int(c0 + 0.5)}–{int(c1 - 0.5)}" if c1 - c0 > 1 else str(int(c0 + 0.5)) for c0, c1 in zip(clase[:-1], clase[1:])]
        zc.png_harta(out / f"{nume}_an_record_harta.png", an_rec, g, f"{titlu}: anul recordului", "anul", "viridis",
                     zona=zona, subtitlu=sub, clase=clase, etichete_clase=et_cl, statistici=False)
    if iesiri.get("cog"):
        fis.append(zc.scrie_cog(out / f"{nume}_an_record.tif", [an_rec], g, [f"{titlu}: anul recordului"], "an", cmap="viridis"))
    # data recordului (zi / fereastră: ziua din an; luni: luna)
    if unitate in ("zi", "fereastra", "luni"):
        z = data_rec.astype("datetime64[D]")
        if unitate == "luni":
            h = (z.astype("datetime64[M]").astype(int) % 12 + 1).astype("float32")
            clase_d, et_d, un_d = [x + 0.5 for x in range(0, 13)], LUNI_SCURT, "luna"
        else:
            h = ((z - z.astype("datetime64[Y]").astype("datetime64[D]")).astype(int) + 1).astype("float32")
            clase_d = [0.5] + [int((np.datetime64(f"2001-{m:02d}-01") - np.datetime64("2001-01-01")).astype(int)) + 0.5
                               for m in range(2, 13)] + [366.5]
            et_d, un_d = LUNI_SCURT, "ziua din an (începutul)"
        h = zc._masca_zona(np.where(are, h, np.nan).astype("float32"), zona)
        pal = _paleta_luni()
        if iesiri.get("png"):
            zc.png_harta(out / f"{nume}_data_record_harta.png", h, g, f"{titlu}: când a fost recordul", un_d, pal,
                         zona=zona, subtitlu=sub, clase=clase_d, etichete_clase=et_d, statistici=False)
        if iesiri.get("cog"):
            fis.append(zc.scrie_cog(out / f"{nume}_data_record.tif", [h], g, [f"{titlu}: {un_d}"], un_d))
    fis += zc._iesiri_harta(out, f"{nume}_marja", marja, g, zona, SimpleNamespace(unitate=um, cmap="magma_r"),
                            f"{titlu}: cu cât a depășit recordul următorul an clasat", sub, _iesiri_doar(iesiri))
    rang_h = None
    if an_ev and int(an_ev) in ani_ok:
        j = ani_ok.index(int(an_ev))
        vj = V[j]
        cmp = (V > vj[None]) if sens == "max" else (V < vj[None])
        rang_h = np.where(np.isfinite(vj), 1 + (cmp & fin).sum(axis=0), np.nan).astype("float32")
        rang_h = zc._masca_zona(rang_h, zona)
        if iesiri.get("png"):
            zc.png_harta(out / f"{nume}_rang_{an_ev}_harta.png", rang_h, g,
                         f"{titlu}: locul anului {an_ev} (1 = record) din {len(ani_ok)} ani", "loc", "YlOrRd_r",
                         zona=zona, subtitlu=sub, clase=[0.5, 1.5, 2.5, 3.5, 5.5, 10.5, 20.5, 1000.5],
                         etichete_clase=["1", "2", "3", "4–5", "6–10", "11–20", "> 20"], statistici=False)
        if iesiri.get("cog"):
            fis.append(zc.scrie_cog(out / f"{nume}_rang_{an_ev}.tif", [rang_h], g, [f"locul anului {an_ev}"], "loc"))
    elif an_ev:
        zc.log(f"   [atenție] anul evidențiat {an_ev} nu e printre anii analizați cu date complete")
    # în câți pixeli deține fiecare an recordul
    valid = np.isfinite(an_rec)
    tot = int(valid.sum())
    frecv = [(a, int((an_rec == a).sum())) for a in ani_ok]
    rand = [[a, c, round(100 * c / tot, 2) if tot else 0] for a, c in frecv]
    if iesiri.get("csv", True):
        fis.append(zc.scrie_csv(out / f"{nume}_ani_record.csv", ["an", "pixeli_cu_record", "procent_din_zona"], rand))
    if iesiri.get("png") and tot:
        fis.append(png_frecventa_ani(out / f"{nume}_ani_record.png", frecv, tot, titlu, sub, int(an_ev) if an_ev else None))
    top3 = sorted(frecv, key=lambda x: -x[1])[:3]
    zc.log("   anii cu cele mai multe recorduri: " + ", ".join(f"{a} ({zc.ro(100 * c / max(tot, 1), 1)} % din pixeli)" for a, c in top3))
    rezumat = {"titlu": titlu, "variabila": var, "sens": sens, "unitate": unitate, "mod": "harta", "ani": ani_ok[:1] + ani_ok[-1:],
               "unitate_masura": um, "pixeli": tot, "ani_record": [{"an": a, "pixeli": c} for a, c in top3],
               "record_maxim_zona": (round(float(np.nanmax(rec)), 2) if sens == "max" else round(float(np.nanmin(rec)), 2)) if tot else None}
    if rang_h is not None:
        r = rang_h[np.isfinite(rang_h)]
        rezumat.update(an_evidentiat=int(an_ev), pixeli_record_an=int((r == 1).sum()),
                       procent_record_an=round(100 * float((r == 1).mean()), 2) if r.size else None)
        zc.log(f"   {an_ev}: record în {int((r == 1).sum())} pixeli ({zc.ro(100 * float((r == 1).mean()), 1)} %), "
               f"în top 3 în {zc.ro(100 * float((r <= 3).mean()), 1)} %")
    (out / f"{nume}_rezumat.json").write_text(json.dumps(rezumat, ensure_ascii=False, indent=1), encoding="utf-8")
    zc.log(f"== gata: {nume}")
    return fis


def _iesiri_doar(iesiri):
    """Hărțile pe pixel: COG / PNG / GeoPackage pe poligoane; fără graficul seriei (nu există o serie pe ani aici)."""
    return {k: v for k, v in iesiri.items() if k in ("cog", "png", "gpkg")}


# =====================================================================================
# Grafice
# =====================================================================================
GRI, ACCENT, EVIDENT = "#b8c2cc", "#c2611f", "#0f6b8c"


def png_clasament(cale, lista, titlu, zona_et, um, unitate, an_ev, media, sens, sezon=None, nota_an=None, restrange=None):
    """Bare orizontale: locul 1 sus (accent), anul evidențiat (alt accent), restul gri; valorile pe bare."""
    plt = zc._plt()
    cale = zc._gata(cale)
    n = len(lista)
    fig, ax = plt.subplots(figsize=(9.5, 0.42 * n + 1.6))
    y = np.arange(n)[::-1]
    vals = [v for _, v, _, _ in lista]
    culori = [ACCENT if loc == 1 else (EVIDENT if an_ev and an_candidat(d0, d1, unitate, restrange) == an_ev else GRI)
              for loc, _, d0, d1 in lista]
    # barele pornesc de la o bază aleasă astfel încât recordul să aibă mereu bara cea mai lungă:
    # maxim → din stânga (0 la precipitații); minim de temperatură → din dreapta (cel mai rece = cea mai lungă)
    span = (max(vals) - min(vals)) or 1.0
    spre_stanga = sens == "min" and um != "mm"
    if spre_stanga:
        baza = max(vals) + 0.6 * span
    else:
        baza = 0.0 if (um == "mm" or min(vals) >= 0) else min(vals) - 0.6 * span
    ax.barh(y, [v - baza for v in vals], left=baza, color=culori, height=0.68)
    for yi, (loc, v, d0, d1) in zip(y, lista):
        ax.text(v, yi, f"  {zc.ro(v, 1)} {um}  ", va="center", ha="right" if spre_stanga else "left", fontsize=9, color="#1d2733")
        ax.text(baza, yi, f"  {eticheta(d0, d1, unitate, sezon)}  ", va="center", ha="left" if spre_stanga else "right",
                fontsize=9, color="#1d2733")
    if media is not None:
        ax.axvline(media, color="#5e6e7c", lw=1, ls="--")
        ax.text(media, n - 0.35, f" media: {zc.ro(media, 1)}", fontsize=8, color="#5e6e7c", va="bottom")
    ext = [min(vals) - 0.18 * (baza - min(vals)), baza] if spre_stanga else [baza, max(vals) + (max(vals) - baza) * 0.18]
    if media is not None:
        ext = [min(ext[0], media), max(ext[1], media)]
    ax.set_yticks([]); ax.set_xlim(*ext)
    if spre_stanga:
        ax.spines["right"].set_visible(True); ax.spines["bottom"].set_visible(True)
    for s in ("top", "left") + (() if spre_stanga else ("right",)):
        ax.spines[s].set_visible(False)
    ax.set_xlabel(um)
    ax.set_title(f"{titlu} · {zona_et}\nprimele {n}" + (f" · {nota_an}" if nota_an else ""), fontsize=11, loc="left")
    fig.text(0.0, -0.02, zc.ATRIBUIRE, fontsize=8, color="#555555")
    fig.savefig(cale, dpi=zc.DPI, bbox_inches="tight"); plt.close(fig)
    zc.log(f"   PNG clasament: {cale}")
    return cale


def png_serie_superlativ(cale, ani_v, vals, lista, titlu, zona_et, um, an_ev, sens):
    """Valoarea fiecărui an (unitățile cu un candidat pe an), recordul și primele 3 marcate."""
    plt = zc._plt()
    cale = zc._gata(cale)
    x = np.asarray(ani_v); y = np.asarray(vals, float); ok = np.isfinite(y)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(x[ok], y[ok], color=GRI, width=0.75)
    sus = {an_candidat(d0, d1, "sezon"): (loc, v) for loc, v, d0, d1 in lista[:3]}
    for a, (loc, v) in sus.items():
        ax.bar([a], [v], color=ACCENT if loc == 1 else "#e3a37c", width=0.75)
        ax.annotate(f"{loc}. {a}", (a, v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8.5,
                    color="#1d2733", fontweight="bold" if loc == 1 else "normal")
    if an_ev and an_ev in set(x[ok]):
        v = y[x == an_ev][0]
        ax.bar([an_ev], [v], color=EVIDENT, width=0.75)
    ax.axhline(np.nanmean(y), color="#5e6e7c", lw=1, ls="--")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_ylabel(um)
    ax.set_title(f"{titlu} · {zona_et}: fiecare an", fontsize=11, loc="left")
    fig.text(0.0, -0.03, zc.ATRIBUIRE, fontsize=8, color="#555555")
    fig.savefig(cale, dpi=zc.DPI, bbox_inches="tight"); plt.close(fig)
    zc.log(f"   PNG serie: {cale}")
    return cale


def png_recorduri_zone(cale, zone, titlu, um, sens):
    """Recordul fiecărei zone, ordonat, cu anul recordului scris pe bară."""
    plt = zc._plt()
    cale = zc._gata(cale)
    z = sorted(zone, key=lambda r: r["record"], reverse=(sens == "max"))
    n = len(z)
    fig, ax = plt.subplots(figsize=(9.5, 0.32 * n + 1.6))
    y = np.arange(n)[::-1]
    vals = [r["record"] for r in z]
    baza = 0.0 if (um == "mm" or min(vals) >= 0) else min(vals) - 1
    ax.barh(y, [v - baza for v in vals], left=baza, color=GRI, height=0.7)
    for yi, r in zip(y, z):
        ax.text(r["record"], yi, f"  {zc.ro(r['record'], 1)} · {r['eticheta']}", va="center", fontsize=8.5)
    ax.set_yticks(y); ax.set_yticklabels([r["zona"] for r in z], fontsize=8.5)
    ax.set_xlim(baza, max(vals) + (max(vals) - baza) * 0.45)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel(um)
    ax.set_title(f"{titlu}: recordul fiecărei zone", fontsize=11, loc="left")
    fig.text(0.0, -0.02, zc.ATRIBUIRE, fontsize=8, color="#555555")
    fig.savefig(cale, dpi=zc.DPI, bbox_inches="tight"); plt.close(fig)
    zc.log(f"   PNG recorduri pe zone: {cale}")
    return cale


def png_frecventa_ani(cale, frecv, tot, titlu, sub, an_ev):
    """În ce procent din pixeli deține fiecare an recordul."""
    plt = zc._plt()
    cale = zc._gata(cale)
    a = np.array([x for x, _ in frecv]); p = np.array([100 * c / tot for _, c in frecv])
    fig, ax = plt.subplots(figsize=(10, 3.8))
    culori = [EVIDENT if an_ev and x == an_ev else (ACCENT if v == p.max() else GRI) for x, v in zip(a, p)]
    ax.bar(a, p, color=culori, width=0.8)
    for x, v in sorted(zip(a, p), key=lambda t: -t[1])[:3]:
        if v > 0:
            ax.annotate(f"{x}: {zc.ro(v, 1)} %", (x, v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_ylabel("% din pixelii zonei")
    ax.set_title(f"{titlu}: în ce an a fost recordul\n{sub}", fontsize=11, loc="left")
    fig.text(0.0, -0.03, zc.ATRIBUIRE, fontsize=8, color="#555555")
    fig.savefig(cale, dpi=zc.DPI, bbox_inches="tight"); plt.close(fig)
    zc.log(f"   PNG anii recordurilor: {cale}")
    return cale
