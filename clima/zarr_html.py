# -*- coding: utf-8 -*-
"""
zarr_html.py — fișa interactivă de episod: un singur fișier HTML, autonom (fără server, funcționează și offline)
================================================================================================================
Primește un dicționar H (pregătit de zarr_episod.analizeaza) și scrie HTML-ul:

  * hărțile (straturile statistice + cubul zilnic) sunt cuantizate pe 16 biți, comprimate (zlib) și incluse în pagină;
  * paletele sunt aceleași ca în PNG-uri (matplotlib), eșantionate în 256 de culori;
  * contururile (frontiera, poligoanele zonei) sunt simplificate (Douglas–Peucker, ~0,5 km) și incluse ca linii;
  * Chart.js (chart.umd.js, din același folder) este inclus în pagină, deci graficele merg fără internet.

Mărimea fișierului: ~0,2–0,5 MB pe strat la rezoluția grilei (0,01°) și ~0,3–0,5 MB pe zi pentru cubul zilnic;
`factor` = 2 sau 3 reduce rezoluția hărților (0,02° / 0,03°) și mărimea de 4 / 9 ori.
"""
from __future__ import annotations

import base64
import json
import math
import warnings
import zlib
from pathlib import Path

import numpy as np

import zarr_clima as zc

FOLDER = Path(__file__).resolve().parent
MB_MAX_ZILE = 14.0       # mărimea (MB, comprimată) peste care cubul zilnic își reduce singur rezoluția


# ------------------------------------------------------------------------------------------------
# paletă și cuantizare
# ------------------------------------------------------------------------------------------------
def _lut(cmap):
    import matplotlib
    from matplotlib.colors import to_hex
    cm = matplotlib.colormaps[cmap]
    return [to_hex(cm(i / 255)) for i in range(256)]


def _bloc(a, f):
    """Reducere prin media blocurilor f×f (NaN ignorat); lucrează pe ultimele două axe."""
    a = np.asarray(a, np.float32)
    if f <= 1:
        return a
    ny, nx = a.shape[-2:]
    py, px = (-ny) % f, (-nx) % f
    a = np.pad(a, [(0, 0)] * (a.ndim - 2) + [(0, py), (0, px)], constant_values=np.nan)
    sh = a.shape[:-2] + (a.shape[-2] // f, f, a.shape[-1] // f, f)
    b = a.reshape(sh)
    fin = np.isfinite(b)
    s = np.where(fin, b, 0).sum(axis=(-3, -1))
    n = fin.sum(axis=(-3, -1))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.where(n > 0, s / np.maximum(n, 1), np.nan).astype(np.float32)


def _impacheteaza(a, lo, hi):
    """float → uint16 (65535 = NaN), octeții shuffle-uiți (toți cei mici, apoi toți cei mari), zlib, base64."""
    a = np.asarray(a, np.float32)
    rng = (hi - lo) or 1.0
    q = np.where(np.isfinite(a), np.clip(np.round((a - lo) / rng * 65534), 0, 65534), 65535).astype("<u2")
    sh = q.reshape(-1).view(np.uint8).reshape(-1, 2).T.ravel()
    return base64.b64encode(zlib.compress(sh.tobytes(), 9)).decode("ascii")


def _interval(a):
    f = a[np.isfinite(a)]
    return (float(f.min()), float(f.max())) if f.size else (0.0, 1.0)


def _norm_afisare(a, divergent=False, vmin=None, vmax=None, centru=None):
    """Aceeași regulă ca zc.png_harta: percentilele 2–98 (sau simetric în jurul lui 0 pentru anomalii)."""
    f = a[np.isfinite(a)]
    if f.size == 0:
        return dict(vmin=0, vmax=1, centru=None)
    if divergent:
        if vmin is not None and vmax is not None:
            return dict(vmin=float(vmin), vmax=float(vmax), centru=float(centru if centru is not None else (vmin + vmax) / 2))
        m = float(np.nanpercentile(np.abs(f), 98)) or 1.0
        return dict(vmin=-m, vmax=m, centru=0.0)
    lo = float(vmin) if vmin is not None else float(np.nanpercentile(f, 2))
    hi = float(vmax) if vmax is not None else float(np.nanpercentile(f, 98))
    return dict(vmin=lo, vmax=hi if hi > lo else lo + 1.0, centru=None)


# ------------------------------------------------------------------------------------------------
# vectori
# ------------------------------------------------------------------------------------------------
def _rdp(p, eps):
    n = len(p)
    if n < 3:
        return p
    keep = np.zeros(n, bool); keep[0] = keep[-1] = True
    stiva = [(0, n - 1)]
    while stiva:
        i, j = stiva.pop()
        if j <= i + 1:
            continue
        a, b = p[i], p[j]; seg = p[i + 1:j]
        d = b - a; L = math.hypot(d[0], d[1])
        dist = np.hypot(*(seg - a).T) if L == 0 else np.abs(d[0] * (seg[:, 1] - a[1]) - d[1] * (seg[:, 0] - a[0])) / L
        k = int(np.argmax(dist))
        if dist[k] > eps:
            m = i + 1 + k; keep[m] = True
            stiva += [(i, m), (m, j)]
    return p[keep]


def _linii_simple(linii, extent, eps=0.005, marja=0.5):
    """Liniile care ating fereastra hărții, simplificate, ca liste plate [lon, lat, lon, lat, …] rotunjite la 3 zecimale."""
    w, e, s, n = extent
    out = []
    for p in linii:
        p = np.asarray(p, float)
        if len(p) < 2:
            continue
        if p[:, 0].max() < w - marja or p[:, 0].min() > e + marja or p[:, 1].max() < s - marja or p[:, 1].min() > n + marja:
            continue
        q = _rdp(p, eps)
        out.append([round(float(v), 3) for v in q.ravel()])
    return out


def _poligoane(zona, extent):
    """[(eticheta, [linii plate])] pentru fiecare poligon din Zona (inelele, pentru testul punct-în-poligon, par–impar)."""
    from osgeo import ogr
    out = []
    for et, wkt in zona.poligoane:
        out.append(dict(nume=et, linii=_linii_simple(zc._linii_geometrie(ogr.CreateGeometryFromWkt(wkt)), extent, eps=0.004)))
    return out


# ------------------------------------------------------------------------------------------------
# curățare JSON, markdown minimal
# ------------------------------------------------------------------------------------------------
def _curata(o):
    if isinstance(o, dict):
        return {str(k): _curata(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_curata(v) for v in o]
    if isinstance(o, np.ndarray):
        return _curata(o.tolist())
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return round(v, 4) if math.isfinite(v) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.datetime64,)):
        return str(o)
    return o


def _md_html(md):
    import html
    import re
    out, lista = [], False

    def inline(t):
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", t)

    for ln in md.splitlines():
        if ln.startswith("- "):
            if not lista:
                out.append("<ul>"); lista = True
            out.append(f"<li>{inline(ln[2:])}</li>")
            continue
        if lista:
            out.append("</ul>"); lista = False
        if ln.startswith("## "):
            out.append(f"<h3>{inline(ln[3:])}</h3>")
        elif ln.startswith("# "):
            out.append(f"<h2>{inline(ln[2:])}</h2>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
    if lista:
        out.append("</ul>")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------
# construirea paginii
# ------------------------------------------------------------------------------------------------
def scrie_html(cale, H, factor=1):
    """H = dict pregătit de zarr_episod. Scrie fișierul și returnează calea."""
    cale = zc._gata(cale)
    luts = {}

    def lut(nume):
        if nume not in luts:
            luts[nume] = _lut(nume)
        return nume

    D = {k: v for k, v in H.items() if k not in ("harti", "raport_md")}
    D["raport_html"] = _md_html(H.get("raport_md", ""))
    if H.get("calendar"):
        lut(H["calendar"]["lut"])
    if H.get("zone_straturi"):
        D["zone_straturi"] = []
        for L in H["zone_straturi"]:
            arr = np.array([np.nan if x is None else x for x in L["arr"]], float)
            nrm = _norm_afisare(arr, L.get("divergent", False), L.get("vmin"), L.get("vmax"), L.get("centru"))
            D["zone_straturi"].append(dict(id=L["id"], titlu=L["titlu"], unit=L["unit"], vals=arr, lut=lut(L["cmap"]), **nrm))

    # ----------------------------------------------------------------- hărți
    hz = H.get("harti")
    if hz:
        g = hz["grila"]                                    # dict: extent [w, e, s, n], pas, ny, nx
        w, e, s, n = g["extent"]
        f = max(1, int(factor))
        strat = []
        for L in hz["straturi"]:
            a = _bloc(L["arr"], f)
            lo, hi = _interval(a)
            nrm = _norm_afisare(L["arr"], L.get("divergent", False), L.get("vmin"), L.get("vmax"), L.get("centru"))
            d = dict(id=L["id"], titlu=L["titlu"], unit=L["unit"], descr=L.get("descr", ""), nx=int(a.shape[1]), ny=int(a.shape[0]),
                     lo=lo, hi=hi, blob=_impacheteaza(a, lo, hi), lut=lut(L["cmap"]), **nrm)
            if L.get("clase"):
                import matplotlib
                from matplotlib.colors import BoundaryNorm, to_hex
                cl = list(L["clase"]); bn = BoundaryNorm(cl, 256, extend="both"); cm = matplotlib.colormaps[L["cmap"]]
                d["clase"] = cl; d["etichete"] = L["etichete"]
                d["culori"] = [to_hex(cm(bn((a_ + b_) / 2))) for a_, b_ in zip(cl[:-1], cl[1:])]
            strat.append(d)
        cub = None
        if hz.get("cub") is not None:
            cube = np.asarray(hz["cub"], np.float32)       # (zile, ny, nx)
            ff = f
            while True:
                c2 = _bloc(cube, ff)
                lo, hi = _interval(c2)
                blob = _impacheteaza(c2, lo, hi)
                if len(blob) / 1e6 <= MB_MAX_ZILE or ff >= 6:
                    break
                ff += 1
            zc.log(f"   HTML: cub zilnic {c2.shape[0]} zile × {c2.shape[1]}×{c2.shape[2]} (factor {ff}), {len(blob) / 1e6:.1f} MB")
            cum = hz["cum_mod"]
            pozitiv = cum == "suma"
            cub = dict(zile=[str(z) for z in hz["zile"]], nx=int(c2.shape[2]), ny=int(c2.shape[1]), factor=ff, lo=lo, hi=hi, blob=blob,
                       cum_mod=cum, unit=hz["unit_zi"], titlu_zi=hz["titlu_zi"], titlu_cum=hz["titlu_cum"],
                       lut_zi=lut(hz["cmap_zi"]), lut_cum=lut(hz["cmap_cum"]),
                       vmin_zi=hz["v_zi"][0], vmax_zi=hz["v_zi"][1], vmin_cum=hz["v_cum"][0], vmax_cum=hz["v_cum"][1], pozitiv=pozitiv)
        D["harti"] = dict(extent=[w, e, s, n], pas=g["pas"], factor=f, straturi=strat, cub=cub,
                          contur=_linii_simple(hz.get("contur") or [], (w, e, s, n)),
                          poligoane=hz.get("poligoane") or [], punct=hz.get("punct"))
    D["luts"] = luts

    sablon = (FOLDER / "fisa_episod_sablon.html").read_text(encoding="utf-8")
    chart = (FOLDER / "chart.umd.js").read_text(encoding="utf-8")
    js = json.dumps(_curata(D), ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    titlu = f"{H['meta']['titlu_var']} · {H['meta']['zona']} · {H['meta']['perioada']}"
    html = (sablon.replace("__TITLU__", titlu.replace("<", "&lt;"))
                  .replace("/*__CHARTJS__*/", chart.replace("</script", "<\\/script"))
                  .replace("/*__DATE__*/", "const D = " + js + ";"))
    cale.write_text(html, encoding="utf-8")
    zc.log(f"   HTML: {cale} ({cale.stat().st_size / 1e6:.1f} MB)")
    return cale
