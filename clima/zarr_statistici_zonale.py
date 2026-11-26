# -*- coding: utf-8 -*-
"""
zarr_statistici_zonale.py — statistici zilnice pe zone (min / max / medie a pixelilor) + agregări lunare și sezoniere
====================================================================================================================
Folosit de 18_statistici_zonale.py. Reunește într-un singur pas:
  (1) seria zilnică pe fiecare zonă: pentru fiecare zi, minima, maxima și media pixelilor din poligon;
  (2) agregările: lunar pe fiecare an, lunar multianual, sezonier pe fiecare an climatic, sezonier multianual.

Cubul se citește o singură dată pentru toate zonările (județe, regiuni…), în blocuri de timp aliniate la chunk-uri.
"""
import csv
import math
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

import zarr_clima as zc

# numele variabilelor în CSV (aceleași ca în scripturile vechi statistici_nc.py / statistici_anotimpuale.py)
CHEI = {"precipitation": "precip", "max_temp": "tmax", "min_temp": "tmin", "tmedie": "tmed"}
SEZON_LUNI = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}
ORDINE_SEZON = {"DJF": 1, "MAM": 2, "JJA": 3, "SON": 4}


def _sezon(an, luna):
    """(an_climatic, sezon). Decembrie intră în DJF-ul anului următor."""
    if luna == 12:
        return an + 1, "DJF"
    for s, l in SEZON_LUNI.items():
        if luna in l:
            return an, s


def _zile_luna(an, luna):
    a = np.datetime64(f"{an}-{luna:02d}", "M")
    return int(((a + 1).astype("datetime64[D]") - a.astype("datetime64[D]")).astype(int))


def _zile_sezon(an_climatic, sezon):
    """Numărul nominal de zile ale unui sezon dintr-un an climatic (DJF include decembrie din anul precedent)."""
    if sezon == "DJF":
        return _zile_luna(an_climatic - 1, 12) + _zile_luna(an_climatic, 1) + _zile_luna(an_climatic, 2)
    return sum(_zile_luna(an_climatic, l) for l in SEZON_LUNI[sezon])


class _ScriitorCSV:
    def __init__(self, fmt):
        if fmt not in ("standard", "ro"):
            raise ValueError('FORMAT_CSV trebuie să fie "standard" (virgulă + punct zecimal) sau "ro" (; + virgulă zecimală)')
        self.sep = "," if fmt == "standard" else ";"
        self.ro = fmt == "ro"

    def val(self, v):
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return ""
        if isinstance(v, float):
            s = f"{round(v, 4):.4f}".rstrip("0").rstrip(".")
            if s in ("-0", ""):
                s = "0"
            return s.replace(".", ",") if self.ro else s
        return v

    def scrie(self, cale, antet, randuri):
        cale = Path(cale); cale.parent.mkdir(parents=True, exist_ok=True)
        with open(cale, "w", newline="", encoding="utf-8-sig") as f:   # BOM: diacriticele se văd corect în Excel
            w = csv.writer(f, delimiter=self.sep)
            w.writerow(antet)
            for r in randuri:
                w.writerow([self.val(v) for v in r])
        zc.log(f"   CSV: {cale.name} ({len(randuri)} rânduri)")
        return cale


def ruleaza_statistici_zonale(fisier, strat, zonari, variabile, perioada, iesiri, out, format_csv="standard"):
    out = Path(out)
    t_start = time.perf_counter()
    cw = _ScriitorCSV(format_csv)
    for v in variabile:
        if v not in CHEI:
            raise ValueError(f"Variabilă necunoscută: «{v}». Alegeți dintre: {', '.join(CHEI)}")
    if not zonari:
        raise ValueError("ZONARI este gol: dați cel puțin o zonare (ex. județele, coloana „name”).")

    cub, fr = zc.deschide()
    # ------------------------------------------------------------------ zonele și grila comună
    zone = []
    for zn in zonari:
        z = zc.Zona.poligoane(fisier, coloana=zn["coloana"], strat=strat, valori=zn.get("valori"))
        if zn.get("altitudine"):
            z.cu_altitudine(*zn["altitudine"])
        g = zc.grila_zonei(cub, z)
        zone.append((zn, z, g))
    bb = [z.bbox for _, z, _ in zone]
    zu = zc.Zona.dreptunghi(min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb))
    gu = zc.grila_zonei(cub, zu)
    nyu, nxu = gu.forma
    indici = []                                   # pentru fiecare zonare: [(eticheta, indici plați în grila comună)]
    for zn, z, g in zone:
        dy, dx = g.iy0 - gu.iy0, g.ix0 - gu.ix0
        idg = np.zeros((nyu, nxu), "int32")
        idg[dy:dy + g.forma[0], dx:dx + g.forma[1]] = z._id
        flat = idg.ravel()
        lista = []
        for k, (et, _) in enumerate(z.poligoane, 1):
            ix = np.nonzero(flat == k)[0]
            lista.append((et, ix))
        goale = [et for et, ix in lista if ix.size == 0]
        if goale:
            zc.log(f"   [atenție] zone fără niciun pixel în grilă (în afara cubului?): {', '.join(goale)}")
        indici.append(lista)
        zc.log(f"   zonarea „{zn['prefix']}”: {len(lista)} zone · pixeli pe zonă: "
               f"{min(ix.size for _, ix in lista)}–{max(ix.size for _, ix in lista)}")
    zc.log(f"   grila comună: {nyu} × {nxu} pixeli")

    # ------------------------------------------------------------------ (1) seria zilnică pe zone
    zilnic = [defaultdict(list) for _ in zone]    # pentru fiecare zonare: {cheie_var: [rânduri]}
    t_cub0 = np.datetime64(str(cub.time.values[0])[:10], "D")
    for var in variabile:
        cheie = CHEI[var]
        surse = ("max_temp", "min_temp") if var == "tmedie" else (var,)
        frontiera = min(fr[s] for s in surse)
        d0 = max(np.datetime64(perioada[0], "D"), t_cub0)
        d1 = np.datetime64(perioada[1], "D") if perioada[1] else frontiera
        if d1 > frontiera:
            zc.log(f"   [atenție] {cheie}: sfârșitul {d1} depășește frontiera datelor ({frontiera}); tai la {frontiera}")
            d1 = frontiera
        if d1 < d0:
            zc.log(f"   [atenție] {cheie}: perioada {d0} → {d1} e goală; sar peste variabilă"); continue
        ct = cub[surse[0]].encoding.get("chunks", (90,))[0]
        i0 = int((d0 - t_cub0).astype(int)); i1 = int((d1 - t_cub0).astype(int))
        blocuri = [(t_cub0 + max(a, i0), t_cub0 + min(a + ct - 1, i1)) for a in range((i0 // ct) * ct, i1 + 1, ct)]
        gb = sum(zc.estimeaza_cost(cub, s, a, b, gu)[1] for a, b in blocuri for s in surse) / 1000
        zc.log(f"== {cheie}: {d0} → {d1} · {len(blocuri)} blocuri, ~{gb:.1f} GB de citit")
        t0 = time.perf_counter()
        for kb, (a, b) in enumerate(blocuri, 1):
            d, zile = zc.citeste(cub, surse, a, b, gu)
            v = (d["max_temp"] + d["min_temp"]) / 2 if var == "tmedie" else d[var]
            del d
            vf = v.reshape(v.shape[0], -1)
            for kz, lista in enumerate(indici):
                for et, ix in lista:
                    if ix.size == 0:
                        continue
                    sub = vf[:, ix]
                    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
                        warnings.simplefilter("ignore", category=RuntimeWarning)
                        mn, mx, me = np.nanmin(sub, axis=1), np.nanmax(sub, axis=1), np.nanmean(sub, axis=1)
                    for i, zi in enumerate(zile):
                        s = str(zi)
                        an = int(s[:4])
                        zi_an = int((zi - np.datetime64(f"{an}-01-01")).astype(int)) + 1
                        zilnic[kz][cheie].append([cheie, an, zi_an, s, et, float(mn[i]), float(mx[i]), float(me[i])])
            if kb == 1 or kb == len(blocuri) or kb % 10 == 0:
                rest = (time.perf_counter() - t0) / kb * (len(blocuri) - kb)
                zc.log(f"   bloc {kb}/{len(blocuri)}: {a} → {b}" + (f" · mai durează ~{rest / 60:.0f} min" if kb < len(blocuri) else ""))

    # ------------------------------------------------------------------ ieșiri pe fiecare zonare
    fisiere = []
    for (zn, z, _), zil in zip(zone, zilnic):
        pre, ent = zn["prefix"], zn["eticheta"]
        antet = ["variabila", "an", "banda_zi", "data_calendaristica", ent, "min", "max", "media"]
        toate = []
        for cheie in [CHEI[v] for v in variabile if CHEI[v] in zil]:
            rand = sorted(zil[cheie], key=lambda r: (r[4], r[3]))
            toate += rand
            if iesiri.get("zilnic_pe_variabila"):
                fisiere.append(cw.scrie(out / f"stats_{pre}_{cheie}.csv", antet, rand))
        if iesiri.get("zilnic_total"):
            fisiere.append(cw.scrie(out / f"stats_{pre}.csv", antet, toate))
        fisiere += _agregari(toate, pre, ent, out, cw, iesiri)
    zc.log(f"== gata în {(time.perf_counter() - t_start) / 60:.1f} min · fișierele în {out}")
    return fisiere


def _agregari(randuri, pre, ent, out, cw, iesiri):
    """Lunar pe ani, lunar multianual, sezonier pe ani, sezonier multianual (ca statistici_anotimpuale.py)."""
    luna_an = defaultdict(list); luna_clim = defaultdict(list)
    sez_an = defaultdict(list); sez_clim = defaultdict(list)
    ani_luna = defaultdict(set); ani_sezon = defaultdict(set)      # ce ani (calendaristici / climatici) apar
    for var, an, _, data, et, mn, mx, me in randuri:
        if not (math.isfinite(mn) and math.isfinite(mx) and math.isfinite(me)):
            continue                                              # zi fără date în zonă: se omite
        luna = int(data[5:7])
        rec = (mn, mx, me)
        luna_an[(var, an, luna, et)].append(rec); luna_clim[(var, luna, et)].append(rec)
        ac, s = _sezon(an, luna)
        sez_an[(var, ac, s, et)].append(rec); sez_clim[(var, s, et)].append(rec)
        ani_luna[(var, luna)].add(an); ani_sezon[(var, s)].add(ac)

    def st(recs):
        n = len(recs)
        return n, min(r[0] for r in recs), max(r[1] for r in recs), sum(r[2] for r in recs) / n, sum(r[2] for r in recs)

    def lung_medie_luna(var, luna):
        a = sorted(ani_luna[(var, luna)]); return sum(_zile_luna(x, luna) for x in a) / len(a)

    def lung_medie_sezon(var, s):
        a = sorted(ani_sezon[(var, s)]); return sum(_zile_sezon(x, s) for x in a) / len(a)

    fis = []
    # 1. lunar pe fiecare an
    r = []
    for k in sorted(luna_an, key=lambda x: (x[0], x[3], x[1], x[2])):
        var, an, luna, et = k
        n, mn, mx, me, sm = st(luna_an[k])
        r.append([var, an, luna, et, n, mn, mx, me, sm if var == "precip" else None])
    if iesiri.get("lunar_anual"):
        fis.append(cw.scrie(out / f"stats_{pre}_lunar_anual.csv",
                            ["variabila", "an", "luna", ent, "nr_zile", "min_absolut", "max_absolut", "media_lunara",
                             "precip_cumulat_mm"], r))
    # 2. lunar multianual
    r = []
    for k in sorted(luna_clim, key=lambda x: (x[0], x[2], x[1])):
        var, luna, et = k
        n, mn, mx, me, _ = st(luna_clim[k])
        r.append([var, luna, et, n, mn, mx, me, me * lung_medie_luna(var, luna) if var == "precip" else None])
    if iesiri.get("lunar_multianual"):
        fis.append(cw.scrie(out / f"stats_{pre}_lunar_multianual.csv",
                            ["variabila", "luna", ent, "nr_total_zile", "min_absolut_multianual", "max_absolut_multianual",
                             "media_multianuala", "precip_mediu_lunar_mm"], r))
    # 3. sezonier pe fiecare an climatic
    r = []
    for k in sorted(sez_an, key=lambda x: (x[0], x[3], x[1], ORDINE_SEZON[x[2]])):
        var, ac, s, et = k
        n, mn, mx, me, sm = st(sez_an[k])
        r.append([var, ac, s, et, n, "DA" if n >= _zile_sezon(ac, s) else "NU", mn, mx, me, sm if var == "precip" else None])
    if iesiri.get("sezonier_anual"):
        fis.append(cw.scrie(out / f"stats_{pre}_sezonier_anual.csv",
                            ["variabila", "an_climatic", "sezon", ent, "nr_zile", "sezon_complet", "min_absolut",
                             "max_absolut", "media_sezoniera", "precip_cumulat_mm"], r))
    # 4. sezonier multianual
    r = []
    for k in sorted(sez_clim, key=lambda x: (x[0], x[2], ORDINE_SEZON[x[1]])):
        var, s, et = k
        n, mn, mx, me, _ = st(sez_clim[k])
        r.append([var, s, et, n, mn, mx, me, me * lung_medie_sezon(var, s) if var == "precip" else None])
    if iesiri.get("sezonier_multianual"):
        fis.append(cw.scrie(out / f"stats_{pre}_sezonier_multianual.csv",
                            ["variabila", "sezon", ent, "nr_total_zile", "min_absolut_multianual", "max_absolut_multianual",
                             "media_multianuala", "precip_mediu_sezonier_mm"], r))
    return fis
