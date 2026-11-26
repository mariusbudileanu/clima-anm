# -*- coding: utf-8 -*-
"""
integritate.py — „Verifică datele”: chunk-uri lipsă și blocuri nescrise în cubul anm-daily-grids
==================================================================================================
Două verificări, pe fiecare variabilă (Tmax, Tmin, P):

  1. ISTORICUL (fără descărcare): există fiecare chunk (timp × bloc spațial 161 × 324)? O cerere HEAD pe chunk,
     în paralel; blocurile care nu au existat niciodată sunt în afara domeniului (nu e o problemă).
  2. ZILELE RECENTE (citire efectivă, ~0,2 GB): în ultimele N zile până la frontieră, zilele în care un bloc
     întreg are exact 0 la temperaturi (date nescrise: Zarr pune valoarea de umplere) și chunk-urile lipsă.

Rezultatul: „ultima zi sigură” a fiecărei variabile (comparată cu frontiera declarată de cub), harta disponibilității
pe blocuri și zile, lista problemelor (CSV) și rapoartele JSON în folderul rulării și în rezultate/_cache/integritate.json
(citit de antetul interfeței). Analizele tratează oricum automat aceste goluri ca date lipsă (zarr_clima.citeste).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import numpy as np

import zarr_clima as zc

VARS = ("max_temp", "min_temp", "precipitation")
NUME = {"max_temp": "Tmax", "min_temp": "Tmin", "precipitation": "P"}


def _cheie(v, t, y, x, sep="."):
    return f"{v}/{t}{sep}{y}{sep}{x}"


async def _exista_toate(store, chei, simultan=32):
    sem = asyncio.Semaphore(simultan)

    async def una(k):
        async with sem:
            for inc in range(3):
                try:
                    return await store.exists(k)
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(1 + inc)
            return None                                  # nu s-a putut verifica

    return await asyncio.gather(*(una(k) for k in chei))


def _sync(coro):
    """Rulează o corutină în bucla de evenimente a lui zarr: store-ul HTTP (aiohttp) e legat de ea,
    iar dintr-o buclă nouă (asyncio.run) dă „RuntimeError … attached to a different loop”."""
    try:
        from zarr.core.sync import sync
    except ImportError:                                    # zarr foarte vechi
        return asyncio.run(coro)
    return sync(coro)


def _separator(store):
    try:
        from zarr.core.buffer import default_buffer_prototype
        b = _sync(store.get(".zmetadata", default_buffer_prototype()))
        m = json.loads(b.to_bytes())["metadata"]
        return m.get("max_temp/.zarray", {}).get("dimension_separator") or "."
    except Exception:  # noqa: BLE001
        return "."


def existenta(cub, v, ct_max):
    """Matricea (chunk timp, chunk y, chunk x) → True / False / None (neverificabil), până la chunk-ul ct_max."""
    store = zc.STORE_ULTIM
    ctn, cyn, cxn = [int(c) for c in (cub[v].encoding.get("chunks") or (90, 161, 324))]
    ny, nx = cub[v].shape[1:]
    nyc, nxc = -(-ny // cyn), -(-nx // cxn)
    sep = _separator(store)
    chei = [(t, y, x) for t in range(ct_max + 1) for y in range(nyc) for x in range(nxc)]
    rez = _sync(_exista_toate(store, [_cheie(v, t, y, x, sep) for t, y, x in chei]))
    E = np.zeros((ct_max + 1, nyc, nxc), dtype="int8")          # 1 există, 0 lipsește, -1 neverificabil
    for (t, y, x), r in zip(chei, rez):
        E[t, y, x] = -1 if r is None else int(bool(r))
    return E, (ctn, cyn, cxn)


def ruleaza_integritate(out, nume, zile_recente=150, istoric=True, iesiri=None):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    iesiri = iesiri or {"png": True, "csv": True}
    zc.log(f"== {nume}: verificarea integrității datelor (ultimele {zile_recente} de zile" + (" + istoricul complet)" if istoric else ")"))
    cub, fr = zc.deschide()
    t0_cub = np.datetime64(str(cub.time.values[0])[:10], "D")
    raport = {"verificat": time.strftime("%Y-%m-%d %H:%M"), "sursa": zc.URL, "variabile": {}}
    probleme = []
    if zc.STORE_ULTIM is None:
        zc.log("   [atenție] nu am acces la store-ul cubului: verific doar valorile recente")
    for v in VARS:
        if v not in fr:
            continue
        frontiera = fr[v]
        ctn, cyn, cxn = [int(c) for c in (cub[v].encoding.get("chunks") or (90, 161, 324))]
        ct_fr = int((frontiera - t0_cub).astype(int)) // ctn
        info = {"frontiera_declarata": str(frontiera)}
        # 1) istoricul: existența chunk-urilor
        if istoric and zc.STORE_ULTIM is not None:
            t = time.perf_counter()
            E, _ = existenta(cub, v, ct_fr)
            domeniu = (E == 1).mean(axis=0) >= 0.5                 # blocurile care au, de regulă, date
            lipsa = (E == 0) & domeniu[None]
            ct_lipsa = sorted({int(t_) for t_, _, _ in zip(*np.nonzero(lipsa))})
            info.update(chunkuri_verificate=int(E.size), blocuri_domeniu=int(domeniu.sum()),
                        chunkuri_lipsa=int(lipsa.sum()), neverificabile=int((E == -1).sum()))
            for t_, y_, x_ in zip(*np.nonzero(lipsa)):
                d0 = t0_cub + int(t_) * ctn
                d1 = min(d0 + ctn - 1, frontiera)
                probleme.append([NUME[v], "chunk lipsă", str(d0), str(d1), int(y_), int(x_), *_bbox(cub, y_, x_, cyn, cxn)])
            zc.log(f"   {NUME[v]}: {E.size} chunk-uri verificate în {time.perf_counter() - t:.0f} s · "
                   f"{int(domeniu.sum())} blocuri în domeniu · {int(lipsa.sum())} lipsă"
                   + (f" (în {len(ct_lipsa)} trimestre, ultimul: {t0_cub + ct_lipsa[-1] * ctn})" if ct_lipsa else ""))
            info["_E"] = E
        raport["variabile"][v] = info
    # 2) zilele recente: citire efectivă pe toată grila (corecția din zarr_clima înregistrează golurile)
    g = zc.grila_zonei(cub, zc.Zona.tara())
    fr_min = min(fr.values())
    d0 = fr_min - np.timedelta64(int(zile_recente) - 1, "D")
    zc.CHUNKURI_LIPSA.clear(); zc.ZILE_SUSPECTE.clear()
    zile = None
    disp = {}
    for v in VARS:
        d, zile = zc.citeste(cub, (v,), d0, fr_min, g)
        a = d[v]; del d
        # disponibilitatea pe bloc și zi: 2 = date, 1 = chunk lipsă, 3 = bloc nescris (exact 0), 0 = în afara domeniului
        M = np.zeros((len(zile), len(list(zc._blocuri_spatiale(g)))), dtype="int8")
        for j, (cy, cx, rs, cs) in enumerate(zc._blocuri_spatiale(g)):
            ok = np.isfinite(a[:, rs, cs]).sum(axis=(1, 2))
            M[:, j] = np.where(ok >= zc.MIN_PIXELI_BLOC, 2, 0)
            susp = zc.ZILE_SUSPECTE.get((v, cy, cx), set())
            lips = [(t_, y_, x_) for (vv, t_, y_, x_) in zc.CHUNKURI_LIPSA if vv == v and (y_, x_) == (cy, cx)]
            ct_lips = {t_ for t_, _, _ in lips}
            for k, z in enumerate(zile):
                ct = int((z - t0_cub).astype(int)) // 90
                if ct in ct_lips:
                    M[k, j] = 1
                elif z.item() in susp:
                    M[k, j] = 3
        disp[v] = M
        del a
    blocuri = list(zc._blocuri_spatiale(g))
    for v in VARS:
        M = disp[v]
        E = raport["variabile"].get(v, {}).get("_E")
        if E is not None:                                            # domeniul: blocurile care au de regulă chunk-uri
            dom_h = (E == 1).mean(axis=0) >= 0.5
            dom = np.array([bool(dom_h[cy, cx]) for cy, cx, _, _ in blocuri])
        else:                                                        # fără istoric: blocurile cu date în ≥ 30 % din zile
            dom = (M == 2).mean(axis=0) >= 0.3
        M[:, ~dom] = 0                                               # în afara domeniului: nu e o problemă
        rau = ((M == 1) | (M == 3)) & dom[None]
        zi_rea = np.flatnonzero(rau.any(axis=1))
        sigura = zile[zi_rea[0]] - np.timedelta64(1, "D") if len(zi_rea) else fr_min
        info = raport["variabile"].setdefault(v, {"frontiera_declarata": str(fr[v])})
        info.update(ultima_zi_sigura=str(sigura), zile_recente_afectate=int(len(zi_rea)),
                    blocuri_afectate=int(rau.any(axis=0).sum()))
        # perioadele continue cu probleme, pe bloc
        for j in np.flatnonzero(rau.any(axis=0)):
            cy, cx = blocuri[j][:2]
            for cod, tip in ((3, "bloc nescris (valori exact 0)"), (1, "chunk lipsă")):
                if cod == 1 and E is not None:                       # deja în lista istoricului
                    continue
                for a_, b_ in _segmente(np.flatnonzero(M[:, j] == cod)):
                    probleme.append([NUME[v], tip, str(zile[a_]), str(zile[b_]), cy, cx, *_bbox(cub, cy, cx, 161, 324)])
        stare = "ok" if not len(zi_rea) and not info.get("chunkuri_lipsa") else "probleme"
        info["stare"] = stare
        zc.log(f"   {NUME[v]}: frontiera declarată {fr[v]} · ultima zi sigură {sigura}"
               + (f" · {len(zi_rea)} zile recente afectate în {int(rau.any(axis=0).sum())} blocuri" if len(zi_rea) else " · zilele recente sunt complete"))
    # rezumat
    sigure = [np.datetime64(i["ultima_zi_sigura"]) for i in raport["variabile"].values() if "ultima_zi_sigura" in i]
    raport["ultima_zi_sigura"] = str(min(sigure)) if sigure else None
    raport["frontiera_declarata"] = str(fr_min)
    raport["stare"] = "ok" if all(i.get("stare") == "ok" for i in raport["variabile"].values()) else "probleme"
    raport["probleme"] = len(probleme)
    fis = []
    if iesiri.get("png", True):
        fis.append(png_disponibilitate(out / f"{nume}_disponibilitate.png", disp, zile, blocuri, cub, raport))
        E_all = {v: i.pop("_E") for v, i in raport["variabile"].items() if "_E" in i}
        if E_all:
            fis.append(png_istoric(out / f"{nume}_istoric_chunkuri.png", E_all, t0_cub, raport))
    else:
        for i in raport["variabile"].values():
            i.pop("_E", None)
    if iesiri.get("csv", True):
        fis.append(zc.scrie_csv(out / f"{nume}_probleme.csv", ["variabila", "tip", "de_la", "pana_la", "bloc_y", "bloc_x",
                                                               "lon_min", "lat_min", "lon_max", "lat_max"], probleme))
    (out / f"{nume}_raport.json").write_text(json.dumps(raport, ensure_ascii=False, indent=1), encoding="utf-8")
    try:                                                          # pentru antetul interfeței
        (zc.dir_cache("integritate") / "ultimul.json").write_text(json.dumps(raport, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    if raport["stare"] == "ok":
        zc.log(f"   REZULTAT: datele sunt complete până la {raport['ultima_zi_sigura']} (frontiera declarată).")
    else:
        zc.log(f"   REZULTAT: atenție — frontiera declarată e {raport['frontiera_declarata']}, dar datele sigure "
               f"(toate variabilele, toate blocurile) merg până la {raport['ultima_zi_sigura']}. {len(probleme)} probleme "
               f"în {nume}_probleme.csv. Analizele tratează automat golurile ca date lipsă.")
    zc.log(f"== gata: {nume}")
    return fis


def _segmente(k):
    """Indici sortați → perioade continue [(început, sfârșit)]."""
    if not len(k):
        return []
    rup = np.flatnonzero(np.diff(k) > 1)
    inc = np.r_[k[0], k[rup + 1]]; sf = np.r_[k[rup], k[-1]]
    return list(zip(inc, sf))


def _bbox(cub, cy, cx, cyn, cxn):
    y = cub.y.values; x = cub.x.values
    ys = y[int(cy) * cyn:(int(cy) + 1) * cyn]; xs = x[int(cx) * cxn:(int(cx) + 1) * cxn]
    if not len(ys) or not len(xs):
        return ["", "", "", ""]
    return [round(float(xs.min()), 2), round(float(ys.min()), 2), round(float(xs.max()), 2), round(float(ys.max()), 2)]


def _eticheta_bloc(cub, cy, cx):
    b = _bbox(cub, cy, cx, 161, 324)
    return f"{b[0]:.1f}–{b[2]:.1f}°E, {b[1]:.1f}–{b[3]:.1f}°N" if b[0] != "" else f"bloc {cy}.{cx}"


def png_disponibilitate(cale, disp, zile, blocuri, cub, raport):
    """Pentru fiecare variabilă: blocurile (rânduri) × zilele recente (coloane): date / lipsă sau nescrise / în afara domeniului."""
    plt = zc._plt()
    from matplotlib.colors import ListedColormap
    cale = zc._gata(cale)
    nb = len(blocuri)
    fig, axe = plt.subplots(len(disp), 1, figsize=(12, 1.0 + 0.36 * nb * len(disp)), sharex=True)
    axe = np.atleast_1d(axe)
    cm = ListedColormap(["#f3f5f7", "#c92a2a", "#7fb3a0", "#f59f00"])        # în afara domeniului, lipsă, date, nescris
    x = np.arange(len(zile))
    for ax, (v, M) in zip(axe, disp.items()):
        ax.imshow(M.T, aspect="auto", cmap=cm, vmin=0, vmax=3, interpolation="nearest",
                  extent=(-0.5, len(zile) - 0.5, nb - 0.5, -0.5))
        ax.set_yticks(range(nb)); ax.set_yticklabels([_eticheta_bloc(cub, cy, cx) for cy, cx, _, _ in blocuri], fontsize=7)
        i = raport["variabile"].get(v, {})
        ax.set_title(f"{NUME[v]} · ultima zi sigură: {i.get('ultima_zi_sigura', '?')} (frontiera declarată {i.get('frontiera_declarata', '?')})",
                     fontsize=9.5, loc="left")
        for s_ in ("top", "right"):
            ax.spines[s_].set_visible(False)
    luni = [k for k in x if str(zile[k])[8:10] == "01"]
    axe[-1].set_xticks(luni); axe[-1].set_xticklabels([str(zile[k])[:7] for k in luni], fontsize=8)
    fig.suptitle(f"Disponibilitatea datelor în ultimele {len(zile)} zile, pe blocuri de chunk (161 × 324 pixeli)",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.text(0.01, -0.01, "verde = date · roșu = chunk lipsă · portocaliu = bloc nescris (valori exact 0) · gri deschis = "
             "în afara domeniului (fără date de regulă)", fontsize=8.5, color="#555555")
    fig.tight_layout()
    fig.savefig(cale, dpi=zc.DPI, bbox_inches="tight"); plt.close(fig)
    zc.log(f"   PNG disponibilitate: {cale}")
    return cale


def png_istoric(cale, E_all, t0_cub, raport):
    """Existența chunk-urilor pe tot istoricul: pentru fiecare variabilă, câte blocuri din domeniu lipsesc în fiecare trimestru."""
    plt = zc._plt()
    cale = zc._gata(cale)
    fig, ax = plt.subplots(figsize=(12, 3.2))
    for v, E in E_all.items():
        dom = (E == 1).mean(axis=0) >= 0.5
        lips = ((E == 0) & dom[None]).sum(axis=(1, 2))
        ani = [int(str(t0_cub + t * 90)[:4]) + (int(str(t0_cub + t * 90)[5:7]) - 1) / 12 for t in range(E.shape[0])]
        ax.plot(ani, lips, lw=1.6, label=f"{NUME[v]} ({int(lips.sum())} lipsă)")
    ax.set_ylabel("blocuri lipsă / trimestru")
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    ax.set_title("Istoricul: chunk-uri lipsă din domeniu (0 = complet)", fontsize=11, loc="left")
    fig.savefig(cale, dpi=zc.DPI, bbox_inches="tight"); plt.close(fig)
    zc.log(f"   PNG istoric: {cale}")
    return cale
