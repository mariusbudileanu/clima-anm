# -*- coding: utf-8 -*-
"""
teste_cunoscute.py — teste cu RĂSPUNS CALCULAT DE MÂNĂ pentru nucleul Clima ANM
==============================================================================
Fiecare test pornește de la date mici, scrise explicit, al căror rezultat corect se poate verifica pe hârtie.
Spre deosebire de testarea rețetelor (care verifică doar că o rulare produce fișiere), aici se verifică
VALOAREA climatică. Multe teste reproduc scenarii din auditul independent v4 (codurile în paranteză).

  instrumente/pixi run --manifest-path pixi.toml python instrumente/teste_cunoscute.py

Cum adaugi un test pentru un indicator nou: scrie o funcție test_…() cu o serie de câteva zile, calculează
rezultatul de mână în comentariu, apoi compară cu `egal(...)`. Include mereu și un caz cu zile lipsă (NaN).
"""
from __future__ import annotations

import ast
import math
import sys
import traceback
from pathlib import Path

import numpy as np

RAD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAD / "clima"))
import zarr_clima as zc  # noqa: E402

NAN = np.nan


def egal(a, b, tol=1e-6, msg=""):
    a = np.asarray(a, float); b = np.asarray(b, float)
    ok = a.shape == b.shape and np.all((np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= tol))
    if not ok:
        raise AssertionError(f"{msg}: obținut {a.tolist()}, așteptat {b.tolist()}")


def zile_an(an):
    return np.arange(np.datetime64(f"{an}-01-01"), np.datetime64(f"{an + 1}-01-01"))


# ------------------------------------------------------------------ indicatori pe o serie
def test_medie_si_suma_cu_lipsa():
    # Tmax: 10, 20, NaN, 30 → media zilelor existente = 20 (np.nanmean). P: 1, NaN, 2 → suma = 3 (lipsa = 0).
    z = np.arange(np.datetime64("2020-01-01"), np.datetime64("2020-01-05"))
    egal(zc.i_medie({"max_temp": np.array([10, 20, NAN, 30.0])[:, None, None]}, z, var="max_temp"), [[20]], msg="media")
    z3 = z[:3]
    # v1.1: suma se corectează pentru ziua lipsă: (1 + 2) × 3/2 = 4,5 (înainte: 3, lipsa intra ca 0 mm)
    egal(zc.i_suma({"precipitation": np.array([1, NAN, 2.0])[:, None, None]}, z3, var="precipitation"), [[4.5]], msg="suma")


def test_sezon_fara_inghet_borne_si_lipsa():
    z = zile_an(2021)                                     # 365 zile
    T = np.full((365, 1, 3), 5.0)
    T[99, 0, 0] = -1; T[200, 0, 0] = -1                  # îngheț în ziua 100 și 201 → 100 zile strict între ele
    T[150, 0, 1] = NAN; T[99, 0, 1] = -1; T[200, 0, 1] = -1   # aceeași, dar o zi LIPSĂ între borne → necunoscut (E.5)
    T[10, 0, 2] = NAN                                     # fără niciun îngheț; ziua lipsă e ÎNAINTE: tot an cald? → necunoscut
    egal(zc.i_sezon_fara_inghet({"min_temp": T}, z), [[100, NAN, NAN]], msg="sezon fără îngheț")


def test_sezon_fara_inghet_an_fara_inghet():
    z = zile_an(2020)                                     # an bisect, fără niciun îngheț → 366 zile (cenzurare la capete)
    egal(zc.i_sezon_fara_inghet({"min_temp": np.full((366, 1, 1), 5.0)}, z), [[366]], msg="an fără îngheț")


def test_de_martonne_munte():
    # T medie −12 °C (≤ −10): indicele nu are sens → NaN, nu „arid”
    z = np.arange(np.datetime64("2021-01-01"), np.datetime64("2021-01-11"))
    d = {"precipitation": np.full((10, 1, 1), 2.0), "max_temp": np.full((10, 1, 1), -10.0), "min_temp": np.full((10, 1, 1), -14.0)}
    egal(zc.i_de_martonne(d, z), [[NAN]], msg="De Martonne la T ≤ −10")


def test_rxnday_fereastra_prea_lunga():
    z = np.arange(np.datetime64("2021-01-01"), np.datetime64("2021-01-04"))   # 3 zile, fereastră de 5 → NaN (E.6)
    egal(zc.i_rxnday({"precipitation": np.ones((3, 1, 1))}, z, n=5), [[NAN]], msg="Rx5day pe 3 zile")
    egal(zc.i_rxnday({"precipitation": np.array([1, 4, 2.0])[:, None, None]}, z, n=2), [[6]], msg="Rx2day")


def test_cdd_ruptura_la_lipsa():
    # P: 0 0 NaN 0 0 0 5 → șirurile uscate: 2, apoi 3 (ziua lipsă rupe șirul) → CDD = 3
    z = np.arange(np.datetime64("2021-07-01"), np.datetime64("2021-07-08"))
    egal(zc.i_cdd({"precipitation": np.array([0, 0, NAN, 0, 0, 0, 5.0])[:, None, None]}, z), [[3]], msg="CDD")


def test_cwd_sdii_prcptot():
    # P: 3, 0.5, 2, 4, NaN, 1, 1, 0 (mm), prag 1 mm
    #   zile ploioase (≥ 1): 3 | 2, 4 | 1, 1  → CWD = 2 (ziua lipsă rupe șirul „2, 4, NaN, 1, 1”)
    #   PRCPTOT = 3 + 2 + 4 + 1 + 1 = 11 (0,5 mm e o urmă, nu intră) · SDII = 11 / 5 = 2,2 mm/zi
    z = np.arange(np.datetime64("2021-05-01"), np.datetime64("2021-05-09"))
    d = {"precipitation": np.array([3, 0.5, 2, 4, NAN, 1, 1, 0])[:, None, None]}
    # v1.1: PRCPTOT se corectează pentru ziua lipsă ca toate sumele: 11 × 8/7 = 12,571 mm (SDII, un raport, nu)
    egal(zc.i_cwd(d, z), [[2]], msg="CWD"); egal(zc.i_prcptot(d, z), [[11 * 8 / 7]], tol=1e-4, msg="PRCPTOT")
    egal(zc.i_sdii(d, z), [[2.2]], tol=1e-5, msg="SDII")
    uscat = {"precipitation": np.array([0, 0.3, 0.2])[:, None, None]}       # nicio zi ploioasă: SDII nedefinit, nu 0
    egal(zc.i_sdii(uscat, z[:3]), [[NAN]], msg="SDII fără zile ploioase")


def test_sen_si_mann_kendall():
    import math
    ani = np.arange(2001, 2011)                                  # 10 ani
    # serie strict crescătoare cu 1/an → Sen = 10/deceniu; S = 45, var = 10·9·25/18 = 125, z = (45−1)/√125
    b, p = zc.sen_mk_deceniu(ani, np.arange(10.0)[:, None])
    egal(b, [10], msg="Sen, serie liniară"); egal(p, [math.erfc((44 / math.sqrt(125)) / math.sqrt(2))], tol=1e-9, msg="MK p")
    # un an excepțional (+100) nu mișcă panta Theil–Sen (OLS ar urca mult)
    y = np.arange(10.0); y[9] += 100
    b2, _ = zc.sen_mk_deceniu(ani, y[:, None]); egal(b2, [10], msg="Sen robust la un an extrem")
    # valori egale (perechi): 1,1,2,2,…,5,5 → S = 40, corecție 5·(2·1·9) = 90, var = (2250 − 90)/18 = 120
    y3 = np.repeat(np.arange(1.0, 6.0), 2)
    _, p3 = zc.sen_mk_deceniu(ani, y3[:, None])
    egal(p3, [math.erfc((39 / math.sqrt(120)) / math.sqrt(2))], tol=1e-9, msg="MK cu valori egale")


def test_sen_mk_fata_de_definitie():
    # 200 de serii aleatoare (valori întregi → multe egalități, plus ani lipsă), comparate cu o implementare
    # directă, pereche cu pereche, după definiție — independentă de varianta vectorizată din program.
    import math
    from collections import Counter
    rng = np.random.default_rng(7)
    ani = np.arange(1981, 2011)
    Y = rng.integers(0, 12, size=(30, 200)).astype(float) + np.linspace(0, 4, 30)[:, None].round()
    Y[rng.random(Y.shape) < 0.08] = NAN
    b, p = zc.sen_mk_deceniu(ani, Y)
    for k in range(200):
        x = ani[np.isfinite(Y[:, k])]; y = Y[np.isfinite(Y[:, k]), k]; n = len(y)
        pante = [(y[j] - y[i]) / (x[j] - x[i]) for i in range(n) for j in range(i + 1, n)]
        S = sum(np.sign(y[j] - y[i]) for i in range(n) for j in range(i + 1, n))
        t = [c for c in Counter(y).values() if c > 1]
        var = (n * (n - 1) * (2 * n + 5) - sum(c * (c - 1) * (2 * c + 5) for c in t)) / 18
        z = (S - np.sign(S)) / math.sqrt(var)
        egal(b[k], 10 * np.median(pante), tol=1e-4, msg=f"Sen, seria {k}")
        egal(p[k], math.erfc(abs(z) / math.sqrt(2)), tol=1e-6, msg=f"MK, seria {k}")


def test_p_student_din_tabele():
    # valori critice bilaterale din tabelele Student (orice manual de statistică): t(0,975; df) → p = 0,05
    for t, df, ref in [(12.706205, 1, 0.05), (2.228139, 10, 0.05), (3.169273, 10, 0.01), (2.0, 10, 0.0733880),
                       (2.000298, 60, 0.05), (1.959964, 1e7, 0.05), (0.0, 7, 1.0)]:
        egal(float(zc.p_student(t, df)), ref, tol=2e-6, msg=f"p Student t={t}, df={df}")


def test_ols_p_student_pe_serie_scurta():
    # 12 ani, y = an + zgomot fix: panta și t calculate de mână; p vine din Student cu 10 g.l., NU din normală
    ani = np.arange(2001, 2013); y = (ani - 2001) * 0.1 + np.array([0.3, -0.2, 0.5, -0.4, 0.1, -0.3, 0.4, 0.0, -0.5, 0.2, -0.1, 0.3])
    x = ani - ani.mean(); b = (x * (y - y.mean())).sum() / (x * x).sum()
    se = math.sqrt(((y - y.mean() - b * x) ** 2).sum() / 10 / (x * x).sum())
    bd, pd = zc.panta_deceniu(ani, y[:, None, None])
    egal(bd[0, 0], 10 * b, tol=1e-5, msg="panta OLS/deceniu")
    egal(pd[0, 0], float(zc.p_student(b / se, 10)), tol=1e-6, msg="p OLS = Student, 10 g.l.")
    assert pd[0, 0] > math.erfc(abs(b / se) / math.sqrt(2)), "p Student trebuie să fie mai mare decât aproximarea normală"


def test_sensibilitate_un_an():
    # seria e plată (0), cu un singur an extrem la final: fără el, tendința dispare → anul cel mai influent = 2020
    ani = list(range(2001, 2021)); y = np.zeros(20); y[-1] = 10.0
    rand, rez = zc.sensibilitate_un_an(ani, y, (2011, 2020))
    assert rez["an_tendinta"]["an"] == 2020, rez["an_tendinta"]
    egal(rez["an_tendinta"]["tendinta_fara"], 0.0, msg="tendința fără anul extrem")
    egal(rez["medie"], 1.0, msg="media 2011–2020"); egal(rez["an_medie"]["medie_fara"], 0.0, msg="media fără 2020")
    assert rez["marime_schimbata"], "fără 2020 panta ajunge la 0: mărimea atârnă de un singur an"
    _, rez2 = zc.sensibilitate_un_an(ani, np.arange(20.0), (2011, 2020))      # trend liniar perfect: robust
    assert not rez2["marime_schimbata"] and not rez2["semn_schimbat"]


# ------------------------------------------------------------------ v5.0 B: percentile, SPI, SPEI, PET
def test_cuantila_tip8():
    # 1…10, q = 0,9: h = (10 + 1/3)·0,9 + 1/3 = 9,6333 → x9 + 0,6333·(x10 − x9) = 9,6333 (de mână)
    egal(zc.cuantila_t8(np.arange(1.0, 11.0), 0.9), 9.0 + (10 + 1 / 3) * 0.9 + 1 / 3 - 9.0, tol=1e-12, msg="tip 8 pe 1…10")
    rng = np.random.default_rng(3); X = rng.normal(size=(150, 40)); X[rng.random(X.shape) < 0.1] = NAN
    ref = [np.percentile(c[np.isfinite(c)], 10, method="median_unbiased") for c in X.T]
    egal(zc.cuantila_t8(X, 0.1), ref, tol=1e-10, msg="tip 8 = numpy median_unbiased, cu NaN")


def test_zi_365_si_29_februarie():
    z = np.array(["2023-01-01", "2024-02-28", "2024-02-29", "2024-03-01", "2023-03-01", "2024-12-31"], dtype="datetime64[D]")
    egal(zc.zi_365(z), [0, 58, 58, 59, 59, 364], msg="29 februarie ia pragul lui 28; 1 martie = 59 în orice an")


def test_praguri_zilnice_fereastra_5():
    # 3 ani de bază (2003–2005, cu 2004 bisect); valoarea zilei = indicele anului (0, 1, 2) → fereastra are 5 × {0, 1, 2}.
    # 15 valori: p90 → h = 14,13 → 2; p50 → h = 8 → 1. Ziua 0 a primului an pierde 2 vecini (fereastră trunchiată).
    zile = np.arange(np.datetime64("2003-01-01"), np.datetime64("2006-01-01"))
    X = (zile.astype("datetime64[Y]").astype(int) - 33).astype(float)[:, None]
    p90 = zc.praguri_zilnice(X, zile, 0.9); p50 = zc.praguri_zilnice(X, zile, 0.5)
    assert p90.shape == (365, 1)
    egal(p90[100, 0], 2.0, msg="p90 interior"); egal(p50[100, 0], 1.0, msg="p50 interior"); egal(p50[0, 0], 1.0, msg="p50 la margine")


def test_tx90p_si_wsdi_pe_serie():
    # prag constant 30 °C; 18 zile: 6 calde, 1 rece, 2 calde, 1 lipsă, 7 calde, 1 rece
    t = np.array([31] * 6 + [29] + [31] * 2 + [NAN] + [31] * 7 + [25], float)[:, None, None]
    zile = np.arange(np.datetime64("2024-07-01"), np.datetime64("2024-07-19"))
    ctx = {"prag": np.full((365, 1, 1), 30.0, "float32")}
    egal(zc.i_pct_zile({"max_temp": t}, zile, "tx90p", 1991, 2020, _ctx=ctx), [[100 * 15 / 17]], msg="TX90p = 15 din 17 zile cu date")
    egal(zc.i_wsdi({"max_temp": t}, zile, 6, 1991, 2020, _ctx=ctx), [[13]], msg="WSDI = 6 + 7 (șirul de 2 nu contează; lipsa rupe)")
    egal(zc.i_wsdi({"max_temp": t}, zile, 2, 1991, 2020, _ctx=ctx), [[15]], msg="WSDI cu durata 2")


def test_r95p_si_r95ptot():
    p = np.array([0, 0.5, 1, 5, 12, 20, NAN], float)[:, None, None]; ctx = {"prag": np.array([[10.0]])}
    egal(zc.i_rnnp({"precipitation": p}, None, "95", 1991, 2020, _ctx=ctx), [[32.0]], msg="R95p = 12 + 20")
    egal(zc.i_rnnptot({"precipitation": p}, None, "95", 1991, 2020, _ctx=ctx), [[100 * 32 / 38]], msg="R95pTOT = 32 / (1+5+12+20)")
    egal(zc.i_rnnptot({"precipitation": np.full((5, 1, 1), 0.5)}, None, "95", 1991, 2020, _ctx=ctx), [[NAN]], msg="fără zile ≥ 1 mm → NaN")


def test_gamma_incompleta_si_normala_inversa():
    x = np.array([0.1, 1.0, 3.0, 12.0])
    egal(zc.gamma_inc(1.0, x), 1 - np.exp(-x), tol=1e-12, msg="P(1, x) = 1 − e^−x")
    egal(zc.gamma_inc(2.0, x), 1 - np.exp(-x) * (1 + x), tol=1e-12, msg="P(2, x) = 1 − e^−x (1 + x)")
    egal(zc.gamma_inc(0.5, 0.3), math.erf(math.sqrt(0.3)), tol=1e-12, msg="P(1/2, x) = erf(√x)")
    egal(zc.normala_inversa(np.array([0.5, 0.975, 0.025, 0.2])), [0.0, 1.959963985, -1.959963985, -0.841621234], tol=1e-8,
         msg="Φ⁻¹ din tabele")


def test_spi_valori_de_mana():
    par = {"alfa": np.array(1.0), "beta": np.array(1.0), "q": np.array(0.0)}
    egal(zc.spi_din(math.log(2), par), 0.0, tol=1e-9, msg="mediana exponențialei (ln 2) → SPI 0")
    par["q"] = np.array(0.2)
    egal(zc.spi_din(0.0, par), -0.841621234, tol=1e-8, msg="total 0 cu q = 0,2 → Φ⁻¹(0,2)")
    rng = np.random.default_rng(5); par = zc.ajusteaza_gamma(rng.gamma(3.0, 50.0, size=(20000, 1)))
    egal(par["alfa"], [3.0], tol=0.1, msg="Thom: α"); egal(par["beta"], [50.0], tol=2.0, msg="Thom: β")
    X = rng.gamma(3.0, 50.0, size=(30, 3000)); s = zc.spi_din(X, zc.ajusteaza_gamma(X))
    assert abs(np.nanmean(s)) < 0.05 and abs(np.nanstd(s) - 1) < 0.06, (np.nanmean(s), np.nanstd(s))


def test_spei_logistica_generalizata():
    # eșantion „perfect” dintr-o logistică generalizată cunoscută → parametrii se refac
    F = (np.arange(1, 5001) - 0.5) / 5000; k, a, xi = -0.15, 40.0, -250.0
    x = xi + a / k * (1 - ((1 - F) / F) ** k)
    par = zc.ajusteaza_loglogistica(x[:, None])
    egal(par["k"], [k], tol=2e-3, msg="κ"); egal(par["alfa"], [a], tol=0.1, msg="α"); egal(par["xi"], [xi], tol=0.1, msg="ξ")
    # 30 de ani, log-logistică β = 8: SPEI în bază ≈ N(0, 1) (formula cu poziții de reprezentare dădea abaterea ~1,5)
    rng = np.random.default_rng(0); U = rng.random((30, 4000)); X = -400 + 100 * (U / (1 - U)) ** (1 / 8)
    s = zc.spei_din(X, zc.ajusteaza_loglogistica(X))
    assert abs(np.nanmean(s)) < 0.05 and abs(np.nanstd(s) - 1) < 0.05, (np.nanmean(s), np.nanstd(s))
    assert np.isnan(zc.ajusteaza_loglogistica(X)["k"]).mean() < 0.01


def test_radiatia_si_pet_hargreaves():
    egal(zc.radiatia_extraterestra(-20.0, 246), 32.2, tol=0.05, msg="FAO-56 exemplul 8: 20° S, 3 septembrie")
    zile = np.array(["2024-07-24"], dtype="datetime64[D]")
    pet = zc.pet_hargreaves(np.array([[[30.0]]]), np.array([[[18.0]]]), zile, np.array([44.4]))
    ra = float(zc.radiatia_extraterestra(44.4, 206))
    egal(pet, [[[0.0023 * 0.408 * ra * (24 + 17.8) * math.sqrt(12)]]], tol=1e-9, msg="PET Hargreaves, formula FAO-56 ec. 52")
    egal(zc.pet_hargreaves(np.array([[[20.0]]]), np.array([[[20.0]]]), zile, np.array([44.4])), [[[0.0]]], msg="amplitudine 0 → PET 0")


def test_baza_scurta_refuzata():
    import indicatori as ri
    try:
        ri.construieste("spi", baza_de=2015, baza_pana=2020)
    except ValueError:
        return
    raise AssertionError("o bază de 6 ani trebuia refuzată")


# ------------------------------------------------------------------ v5.1: memorie
def test_calcul_pe_benzi_identic():
    # 150 de rânduri (> BANDA = 64): rezultatul pe benzi = calculul dintr-o bucată, inclusiv cu praguri tăiate pe bandă
    import indicatori as ri
    rng = np.random.default_rng(7); t, ny, nx = 60, 150, 7
    zile = np.arange(np.datetime64("2021-07-01"), np.datetime64("2021-07-01") + t)
    d = {"max_temp": rng.normal(30, 4, (t, ny, nx)).astype("float32"),
         "min_temp": rng.normal(18, 3, (t, ny, nx)).astype("float32"),
         "precipitation": (rng.gamma(0.5, 6, (t, ny, nx)) * (rng.random((t, ny, nx)) < 0.3)).astype("float32")}
    d["max_temp"][rng.random((t, ny, nx)) < 0.05] = NAN
    cazuri = [("zile_peste", dict(var="max_temp", prag=30.0)), ("rxnday", dict(n=5)), ("cdd", {}),
              ("pct_zile", dict(indice="tx90p")), ("bilant", {})]
    for cod, kw in cazuri:
        ind = ri.construieste(cod, **kw)
        if ind.pregatire is not None:
            ind.ctx = {"prag": rng.normal(31, 1, (365, ny, nx)).astype("float32"), "lat": np.linspace(48, 44, ny)}
        dd = {v: d[v] for v in ind.variabile}
        intreg = ind._calc(dd, zile, ind.ctx)
        egal(ind.calculeaza(dd, zile), intreg, tol=1e-5, msg=f"{cod}: pe benzi = dintr-o bucată")


def test_perioada_relativa():
    import motoare as mo
    import ruleaza as rl
    p = {"PERIOADA": ["-30", None]}
    zc_desch = zc.deschide
    zc.deschide = lambda *a, **k: (None, {"max_temp": np.datetime64("2026-11-18"), "precipitation": np.datetime64("2026-11-20")})
    try:
        rl._date_relative(p, mo.MOTOARE["episod_zilnic"])
    finally:
        zc.deschide = zc_desch
    assert p["PERIOADA"] == ["2026-10-20", "2026-11-18"], p          # 30 de zile până la frontiera comună


# ------------------------------------------------------------------ v5.1: superlative
def test_superlative_candidati_de_mana():
    import zarr_superlative as zs
    zile = np.arange(np.datetime64("2023-01-01"), np.datetime64("2025-01-01"))
    P = np.zeros(len(zile)); i = lambda d: int((np.datetime64(d) - zile[0]).astype(int))   # noqa: E731
    P[i("2023-05-10")] = 20; P[i("2023-05-11")] = 30; P[i("2023-05-12")] = 25        # mai 2023: 75 mm
    P[i("2024-05-03")] = 40                                                           # mai 2024: 40 mm
    P[i("2024-12-31")] = 12                                                           # fereastra 30 dec – 1 ian iese din date
    D = P[:, None]
    ini, fr = zile[0], zile[-1]
    v23, iv = zs.candidati(D, zile, zs.intervale_an(2023, "luna", luna=5), "suma", ini, fr, "luna")
    egal(v23[:, 0], [75.0], msg="suma lunii mai 2023")
    v, iv = zs.candidati(D, zile, zs.intervale_an(2023, "fereastra", n=3), "suma", ini, fr, "fereastra")
    k = int(np.nanargmax(v[:, 0])); egal(v[k, 0], 75.0, msg="cele mai ploioase 3 zile")
    assert str(iv[k][0]) == "2023-05-10", iv[k]
    v24, iv24 = zs.candidati(D, zile, zs.intervale_an(2024, "fereastra", n=3), "suma", ini, fr, "fereastra")
    assert str(iv24[-1][1]) <= "2024-12-31", "ferestrele care ies din date se exclud"
    D2 = D.copy(); D2[i("2023-05-01"):i("2023-05-05")] = NAN                           # 4 zile lipsă din 31 → 87 % < 90 %
    vv, _ = zs.candidati(D2, zile, zs.intervale_an(2023, "luna", luna=5), "suma", ini, fr, "luna")
    assert np.isnan(vv[0, 0]), "luna cu sub 90 % zile valide e invalidă"
    T = np.arange(len(zile), dtype=float)[:, None]
    vm, _ = zs.candidati(T, zile, zs.intervale_an(2023, "luna", luna=2), "medie", ini, fr, "luna")
    egal(vm[0, 0], (31 + 58) / 2, msg="media lui februarie (zilele 31…58)")


def test_superlative_clasament_si_texte():
    import zarr_superlative as zs
    d = lambda s: np.datetime64(s)                                                      # noqa: E731
    iv = [(d("2024-07-24"), d("2024-07-26")), (d("2024-07-25"), d("2024-07-27")), (d("2021-08-01"), d("2021-08-03"))]
    lista = zs.clasament_zona([50.0, 52.0, 40.0], iv, "max", 3, "fereastra")
    assert [round(x[1]) for x in lista] == [52, 40], "ferestrele suprapuse = același episod: rămâne doar cea mai bună"
    lista = zs.clasament_zona([5.0, 3.0, 4.0], iv[:1] * 3, "min", 2, "zi")
    assert [x[1] for x in lista] == [3.0, 4.0]
    a, b = zs.intervale_an(2026, "interval", interval=["12-15", "01-15"])[0]
    assert (str(a), str(b)) == ("2025-12-15", "2026-01-15")
    assert zs.an_candidat(a, b, "interval") == 2026 and zs.an_candidat(d("2025-12-30"), d("2026-01-01"), "fereastra") == 2025
    assert zs.titlu_superlativ("max_temp", "max", "sezon", sezon="JJA") == "Cea mai caldă vară (după Tmax)"
    assert zs.titlu_superlativ("precipitation", "max", "fereastra", n=3) == "Cele mai ploioase 3 zile consecutive"
    assert zs.titlu_superlativ("precipitation", "min", "luna", luna=5) == "Cea mai secetoasă lună mai"
    assert zs.eticheta(d("2024-07-30"), d("2024-08-01"), "fereastra") == "30 iulie – 1 august 2024"
    assert zs.eticheta(d("2024-06-01"), d("2024-08-31"), "sezon", "JJA") == "vara 2024"
    try:
        zs.valideaza("precipitation", "min", "zi")
    except ValueError:
        return
    raise AssertionError("ziua cu cele mai puține precipitații trebuia refuzată")


# ------------------------------------------------------------------ zone, măști, paleta
def test_masca_fara_poligoane():
    # Zona „țară” cu filtru de altitudine: masca [1, 0] → totalul folosește DOAR primul pixel (C.1)
    z = zc.Zona.tara(); z._id = np.array([[1, 0]], "int32")
    g = zc.Grila(0, 1, 0, 2, np.array([20.135, 20.145]), np.array([48.355]))
    et, cols, tot = zc._coloane_zone(z, g)
    egal(tot, [0], msg="coloanele totalului cu mască")


def test_paleta_dupa_sens():
    # De Martonne mai mare = mai umed (BrBG); mai multe zile cu P < 1 mm = mai uscat (BrBG_r) (D.5)
    assert zc._cmap_anomalie(zc.indicator("de_martonne")) == "BrBG"
    assert zc._cmap_anomalie(zc.indicator("zile_sub", var="precipitation", prag=1.0, strict=True)) == "BrBG_r"
    assert zc._cmap_anomalie(zc.indicator("zile_peste", var="max_temp", prag=30.0)) == "RdBu_r"
    assert zc._cmap_anomalie(zc.indicator("zile_sub", var="min_temp", prag=0.0, strict=True)) == "RdBu"


def test_validitate_per_indicator():
    # Tmax complet, P cu 50 % zile lipsă: media Tmax NU trebuie să devină NoData din cauza lui P (E.5).
    # Reproducem regula din harti_anuale: validitatea pe variabilele FIECĂRUI indicator.
    ind_t = zc.indicator("medie", var="max_temp"); ind_p = zc.indicator("suma", var="precipitation")
    d = {"max_temp": np.full((10, 1, 1), 20.0), "precipitation": np.where(np.arange(10) % 2 == 0, 1.0, NAN)[:, None, None]}
    rez = {}
    for ind in (ind_t, ind_p):
        valid = np.logical_and.reduce([np.isfinite(d[v]) for v in ind.variabile]); nr = valid.sum(axis=0)
        rez[ind.cod] = np.where((nr > 0) & (nr >= 0.9 * 10), ind.calculeaza(d, np.arange(10)), np.nan)
    egal(rez[ind_t.cod], [[20]], msg="Tmax valid"); egal(rez[ind_p.cod], [[NAN]], msg="P sub prag")


def test_media_zonei_dupa_indicatorul_pixelului():
    # D.1: pixelul A are 10 zile la 0 °C; pixelul B are 8 zile la 20 °C și 2 lipsă (sub PRAG_VALID 0,9 → NoData).
    # Corect (întâi pixelul, apoi zona): media zonei = 0 °C. Media zilnică a zonei ar da (8·10 + 2·0)/10 = 8 °C.
    A = np.zeros(10); B = np.r_[np.full(8, 20.0), NAN, NAN]
    pix = []
    for s in (A, B):
        nr = np.isfinite(s).sum()
        pix.append(np.nanmean(s) if nr >= 0.9 * 10 else np.nan)
    egal(np.nanmean(pix), 0.0, msg="media zonei")


# ------------------------------------------------------------------ episod: rang, Gumbel
def test_top_fara_plafon():
    # 700 de evenimente distincte peste prag trebuie numărate toate (E.2; înainte se opreau la 600)
    import zarr_episod as ze
    n = 700 * 5
    s = np.zeros(n); s[::5] = 10.0
    zile = np.arange(np.datetime64("1900-01-01"), np.datetime64("1900-01-01") + n)
    assert len(ze._top_declusterizat(s, zile, 1, True, prag=5.0)) == 700


def test_gumbel_coada_si_scara_nula():
    import zarr_episod as ze
    assert ze._gumbel(np.full(20, 3.0)) is None                       # scara nulă → fără ajustare
    egal(ze._perioada_revenire(-100, 0.0, 1.0), 1.0, msg="T la valori mici")
    T = ze._perioada_revenire(ze._nivel_revenire(50, 0.0, 1.0), 0.0, 1.0)
    egal(T, 50, tol=1e-6, msg="T(nivelul de 50 de ani)")


# ------------------------------------------------------------------ exportul Python (E.1)
def test_export_titlu_periculos():
    import motoare as mo
    titlu = 'Test"""\nimport os; os.system("echo atac")\n"""'
    job = {"titlu": titlu, "motor": "harta", "_radacina": str(RAD)}
    cod = "\n".join(mo._antet_py(job, {}) if isinstance(mo._antet_py(job, {}), list) else [mo._antet_py(job, {})])
    arbore = ast.parse(cod)
    apeluri = [n for n in ast.walk(arbore) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "system"]
    assert not apeluri, "titlul a devenit cod executabil"
    z = mo._py_zona({"tip": "dreptunghi", "lon_min": "25", "lat_min": "45", "lon_max": "26", "lat_max": "46"})
    assert z == "zc.Zona.dreptunghi(25.0, 45.0, 26.0, 46.0)", z


# ------------------------------------------------------------------ integritatea datelor (goluri în cub)
def test_bloc_zero_si_chunk_lipsa():
    from types import SimpleNamespace
    b = np.random.default_rng(1).normal(5, 3, (4, 10, 10)).astype("float32")
    b[2] = 0.0                                        # zi nescrisă: tot blocul exact 0
    b[3, :5] = 0.0                                    # zi reală cu câțiva pixeli la 0: NU e suspectă
    assert list(zc.zile_bloc_zero(b)) == [False, False, True, False], "zile-bloc zero"
    mic = np.zeros((1, 5, 5), "float32")              # sub MIN_PIXELI_BLOC: nu se decide nimic
    assert not zc.zile_bloc_zero(mic)[0]
    # citirea: chunk lipsă → NaN, bloc la zero → NaN, blocul vecin rămâne neatins
    vechi = (set(zc.CHUNKURI_LIPSA), dict(zc._CORECTII))
    try:
        zc.CHUNKURI_LIPSA.clear(); zc.CHUNKURI_LIPSA.add(("max_temp", 7, 0, 0))
        g = SimpleNamespace(iy0=0, iy1=20, ix0=0, ix1=20)
        arr = np.full((3, 20, 20), 4.0, "float32"); arr[1, :, 10:] = 0.0
        zile = np.arange("2026-01-01", "2026-01-04", dtype="datetime64[D]")
        zc._corecteaza_bucata(None, "max_temp", arr, zile, 7, g, (90, 10, 10))
        assert np.isnan(arr[:, :10, :10]).all(), "chunk-ul lipsă trebuie să devină NaN"
        assert np.isnan(arr[1, 10:, 10:]).all() and np.isnan(arr[1, :10, 10:]).all(), "blocurile la 0 → NaN"
        assert (arr[[0, 2], 10:, :] == 4).all(), "zilele bune nu se ating"
        assert zc.raport_corectii() is not None
    finally:
        zc.CHUNKURI_LIPSA.clear(); zc.CHUNKURI_LIPSA.update(vechi[0]); zc._CORECTII.update(vechi[1])


# ------------------------------------------------------------------ regresii din auditul Gemini (v1.1.0)
def test_suma_corectata_pentru_zilele_lipsa():
    # 10 zile, una lipsă, 2 mm/zi: suma corectă e 20 mm (9 × 2 × 10/9), nu 18 (lipsa ca 0)
    a = np.full((10, 1, 1), 2.0); a[3] = NAN
    egal(float(zc._suma_corectata(a)[0, 0]), 20.0, 1e-5, "suma × n/n_valide")
    egal(float(zc.i_suma({"precipitation": a}, None, "precipitation")[0, 0]), 20.0, 1e-5, "i_suma")
    assert np.isnan(zc._suma_corectata(np.full((5, 1, 1), NAN))[0, 0]), "fără nicio zi validă → NaN"
    # SPEI și SPI pe același gol trebuie să se miște în aceeași direcție: bilanțul nu mai câștigă „+PET” pe zilele lipsă
    P = np.full((10, 1, 1), 1.0); P[2] = NAN
    D = P - 3.0                                        # P − PET = −2 mm/zi
    egal(float(zc._suma_corectata(D)[0, 0]), -20.0, 1e-5, "bilanțul cu o zi lipsă")


def test_trend_serie_constanta_p_unu():
    ani = np.arange(1991, 2021)
    st = np.zeros((30, 1, 2), "float32"); st[:, 0, 1] = 0.3 * (ani - 1991)      # pixel 0: constant; pixel 1: perfect liniar
    b, p = zc.panta_deceniu(ani, st)
    egal(float(b[0, 0]), 0.0, 1e-6, "panta constantă"); egal(float(p[0, 0]), 1.0, 1e-9, "p = 1 pentru serie constantă")
    egal(float(b[0, 1]), 3.0, 1e-4, "panta liniară /deceniu"); egal(float(p[0, 1]), 0.0, 1e-9, "p = 0 pentru serie perfect liniară")
    _, pm = zc.sen_mk_deceniu(ani, np.zeros((30, 1, 1), "float32"))
    egal(float(pm[0, 0]), 1.0, 1e-9, "Mann–Kendall: p = 1 pentru serie constantă")
    egal(zc._panta(list(ani), [5.0] * 30, "ols")[1], 1.0, 1e-9, "_panta pe zonă, serie constantă")


def test_punct_in_afara_grilei():
    from types import SimpleNamespace
    cub = SimpleNamespace(x=SimpleNamespace(values=np.arange(20.135, 29.86, 0.01)),
                          y=SimpleNamespace(values=np.arange(48.355, 43.53, -0.01)))
    g = zc.grila_zonei(cub, zc.Zona.punct(26.10, 44.43, "București"))
    assert g.ix1 - g.ix0 == 1 and abs(float(g.x[0]) - 26.10) <= 0.0051
    try:
        zc.grila_zonei(cub, zc.Zona.punct(44.43, 26.10, "inversat")); raise AssertionError("trebuia să refuze")
    except ValueError as e:
        assert "inversate" in str(e), e


def test_ani_contigui_pentru_dungi():
    x, y = zc.ani_contigui([2000, 2001, 2003], [1.0, 2.0, 4.0])
    assert list(x) == [2000, 2001, 2002, 2003] and np.isnan(y[2]) and y[3] == 4.0
    x, A = zc.ani_contigui([1, 3], np.array([[1.0, 3.0], [5.0, 7.0]]))   # pe zone: ultima axă e anul
    assert A.shape == (2, 3) and np.isnan(A[:, 1]).all()


def test_bloc_zero_pe_un_singur_pixel():
    # un punct (1 pixel) dintr-un bloc nescris: fereastra are sub 50 de pixeli, deci se judecă blocul întreg
    import xarray as xr
    from types import SimpleNamespace
    zile = np.arange("2026-01-01", "2026-03-31", dtype="datetime64[D]")              # 89 de zile, un chunk
    t = np.random.default_rng(3).normal(5, 2, (len(zile), 10, 10)).astype("float32")
    t[40] = 0.0                                                                         # ziua 41: bloc nescris
    cub = xr.Dataset({"max_temp": (("time", "y", "x"), t)}, coords={"time": zile})
    vechi = (dict(zc.FRONTIERE_ULTIME or {}), dict(zc._MASCA_RECENTA), set(zc.CHUNKURI_LIPSA), dict(zc._CORECTII))
    try:
        zc.FRONTIERE_ULTIME = {"max_temp": zile[-1]}; zc._MASCA_RECENTA.clear(); zc.CHUNKURI_LIPSA.clear()
        arr = t[:, 3:4, 3:4].copy()
        zc._corecteaza_bucata(cub, "max_temp", arr, zile, 0, SimpleNamespace(iy0=3, iy1=4, ix0=3, ix1=4), (90, 10, 10))
        assert np.isnan(arr[40, 0, 0]), "ziua nescrisă trebuie să devină NaN și pe un singur pixel"
        assert np.isfinite(arr[np.arange(len(zile)) != 40]).all(), "celelalte zile rămân"
    finally:
        zc.FRONTIERE_ULTIME = vechi[0]; zc._MASCA_RECENTA.clear(); zc._MASCA_RECENTA.update(vechi[1])
        zc.CHUNKURI_LIPSA.clear(); zc.CHUNKURI_LIPSA.update(vechi[2]); zc._CORECTII.update(vechi[3])


def test_reperele_de_an():
    import importlib
    ruleaza = importlib.import_module("ruleaza")
    f = lambda r, d: ruleaza.an_reper(r, np.datetime64(d))
    assert f("ultimul_an", "2026-11-25") == 2025 and f("ultimul_an", "2026-12-31") == 2026
    assert f("ultima_vara", "2026-08-30") == 2025 and f("ultima_vara", "2026-09-01") == 2026
    assert f("ultima_iarna", "2026-02-27") == 2025 and f("ultima_iarna", "2026-03-01") == 2026


# ------------------------------------------------------------------ v1.1 etapa 2: stilul QGIS și „Date și metode”
def test_qml_aceleasi_culori_ca_png():
    import tempfile
    import xml.etree.ElementTree as ET
    import matplotlib
    from matplotlib.colors import BoundaryNorm
    h = np.linspace(5, 40, 400).reshape(20, 20)
    with tempfile.TemporaryDirectory() as d:
        q = zc.scrie_qml(Path(d) / "x.tif", h, "BrBG", clase=[10, 20, 24, 28, 35])
        it = ET.parse(q).getroot().findall(".//colorrampshader/item")
        assert [i.get("value") for i in it] == ["10", "20", "24", "28", "35", "inf"], "limitele claselor"
        cm = matplotlib.colormaps["BrBG"]; nrm = BoundaryNorm([10, 20, 24, 28, 35], cm.N, extend="both")
        png = "#{:02x}{:02x}{:02x}".format(*(int(round(255 * x)) for x in cm(nrm(22))[:3]))
        assert it[2].get("color") == png, "clasa 20–24 are culoarea din PNG"
        assert it[2].get("label") == "20 – 24"
        q = zc.scrie_qml(Path(d) / "y.tif", h - 22, "RdBu_r", divergent=True)            # divergent: centrat pe 0
        it = ET.parse(q).getroot().findall(".//colorrampshader/item")
        egal(float(it[5].get("value")), 0.0, 1e-9, "mijlocul rampei divergente"); egal(float(it[0].get("value")), -float(it[-1].get("value")), 1e-6)


def test_metode_text():
    import metode_text as mt
    f = {"motor": "trend", "titlu": "Tendința (+2)", "reteta_titlu": "Viteza de încălzire", "pornit": "2026-11-27T10:00",
         "frontiera_datelor": {"max_temp": "2026-11-18"},
         "parametri": {"INDICATORI": [{"cod": "medie", "var": "max_temp"}], "ANI": [1961, 2025], "SEZON": "JJA",
                       "METODA_TREND": "sen_mk", "ALFA": 0.05, "ZONA": {"tip": "tara"}, "_setari": {"PRAG_VALID": 0.9}}}
    m = mt.compune(f, "1.1.0")
    assert "„Viteza de încălzire”" in m["ro"] and "(+2)" not in m["ro"], "titlul fără „(+2)”"
    assert "1961–2025" in m["ro"] and "vara (iunie–august)" in m["ro"] and "α = 0,05" in m["ro"]
    assert any(r.startswith("Sen, P. K.") for r in m["referinte"]) and any(r.startswith("Mann, H. B.") for r in m["referinte"])
    assert any("10.5281/zenodo.24564871" in r and "1.1.0" in r for r in m["referinte"]), "citarea programului, cu versiunea"
    assert mt.compune({"motor": "integritate"}) is None


def test_cale_de_pe_alt_calculator():
    # o fișă de reproducere primită de la altcineva: calea absolută nu există aici → date/<nume>, dacă există
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "date").mkdir(); (Path(d) / "date" / "judete.gpkg").write_bytes(b"x")
        r = zc._cale(r"C:\Users\prof\Documente\judete.gpkg", d)
        assert r == (Path(d) / "date" / "judete.gpkg").resolve(), r
        assert zc._cale("date/judete.gpkg", d) == (Path(d) / "date" / "judete.gpkg").resolve()
        lipsa = zc._cale(r"C:\Users\prof\altceva.gpkg", d)              # nici în date/: rămâne calea dată (eroare clară)
        assert lipsa.name.endswith("altceva.gpkg")
        assert zc._cale("rezultate/x", d) == (Path(d) / "rezultate" / "x").resolve(), "folderele de ieșire nu se ating"


# ------------------------------------------------------------------ v1.1 etapa 4: climatograma Walter–Lieth
def test_climatograma_luni_aride_si_inghet():
    import zarr_climatograma as zcg
    # doi ani sintetici, o zonă: Tmax = 10 + 15·sin, Tmin = Tmax − 10; P = 1 mm/zi, iar în iulie 0,2 mm/zi (aridă)
    S = {"max_temp": {}, "min_temp": {}, "precipitation": {}}
    for an in (2001, 2002):
        z = np.arange(f"{an}-01-01", f"{an + 1}-01-01", dtype="datetime64[D]")
        doy = (z - z[0]).astype(int)
        tx = 10 + 15 * np.sin(2 * np.pi * (doy - 105) / 365)
        luna = z.astype("datetime64[M]").astype(int) % 12 + 1
        p = np.where(luna == 7, 0.2, 1.0)
        S["max_temp"][an] = tx[None].astype("float32"); S["min_temp"][an] = (tx - 10)[None].astype("float32")
        S["precipitation"][an] = p[None].astype("float32")
    st = zcg.statistici_perioada(S, [2001, 2002], np.datetime64("2030-01-01"), k=0)
    egal(st["P"][6], 0.2 * 31, 1e-4, "P iulie = 6,2 mm"); egal(st["P"][0], 31.0, 1e-4, "P ianuarie = 31 mm")
    egal(st["T"][6], st["Tmax"][6] - 5, 1e-5, "T = (Tmax + Tmin)/2")
    assert st["luni_aride"] == ["iul"] or "iul" in st["luni_aride"], st["luni_aride"]    # 6,2 mm < 2 × ~20 °C
    assert "ian" in st["luni_inghet"] and "iul" not in st["luni_inghet"], st["luni_inghet"]
    egal(zcg._y_p([40, 100, 300]), [20, 50, 60], 1e-9, "scara P: P/2 până la 100 mm, apoi 1:10")
    assert st["n_ani"] == 2 and np.isfinite(st["P_an"])


def test_fdr_benjamini_hochberg():
    # exemplul clasic: p = [0,01; 0,04; 0,03; 0,005], m = 4 → q = [0,02; 0,04; 0,04; 0,02]
    egal(zc.fdr_bh([0.01, 0.04, 0.03, 0.005]), [0.02, 0.04, 0.04, 0.02], 1e-12, "q Benjamini–Hochberg")
    q = zc.fdr_bh(np.array([[0.2, np.nan], [0.9, 0.001]]))
    assert np.isnan(q[0, 1]) and q.shape == (2, 2) and (q[np.isfinite(q)] <= 1).all()
    egal(float(q[1, 1]), 0.003, 1e-12, "cel mai mic p × m / 1")
    # sub ipoteza nulă (p uniforme), după corecție aproape nimic nu mai e semnificativ
    u = np.random.default_rng(7).uniform(size=20000)
    assert (u < 0.05).mean() > 0.04 and (zc.fdr_bh(u) < 0.05).mean() < 0.001


# ------------------------------------------------------------------
def main():
    teste = [(k, f) for k, f in sorted(globals().items()) if k.startswith("test_") and callable(f)]
    esuate = 0
    for k, f in teste:
        try:
            f(); print(f"OK    {k}")
        except Exception:  # noqa: BLE001
            esuate += 1; print(f"EȘUAT {k}"); traceback.print_exc(limit=2)
    print(f"\n{len(teste) - esuate}/{len(teste)} teste cu răspuns cunoscut trecute")
    return 1 if esuate else 0


if __name__ == "__main__":
    sys.exit(main())
