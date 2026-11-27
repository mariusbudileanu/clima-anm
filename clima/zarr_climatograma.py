# -*- coding: utf-8 -*-
"""
zarr_climatograma.py — climatograma Walter–Lieth pentru un punct sau o zonă, pe una sau două perioade
(implicit normalele 1961–1990 și 1991–2020), din seriile zilnice ale zonei (cache-ul seriilor, ca la rețeta 15).

Convențiile Walter–Lieth (Walter & Lieth, 1960):
  * temperatura medie lunară (roșu, axa stângă) și precipitațiile medii lunare (albastru, axa dreaptă), cu
    10 °C ↔ 20 mm (P = 2T); peste 100 mm scara precipitațiilor se comprimă de 10 ori (fond albastru plin);
  * perioada aridă (curba P sub curba T, adică P < 2T): punctată; perioada umedă (P > 2T): hașură verticală;
  * sub axă, bara de îngheț: lună cu media minimelor < 0 °C = îngheț sigur (plin), lună cu minima absolută < 0 °C
    = îngheț probabil (hașurat);
  * pe marginea stângă: media maximelor celei mai calde luni, media minimelor celei mai reci luni și extremele absolute.
Valorile sunt ale seriei MEDII a zonei (pentru un punct: ale pixelului). O lună intră într-o perioadă doar dacă are
date în cel puțin 80 % din anii perioadei.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

import zarr_clima as zc

LUNI = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
LUNI_LUNG = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "nov", "dec"]
ROSU, ALBASTRU, ARID, UMED, ADANC = "#c0392b", "#1f63b5", "#d9480f", "#4c8fd6", "#1d4f91"
PRAG_ANI = 0.8
MIN_ANI = 10                    # sub 10 ani, o climatogramă nu are sens (normalele: 30 de ani)


# ------------------------------------------------------------------------------------------------------ calculul
def statistici_perioada(S, ani, frontiera, k=-1):
    """S = {var: {an: ndarray (n_zone, zile)}} → statisticile lunare ale zonei k pe anii `ani`.
    → dict cu T, Tmax, Tmin, P (12 luni), extremele absolute pe lună, anii folosiți."""
    ani = [a for a in ani if all(a in S[v] for v in S)]
    L = {v: [] for v in S}
    for a in ani:
        for v in S:
            L[v].append(zc._lunare(S[v], v, a, frontiera)[k])
    L = {v: np.array(L[v]) if L[v] else np.full((0, 12), np.nan) for v in L}
    n = len(ani)
    ok = lambda M: (np.isfinite(M).sum(axis=0) >= max(1, PRAG_ANI * n)) if n else np.zeros(12, bool)  # noqa: E731
    med = lambda M: np.where(ok(M), np.nanmean(np.where(np.isfinite(M), M, np.nan), axis=0), np.nan) if n else np.full(12, np.nan)  # noqa: E731
    tmax, tmin, p = med(L["max_temp"]), med(L["min_temp"]), med(L["precipitation"])
    t = (tmax + tmin) / 2
    # extremele absolute ale seriei zilnice a zonei, pe lună
    absmax, absmin = np.full(12, np.nan), np.full(12, np.nan)
    for a in ani:
        z0 = np.datetime64(f"{a}-01-01")
        for m in range(12):
            i0 = int((np.datetime64(f"{a}-{m + 1:02d}-01") - z0).astype(int))
            i1 = int(((np.datetime64(f"{a}-{m + 1:02d}", "M") + 1).astype("datetime64[D]") - z0).astype(int))
            for v, f, dest in (("max_temp", np.nanmax, absmax), ("min_temp", np.nanmin, absmin)):
                x = S[v][a][k, i0:i1] if S[v][a].shape[1] >= i1 else np.array([])
                x = x[np.isfinite(x)]
                if x.size:
                    dest[m] = f([dest[m], f(x)]) if np.isfinite(dest[m]) else f(x)
    luni_valide = int(np.isfinite(t).sum())
    return {"ani": ani, "n_ani": n, "T": t, "Tmax": tmax, "Tmin": tmin, "P": p, "abs_max": absmax, "abs_min": absmin,
            "T_an": float(np.nanmean(t)) if luni_valide == 12 else np.nan,
            "P_an": float(np.nansum(p)) if np.isfinite(p).all() else np.nan,
            "luni_aride": [LUNI_LUNG[m] for m in range(12) if np.isfinite(p[m]) and p[m] < 2 * t[m]],
            "luni_inghet": [LUNI_LUNG[m] for m in range(12) if np.isfinite(tmin[m]) and tmin[m] < 0]}


# ------------------------------------------------------------------------------------------------------ desenul
def _y_p(p):
    """Precipitațiile în unitățile axei temperaturii: P/2 până la 100 mm, apoi 50 + (P − 100)/20 (scara 1:10)."""
    p = np.asarray(p, float)
    return np.where(p <= 100, p / 2, 50 + (p - 100) / 20)


def _panou(ax, st, titlu, sub, y_lim):
    import matplotlib.ticker as mt
    x = np.arange(1, 13)
    t, yp = st["T"], _y_p(st["P"])
    xf = np.linspace(0.5, 12.5, 721)
    # ciclul anual: interpolare circulară (decembrie se leagă de ianuarie)
    xe = np.r_[0, x, 13]
    te = np.r_[t[-1], t, t[0]]; pe = np.r_[yp[-1], yp, yp[0]]
    ok = np.isfinite(te) & np.isfinite(pe)
    if ok.sum() >= 4:
        tf, pf = np.interp(xf, xe[ok], te[ok]), np.interp(xf, xe[ok], pe[ok])
        pf_jos = np.minimum(pf, 50)
        arid, umed = pf_jos < tf, pf_jos > tf
        ax.fill_between(xf, pf_jos, tf, where=arid, facecolor="none", edgecolor=ARID, hatch="...", lw=0,
                        interpolate=True, label="perioadă aridă (P < 2T)" if arid.any() else None)
        ax.fill_between(xf, tf, pf_jos, where=umed, facecolor="none", edgecolor=UMED, hatch="|||", lw=0,
                        interpolate=True, label="perioadă umedă (P > 2T)" if umed.any() else None)
        if (pf > 50).any():
            ax.fill_between(xf, 50, pf, where=pf > 50, color=ADANC, lw=0, interpolate=True, label="P > 100 mm (scara 1:10)")
    ax.plot(x, t, color=ROSU, lw=2.2, marker="o", ms=3.5, zorder=4)
    ax.plot(x, yp, color=ALBASTRU, lw=2.2, marker="o", ms=3.5, zorder=4)
    lo, hi = y_lim
    ax.set_xlim(0.5, 12.5); ax.set_ylim(lo, hi)
    ax.set_xticks(x); ax.set_xticklabels(LUNI, fontsize=9)
    ax.yaxis.set_major_locator(mt.MultipleLocator(10))
    ax.set_ylabel("Temperatura (°C)", color=ROSU)
    ax.tick_params(axis="y", colors=ROSU)
    ax2 = ax.twinx(); ax2.set_ylim(lo, hi)
    poz = [v for v in range(0, 51, 10)] + [50 + k * 5 for k in range(1, int((hi - 50) / 5) + 1)] if hi > 50 else list(range(0, int(hi) + 1, 10))
    ax2.set_yticks([v for v in poz if lo <= v <= hi])
    ax2.set_yticklabels([f"{int(v * 2)}" if v <= 50 else f"{int(100 + (v - 50) * 20)}" for v in poz if lo <= v <= hi])
    ax2.set_ylabel("Precipitații (mm)", color=ALBASTRU)
    ax2.tick_params(axis="y", colors=ALBASTRU)
    ax.axhline(0, color="#333333", lw=0.8)
    for s in ("top",):
        ax.spines[s].set_visible(False); ax2.spines[s].set_visible(False)
    # bara de îngheț, sub zero
    yb = lo + (hi - lo) * 0.012
    hb = (hi - lo) * 0.035
    for m in range(12):
        if np.isfinite(st["Tmin"][m]) and st["Tmin"][m] < 0:
            ax.add_patch(_drept(m + 0.5, yb, 1, hb, ADANC, None))
        elif np.isfinite(st["abs_min"][m]) and st["abs_min"][m] < 0:
            ax.add_patch(_drept(m + 0.5, yb, 1, hb, "none", "////", ADANC))
    # antetul și marginea
    fmt = lambda v, u: "–" if not np.isfinite(v) else f"{v:.1f}".replace(".", ",").replace("-", "−") + u  # noqa: E731
    ax.set_title(titlu, loc="left", fontsize=12, fontweight="bold", pad=22)
    ax.text(0, 1.035, sub, transform=ax.transAxes, fontsize=9, color="#555555", va="bottom")
    pan = st["P_an"]
    ax.text(1, 1.035, f"T {fmt(st['T_an'], ' °C')}   ·   P {('–' if not np.isfinite(pan) else f'{pan:.0f} mm')}",
            transform=ax.transAxes, fontsize=11, fontweight="bold", ha="right", va="bottom")
    marg = [("max. abs.", np.nanmax(st["abs_max"]) if np.isfinite(st["abs_max"]).any() else np.nan),
            ("media max. luna caldă", np.nanmax(st["Tmax"]) if np.isfinite(st["Tmax"]).any() else np.nan),
            ("media min. luna rece", np.nanmin(st["Tmin"]) if np.isfinite(st["Tmin"]).any() else np.nan),
            ("min. abs.", np.nanmin(st["abs_min"]) if np.isfinite(st["abs_min"]).any() else np.nan)]
    for i, (et, v) in enumerate(marg):
        ax.text(0.012, 0.97 - i * 0.055, f"{fmt(v, ' °C')}  {et}", transform=ax.transAxes, fontsize=8, color="#444444",
                va="top", bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.8))
    return ax2


def _drept(x, y, w, h, fc, hatch, ec=None):
    from matplotlib.patches import Rectangle
    return Rectangle((x, y), w, h, facecolor=fc, hatch=hatch, edgecolor=ec or fc, lw=0.6, zorder=5)


def png_climatograma(cale, perioade, zona_et, altitudine=None):
    plt = zc._plt()
    n = len(perioade)
    toate_t = np.concatenate([st["T"] for _, st in perioade] + [st["Tmin"] for _, st in perioade])
    toate_p = np.concatenate([_y_p(st["P"]) for _, st in perioade])
    lo = min(-10.0, np.floor(np.nanmin(toate_t) / 10) * 10 - 5) if np.isfinite(toate_t).any() else -10
    hi = max(50.0, np.ceil(max(np.nanmax(toate_t), np.nanmax(toate_p)) / 10) * 10) if np.isfinite(toate_p).any() else 50
    fig, axe = plt.subplots(1, n, figsize=(6.4 * n, 5.6), sharey=True, squeeze=False)
    alt_txt = f" · {altitudine:.0f} m" if altitudine is not None and np.isfinite(altitudine) else ""
    for ax, (et, st) in zip(axe[0], perioade):
        _panou(ax, st, zona_et + alt_txt, f"{et} · {st['n_ani']} ani", (lo, hi))
    h, l = [], []
    for ax in axe[0]:                                   # legenda: tot ce apare în oricare panou, o singură dată
        for hh, ll in zip(*ax.get_legend_handles_labels()):
            if ll not in l:
                h.append(hh); l.append(ll)
    if h:
        fig.legend(h, l, loc="lower center", ncol=3, frameon=False, fontsize=9, bbox_to_anchor=(0.5, -0.01))
    fig.text(0.01, -0.045, "Walter–Lieth: 10 °C ↔ 20 mm; peste 100 mm, scara 1:10. Bara de jos: îngheț sigur (plin: media "
                           "minimelor < 0 °C) și probabil\n(hașurat: minima absolută < 0 °C). T și P anuale: dreapta sus. "
                           "Date: ANM / EOCube.ro, CC BY 4.0 · Clima ANM.", fontsize=8, color="#666666")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(cale, dpi=150, bbox_inches="tight"); plt.close(fig)
    zc.log(f"   PNG: {cale}")
    return Path(cale)


def png_diferente(cale, A, B, et_a, et_b, zona_et):
    """ΔT (°C) și ΔP (%) pe luni: B față de A."""
    plt = zc._plt()
    x = np.arange(12)
    dT = B["T"] - A["T"]
    with np.errstate(divide="ignore", invalid="ignore"):
        dP = np.where(A["P"] > 0, (B["P"] - A["P"]) / A["P"] * 100, np.nan)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8))
    a1.bar(x, dT, color=[ROSU if v > 0 else ALBASTRU for v in np.nan_to_num(dT)], width=0.7)
    a1.set_title(f"Temperatura: {et_b} față de {et_a} (°C)", loc="left", fontsize=10)
    a2.bar(x, dP, color=["#8c6d1f" if v < 0 else "#2b8a3e" for v in np.nan_to_num(dP)], width=0.7)
    a2.set_title(f"Precipitațiile: {et_b} față de {et_a} (%)", loc="left", fontsize=10)
    import matplotlib.ticker as mt
    for a in (a1, a2):
        a.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",").replace("-", "−")))
        a.axhline(0, color="#333333", lw=0.8); a.set_xticks(x); a.set_xticklabels(LUNI, fontsize=9)
        a.spines["top"].set_visible(False); a.spines["right"].set_visible(False)
        a.grid(axis="y", color="#e5e5e5", lw=0.6); a.set_axisbelow(True)
    fig.suptitle(zona_et, x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(cale, dpi=150, bbox_inches="tight"); plt.close(fig)
    zc.log(f"   PNG: {cale}")
    return Path(cale)


# ------------------------------------------------------------------------------------------------------ rularea
def ruleaza_climatograma(zona, perioada_a, perioada_b, iesiri, out, nume, total_nume="Toată zona"):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    perioade = [(int(perioada_a[0]), int(perioada_a[1]))] + ([(int(perioada_b[0]), int(perioada_b[1]))] if perioada_b else [])
    zc.log(f"== {nume}: climatograma Walter–Lieth · {zona.descriere()} · " + " și ".join(f"{a}–{b}" for a, b in perioade))
    cub, fr = zc.deschide()
    g = zc.grila_zonei(cub, zona)
    ani = sorted({a for p0, p1 in perioade for a in range(p0, p1 + 1)})
    S = {}
    for v in ("max_temp", "min_temp", "precipitation"):
        et, S[v], _ = zc.serii_zonale(cub, fr, v, ani, zona, g, total_nume, zc.dir_cache("serii"))
    frontiera = min(fr[v] for v in S)
    zona_et = et[-1] if len(et) > 1 else (zona.nume or zona.descriere())
    rez = []
    for p0, p1 in perioade:
        st = statistici_perioada(S, list(range(p0, p1 + 1)), frontiera)
        lipsa = (p1 - p0 + 1) - st["n_ani"]
        if lipsa:
            zc.log(f"   [atenție] {p0}–{p1}: {lipsa} ani fără date complete (în afara cubului sau după frontieră)")
        if st["n_ani"] < MIN_ANI:
            raise ValueError(f"Perioada {p0}–{p1} are doar {st['n_ani']} ani cu date: o climatogramă cere cel puțin 10 "
                             f"(normalele climatice: 30).")
        rez.append((f"{p0}–{p1}", st))
        zc.log(f"   {p0}–{p1}: T = {st['T_an']:.1f} °C, P = {st['P_an']:.0f} mm; luni aride: "
               f"{', '.join(st['luni_aride']) or 'niciuna'}; luni cu îngheț sigur: {', '.join(st['luni_inghet']) or 'niciuna'}")
    try:
        alt = float(zc.medie_zona(zc.altitudine(g), zona))
    except Exception:  # noqa: BLE001 (altitudinea e doar informativă)
        alt = None
    fis = []
    if iesiri.get("png", True):
        fis.append(png_climatograma(out / f"{nume}.png", rez, zona_et, alt))
        if len(rez) == 2:
            fis.append(png_diferente(out / f"{nume}_diferente.png", rez[0][1], rez[1][1], rez[0][0], rez[1][0], zona_et))
    if iesiri.get("csv", True):
        f = out / f"{nume}.csv"
        with open(f, "w", newline="", encoding="utf-8-sig") as h:
            w = csv.writer(h, delimiter=";")
            cap = ["luna"]
            for et_p, _ in rez:
                cap += [f"T_{et_p}", f"Tmax_{et_p}", f"Tmin_{et_p}", f"P_{et_p}", f"Tmax_abs_{et_p}", f"Tmin_abs_{et_p}"]
            if len(rez) == 2:
                cap += ["dT", "dP_procent"]
            w.writerow(cap)
            r = lambda v, d=1: "" if not np.isfinite(v) else f"{v:.{d}f}".replace(".", ",")  # noqa: E731
            for m in range(12):
                row = [LUNI_LUNG[m]]
                for _, st in rez:
                    row += [r(st["T"][m]), r(st["Tmax"][m]), r(st["Tmin"][m]), r(st["P"][m]), r(st["abs_max"][m]), r(st["abs_min"][m])]
                if len(rez) == 2:
                    A, B = rez[0][1], rez[1][1]
                    row += [r(B["T"][m] - A["T"][m], 2), r((B["P"][m] - A["P"][m]) / A["P"][m] * 100 if A["P"][m] else np.nan)]
                w.writerow(row)
            w.writerow(["an"] + sum(([r(st["T_an"]), "", "", r(st["P_an"], 0), "", ""] for _, st in rez), [])
                       + ([r(rez[1][1]["T_an"] - rez[0][1]["T_an"], 2),
                           r((rez[1][1]["P_an"] - rez[0][1]["P_an"]) / rez[0][1]["P_an"] * 100)] if len(rez) == 2 else []))
        zc.log(f"   CSV: {f}"); fis.append(f)
    rezumat = {"zona": zona_et, "altitudine": alt, "perioade": [
        {"perioada": et_p, "ani": st["n_ani"], "T_an": st["T_an"], "P_an": st["P_an"], "luni_aride": st["luni_aride"],
         "luni_inghet": st["luni_inghet"]} for et_p, st in rez]}
    (out / f"{nume}_rezumat.json").write_text(json.dumps(rezumat, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return fis
