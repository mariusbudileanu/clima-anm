# -*- coding: utf-8 -*-
"""
zarr_episod.py — analiza generică a unei perioade / a unui episod excepțional (folosit de 16_analiza_episod.py)
==========================================================================================================
NU se rulează direct. Folosește nucleul zarr_clima.py.

Trei surse de date, toate cu cache (rezultate/_cache/serii, rezultate/_cache/episod):
  A. seria zilnică medie a zonei de analiză, pe TOT istoricul (1961 → frontieră)
     → raritate, top episoade, perioadă de revenire, șiruri, praguri, context anterior, calendar, frecvență;
  B. fereastra episodului, în fiecare an, pe grila hărților
     → hărți: statistici, anomalie, rang istoric per pixel, extinderea spațială, animația GIF;
  C. celelalte variabile pe aceleași ferestre, pentru zonă → contextul (termic / pluviometric).

Analizele (numerotarea din discuție):
   1 rangul pe aceeași fereastră calendaristică       8 hărțile episodului (+ rangul per pixel)
   2 topul episoadelor de N zile, oricând în an        9 extinderea spațială (fracția din teritoriu)
   3 perioada de revenire (Gumbel, metoda momentelor) 10 contextul celorlalte variabile
   4 șiruri de zile excepționale (ploioase / >p90)     11 calendarul termic zi × an
   5 ziua extremă și pragurile p95 / p99              12 animația GIF zi cu zi
   6 echivalențe (% din normala lunii / anului)       13 comparația cu alte episoade
   7 contextul anterior (30 / 60 / 90 de zile)        14 frecvența episoadelor similare în timp
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

import zarr_clima as zc

INCEPUT_CUB = np.datetime64("1961-01-01", "D")      # prima zi a cubului; se citește din store în analizeaza()

LUNI = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi", "dec"]
LUNI_LUNG = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie",
             "octombrie", "noiembrie", "decembrie"]


# =====================================================================================
# Utilitare de timp și de serie
# =====================================================================================
def _bisect(an):
    return an % 4 == 0 and (an % 100 != 0 or an % 400 == 0)


def _fereastra_an(d0, n, an):
    """Aceeași zi de start (lună-zi) în anul `an`, aceeași lungime `n` (29 feb → 28 feb în anii nebisecți)."""
    an0 = int(str(d0)[:4]); md = str(d0)[5:10]
    if md == "02-29" and not _bisect(an):
        md = "02-28"
    a = np.datetime64(f"{an}-{md}")
    return a, a + (n - 1), an - an0


def _serie_continua(serii, k):
    ani = sorted(serii)
    z = np.concatenate([np.datetime64(f"{a}-01-01") + np.arange(serii[a].shape[1]) for a in ani])
    v = np.concatenate([serii[a][k] for a in ani]).astype(float)
    return z, v


def _doy366(zile):
    """Indicele zilei pe o axă de 366 de zile (29 feb = 59)."""
    ani = zile.astype("datetime64[Y]").astype(int) + 1970
    i = (zile - zile.astype("datetime64[Y]").astype("datetime64[D]")).astype(int)
    bis = np.array([_bisect(a) for a in ani])
    return np.where(~bis & (i >= 59), i + 1, i)


def _rulant_n(v, n, mod):
    """Statistica ferestrei de n zile care se ÎNCHEIE la fiecare zi (sumă sau medie), NaN sub 90 % zile valide."""
    fin = np.isfinite(v)
    c = np.cumsum(np.r_[0.0, np.where(fin, v, 0.0)]); cn = np.cumsum(np.r_[0, fin.astype(int)])
    s = c[n:] - c[:-n]; k = cn[n:] - cn[:-n]
    out = np.full(len(v), np.nan)
    ok = k >= 0.9 * n
    val = s * n / np.maximum(k, 1) if mod == "suma" else s / np.maximum(k, 1)
    out[n - 1:] = np.where(ok, val, np.nan)
    return out


def _stat(v, mod, minim=0.9):
    v = np.asarray(v, float); fin = np.isfinite(v); n = v.size
    if n == 0 or fin.sum() < minim * n:
        return np.nan
    return float(np.nansum(v) * n / fin.sum()) if mod == "suma" else float(np.nanmean(v))


def _runs(mask):
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(int))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


FEREASTRA_SEZON = 30      # (2) și (3): doar episoadele care se încheie la ±30 zile (în calendar) de sfârșitul episodului
FEREASTRA_PRAG = 15       # (5): p95/p99 din zilele aflate la ±15 zile (în calendar) de zilele episodului; ×2 la precipitații


def _dist_doy(doy, ref):
    """Distanța circulară (zile) pe axa de 366 de zile, între fiecare valoare din `doy` și `ref`."""
    d = np.abs(np.asarray(doy) - ref)
    return np.minimum(d, 366 - d)


def _gumbel(maxime):
    """Ajustare Gumbel prin metoda momentelor: (mu, beta). Fără scipy."""
    x = np.asarray([m for m in maxime if np.isfinite(m)], float)
    if x.size < 10:
        return None
    beta = x.std(ddof=1) * math.sqrt(6) / math.pi
    if not np.isfinite(beta) or beta <= 0:
        return None
    mu = x.mean() - 0.5772156649 * beta
    return mu, beta


def _perioada_revenire(x, mu, beta):
    z = (float(x) - mu) / beta
    if z < -7:
        return 1.0
    coada = -math.expm1(-math.exp(-z))
    return 1.0 / coada if coada else np.inf


def _nivel_revenire(T, mu, beta):
    return mu - beta * math.log(-math.log(1 - 1 / T))


def _sau_liniuta(x):
    return "–" if x is None else x


def _top_declusterizat(stat, zile, n, mare=True, top=10, exclus=None, prag=None, max_iter=None):
    """Evenimente de n zile care nu se suprapun (cel mai mare, apoi următorul în afara lui ±n zile …).
    `exclus` = (z0, z1) interval de exclus (episodul curent). Returnează [(start, sfârșit, valoare)]."""
    s = np.where(np.isfinite(stat), stat if mare else -stat, -np.inf).astype(float)
    if exclus is not None:
        m = (zile >= exclus[0]) & (zile - (n - 1) <= exclus[1])
        s[m] = -np.inf
    out = []
    for _ in range(len(s) if max_iter is None else max_iter):
        i = int(np.argmax(s))
        if not np.isfinite(s[i]):
            break
        v = s[i] if mare else -s[i]
        if prag is not None and ((v <= prag) if mare else (v >= prag)):
            break
        out.append((zile[i] - (n - 1), zile[i], float(stat[i])))
        s[max(0, i - (n - 1)): i + n] = -np.inf
        if prag is None and len(out) >= top:
            break
    return out


# =====================================================================================
# Citiri pe ferestre (sursele B și C)
# =====================================================================================
def _citeste_ferestre(cub, variabile, d0, n, ani, g, frontiera, functie, eticheta=""):
    """Pentru fiecare an: citește fereastra (start = aceeași lună-zi, n zile) și aplică `functie(an, date, zile)`."""
    out = {}
    lista = []
    for an in ani:
        a, b, _ = _fereastra_an(d0, n, an)
        if b > frontiera or a < INCEPUT_CUB:
            continue
        lista.append((an, a, b))
    if not lista:
        return out
    mb = sum(sum(zc.estimeaza_cost(cub, v, a, b, g)[1] for v in variabile) for _, a, b in lista)
    zc.log(f"   {eticheta}: {len(lista)} ferestre de {_nz(n)}, ~{mb / 1000:.2f} GB")
    t0 = time.perf_counter()
    for k, (an, a, b) in enumerate(lista, 1):
        d, zile = zc.citeste(cub, variabile, a, b, g)
        out[an] = functie(an, d, zile)
        del d                                         # un singur an în memorie (v5.1)
        if k % 10 == 0 or k == len(lista):
            zc.log(f"   {eticheta}: {k}/{len(lista)} ani ({time.perf_counter() - t0:.0f} s)")
    return out


def _stat_pixeli(v, mod):
    """v (t, y, x) → statistica per pixel pe fereastră; NaN sub 90 % zile valide."""
    fin = np.isfinite(v); nv = fin.sum(axis=0); n = v.shape[0]
    s = np.where(fin, v, 0).sum(axis=0)
    ok = nv >= 0.9 * n
    val = s * n / np.maximum(nv, 1) if mod == "suma" else s / np.maximum(nv, 1)
    return np.where(ok, val, np.nan).astype("float32")


# =====================================================================================
# GRAFICE
# =====================================================================================
def _plt():
    return zc._plt()


def _salv(fig, cale, tip):
    plt = _plt()
    cale = zc._gata(cale); fig.savefig(cale, dpi=zc.DPI); plt.close(fig)
    zc.log(f"   PNG {tip}: {cale}")
    return cale


def _fmt_zi(z):
    s = str(z); return f"{int(s[8:10])} {LUNI[int(s[5:7]) - 1]} {s[:4]}"


def g_rang_fereastra(cale, tab, ep_an, ep_val, clim, unit, titlu, mare):
    """(1) Valoarea ferestrei în fiecare an, episodul evidențiat, normala, top 3 etichetat."""
    plt = _plt()
    ani = np.array([r[0] for r in tab]); v = np.array([r[1] for r in tab], float)
    fig, ax = plt.subplots(figsize=(13, 4.8))
    cul = np.where(ani == ep_an, "#e34948", "#9db8d9")
    temp = unit != "mm"
    if temp and np.isfinite(clim):
        # temperaturi: barele pornesc de la normală (o bară de la 0 °C nu are sens fizic)
        ax.bar(ani, np.nan_to_num(v - clim), bottom=clim, color=cul, width=0.8)
    else:
        ax.bar(ani, np.nan_to_num(v), color=cul, width=0.8)
    if np.isfinite(clim):
        ax.axhline(clim, color="#008300", lw=1.4, label=f"normala ferestrei: {zc.ro(clim, 1)} {unit}")
    ordine = np.argsort(-v if mare else v)
    for j in [o for o in ordine if np.isfinite(v[o])][:3]:
        sus = (not temp) or v[j] >= clim
        ax.annotate(f"{ani[j]}\n{zc.ro(v[j], 1)}", (ani[j], v[j]), xytext=(0, 4 if sus else -4), textcoords="offset points",
                    ha="center", va="bottom" if sus else "top", fontsize=8, fontweight="bold" if ani[j] == ep_an else "normal")
    ax.bar([], [], color="#e34948", label=f"{ep_an} (episodul): {zc.ro(ep_val, 1)} {unit}")
    if temp:
        lo_, hi_ = np.nanmin(np.r_[v, clim]), np.nanmax(np.r_[v, clim]); pad = 0.25 * (hi_ - lo_ or 1)
        ax.set_ylim(lo_ - pad, hi_ + pad)
    else:
        hi_ = np.nanmax(np.r_[v, 0]); ax.set_ylim(0, hi_ * 1.18 or 1)
    ax.set_ylabel(unit); ax.grid(axis="y", color="#e6e5e0")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2, frameon=False, fontsize=9)
    ax.set_title(titlu, fontsize=11)
    fig.text(0, -0.02, zc.ATRIBUIRE, fontsize=8, color="#555555")
    return _salv(fig, cale, "rang fereastră")


def g_top_episoade(cale, top, ep, unit, titlu, n):
    """(2) Topul episoadelor de n zile (fără suprapuneri) + episodul curent."""
    plt = _plt()
    linii = [(f"{_fmt_zi(a)} – {_fmt_zi(b)}", v, False) for a, b, v in top]
    linii.append((f"EPISODUL {_fmt_zi(ep[0])} – {_fmt_zi(ep[1])} (locul {ep[4]})", ep[2], True))
    linii.sort(key=lambda x: -x[1] if ep[3] else x[1])
    fig, ax = plt.subplots(figsize=(11, 0.42 * len(linii) + 1.6))
    y = np.arange(len(linii))[::-1]
    ax.barh(y, [l[1] for l in linii], color=["#e34948" if l[2] else "#2a78d6" for l in linii], height=0.7)
    for yy, l in zip(y, linii):
        ax.text(l[1], yy, f" {zc.ro(l[1], 1 if unit == 'mm' else 2)}", va="center", fontsize=8.5)
    ax.set_yticks(y, [l[0] for l in linii], fontsize=8.5)
    ax.set_xlabel(unit); ax.grid(axis="x", color="#e6e5e0")
    ax.set_title(titlu, fontsize=11)
    fig.text(0, -0.02, f"Episoade de {_nz(n)} consecutive, fără suprapuneri, încheiate la ±{FEREASTRA_SEZON} zile (în calendar) de episod · {zc.ATRIBUIRE}", fontsize=8, color="#555555")
    return _salv(fig, cale, "top episoade")


def g_gumbel(cale, maxime, ani_m, mu, beta, ep_val, T_ep, unit, titlu, semn, eticheta_y=None):
    """(3) Graficul probabilității Gumbel: maximele din fereastra sezonieră a fiecărui an, dreapta ajustată, episodul."""
    plt = _plt()
    x = np.sort(np.asarray(maxime, float) * semn)
    n = x.size; F = (np.arange(1, n + 1) - 0.44) / (n + 0.12)           # Gringorten
    yred = -np.log(-np.log(F))
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.scatter(yred, x * semn, s=16, color="#2a78d6", label=f"maximele sezoniere ({n} ani, aceeași perioadă a anului)")
    yy = np.linspace(min(yred.min(), -1.6), 5.0, 100)
    ax.plot(yy, (mu + beta * yy) * semn, color="#0b0b0b", lw=1.2, label="Gumbel (metoda momentelor)")
    if np.isfinite(ep_val):
        ye = (ep_val * semn - mu) / beta
        ax.scatter([ye], [ep_val], s=90, marker="*", color="#e34948", zorder=5,
                   label=f"episodul: {zc.ro(ep_val, 1 if unit == 'mm' else 2)} {unit} → " + (f"T ≈ {zc.ro(T_ep, 0)} ani" if T_ep >= 2 else "T < 2 ani (obișnuit)"))
    for T in (2, 5, 10, 25, 50, 100):
        ax.axvline(-math.log(-math.log(1 - 1 / T)), color="#e6e5e0", lw=0.8)
        ax.text(-math.log(-math.log(1 - 1 / T)), ax.get_ylim()[1], f"{T} ani", fontsize=7.5, ha="center", va="bottom", color="#52514e")
    ax.set_xlabel("variabila redusă Gumbel  −ln(−ln F)"); ax.set_ylabel(eticheta_y or unit)
    ax.legend(loc="upper left", fontsize=8.5, frameon=False); ax.set_title(titlu, fontsize=11, pad=16)
    fig.text(0, -0.02, f"Orientativ: ~{n} valori; incertitudinea crește mult peste 2–3 × durata seriei · {zc.ATRIBUIRE}",
             fontsize=8, color="#555555")
    return _salv(fig, cale, "Gumbel")


def g_siruri(cale, siruri, ep_sir, titlu, unit_sir):
    """(4) Cele mai lungi șiruri istorice + șirul episodului."""
    plt = _plt()
    linii = [(f"{_fmt_zi(a)} – {_fmt_zi(b)}", L, False) for a, b, L in siruri]
    if ep_sir:
        linii.append((f"EPISODUL {_fmt_zi(ep_sir[0])} – {_fmt_zi(ep_sir[1])}", ep_sir[2], True))
    linii.sort(key=lambda x: -x[1])
    fig, ax = plt.subplots(figsize=(10, 0.4 * len(linii) + 1.6))
    y = np.arange(len(linii))[::-1]
    ax.barh(y, [l[1] for l in linii], color=["#e34948" if l[2] else "#6250d6" for l in linii], height=0.7)
    for yy, l in zip(y, linii):
        ax.text(l[1], yy, f" {_nz(l[1])}", va="center", fontsize=8.5)
    ax.set_yticks(y, [l[0] for l in linii], fontsize=8.5); ax.set_xlabel(unit_sir)
    ax.grid(axis="x", color="#e6e5e0"); ax.set_title(titlu, fontsize=11)
    fig.text(0, -0.02, zc.ATRIBUIRE, fontsize=8, color="#555555")
    return _salv(fig, cale, "șiruri")


def g_episod_zilnic(cale, zile, val, clim_med, clim_p10, clim_p90, p95, p99, unit, titlu, precip, ant_zile=0, mare=True):
    """(5) Zilele episodului (și perioada anterioară) față de climatologie și pragurile p95 / p99."""
    plt = _plt()
    import matplotlib.dates as mdates
    dz = zile.astype("datetime64[ms]").astype(object)
    fig, axs = plt.subplots(2 if precip else 1, 1, figsize=(12, 7 if precip else 4.8), sharex=True, squeeze=False)
    a = axs[0, 0]
    ep = np.arange(len(zile)) >= ant_zile
    if precip:
        a.bar(dz, np.nan_to_num(val), color=np.where(ep, "#2a78d6", "#9db8d9"), width=0.9)
        a.plot(dz, clim_med, color="#008300", lw=1.2, label="media zilnică climatologică")
        for p, et, c in ((p95, "p95 zile ploioase", "#eb6834"), (p99, "p99 zile ploioase", "#e34948")):
            if np.isfinite(p):
                a.axhline(p, color=c, ls="--", lw=1, label=f"{et}: {zc.ro(p, 1)} mm")
        a.set_ylabel("mm/zi")
        b = axs[1, 0]
        cum = np.nancumsum(np.where(ep, np.nan_to_num(val), 0))
        b.plot(dz, np.where(ep, cum, np.nan), color="#0b0b0b", lw=2, label="cumulat în episod")
        b.plot(dz, np.where(ep, np.cumsum(np.where(ep, clim_med, 0)), np.nan), color="#008300", ls="--", lw=1.3,
               label="cumulat normal")
        b.set_ylabel("mm cumulați"); b.legend(loc="upper left", fontsize=8.5, frameon=False); b.grid(axis="y", color="#e6e5e0")
        b.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    else:
        a.fill_between(dz, clim_p10, clim_p90, color="#2a78d6", alpha=0.13, lw=0, label="p10–p90 climatologic")
        a.plot(dz, clim_med, color="#2a78d6", ls="--", lw=1, label="media climatologică")
        a.plot(dz, val, color="#0b0b0b", lw=1.5, marker="o", ms=3, label="valoarea zilnică")
        for p, et, c in ((p95, "p95" if mare else "p5", "#eb6834"), (p99, "p99" if mare else "p1", "#e34948")):
            if np.isfinite(p):
                a.axhline(p, color=c, ls="--", lw=1, label=f"{et}: {zc.ro(p, 1)} {unit}")
        a.set_ylabel(unit); a.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    if ant_zile:
        for ax in axs[:, 0]:
            ax.axvspan(dz[0], dz[ant_zile], color="#8a8986", alpha=0.08, lw=0)
    a.legend(loc="upper left", fontsize=8.5, frameon=False, ncol=2); a.grid(axis="y", color="#e6e5e0")
    a.set_title(titlu, fontsize=11)
    fig.text(0, -0.01, (f"Gri deschis: {ant_zile} zile înaintea episodului · " if ant_zile else "") + zc.ATRIBUIRE,
             fontsize=8, color="#555555")
    fig.tight_layout()
    return _salv(fig, cale, "episod zilnic")


def g_antecedent(cale, zile, val, clim_cum_p10, clim_cum_med, clim_cum_p90, d0, unit, titlu, precip, anomalie_zi=None):
    """(7) Cele 90 de zile dinainte + episodul: cumulul față de climatologie (precipitații) sau anomaliile zilnice."""
    plt = _plt()
    import matplotlib.dates as mdates
    dz = zile.astype("datetime64[ms]").astype(object)
    fig, ax = plt.subplots(figsize=(12, 4.8))
    if precip:
        ax.fill_between(dz, clim_cum_p10, clim_cum_p90, color="#2a78d6", alpha=0.13, lw=0, label="p10–p90 climatologic")
        ax.plot(dz, clim_cum_med, color="#2a78d6", ls="--", lw=1.1, label="media climatologică")
        ax.plot(dz, np.nancumsum(np.nan_to_num(val)), color="#0b0b0b", lw=2, label="cumulat observat")
        ax.set_ylabel("mm cumulați")
    else:
        an = anomalie_zi
        ax.bar(dz, np.where(an >= 0, an, 0), color="#e34948", width=0.9)
        ax.bar(dz, np.where(an < 0, an, 0), color="#2a78d6", width=0.9)
        ax.axhline(0, color="#52514e", lw=0.8); ax.set_ylabel(f"anomalie zilnică ({unit})")
    ax.axvline(d0.astype("datetime64[ms]").astype(object), color="#e34948", lw=1.4, ls=":")
    ax.text(d0.astype("datetime64[ms]").astype(object), ax.get_ylim()[1], " începutul episodului", color="#e34948",
            fontsize=8.5, va="top")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b")); ax.grid(axis="y", color="#e6e5e0")
    if precip:
        ax.legend(loc="upper left", fontsize=8.5, frameon=False)
    ax.set_title(titlu, fontsize=11)
    fig.text(0, -0.02, zc.ATRIBUIRE, fontsize=8, color="#555555")
    return _salv(fig, cale, "context anterior")


def g_context(cale, rand, titlu):
    """(10) Episodul față de normala ferestrei pentru celelalte variabile (bare pereche)."""
    plt = _plt()
    fig, axs = plt.subplots(1, len(rand), figsize=(3.2 * len(rand), 4.2), squeeze=False)
    for ax, (nume, ep, cl, unit) in zip(axs[0], rand):
        # puncte (nu bare): axa nu începe de la 0, deci diferența se vede corect și pentru temperaturi negative
        d = round(ep - cl, 1) + 0.0
        c = "#e34948" if d > 0 else ("#2a78d6" if d < 0 else "#8a8986")
        ax.plot([0, 1], [cl, ep], color="#c3c2b7", lw=1.5, zorder=1)
        ax.scatter([0], [cl], s=90, color="#8a8986", zorder=3)
        ax.scatter([1], [ep], s=110, color=c, zorder=3)
        for x, v in ((0, cl), (1, ep)):
            ax.annotate(zc.ro(v, 1), (x, v), xytext=(10, 0), textcoords="offset points", va="center", fontsize=9)
        ax.set_xticks([0, 1], ["normala", "episodul"]); ax.set_xlim(-0.4, 1.6)
        lo, hi = min(cl, ep), max(cl, ep); pad = max(0.5, 0.35 * (hi - lo))
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_title(f"{nume} ({unit})\nanomalie {'+' if d >= 0 else '−'}{zc.ro(abs(d), 1)}", fontsize=10)
        ax.grid(axis="y", color="#e6e5e0")
    fig.suptitle(titlu, x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0.03, 1, 0.93))
    fig.text(0, 0, zc.ATRIBUIRE, fontsize=8, color="#555555")
    return _salv(fig, cale, "context")


def g_calendar(cale, zile, val, anomalie, precip, d0, d1, titlu, unit):
    """(11) Calendar termic: rânduri = ani, coloane = zile; episodul încadrat."""
    plt = _plt()
    from matplotlib.colors import LogNorm, TwoSlopeNorm
    ani = zile.astype("datetime64[Y]").astype(int) + 1970
    lista = np.unique(ani)
    M = np.full((len(lista), 366), np.nan)
    di = _doy366(zile)
    M[ani - lista[0], di] = anomalie if not precip else val
    lipsa29 = np.isnan(M[:, 59]) & np.isfinite(M[:, 58]) & np.isfinite(M[:, 60])   # 29 feb în anii nebisecți: doar pentru afișare
    M[lipsa29, 59] = (M[lipsa29, 58] + M[lipsa29, 60]) / 2
    fig, ax = plt.subplots(figsize=(14, 0.11 * len(lista) + 2.4))
    if precip:
        im = ax.imshow(np.where(M >= 0.1, M, np.nan), aspect="auto", cmap="Blues",
                       norm=LogNorm(0.1, max(1.0, np.nanpercentile(M, 99.9))), interpolation="nearest",
                       extent=[0.5, 366.5, lista[-1] + 0.5, lista[0] - 0.5])
        lab = "precipitații zilnice (mm, scară logaritmică; alb = < 0,1 mm)"
    else:
        m = np.nanpercentile(np.abs(M), 99) or 1
        im = ax.imshow(M, aspect="auto", cmap="RdBu_r", norm=TwoSlopeNorm(0, -m, m), interpolation="nearest",
                       extent=[0.5, 366.5, lista[-1] + 0.5, lista[0] - 0.5])
        lab = f"anomalie zilnică ({unit})"
    a0 = int(_doy366(np.array([d0]))[0]) + 1; a1 = int(_doy366(np.array([d1]))[0]) + 1
    y0 = int(str(d0)[:4]); y1 = int(str(d1)[:4])
    from matplotlib.patches import Rectangle
    if y0 == y1:
        ax.add_patch(Rectangle((a0 - 0.5, y0 - 0.5), a1 - a0 + 1, 1, fill=False, ec="#e34948", lw=2))
    else:
        ax.add_patch(Rectangle((a0 - 0.5, y0 - 0.5), 366.5 - a0 + 0.5, 1, fill=False, ec="#e34948", lw=2))
        ax.add_patch(Rectangle((0.5, y1 - 0.5), a1, 1, fill=False, ec="#e34948", lw=2))
    # fereastra episodului în toți anii (bandă discretă)
    ax.axvspan(a0 - 0.5, (a1 + 0.5) if y0 == y1 else 366.5, color="#e34948", alpha=0.06, lw=0)
    inceput_luni = [1, 32, 61, 92, 122, 153, 183, 214, 245, 275, 306, 336]
    ax.set_xticks(inceput_luni, LUNI, fontsize=8.5)
    ax.set_ylabel("an")
    cb = plt.colorbar(im, ax=ax, pad=0.01); cb.set_label(lab); cb.outline.set_visible(False)
    ax.set_title(titlu, fontsize=11)
    fig.text(0, -0.02, f"Chenar roșu: episodul · bandă roșie: aceeași fereastră în toți anii · {zc.ATRIBUIRE}",
             fontsize=8, color="#555555")
    return _salv(fig, cale, "calendar")


def g_comparatii(cale, curbe, unit, titlu, precip):
    """(13) Episodul curent față de alte episoade (aliniate pe ziua 1…N)."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(11, 5))
    for i, (et, v, curent) in enumerate(curbe):
        x = np.arange(1, len(v) + 1)
        y = np.nancumsum(np.nan_to_num(v)) if precip else v
        ax.plot(x, y, lw=2.6 if curent else 1.4, color="#e34948" if curent else zc.PALETA_ZONE[i % len(zc.PALETA_ZONE)],
                marker="o", ms=3, label=et, zorder=5 if curent else 3)
    ax.set_xlabel("ziua episodului"); ax.set_ylabel(("mm cumulați" if precip else f"anomalie zilnică ({unit})"))
    if not precip:
        ax.axhline(0, color="#52514e", lw=0.8)
    ax.grid(axis="y", color="#e6e5e0")
    ax.legend(fontsize=8.5, frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1))
    ax.set_title(titlu, fontsize=11)
    fig.text(0, -0.02, zc.ATRIBUIRE, fontsize=8, color="#555555")
    return _salv(fig, cale, "comparații")


def g_frecventa(cale, ani, ev, sir, titlu, et_ev, et_sir):
    """(14) Numărul anual de episoade similare și de șiruri lungi, cu mediile pe decenii și tendința."""
    plt = _plt()
    fig, axs = plt.subplots(2, 1, figsize=(12, 6.6), sharex=True)
    for ax, y, et, c in ((axs[0], ev, et_ev, "#2a78d6"), (axs[1], sir, et_sir, "#6250d6")):
        y = np.asarray(y, float)
        ax.bar(ani, y, color=c, width=0.8, alpha=0.8)
        dec = sorted({a // 10 * 10 for a in ani})
        for d in dec:
            m = (np.asarray(ani) >= d) & (np.asarray(ani) < d + 10)
            if m.sum() >= 5:
                ax.plot([d - 0.4, d + 9.4], [y[m].mean()] * 2, color="#0b0b0b", lw=2)
        b, p = zc._panta(ani, y)
        ax.set_title(f"{et} · tendință {'+' if b >= 0 else '−'}{zc.ro(abs(b), 2)} pe deceniu (p = {zc.ro(p, 3)}) · linie neagră: media deceniului",
                     fontsize=10)
        ax.grid(axis="y", color="#e6e5e0"); ax.set_ylabel("nr./an")
        from matplotlib.ticker import MaxNLocator
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    fig.suptitle(titlu, x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.text(0, 0, zc.ATRIBUIRE, fontsize=8, color="#555555")
    return _salv(fig, cale, "frecvență")


def g_extindere(cale, praguri, fractii, et_praguri, rang1, rang3, titlu):
    """(9) Fracția din teritoriu peste praguri + fracția cu record / top 3 istoric."""
    plt = _plt()
    et = et_praguri + ["record istoric (rang 1)", "top 3 istoric"]
    v = list(fractii) + [rang1, rang3]
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(et) + 1.5))
    y = np.arange(len(et))[::-1]
    ax.barh(y, v, color=["#2a78d6"] * len(fractii) + ["#e34948", "#eb6834"], height=0.65)
    for yy, x in zip(y, v):
        ax.text(x, yy, f" {zc.ro(x, 1)} %", va="center", fontsize=9)
    ax.set_yticks(y, et); ax.set_xlim(0, max(100, max(v) * 1.15)); ax.set_xlabel("% din pixelii valizi ai hărții")
    ax.grid(axis="x", color="#e6e5e0"); ax.set_title(titlu, fontsize=11)
    fig.text(0, -0.02, zc.ATRIBUIRE, fontsize=8, color="#555555")
    return _salv(fig, cale, "extindere")


def gif_episod(cale, zile, D, g, zona_h, var, precip, puncte, fps=2):
    """(12) Animație zi cu zi: valoarea zilei și cumulul (precipitații) / media de la început (temperaturi)."""
    plt = _plt()
    from matplotlib.animation import FuncAnimation, PillowWriter
    import matplotlib
    cum = np.nancumsum(np.nan_to_num(D), axis=0) if precip else np.cumsum(np.nan_to_num(D), axis=0) / np.arange(1, len(zile) + 1)[:, None, None]
    masca = np.isfinite(D).any(axis=0)
    cum = np.where(masca[None], cum, np.nan)
    v1 = np.nanpercentile(D, 99) if precip else None
    v2 = np.nanpercentile(cum[-1], 99) if precip else None
    lat_m = (g.extent[2] + g.extent[3]) / 2
    fig, axs = plt.subplots(1, 2, figsize=(14, 5.4))
    if precip:
        k1 = dict(cmap="Blues", vmin=0, vmax=max(v1, 1)); k2 = dict(cmap="YlGnBu", vmin=0, vmax=max(v2, 1))
    else:
        lo, hi = np.nanpercentile(D, 2), np.nanpercentile(D, 98)
        k1 = dict(cmap="RdYlBu_r", vmin=lo, vmax=hi); k2 = dict(cmap="RdYlBu_r", vmin=lo, vmax=hi)
    im1 = axs[0].imshow(D[0], extent=g.extent, interpolation="nearest", **k1)
    im2 = axs[1].imshow(cum[0], extent=g.extent, interpolation="nearest", **k2)
    for ax, im, t in ((axs[0], im1, "ziua"), (axs[1], im2, "cumulat" if precip else "media de la început")):
        zc._contururi(ax, zona_h, g)
        for px, py, _ in puncte:
            ax.plot(px, py, marker="*", ms=11, mfc="#ffd400", mec="#0b0b0b")
        ax.set_aspect(1 / math.cos(math.radians(lat_m)))
        cb = plt.colorbar(im, ax=ax, shrink=0.75); cb.set_label(zc.UNITATI.get(var, "°C")); cb.outline.set_visible(False)
    t1 = axs[0].set_title(""); t2 = axs[1].set_title("")

    def cadru(i):
        im1.set_data(D[i]); im2.set_data(cum[i])
        t1.set_text(f"{var} · {zile[i]}"); t2.set_text(f"{'cumulat' if precip else 'media'} {zile[0]} → {zile[i]}")
        return im1, im2, t1, t2

    FuncAnimation(fig, cadru, frames=len(zile)).save(zc._gata(cale), writer=PillowWriter(fps=fps), dpi=90)
    plt.close(fig)
    zc.log(f"   GIF: {cale}")
    return cale


# =====================================================================================
# ANALIZA
# =====================================================================================
def analizeaza(PARAMETRU, PERIOADA, REFERINTA, CLIMATOLOGIE, ZONA, ZONA_ANALIZA, HARTI_ZONA, IESIRI, ANALIZE, OUT, NUME,
               PRAG_ZI_PLOIOASA=1.0, SENS="auto", ZILE_ANTERIOARE=(30, 60, 90), EPISOADE_COMPARATIE=(),
               MIN_ZILE_SIR=5, PRAGURI_EXTINDERE=None, TOP_N=10, FPS_GIF=2, HTML_FACTOR=1):
    out = Path(OUT)
    precip = PARAMETRU == "precipitation"
    mod = "suma" if precip else "medie"
    unit = "mm" if precip else "°C"
    unit_zi = "mm/zi" if precip else "°C"
    titlu_var = zc._titlu_var(PARAMETRU)
    rez = {"parametru": PARAMETRU, "perioada_ceruta": list(PERIOADA), "avertismente": []}

    def avert(m):
        zc.log(f"   [atenție] {m}"); rez["avertismente"].append(m)

    cub, fr = zc.deschide()
    frontiera = min(fr[v] for v in zc._variabile_pentru(PARAMETRU))
    d0 = np.datetime64(PERIOADA[0]); d1 = np.datetime64(PERIOADA[1] or str(frontiera))
    if d0 > frontiera:
        raise ValueError(f"Perioada începe după frontiera datelor ({frontiera}).")
    if d1 > frontiera:
        avert(f"perioada cerută se termină la {d1}, dar datele există doar până la {frontiera}: analiza se face pe "
              f"{d0} → {frontiera}; toate comparațiile istorice folosesc aceeași lungime")
        d1 = frontiera
    N = int((d1 - d0).astype(int)) + 1
    an_ep = int(str(d0)[:4])
    rez.update(perioada=[str(d0), str(d1)], zile=N, frontiera=str(frontiera))
    zc.log(f"== {NUME}: {titlu_var} · {d0} → {d1} ({_nz(N)}) · frontiera {frontiera}")

    # ---------------------------------------------------------------- A. serii zonale (tot istoricul)
    g = zc.grila_zonei(cub, ZONA)
    total_nume = ZONA.nume if ZONA.punct else ("Toate zonele" if ZONA.poligoane else "România")
    global INCEPUT_CUB
    INCEPUT_CUB = np.datetime64(str(cub.time.values[0])[:10], "D")      # 1961-01-01 pe cubul EOCube
    ani_toti = range(int(str(INCEPUT_CUB)[:4]), int(str(frontiera)[:4]) + 1)
    etichete, serii, _ = zc.serii_zonale(cub, fr, PARAMETRU, ani_toti, ZONA, g, total_nume, zc.dir_cache("serii"))
    k_za = zc.potriveste_zona(ZONA_ANALIZA, etichete) if ZONA_ANALIZA else None
    if k_za is not None:
        k = k_za
    else:
        if ZONA_ANALIZA:
            avert(f"zona de analiză „{ZONA_ANALIZA}” nu există; folosesc „{etichete[-1]}”. Zone: {', '.join(etichete[:12])}…")
        k = len(etichete) - 1
    zona_et = etichete[k]
    rez["zona"] = zona_et
    zile, val = _serie_continua(serii, k)
    m_ep = (zile >= d0) & (zile <= d1)
    v_ep = val[m_ep]
    if np.isnan(v_ep).any():
        avert(f"{int(np.isnan(v_ep).sum())} zile fără date în episod (NaN) pentru „{zona_et}”")
    ep_val = _stat(v_ep, mod)
    if v_ep.size != N or not np.isfinite(ep_val):
        raise ValueError("Episodul nu are acoperirea necesară pentru comparația cu ferestrele istorice (90 %).")

    # climatologie zilnică (pentru anomalii, praguri, plicuri)
    clim_ani = [a for a in range(CLIMATOLOGIE[0], CLIMATOLOGIE[1] + 1) if a in serii and np.datetime64(f"{a}-12-31") <= frontiera]
    cl = zc._climatologie_zilnica(serii, k, CLIMATOLOGIE, frontiera)
    if not cl:
        raise ValueError(f"Niciun an complet în climatologia {CLIMATOLOGIE}.")
    doy = _doy366(zile)
    anomalie_zi = val - cl["med"][doy] if cl else np.full_like(val, np.nan)

    # sensul (episod cald / rece) pentru temperaturi
    if precip:
        mare = True
    elif SENS in ("mare", "mic"):
        mare = SENS == "mare"
    else:
        mare = np.nanmean(anomalie_zi[m_ep]) >= 0
    rez["sens"] = "mare" if mare else "mic"

    # ---------------------------------------------------------------- 1. rangul pe aceeași fereastră
    tab = []
    for an in ani_toti:
        a, b, _ = _fereastra_an(d0, N, an)
        if b > frontiera:
            continue
        mm = (zile >= a) & (zile <= b)
        tab.append((an, _stat(val[mm], mod)))
    vals = np.array([t[1] for t in tab], float)
    ok = np.isfinite(vals)
    n_ani = int(ok.sum())
    if not n_ani:
        raise ValueError("Nu există ferestre istorice cu acoperire suficientă.")
    clim_fer = float(np.nanmean([v for a, v in tab if CLIMATOLOGIE[0] <= a <= CLIMATOLOGIE[1]]))
    rang = int(1 + sum(1 for a, v in tab if np.isfinite(v) and a != an_ep and ((v > ep_val) if mare else (v < ep_val))))
    rec = max(((a, v) for a, v in tab if np.isfinite(v)), key=lambda t: t[1] if mare else -t[1])
    rez["fereastra"] = dict(valoare=ep_val, normala=clim_fer, anomalie=ep_val - clim_fer,
                            procent_din_normala=100 * ep_val / clim_fer if precip and clim_fer > 0 else None,
                            rang=rang, din_ani=n_ani, percentila=100 * (1 - (rang - 1) / max(n_ani, 1)),
                            record_an=int(rec[0]), record_valoare=float(rec[1]))
    zc.log(f"   (1) fereastra: {zc.ro(ep_val, 1)} {unit} · normala {zc.ro(clim_fer, 1)} · rang {rang} din {n_ani} "
           f"· record {rec[0]} ({zc.ro(rec[1], 1)})")

    # ---------------------------------------------------------------- referința aleasă (anomalia „principală”)
    tip = REFERINTA[0]
    if tip == "climatologie":
        ref_val = float(np.nanmean([v for a, v in tab if REFERINTA[1] <= a <= REFERINTA[2]]))
        ref_et = f"media aceleiași ferestre {REFERINTA[1]}–{REFERINTA[2]}"
    elif tip == "an":
        a, b, _ = _fereastra_an(d0, N, int(REFERINTA[1])); mm = (zile >= a) & (zile <= b)
        ref_val = _stat(val[mm], mod); ref_et = f"aceeași fereastră în {REFERINTA[1]} ({a} → {b})"
    else:
        if tip == "luna":
            a = np.datetime64(f"{REFERINTA[1]}-01"); b = (np.datetime64(REFERINTA[1], "M") + 1).astype("datetime64[D]") - 1
            ref_et = f"luna {REFERINTA[1]}"
        else:
            a, b = np.datetime64(REFERINTA[1]), np.datetime64(REFERINTA[2]); ref_et = f"perioada {a} → {b}"
        mm = (zile >= a) & (zile <= b); L = int(mm.sum())
        ref_val = _stat(val[mm], mod)
        if precip and L:
            ref_val = ref_val * N / L
            ref_et += f" (adusă la {_nz(N)}: × {N}/{L})"
    rez["referinta"] = dict(tip=tip, descriere=ref_et, valoare=ref_val, anomalie=ep_val - ref_val,
                            procent=100 * ep_val / ref_val if precip and ref_val else None)
    zc.log(f"   referința: {ref_et} = {zc.ro(ref_val, 1)} {unit} → anomalia {zc.ro(ep_val - ref_val, 1)}"
           + (f" ({zc.ro(100 * ep_val / ref_val, 0)} %)" if precip and ref_val else ""))

    # ---------------------------------------------------------------- 2. topul episoadelor de N zile (același sezon)
    # Doar episoadele care se încheie la ±FEREASTRA_SEZON zile de data din calendar a episodului: regimul sezonier
    # e comparabil (o anomalie de +6 °C vara nu se compară cu una de +12 °C iarna, unde variabilitatea e dublă;
    # o ploaie de toamnă nu se compară cu aversele din iunie).
    if precip:
        rul = _rulant_n(val, N, "suma")
    else:
        rul = _rulant_n(anomalie_zi, N, "medie")
    ep_rul = rul[np.where(zile == d1)[0][0]] if (zile == d1).any() else np.nan
    doy_d1 = int(_doy366(np.array([d1]))[0])
    in_sez = _dist_doy(doy, doy_d1) <= FEREASTRA_SEZON
    rul_sez = np.where(in_sez, rul, np.nan)
    # „anul sezonului”: axa timpului decalată astfel încât fereastra ±30 zile să cadă întreagă într-un singur an
    # (un episod din ianuarie și decembrie-ul de dinainte aparțin aceluiași sezon, nu la doi ani diferiți)
    ani_z = zile.astype("datetime64[Y]").astype(int) + 1970
    ani_sez = (zile - np.timedelta64(doy_d1 - 183, "D")).astype("datetime64[Y]").astype(int) + 1970
    top = _top_declusterizat(rul_sez, zile, N, mare, TOP_N, exclus=(d0, d1))
    peste = _top_declusterizat(rul_sez, zile, N, mare, exclus=(d0, d1), prag=ep_rul) if np.isfinite(ep_rul) else []
    rang_global = len(peste) + 1 if np.isfinite(ep_rul) else None
    an0, an1 = int(ani_z.min()), int(ani_z.max())
    sez_et = (f"încheiate între {_fmt_zi(d1 - FEREASTRA_SEZON).rsplit(' ', 1)[0]} și "
              f"{_fmt_zi(d1 + FEREASTRA_SEZON).rsplit(' ', 1)[0]}, în orice an")
    rez["top_episoade"] = dict(valoare_episod=float(ep_rul), loc=rang_global, interval=[an0, an1],
                               fereastra_sezon=FEREASTRA_SEZON, sezon=sez_et,
                               top=[dict(start=str(a), sfarsit=str(b), valoare=v) for a, b, v in top])
    zc.log(f"   (2) între episoadele de {_nz(N)} din același sezon ({sez_et}, {an0}–{an1}): locul {_sau_liniuta(rang_global)}")

    # ---------------------------------------------------------------- 3. Gumbel pe maximele sezoniere
    # Un maxim pe an, dar numai din fereastra sezonieră de mai sus: eșantionul e omogen, iar perioada de revenire
    # răspunde la „cât de rar e un asemenea episod ÎN ACEASTĂ PERIOADĂ A ANULUI”. Doar sezoanele încheiate și complete.
    semn = 1 if mare else -1
    maxime, ani_m = [], []
    for an in sorted(set(ani_sez[in_sez])):
        grp = in_sez & (ani_sez == an)
        # Construire și zilele așteptate din afara cubului, inclusiv ferestrele de la Anul Nou.
        calendar = np.arange(np.datetime64(f"{an-1}-11-01"), np.datetime64(f"{an+1}-03-01"))
        an_calendar = (calendar - np.timedelta64(doy_d1 - 183, "D")).astype("datetime64[Y]").astype(int) + 1970
        asteptate = calendar[(an_calendar == an) & (_dist_doy(_doy366(calendar), doy_d1) <= FEREASTRA_SEZON)]
        n_nom = len(asteptate)
        if not n_nom or asteptate[0] - (N - 1) < zile[0] or asteptate[-1] > frontiera:
            continue
        x = rul[grp]
        if np.isfinite(x).sum() >= 0.8 * n_nom:
            maxime.append(np.nanmax(x * semn) * semn); ani_m.append(int(an))
    gb = _gumbel([m * semn for m in maxime])
    T_ep = _perioada_revenire(ep_rul * semn, *gb) if gb and np.isfinite(ep_rul) else np.nan
    rez["gumbel"] = dict(mu=gb[0], beta=gb[1], perioada_revenire_ani=T_ep, n_sezoane=len(maxime), sezon=sez_et,
                         niveluri={T: _nivel_revenire(T, *gb) * semn for T in (2, 5, 10, 25, 50, 100)}) if gb else None
    if gb and np.isfinite(T_ep):
        zc.log(f"   (3) perioada de revenire estimată (Gumbel, {len(maxime)} sezoane): "
               + (f"≈ {zc.ro(T_ep, 0)} ani" if T_ep >= 2 else "sub 2 ani"))

    # ---------------------------------------------------------------- 4. șiruri
    if precip:
        exc = val >= PRAG_ZI_PLOIOASA; et_sir = f"zile consecutive cu ≥ {zc.ro(PRAG_ZI_PLOIOASA, 1)} mm"
    else:
        ref_p = cl["p90"][doy] if mare else cl["p10"][doy]
        exc = (val > ref_p) if mare else (val < ref_p)
        et_sir = f"zile consecutive {'peste p90' if mare else 'sub p10'} climatologic"
    exc = exc & np.isfinite(val)
    siruri = [(zile[i], zile[j - 1], j - i) for i, j in _runs(exc)]
    sir_ep = max([s for s in siruri if s[1] >= d0 and s[0] <= d1], key=lambda s: s[2], default=None)
    top_sir = sorted([s for s in siruri if not (sir_ep and s[0] == sir_ep[0])], key=lambda s: -s[2])[:TOP_N]
    luni_ep = {int(str(d0)[5:7]), int(str(d1)[5:7])}
    sez = {((m - 2) % 12) + 1 for m in luni_ep} | {(m % 12) + 1 for m in luni_ep} | luni_ep
    top_sez = sorted([s for s in siruri if int(str(s[0])[5:7]) in sez and not (sir_ep and s[0] == sir_ep[0])], key=lambda s: -s[2])[:5]
    rez["siruri"] = dict(definitie=et_sir, episod=(dict(start=str(sir_ep[0]), sfarsit=str(sir_ep[1]), zile=int(sir_ep[2])) if sir_ep else None),
                         record=(dict(start=str(top_sir[0][0]), sfarsit=str(top_sir[0][1]), zile=int(top_sir[0][2])) if top_sir else None),
                         record_sezon=(dict(start=str(top_sez[0][0]), sfarsit=str(top_sez[0][1]), zile=int(top_sez[0][2]),
                                            luni=sorted(sez)) if top_sez else None))
    zc.log(f"   (4) șirul episodului: {sir_ep[2] if sir_ep else 0} zile · record {top_sir[0][2] if top_sir else '–'} zile")

    # ---------------------------------------------------------------- 5. ziua extremă și pragurile
    luni_z = zile.astype("datetime64[M]").astype(int) % 12 + 1
    ani_clim = (ani_z >= CLIMATOLOGIE[0]) & (ani_z <= CLIMATOLOGIE[1])
    # Pragurile vin din zilele climatologiei aflate la ±FEREASTRA_PRAG zile (în calendar) de oricare zi a episodului,
    # nu din luni întregi: în octombrie–noiembrie normala scade cu ~10 °C, iar p95 al celor două luni ar fi dominat
    # de începutul lui octombrie. La precipitații fereastra e dublă (zilele ploioase sunt puține).
    w_prag = FEREASTRA_PRAG * (2 if precip else 1)
    doy_ep = np.unique(doy[m_ep])
    aproape = np.zeros(len(zile), bool)
    for q in doy_ep:
        aproape |= _dist_doy(doy, q) <= w_prag
    pool = ani_clim & aproape & np.isfinite(val)
    if precip:
        pool &= val >= PRAG_ZI_PLOIOASA
    if pool.sum() > 20:
        p95, p99 = ((np.nanpercentile(val[pool], 95), np.nanpercentile(val[pool], 99)) if mare
                    else (np.nanpercentile(val[pool], 5), np.nanpercentile(val[pool], 1)))
    else:
        p95, p99 = np.nan, np.nan
    i_ext = (np.nanargmax(v_ep) if mare else np.nanargmin(v_ep)) if np.isfinite(v_ep).any() else None
    zi_ext = (str(zile[m_ep][i_ext]), float(v_ep[i_ext])) if i_ext is not None else (None, np.nan)
    i_rec = np.nanargmax(val) if mare else np.nanargmin(val)
    mm_luna = luni_z == int(str(zi_ext[0] or d0)[5:7])
    i_rec_l = np.where(mm_luna)[0][np.nanargmax(val[mm_luna]) if mare else np.nanargmin(val[mm_luna])]
    _peste = lambda pr: (int(np.nansum((v_ep > pr) if mare else (v_ep < pr))) if np.isfinite(pr) else None)  # noqa: E731
    n95, n99 = _peste(p95), _peste(p99)                     # None = prag necalculabil (prea puține zile), nu „0 zile”
    rez["zi_extrema"] = dict(zi=zi_ext[0], valoare=zi_ext[1], record_absolut=dict(zi=str(zile[i_rec]), valoare=float(val[i_rec])),
                             record_luna=dict(zi=str(zile[i_rec_l]), valoare=float(val[i_rec_l])),
                             percentile=[95, 99] if mare else [5, 1], sens="peste" if mare else "sub",
                             p95=float(p95), p99=float(p99), zile_peste_p95=n95, zile_peste_p99=n99,
                             fereastra_prag=w_prag, zile_prag=int(pool.sum()))
    zc.log(f"   (5) ziua extremă {zi_ext[0]}: {zc.ro(zi_ext[1], 1)} {unit_zi} · record absolut {zc.ro(float(val[i_rec]), 1)} "
           f"({zile[i_rec]}) · {n95 if n95 is not None else '–'} / {n99 if n99 is not None else '–'} zile "
           f"{'peste p95 / p99' if mare else 'sub p5 / p1'} "
           f"(prag din ±{w_prag} zile în calendar, {int(pool.sum())} valori)")

    # ---------------------------------------------------------------- 6. echivalențe
    lunare, anuale = [], []
    for an in clim_ani:
        lunare.append(zc._lunare(serii, PARAMETRU, an, frontiera)[k])
        anuale.append(zc._agregat(serii[an][k][None], PARAMETRU)[0] if an in serii else np.nan)
    lunare = np.array(lunare); norm_luna = np.nanmean(lunare, axis=0); norm_an = float(np.nanmean(anuale))
    # luna de referință = luna cu cele mai multe zile ale episodului (nu luna primei zile: 26 oct.–18 nov. → noiembrie)
    _z0 = np.datetime64(str(d0)[:10], "D")
    _luni = (np.arange(_z0, _z0 + np.timedelta64(int(N), "D")).astype("datetime64[M]").astype(int) % 12) + 1
    luna_ep = int(np.bincount(_luni, minlength=13).argmax())
    _mixt = len(set(_luni.tolist())) > 1
    if precip:
        # % din normala lunii are sens doar pentru episoade de cel mult o lună
        ech = dict(procent_normala_lunii=(100 * ep_val / norm_luna[luna_ep - 1]) if N <= 31 else None, luna=LUNI_LUNG[luna_ep - 1],
                   normala_lunii_mm=float(norm_luna[luna_ep - 1]), procent_normala_anului=100 * ep_val / norm_an,
                   normala_anului_mm=norm_an, zile_normale_echivalente=ep_val / (norm_an / 365.25),
                   zile_ploioase=int(np.nansum(v_ep >= PRAG_ZI_PLOIOASA)))
        zc.log("   (6) " + (f"{zc.ro(ech['procent_normala_lunii'], 0)} % din normala lunii {ech['luna']}"
                         + (" (luna cu cele mai multe zile ale episodului)" if _mixt else "") + ", " if N <= 31 else "")
               + f"{zc.ro(ech['procent_normala_anului'], 1)} % din normala anului (≈ {zc.ro(ech['zile_normale_echivalente'], 0)} zile „normale”)")
    else:
        ech = dict(anomalie=ep_val - clim_fer, normala_lunii=float(norm_luna[luna_ep - 1]), luna=LUNI_LUNG[luna_ep - 1],
                   procent_zile_exceptionale=100 * float(np.nanmean(exc[m_ep])))
    ech["luna_dominanta"] = _mixt
    rez["echivalente"] = ech

    # ---------------------------------------------------------------- 7. contextul anterior
    ant = []
    for L in ZILE_ANTERIOARE:
        a, b = d0 - L, d0 - 1
        v_a = _stat(val[(zile >= a) & (zile <= b)], mod)
        ist = []
        for an in ani_toti:
            aa, bb, _ = _fereastra_an(a, L, an)
            if bb > frontiera:
                continue
            ist.append((an, _stat(val[(zile >= aa) & (zile <= bb)], mod)))
        clim_a = float(np.nanmean([v for an, v in ist if CLIMATOLOGIE[0] <= an <= CLIMATOLOGIE[1]]))
        r_a = 1 + sum(1 for an, v in ist if np.isfinite(v) and an != int(str(a)[:4]) and ((v > v_a) if mare else (v < v_a)))
        ant.append(dict(zile=L, de_la=str(a), pana_la=str(b), valoare=v_a, normala=clim_a, anomalie=v_a - clim_a,
                        procent=100 * v_a / clim_a if precip and clim_a else None, rang=r_a, din_ani=len(ist)))
        zc.log(f"   (7) {_nz(L)} înainte: {zc.ro(v_a, 1)} {unit} (normala {zc.ro(clim_a, 1)}"
               + (f", {zc.ro(100 * v_a / clim_a, 0)} %" if precip and clim_a else f", anomalie {zc.ro(v_a - clim_a, 2)}") + ")")
    rez["context_anterior"] = ant

    # ---------------------------------------------------------------- 13. comparații
    comp = [(f"EPISODUL {_fmt_zi(d0)} – {_fmt_zi(d1)}", (anomalie_zi if not precip else val)[m_ep], True)]
    for a, b, v in top[:3]:
        mm = (zile >= a) & (zile <= b)
        comp.append((f"{_fmt_zi(a)} – {_fmt_zi(b)} (top istoric)", (anomalie_zi if not precip else val)[mm], False))
    for et, start in EPISOADE_COMPARATIE:
        a = np.datetime64(start); b = a + (N - 1); mm = (zile >= a) & (zile <= b)
        if mm.sum() == N:
            comp.append((f"{et} ({_fmt_zi(a)})", (anomalie_zi if not precip else val)[mm], False))
        else:
            avert(f"episodul de comparație „{et}” ({start}) nu e acoperit de date")

    # ---------------------------------------------------------------- 14. frecvența
    ani_compl = [a for a in sorted(set(ani_z)) if np.datetime64(f"{a}-12-31") <= frontiera]
    pool_r = np.isin(ani_z, clim_ani) & np.isfinite(rul)
    prag_ev = np.nanpercentile(rul[pool_r], 95 if mare else 5) if pool_r.any() else np.nan
    evs = _top_declusterizat(rul, zile, N, mare, prag=prag_ev) if np.isfinite(prag_ev) else []
    cnt_ev = [sum(1 for a, b, v in evs if int(str(b)[:4]) == an) for an in ani_compl]
    cnt_sir = [sum(1 for a, b, L in siruri if L >= MIN_ZILE_SIR and int(str(a)[:4]) == an) for an in ani_compl]
    rez["frecventa"] = dict(prag_episod=float(prag_ev), min_zile_sir=MIN_ZILE_SIR,
                            pe_ani={str(a): [e, s] for a, e, s in zip(ani_compl, cnt_ev, cnt_sir)})

    # ---------------------------------------------------------------- C. contextul celorlalte variabile (10)
    context = []
    if ANALIZE.get("context"):
        alte = ["max_temp", "min_temp"] if precip else ["precipitation", "max_temp", "min_temp"]   # citite
        afis = [v for v in alte if v != PARAMETRU]                                                  # afișate
        et_, cols_, tot_ = zc._coloane_zone(ZONA, g)
        coloane = (cols_ + [tot_]) if len(et_) > 1 else (cols_ or [tot_])
        ani_ctx = sorted(set(clim_ani) | {an_ep})

        def f_ctx(an, d, z):
            return {v: zc._medii_zone(d[v], [coloane[k]])[0] for v in alte}

        r_ctx = _citeste_ferestre(cub, tuple(alte), d0, N, ani_ctx, g, frontiera, f_ctx, "context")
        for v in afis:
            m_ = "suma" if v == "precipitation" else "medie"
            ep_v = _stat(r_ctx[an_ep][v], m_, 0.5) if an_ep in r_ctx else np.nan
            cl_v = float(np.nanmean([_stat(r_ctx[a][v], m_) for a in clim_ani if a in r_ctx]))
            context.append((zc._titlu_var(v).split(" (")[0], ep_v, cl_v, "mm" if v == "precipitation" else "°C"))
        if "max_temp" in alte and "min_temp" in alte and an_ep in r_ctx:
            dtr_ep = _stat(r_ctx[an_ep]["max_temp"] - r_ctx[an_ep]["min_temp"], "medie", 0.5)
            dtr_cl = float(np.nanmean([_stat(r_ctx[a]["max_temp"] - r_ctx[a]["min_temp"], "medie") for a in clim_ani if a in r_ctx]))
            context.append(("Amplitudinea diurnă", dtr_ep, dtr_cl, "°C"))
        rez["context"] = [dict(variabila=n_, episod=e, normala=c, anomalie=e - c, unitate=u) for n_, e, c, u in context]
        for n_, e, c, u in context:
            zc.log(f"   (10) {n_}: {zc.ro(e, 1)} {u} (normala {zc.ro(c, 1)}, anomalie {zc.ro(e - c, 1)})")

    # ---------------------------------------------------------------- B. hărți (8, 9, 12)
    harti = {}
    gh = None
    if ANALIZE.get("harti") or ANALIZE.get("gif") or ANALIZE.get("extindere"):
        if HARTI_ZONA.punct:
            avert("HARTI_ZONA este un punct (un singur pixel): hărțile se fac pe toată țara. Pentru hărți pe o regiune "
                  "folosiți HARTI_ZONA = zc.Zona.dreptunghi(lon_min, lat_min, lon_max, lat_max); punctul se setează în ZONA.")
            HARTI_ZONA = zc.Zona.tara()
        gh = zc.grila_zonei(cub, HARTI_ZONA)
        cache = zc.dir_cache("episod")
        import hashlib
        sursa = hashlib.sha256(zc.URL.encode("utf-8")).hexdigest()[:24]
        cheie = f"{sursa}_{PARAMETRU}_{str(d0)[5:10]}_{N}_{gh.iy0}_{gh.iy1}_{gh.ix0}_{gh.ix1}"
        if precip:                                       # W = zilele ≥ PRAG_ZI_PLOIOASA: pragul face parte din cheie
            cheie += f"_p{PRAG_ZI_PLOIOASA:g}"
        fis_c = cache / f"ferestre_{cheie}.npz"
        S, W = {}, {}
        if fis_c.exists():
            with np.load(fis_c, allow_pickle=False) as z:
                S = {int(k_[1:]): z[k_] for k_ in z.files if k_.startswith("s")}
                W = {int(k_[1:]): z[k_] for k_ in z.files if k_.startswith("w")}
            zc.log(f"   cache hărți: {len(S)} ani ({fis_c.name})")
            S.pop(an_ep, None); W.pop(an_ep, None)
        lipsa = [a for a in ani_toti if a not in S and a != an_ep]
        D_ep = None

        def f_h(an, d, z):
            v = zc._valoare_zilnica(d, PARAMETRU)
            return (_stat_pixeli(v, mod), (np.sum(v >= PRAG_ZI_PLOIOASA, axis=0).astype("float32") if precip else None),
                    v if an == an_ep else None, z)

        r_h = _citeste_ferestre(cub, zc._variabile_pentru(PARAMETRU), d0, N, lipsa + [an_ep], gh, frontiera, f_h, "hărți")
        for a, (s_, w_, dd, zz) in r_h.items():
            if a == an_ep:
                D_ep, zile_ep = dd, zz
                S_ep, W_ep = s_, w_
            else:
                S[a] = s_
                if w_ is not None:
                    W[a] = w_
        if lipsa:
            zc._salveaza_cache(fis_c, comprimat=True, **{f"s{a}": S[a] for a in S}, **{f"w{a}": W[a] for a in W})
        if HARTI_ZONA._id is not None:
            msk = HARTI_ZONA._id > 0
            S_ep = np.where(msk, S_ep, np.nan); D_ep = np.where(msk[None], D_ep, np.nan)
        ani_h = sorted(S)
        stiva = np.stack([S[a] for a in ani_h])
        # referința hărților
        if tip == "climatologie":
            ref_h = np.nanmean(np.stack([S[a] for a in ani_h if REFERINTA[1] <= a <= REFERINTA[2]]), axis=0)
        elif tip == "an" and int(REFERINTA[1]) in S:
            ref_h = S[int(REFERINTA[1])]
        else:
            if tip == "an":
                a, b, _ = _fereastra_an(d0, N, int(REFERINTA[1]))
            elif tip == "luna":
                a = np.datetime64(f"{REFERINTA[1]}-01"); b = (np.datetime64(REFERINTA[1], "M") + 1).astype("datetime64[D]") - 1
            else:
                a, b = np.datetime64(REFERINTA[1]), np.datetime64(REFERINTA[2])
            if a < INCEPUT_CUB or b > frontiera:
                raise ValueError(f"Referința cartografică {a}–{b} depășește datele {INCEPUT_CUB}–{frontiera}.")
            dd, _ = zc.citeste(cub, zc._variabile_pentru(PARAMETRU), a, b, gh)
            ref_h = _stat_pixeli(zc._valoare_zilnica(dd, PARAMETRU), mod)
            if precip:
                ref_h = ref_h * N / int((b - a).astype(int) + 1)
        clim_h = np.nanmean(np.stack([S[a] for a in ani_h if CLIMATOLOGIE[0] <= a <= CLIMATOLOGIE[1]]), axis=0)
        if HARTI_ZONA._id is not None:
            clim_h = zc._masca_zona(clim_h, HARTI_ZONA)
        fin = np.isfinite(stiva)
        rang_h = 1 + np.sum(((stiva > S_ep[None]) if mare else (stiva < S_ep[None])) & fin, axis=0).astype("float32")
        rang_h = np.where(np.isfinite(S_ep), rang_h, np.nan)
        n_h = fin.sum(axis=0)
        rang_h = np.where(n_h > 0, rang_h, np.nan)
        harti = {"statistica": S_ep, "medie_zilnica": np.nanmean(D_ep, axis=0) if precip else S_ep,
                 "minim": np.nanmin(D_ep, axis=0), "maxim": np.nanmax(D_ep, axis=0),
                 "anomalie": S_ep - ref_h, "normala_fereastra": clim_h, "rang": rang_h}
        if not precip:
            harti.pop("medie_zilnica")
        if precip:
            harti["procent"] = 100 * S_ep / np.where(ref_h > 0.1, ref_h, np.nan)
            harti["zile_ploioase"] = np.where(np.isfinite(S_ep), W_ep, np.nan)
        # 9. extindere
        valid = np.isfinite(S_ep) & (n_h > 10)
        if PRAGURI_EXTINDERE is None:
            PRAGURI_EXTINDERE = (150, 200, 300) if precip else ((2, 4, 6) if mare else (-2, -4, -6))
        if precip:
            suport = valid & np.isfinite(harti["procent"])
            fr_ = [100 * np.mean(harti["procent"][suport] >= p) if suport.any() else np.nan for p in PRAGURI_EXTINDERE]
            et_p = [f"≥ {p} % din normală" for p in PRAGURI_EXTINDERE]
        else:
            an_ = (S_ep - clim_h)[valid & np.isfinite(clim_h)]
            fr_ = [100 * np.mean((an_ >= p) if mare else (an_ <= p)) for p in PRAGURI_EXTINDERE]
            et_p = [f"anomalie {'≥ +' if mare else '≤ '}{p} °C" for p in PRAGURI_EXTINDERE]
        r1 = 100 * np.mean(rang_h[valid] == 1); r3 = 100 * np.mean(rang_h[valid] <= 3)
        rez["extindere"] = dict(praguri=list(PRAGURI_EXTINDERE), procente=fr_, record_pct=r1, top3_pct=r3,
                                ani_comparati=len(ani_h))
        zc.log(f"   (9) extindere: " + ", ".join(f"{e}: {zc.ro(f, 1)} %" for e, f in zip(et_p, fr_))
               + f" · record pe {zc.ro(r1, 1)} % din teritoriu")

    # =====================================================================================
    # IEȘIRI
    # =====================================================================================
    sl = lambda s: "".join(c if c.isalnum() else "_" for c in s)[:40]  # noqa: E731
    pfx = f"{NUME}"
    per_txt = f"{_fmt_zi(d0)} – {_fmt_zi(d1)} ({_nz(N)})"
    puncte = [(ZONA.punct[0], ZONA.punct[1], zona_et)] if ZONA.punct else []
    fis_qgis = []

    if ANALIZE.get("rang_fereastra"):
        g_rang_fereastra(out / f"{pfx}_01_rang_fereastra.png", tab, an_ep, ep_val, clim_fer, unit,
                         f"(1) {zona_et} · {titlu_var}: {per_txt} în fiecare an · locul {rang} din {n_ani}", mare)
    if ANALIZE.get("top_episoade") and np.isfinite(ep_rul):
        g_top_episoade(out / f"{pfx}_02_top_episoade.png", top, (d0, d1, ep_rul, mare, rang_global),
                       unit if precip else "anomalie medie (°C)",
                       f"(2) {zona_et} · cele mai {'ploioase' if precip else ('calde' if mare else 'reci')} episoade de {_nz(N)} din același sezon, {an0}–{an1}", N)
    if ANALIZE.get("gumbel") and gb and np.isfinite(T_ep):
        g_gumbel(out / f"{pfx}_03_gumbel.png", maxime, ani_m, gb[0], gb[1], ep_rul, T_ep,
                 unit, f"(3) {zona_et} · perioada de revenire pentru {_nz(N)} ({'sumă' if precip else 'anomalie medie'})", semn,
                 eticheta_y=None if precip else "anomalie medie pe episod (°C)")
    if ANALIZE.get("siruri"):
        g_siruri(out / f"{pfx}_04_siruri.png", top_sir, sir_ep, f"(4) {zona_et} · cele mai lungi șiruri: {et_sir}", "zile")
    if ANALIZE.get("zile_episod"):
        A_ = max(ZILE_ANTERIOARE) if ZILE_ANTERIOARE else 0
        A_ = min(A_, 30)
        mm = (zile >= d0 - A_) & (zile <= d1)
        g_episod_zilnic(out / f"{pfx}_05_zile_episod.png", zile[mm], val[mm], cl["med"][doy[mm]], cl["p10"][doy[mm]],
                        cl["p90"][doy[mm]], p95, p99, unit_zi,
                        f"(5) {zona_et} · {titlu_var}, valori zilnice · {per_txt} · ziua extremă {_fmt_zi(np.datetime64(zi_ext[0])) if zi_ext[0] else '–'}: "
                        f"{zc.ro(zi_ext[1], 1)} {unit_zi}", precip, ant_zile=A_, mare=mare)
    if ANALIZE.get("context_anterior") and ZILE_ANTERIOARE:
        L = max(ZILE_ANTERIOARE)
        a = d0 - L; mm = (zile >= a) & (zile <= d1); nz = int(mm.sum())
        if precip:
            bucati = []
            for an in clim_ani:
                aa, bb, _ = _fereastra_an(a, nz, an)
                m2 = (zile >= aa) & (zile <= bb)
                if m2.sum() == nz:
                    bucati.append(np.nancumsum(np.nan_to_num(val[m2])))
            B_ = np.stack(bucati)
            g_antecedent(out / f"{pfx}_07_context_anterior.png", zile[mm], val[mm], np.percentile(B_, 10, 0), B_.mean(0),
                         np.percentile(B_, 90, 0), d0, unit,
                         f"(7) {zona_et} · precipitațiile cumulate în cele {_nz(L)} dinainte și în episod", True)
        else:
            g_antecedent(out / f"{pfx}_07_context_anterior.png", zile[mm], val[mm], None, None, None, d0, "°C",
                         f"(7) {zona_et} · anomaliile zilnice în cele {_nz(L)} dinainte și în episod", False, anomalie_zi[mm])
    if ANALIZE.get("context") and context:
        g_context(out / f"{pfx}_10_context.png", context, f"(10) {zona_et} · celelalte variabile în episod ({per_txt})")
    if ANALIZE.get("calendar"):
        g_calendar(out / f"{pfx}_11_calendar.png", zile, val, anomalie_zi, precip, d0, d1,
                   f"(11) {zona_et} · {titlu_var}: fiecare zi din {an0}–{an1}", unit_zi)
    if ANALIZE.get("comparatii"):
        g_comparatii(out / f"{pfx}_13_comparatii.png", comp, "°C",
                     f"(13) {zona_et} · episodul comparat cu alte episoade de {_nz(N)}", precip)
    if ANALIZE.get("frecventa") and ani_compl:
        g_frecventa(out / f"{pfx}_14_frecventa.png", ani_compl, cnt_ev, cnt_sir,
                    f"(14) {zona_et} · cât de des apar episoade similare",
                    f"episoade de {_nz(N)} peste p{95 if mare else 5} ({zc.ro(prag_ev, 1)} {unit if precip else '°C anomalie'})",
                    f"șiruri ≥ {MIN_ZILE_SIR} {et_sir}")

    if harti:
        sub = f"{per_txt} · zona de analiză: {zona_et}"
        zona_desen = HARTI_ZONA if (HARTI_ZONA.poligoane or not ZONA.poligoane) else ZONA   # conturul poligoanelor analizate
        lista = [("statistica", f"{titlu_var}: {'suma' if precip else 'media'} episodului", unit, "YlGnBu" if precip else "RdYlBu_r", {}),
                 ("minim", f"{titlu_var}: minima zilnică", unit_zi, "Blues" if precip else "RdYlBu_r", {}),
                 ("maxim", f"{titlu_var}: maxima zilnică", unit_zi, "Blues" if precip else "RdYlBu_r", {}),
                 ("normala_fereastra", f"{titlu_var}: normala ferestrei {CLIMATOLOGIE[0]}–{CLIMATOLOGIE[1]}", unit,
                  "YlGnBu" if precip else "RdYlBu_r", {}),
                 ("anomalie", f"Anomalia față de {ref_et}", unit, "BrBG" if precip else "RdBu_r", dict(divergent=True))]
        if precip:
            lista.insert(1, ("medie_zilnica", f"{titlu_var}: media zilnică", unit_zi, "Blues", {}))
            lista += [("procent", f"Precipitațiile în % față de {ref_et}", "%", "BrBG", dict(divergent=True, vmin=0, vmax=300, centru=100)),
                      ("zile_ploioase", f"Zile cu ≥ {zc.ro(PRAG_ZI_PLOIOASA, 1)} mm", "zile", "PuBu", dict(vmin=0, vmax=N))]
        if ANALIZE.get("harti"):
            for cheie_, titlu_, u_, cm_, kw in lista:
                if precip and cheie_ == "minim" and np.nanmax(harti["minim"]) <= 0:
                    continue
                zc.png_harta(out / f"{pfx}_08_harta_{cheie_}.png", harti[cheie_], gh, titlu_, u_, cm_, zona=zona_desen,
                             subtitlu=sub, puncte=puncte, **kw)
            zc.png_harta(out / f"{pfx}_08_harta_rang.png", harti["rang"], gh,
                         f"Rangul istoric al episodului per pixel (1 = record) · {len(ani_h) + 1} ani comparați",
                         "rang", "YlOrRd_r", zona=zona_desen, subtitlu=sub, puncte=puncte,
                         clase=[0.5, 1.5, 2.5, 3.5, 5.5, 10.5, 20.5, 100.5],
                         etichete_clase=["1", "2", "3", "4–5", "6–10", "11–20", "> 20"])
        if ANALIZE.get("extindere"):
            g_extindere(out / f"{pfx}_09_extindere.png", PRAGURI_EXTINDERE, fr_, et_p, r1, r3,
                        f"(9) Extinderea episodului · {per_txt}")
        if IESIRI.get("cog"):
            chei = [c for c in harti]
            fis_qgis.append(zc.scrie_cog(out / f"{pfx}_harti.tif", [harti[c] for c in chei], gh, chei, unit))
        if ANALIZE.get("gif"):
            gif_episod(out / f"{pfx}_12_animatie.gif", zile_ep, D_ep, gh, zona_desen, PARAMETRU, precip, puncte, FPS_GIF)

    # tabele
    if IESIRI.get("csv"):
        zc.scrie_csv(out / f"{pfx}_01_rang_fereastra.csv", ["an", f"valoare_{unit}"], tab)
        zc.scrie_csv(out / f"{pfx}_02_top_episoade.csv", ["start", "sfarsit", "valoare"],
                     [(str(a), str(b), v) for a, b, v in top] + [(str(d0), str(d1), float(ep_rul))])
        if gb:
            zc.scrie_csv(out / f"{pfx}_03_gumbel.csv", ["perioada_revenire_ani", "nivel"],
                         [(T, float(v)) for T, v in rez["gumbel"]["niveluri"].items()] + [("episod", float(ep_rul))])
        zc.scrie_csv(out / f"{pfx}_04_siruri.csv", ["start", "sfarsit", "zile"], [(str(a), str(b), int(L)) for a, b, L in top_sir])
        zc.scrie_csv(out / f"{pfx}_07_context_anterior.csv", list(ant[0].keys()) if ant else ["-"], [list(r.values()) for r in ant])
        if context:
            zc.scrie_csv(out / f"{pfx}_10_context.csv", ["variabila", "episod", "normala", "anomalie", "unitate"],
                         [(n_, e, c, e - c, u) for n_, e, c, u in context])
        zc.scrie_csv(out / f"{pfx}_14_frecventa.csv", ["an", "episoade_similare", "siruri_lungi"], list(zip(ani_compl, cnt_ev, cnt_sir)))
        zc.scrie_csv(out / f"{pfx}_serie_zilnica.csv", ["zi", f"valoare_{unit_zi}", "anomalie"],
                     [(str(z_), float(v_), float(a_)) for z_, v_, a_ in zip(zile[m_ep], val[m_ep], anomalie_zi[m_ep])])
    # statistici pe toate zonele (dacă ZONA are mai multe poligoane)
    if len(etichete) > 1:
        rand = []
        for kk, et in enumerate(etichete):
            z2, v2 = _serie_continua(serii, kk)
            e2 = _stat(v2[(z2 >= d0) & (z2 <= d1)], mod, 0.5)
            ist = []
            for an in ani_toti:
                a, b, _ = _fereastra_an(d0, N, an)
                if b <= frontiera:
                    ist.append((an, _stat(v2[(z2 >= a) & (z2 <= b)], mod)))
            c2 = float(np.nanmean([v for a, v in ist if CLIMATOLOGIE[0] <= a <= CLIMATOLOGIE[1]]))
            r2 = 1 + sum(1 for a, v in ist if np.isfinite(v) and a != an_ep and ((v > e2) if mare else (v < e2)))
            rand.append((et, e2, c2, e2 - c2, (100 * e2 / c2) if precip and c2 else np.nan, r2))
        if IESIRI.get("csv"):
            zc.scrie_csv(out / f"{pfx}_zone.csv", ["zona", "episod", "normala", "anomalie", "procent", "rang"], rand)
        if IESIRI.get("gpkg") and ZONA.poligoane:
            n_ = len(ZONA.poligoane)
            fis_qgis.append(zc.scrie_gpkg_zone(out / f"{pfx}_zone.gpkg", ZONA, {
                "episod": [r[1] for r in rand[:n_]], "normala": [r[2] for r in rand[:n_]], "anomalie": [r[3] for r in rand[:n_]],
                "procent": [r[4] for r in rand[:n_]], "rang": [float(r[5]) for r in rand[:n_]]}))
    elif IESIRI.get("gpkg") and ZONA.punct:
        from osgeo import ogr, osr
        cale = zc._gata(out / f"{pfx}_punct.gpkg")
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(cale))
        srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
        lyr = ds.CreateLayer("rezultate", srs, ogr.wkbPoint)
        campuri = dict(zona=zona_et, perioada=f"{d0}/{d1}", episod=ep_val, normala=clim_fer, anomalie=ep_val - clim_fer,
                       rang=float(rang), din_ani=float(n_ani), revenire_ani=float(T_ep) if np.isfinite(T_ep) else None)
        for c, v in campuri.items():
            lyr.CreateField(ogr.FieldDefn(c, ogr.OFTString if isinstance(v, str) else ogr.OFTReal))
        f = ogr.Feature(lyr.GetLayerDefn())
        for c, v in campuri.items():
            if v is not None:
                f.SetField(c, v)
        p = ogr.Geometry(ogr.wkbPoint); p.AddPoint_2D(*ZONA.punct); f.SetGeometry(p); lyr.CreateFeature(f)
        f = p = lyr = None; ds = None; srs = None
        zc.log(f"   GPKG (punct): {cale}"); fis_qgis.append(cale)

    # raport
    if IESIRI.get("raport"):
        _raport(out / f"{pfx}_raport.md", rez, zona_et, titlu_var, unit, unit_zi, precip, mare, per_txt, CLIMATOLOGIE)
        cale = zc._gata(out / f"{pfx}_rezultate.json")
        cale.write_text(json.dumps(rez, ensure_ascii=False, indent=1, default=lambda o: float(o) if isinstance(o, np.floating) else (int(o) if isinstance(o, np.integer) else str(o))),
                        encoding="utf-8")
        zc.log(f"   JSON: {cale}")
    if IESIRI.get("html"):
        import zarr_html
        H = _construieste_H(dict(locals(), raport_md=_raport(None, rez, zona_et, titlu_var, unit, unit_zi, precip, mare, per_txt, CLIMATOLOGIE)))
        fis_qgis_html = zarr_html.scrie_html(out / f"{pfx}_fisa.html", H, factor=HTML_FACTOR)
    zc.incarca_in_qgis(fis_qgis)
    zc.log(f"== gata: {NUME}")
    return rez


def _de(n):
    """„20 de ani”, dar „13 ani” (regula numeralelor în română)."""
    r = int(n) % 100
    return "de " if (r >= 20 or (r == 0 and n > 0)) else ""


def _nz(n):
    """„1 zi”, „5 zile”, „36 de zile”."""
    return "1 zi" if int(n) == 1 else f"{n} {_de(n)}zile"


def _raport(cale, r, zona, titlu_var, unit, unit_zi, precip, mare, per_txt, clim):
    ro = zc.ro
    f = r["fereastra"]; t = r["top_episoade"]; s = r["siruri"]; z = r["zi_extrema"]; e = r["echivalente"]
    L = [f"# {titlu_var} · {zona} · {per_txt}", "",
         f"Date: frontiera `last_*_time` = {r['frontiera']} · climatologia de referință {clim[0]}–{clim[1]}", ""]
    if r["avertismente"]:
        L += ["## Atenție", ""] + [f"- {a}" for a in r["avertismente"]] + [""]
    L += ["## Pe scurt", ""]
    if precip:
        L.append(f"- **{ro(f['valoare'], 1)} mm** în {_nz(r['zile'])}, față de o normală de {ro(f['normala'], 1)} mm "
                 f"pentru aceeași fereastră (**{ro(f['procent_din_normala'], 0)} %**).")
        L.append("- Echivalent: " + (f"**{ro(e['procent_normala_lunii'], 0)} %** din normala lunii {e['luna']} "
                 f"({ro(e['normala_lunii_mm'], 1)} mm) și " if e['procent_normala_lunii'] is not None else "")
                 + f"**{ro(e['procent_normala_anului'], 1)} %** din normala anului "
                 f"(≈ {ro(e['zile_normale_echivalente'], 0)} zile „normale” de precipitații). Zile ploioase: {e['zile_ploioase']}.")
    else:
        L.append(f"- Media episodului: **{ro(f['valoare'], 1)} °C**, normala ferestrei {ro(f['normala'], 1)} °C "
                 f"(anomalie **{'+' if f['anomalie'] >= 0 else ''}{ro(f['anomalie'], 1)} °C**).")
    rf = r["referinta"]
    L.append(f"- Față de referința aleasă ({rf['descriere']}): {ro(rf['valoare'], 1)} {unit} → anomalie "
             f"{'+' if rf['anomalie'] >= 0 else ''}{ro(rf['anomalie'], 1)} {unit}" + (f" ({ro(rf['procent'], 0)} %)" if rf.get("procent") else "") + ".")
    L.append(f"- **Rangul pe aceeași fereastră calendaristică: locul {f['rang']} din {f['din_ani']} {_de(f['din_ani'])}ani** "
             f"(recordul: {f['record_an']}, {ro(f['record_valoare'], 1)} {unit}).")
    L.append(f"- Între episoadele de {_nz(r['zile'])} din același sezon ({t.get('sezon', 'oricând în an')}), "
             f"{t['interval'][0]}–{t['interval'][1]}: **locul {_sau_liniuta(t['loc'])}**.")
    if r.get("gumbel") and np.isfinite(r["gumbel"]["perioada_revenire_ani"]):
        T_ = r['gumbel']['perioada_revenire_ani']
        L.append("- Perioada de revenire estimată (Gumbel, orientativ): " + (f"**≈ {ro(T_, 0)} ani**" if T_ >= 2 else "**sub 2 ani** (un episod obișnuit în această perioadă a anului)")
                 + f", din maximele a {r['gumbel'].get('n_sezoane', 0)} {_de(r['gumbel'].get('n_sezoane', 0))}sezoane comparabile.")
    if s["episod"]:
        L.append(f"- Șirul de {s['definitie']}: **{_nz(s['episod']['zile'])}** ({s['episod']['start']} → {s['episod']['sfarsit']}); "
                 + (f"recordul: {_nz(s['record']['zile'])} ({s['record']['start']})" if s['record'] else "nu există alt șir în serie")
                 + (f"; recordul pentru același sezon: {_nz(s['record_sezon']['zile'])} ({s['record_sezon']['start']})" if s.get("record_sezon") else "") + ".")
    L.append(f"- Ziua extremă: {z['zi']} cu **{ro(z['valoare'], 1)} {unit_zi}**; recordul absolut: {ro(z['record_absolut']['valoare'], 1)} "
             f"({z['record_absolut']['zi']}); recordul lunii: {ro(z['record_luna']['valoare'], 1)} ({z['record_luna']['zi']}). "
             f"Zile {'peste p95' if mare else 'sub p5'}: {_sau_liniuta(z['zile_peste_p95'])}, "
             f"{'peste p99' if mare else 'sub p1'}: {_sau_liniuta(z['zile_peste_p99'])} "
             f"(praguri din zilele aflate la ±{z.get('fereastra_prag', '?')} zile în calendar de episod).")
    L += ["", "## Contextul anterior", ""]
    for a in r["context_anterior"]:
        L.append(f"- {_nz(a['zile'])} înainte ({a['de_la']} → {a['pana_la']}): {ro(a['valoare'], 1)} {unit}, normala {ro(a['normala'], 1)}"
                 + (f" ({ro(a['procent'], 0)} %)" if a.get("procent") else f" (anomalie {ro(a['anomalie'], 2)})") + f", locul {a['rang']} din {a['din_ani']}.")
    if r.get("context"):
        L += ["", "## Celelalte variabile în episod", ""]
        for c in r["context"]:
            L.append(f"- {c['variabila']}: {ro(c['episod'], 1)} {c['unitate']} (normala {ro(c['normala'], 1)}, anomalie {ro(c['anomalie'], 1)})")
    if r.get("extindere"):
        x = r["extindere"]
        L += ["", "## Extinderea spațială", ""]
        for p, v in zip(x["praguri"], x["procente"]):
            L.append(f"- prag {p}: {ro(v, 1)} % din teritoriul hărții")
        L.append(f"- record istoric pe {ro(x['record_pct'], 1)} % din teritoriu; top 3 pe {ro(x['top3_pct'], 1)} % ({x['ani_comparati'] + 1} ani comparați)")
    L += ["", "## Cele mai mari episoade comparabile", ""]
    for i, ev in enumerate(t["top"], 1):
        L.append(f"{i}. {ev['start']} → {ev['sfarsit']}: {ro(ev['valoare'], 1)}")
    L += ["", "## Limitări", "",
          "- Datele sunt interpolate din observațiile stațiilor; un pixel nu este o stație, iar extremele locale pot fi subestimate.",
          "- Perioada de revenire (Gumbel, metoda momentelor) este orientativă.",
          "- Pentru o zonă (poligon), toate valorile zilnice sunt MEDII pe suprafață: o zi „ploioasă” înseamnă media zonei "
          "≥ prag, deci șirurile de zile ploioase sunt mai lungi și maximele zilnice mai mici decât într-un punct.",
          "- Ultimele zile ale unui episod în curs pot lipsi până la actualizarea cubului (frontiera de mai sus).", "",
          zc.ATRIBUIRE]
    if cale is not None:
        cale = zc._gata(cale); cale.write_text("\n".join(L), encoding="utf-8")
        zc.log(f"   raport: {cale}")
    return "\n".join(L)


# =====================================================================================
# Datele pentru fișa HTML
# =====================================================================================
_DESCR_STRATURI = {
    "statistica": "Suma (precipitații) sau media (temperaturi) pe toată perioada, în fiecare pixel.",
    "medie_zilnica": "Media zilnică a precipitațiilor în episod (suma împărțită la numărul de zile).",
    "minim": "Cea mai mică valoare zilnică din episod, în fiecare pixel.",
    "maxim": "Cea mai mare valoare zilnică din episod, în fiecare pixel.",
    "normala_fereastra": "Valoarea medie a aceleiași ferestre calendaristice în anii climatologiei de referință.",
    "anomalie": "Diferența dintre episod și referința aleasă (roșu/maro = peste, albastru/verde = sub).",
    "procent": "Precipitațiile episodului ca procent din referință (100 % = la fel; ≥ 200 % = dublu).",
    "zile_ploioase": "Numărul de zile din episod cu precipitații peste pragul de zi ploioasă.",
    "rang": "Locul episodului între aceleași ferestre calendaristice din toți anii, în fiecare pixel (1 = record).",
}


def _construieste_H(v):
    """Adună din variabilele locale ale analizeaza() tot ce are nevoie fișa HTML."""
    g = v.__getitem__
    precip, mare = g("precip"), g("mare")
    unit, unit_zi, titlu_var, zona_et = g("unit"), g("unit_zi"), g("titlu_var"), g("zona_et")
    zile, val, d0, d1, N = g("zile"), g("val"), g("d0"), g("d1"), g("N")
    rez, ro = g("rez"), zc.ro
    f, t, e, z = rez["fereastra"], rez["top_episoade"], rez["echivalente"], rez["zi_extrema"]
    gb = rez.get("gumbel")
    T_ep = gb["perioada_revenire_ani"] if gb else float("nan")
    H = dict(meta=dict(titlu_var=titlu_var, zona=zona_et, perioada=g("per_txt"), unit=unit, unit_zi=unit_zi, precip=bool(precip),
                       mare=bool(mare), N=int(N), d0=str(d0), d1=str(d1), parametru=g("PARAMETRU"), referinta=g("ref_et"),
                       clim=list(g("CLIMATOLOGIE")), atribuire=zc.ATRIBUIRE, frontiera=rez["frontiera"]),
             avertismente=rez["avertismente"], raport_md=g("raport_md"))

    # ---- carduri
    rev = ("≈ " + ro(T_ep, 0) + " ani" if T_ep >= 2 else "sub 2 ani") if np.isfinite(T_ep) else "indisponibilă"
    zi_txt = f"{ro(z['valoare'], 1)} {unit_zi}"
    if precip:
        H["carduri"] = [
            dict(et="Suma episodului", val=f"{ro(f['valoare'], 1)} mm", sub=f"normala ferestrei: {ro(f['normala'], 1)} mm"),
            dict(et="Din normală", val=f"{ro(f['procent_din_normala'], 0)} %", sub=f"anomalie {'+' if f['anomalie'] >= 0 else ''}{ro(f['anomalie'], 1)} mm", ton="sus" if f["anomalie"] >= 0 else "jos"),
            dict(et="Rang pe aceeași fereastră", val=f"{f['rang']} din {f['din_ani']}", sub=f"record: {f['record_an']} ({ro(f['record_valoare'], 1)} mm)"),
            dict(et=f"Între episoadele de {_nz(N)}", val=f"locul {_sau_liniuta(t['loc'])}", sub=f"același sezon (±{FEREASTRA_SEZON} zile), {t['interval'][0]}–{t['interval'][1]}"),
            dict(et="Perioadă de revenire", val=rev, sub="Gumbel, orientativ"),
            dict(et="Ziua extremă", val=zi_txt, sub=str(z["zi"])),
        ]
    else:
        H["carduri"] = [
            dict(et="Media episodului", val=f"{ro(f['valoare'], 1)} °C", sub=f"normala ferestrei: {ro(f['normala'], 1)} °C"),
            dict(et="Anomalie", val=f"{'+' if f['anomalie'] >= 0 else '−'}{ro(abs(f['anomalie']), 1)} °C", sub=f"față de {f['din_ani']} ani, aceeași fereastră", ton="sus" if f["anomalie"] >= 0 else "jos"),
            dict(et="Rang pe aceeași fereastră", val=f"{f['rang']} din {f['din_ani']}", sub=f"record: {f['record_an']} ({ro(f['record_valoare'], 1)} °C)"),
            dict(et=f"Între episoadele de {_nz(N)}", val=f"locul {_sau_liniuta(t['loc'])}", sub=f"același sezon (±{FEREASTRA_SEZON} zile), {t['interval'][0]}–{t['interval'][1]}"),
            dict(et="Perioadă de revenire", val=rev, sub="Gumbel, orientativ"),
            dict(et="Ziua extremă", val=zi_txt, sub=str(z["zi"])),
        ]

    # ---- (1) rang
    tab = g("tab")
    H["rang"] = dict(ani=[a for a, _ in tab], val=[x for _, x in tab], normala=g("clim_fer"), an_ep=int(g("an_ep")), ep_val=g("ep_val"))

    # ---- (2) top episoade
    items = [dict(et=f"{_fmt_zi(a)} – {_fmt_zi(b)}", v=x, ep=False) for a, b, x in g("top")]
    if t["loc"] is not None:
        items.append(dict(et=f"EPISODUL {_fmt_zi(d0)} – {_fmt_zi(d1)} (locul {t['loc']})", v=g("ep_rul"), ep=True))
    items.sort(key=lambda r: -r["v"] if mare else r["v"])
    H["top"] = dict(items=items, unit=unit if precip else "anomalie medie (°C)", n=int(N))

    # ---- (3) Gumbel
    if gb and np.isfinite(T_ep):
        semn = g("semn")
        x = np.sort(np.asarray(g("maxime"), float) * semn)
        n = x.size; F = (np.arange(1, n + 1) - 0.44) / (n + 0.12); yred = -np.log(-np.log(F))
        yy = np.linspace(min(yred.min(), -1.6), 5.0, 40)
        ep_rul = g("ep_rul")
        H["gumbel"] = dict(puncte=[[a, b * semn] for a, b in zip(yred, x)], dreapta=[[a, (gb["mu"] + gb["beta"] * a) * semn] for a in yy],
                           ep=[(ep_rul * semn - gb["mu"]) / gb["beta"], ep_rul], T=T_ep, niveluri=gb["niveluri"],
                           unit=unit if precip else "anomalie medie (°C)", n=int(n))

    # ---- (4) șiruri
    si = [dict(et=f"{_fmt_zi(a)} – {_fmt_zi(b)}", v=int(L), ep=False) for a, b, L in g("top_sir")]
    sir_ep = g("sir_ep")
    if sir_ep:
        si.append(dict(et=f"EPISODUL {_fmt_zi(sir_ep[0])} – {_fmt_zi(sir_ep[1])}", v=int(sir_ep[2]), ep=True))
    si.sort(key=lambda r: -r["v"])
    H["siruri"] = dict(items=si, definitie=g("et_sir"))

    # ---- (5) zilele episodului
    cl, doy = g("cl"), g("doy")
    A_ = min(max(g("ZILE_ANTERIOARE")) if g("ZILE_ANTERIOARE") else 0, 30)
    mm = (zile >= d0 - A_) & (zile <= d1)
    epm = np.arange(int(mm.sum())) >= A_
    zv = val[mm]; med = cl["med"][doy[mm]]
    zi = dict(zile=[str(q) for q in zile[mm]], val=zv, med=med, p10=cl["p10"][doy[mm]], p90=cl["p90"][doy[mm]],
              p95=g("p95"), p99=g("p99"), ant=int(A_))
    if precip:
        zi["cum"] = np.where(epm, np.cumsum(np.where(epm, np.nan_to_num(zv), 0)), np.nan)
        zi["cum_med"] = np.where(epm, np.cumsum(np.where(epm, med, 0)), np.nan)
    H["zilnic"] = zi

    # ---- (7) contextul anterior
    ZA = g("ZILE_ANTERIOARE")
    if ZA:
        L_ = max(ZA); a_ = d0 - L_; mm = (zile >= a_) & (zile <= d1); nz = int(mm.sum())
        an_ = dict(zile=[str(q) for q in zile[mm]], idx_ep=int(L_), precip=bool(precip))
        if precip:
            B_ = []
            for an in g("clim_ani"):
                aa, bb, _ = _fereastra_an(a_, nz, an)
                m2 = (zile >= aa) & (zile <= bb)
                if m2.sum() == nz:
                    B_.append(np.nancumsum(np.nan_to_num(val[m2])))
            B_ = np.stack(B_)
            an_.update(obs=np.nancumsum(np.nan_to_num(val[mm])), p10=np.percentile(B_, 10, 0), med=B_.mean(0), p90=np.percentile(B_, 90, 0))
        else:
            an_.update(anom=g("anomalie_zi")[mm])
        H["antecedent"] = an_
        H["antecedent"]["tabel"] = rez["context_anterior"]

    # ---- (10) context
    if g("context"):
        H["context"] = [dict(nume=n_, ep=e_, norm=c_, unit=u_) for n_, e_, c_, u_ in g("context")]

    # ---- (13) comparații
    cur = []
    for et, vv, curent in g("comp"):
        vv = np.asarray(vv, float)
        cur.append(dict(et=et, v=np.nancumsum(np.nan_to_num(vv)) if precip else vv, curent=bool(curent)))
    H["comparatii"] = dict(curbe=cur, precip=bool(precip), unit=unit)

    # ---- (14) frecvență
    ani_c, ev, sir = list(g("ani_compl")), list(g("cnt_ev")), list(g("cnt_sir"))
    def dec(y):
        o = []
        for a in ani_c:
            m_ = [yy for aa, yy in zip(ani_c, y) if aa // 10 == a // 10]
            o.append(float(np.mean(m_)) if len(m_) >= 5 else None)
        return o
    if ani_c:
        b1, p1 = zc._panta(ani_c, ev); b2, p2 = zc._panta(ani_c, sir)
        H["frecventa"] = dict(ani=ani_c, ev=ev, sir=sir, dec_ev=dec(ev), dec_sir=dec(sir), tend_ev=[b1, p1], tend_sir=[b2, p2],
                              et_ev=f"episoade de {_nz(N)} peste p{95 if mare else 5} ({ro(g('prag_ev'), 1)} {unit if precip else '°C anomalie'})",
                              et_sir=f"șiruri ≥ {g('MIN_ZILE_SIR')} {g('et_sir')}")

    # ---- (9) extindere
    if rez.get("extindere") and "et_p" in v:
        H["extindere"] = dict(et=list(g("et_p")) + ["record istoric (rang 1)", "top 3 istoric"], v=list(g("fr_")) + [g("r1"), g("r3")])

    # ---- (11) calendar
    ani = zile.astype("datetime64[Y]").astype(int) + 1970
    lista = np.unique(ani)
    M = np.full((len(lista), 366), np.nan)
    M[ani - lista[0], _doy366(zile)] = val if precip else g("anomalie_zi")
    l29 = np.isnan(M[:, 59]) & np.isfinite(M[:, 58]) & np.isfinite(M[:, 60]); M[l29, 59] = (M[l29, 58] + M[l29, 60]) / 2
    if precip:
        sc = dict(lut="Blues", log=True, lo=0.1, hi=max(1.0, float(np.nanpercentile(M, 99.9))))
    else:
        mx = float(np.nanpercentile(np.abs(M), 99)) or 1.0
        sc = dict(lut="RdBu_r", log=False, lo=-mx, hi=mx)
    H["calendar"] = dict(ani=lista.tolist(), M=np.round(M, 1 if precip else 2), d0=int(_doy366(np.array([d0]))[0]), d1=int(_doy366(np.array([d1]))[0]),
                         y0=int(str(d0)[:4]), y1=int(str(d1)[:4]), unit=unit_zi, **sc)

    # ---- zone (mai multe poligoane)
    ZONA = g("ZONA"); etichete = g("etichete"); serii = g("serii")
    if len(etichete) > 1 and ZONA.poligoane:
        mod = "suma" if precip else "medie"; frontiera = g("frontiera"); CL = g("CLIMATOLOGIE"); an_ep = g("an_ep")
        zz = []
        for kk, et in enumerate(etichete):
            z2, v2 = _serie_continua(serii, kk)
            e2 = _stat(v2[(z2 >= d0) & (z2 <= d1)], mod, 0.5)
            ist = []
            for an in g("ani_toti"):
                a, b, _ = _fereastra_an(d0, N, an)
                if b <= frontiera:
                    ist.append((an, _stat(v2[(z2 >= a) & (z2 <= b)], mod)))
            c2 = float(np.nanmean([x for a, x in ist if CL[0] <= a <= CL[1]]))
            r2 = 1 + sum(1 for a, x in ist if np.isfinite(x) and a != an_ep and ((x > e2) if mare else (x < e2)))
            zz.append(dict(nume=et, ep=e2, norm=c2, anom=e2 - c2, proc=(100 * e2 / c2) if precip and c2 else None, rang=r2,
                           din=len(ist), ani=[a for a, _ in ist], vals=[x for _, x in ist],
                           zi=v2[(z2 >= d0) & (z2 <= d1)], total=kk >= len(ZONA.poligoane)))
        H["zone"] = zz
        npol = len(ZONA.poligoane)
        zs = [dict(id="z_anom", titlu="Pe zone: anomalia", unit=unit, arr=[r["anom"] for r in zz[:npol]],
                   cmap="BrBG" if precip else "RdBu_r", divergent=True),
              dict(id="z_rang", titlu="Pe zone: rangul istoric (1 = record)", unit="rang", arr=[float(r["rang"]) for r in zz[:npol]],
                   cmap="YlOrRd_r", divergent=False, vmin=1, vmax=max(5, max(r["rang"] for r in zz[:npol])))]
        if precip:
            zs.insert(1, dict(id="z_proc", titlu="Pe zone: % din normală", unit="%", arr=[r["proc"] for r in zz[:npol]], cmap="BrBG",
                              divergent=True, vmin=0, vmax=300, centru=100))
        H["zone_straturi"] = zs

    # ---- hărți
    harti = g("harti")
    if harti and "gh" in v and v["gh"] is not None:
        gh = g("gh")
        ny, nx = gh.forma
        straturi = []
        for cheie_, titlu_, u_, cm_, kw in g("lista"):
            if cheie_ not in harti or (precip and cheie_ == "minim" and np.nanmax(harti["minim"]) <= 0):
                continue
            straturi.append(dict(id=cheie_, titlu=titlu_, unit=u_, cmap=cm_, arr=harti[cheie_], descr=_DESCR_STRATURI.get(cheie_, ""), **kw))
        straturi.append(dict(id="rang", titlu=f"Rangul istoric al episodului (1 = record) · {len(g('ani_h')) + 1} ani", unit="rang", cmap="YlOrRd_r",
                             arr=harti["rang"], descr=_DESCR_STRATURI["rang"], clase=[0.5, 1.5, 2.5, 3.5, 5.5, 10.5, 20.5, 100.5],
                             etichete=["1", "2", "3", "4–5", "6–10", "11–20", "> 20"]))
        D_ep = np.asarray(g("D_ep"), np.float32)
        zep = g("zile_ep")
        if precip:
            cumf = np.nansum(np.where(np.isfinite(D_ep), D_ep, 0), axis=0); cumf = np.where(np.isfinite(D_ep).any(axis=0), cumf, np.nan)
            vz = (0.0, max(float(np.nanpercentile(D_ep, 99)), 1.0)); vc = (0.0, max(float(np.nanpercentile(cumf, 99)), 1.0))
            cm_z, cm_c, cum_mod = "Blues", "YlGnBu", "suma"
            t_zi, t_cum = f"{titlu_var} · ziua", "Cumulat de la începutul episodului"
        else:
            vz = vc = (float(np.nanpercentile(D_ep, 2)), float(np.nanpercentile(D_ep, 98)))
            cm_z = cm_c = "RdYlBu_r"; cum_mod = "medie"
            t_zi, t_cum = f"{titlu_var} · ziua", "Media de la începutul episodului"
        contur = zc._citeste_contur(zc.CONTUR_HARTI) if zc.CONTUR_HARTI else []
        H["harti"] = dict(grila=dict(extent=list(gh.extent), pas=zc.PAS, ny=int(ny), nx=int(nx)), straturi=straturi, cub=D_ep, zile=[str(q) for q in zep],
                          cum_mod=cum_mod, unit_zi=unit_zi, titlu_zi=t_zi, titlu_cum=t_cum, cmap_zi=cm_z, cmap_cum=cm_c, v_zi=vz, v_cum=vc,
                          contur=contur, poligoane=None,
                          punct=[ZONA.punct[0], ZONA.punct[1], zona_et] if ZONA.punct else None)
        if ZONA.poligoane:
            import zarr_html
            H["harti"]["poligoane"] = zarr_html._poligoane(ZONA, gh.extent)
    return H
