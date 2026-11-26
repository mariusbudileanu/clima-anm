"""Calibrează estimarea timpului de calcul din „Verifică”: măsoară, pe calculatorul curent,
  · costul fiecărui indicator (nanosecunde pe pixel × zi), pe date sintetice de un an × 128 × 972 pixeli;
  · costul citirii + decompresiei (secunde pe GB comprimat), pe cubul de test (un an de Tmax, toată țara).
Scrie clima/cost_indicatori.json (folosit de clima/estimare.py).

    instrumente/pixi run python instrumente/calibreaza_indicatori.py"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

RAD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAD / "clima"))
import indicatori as ri                                     # noqa: E402
import zarr_clima as zc                                     # noqa: E402

zc.log = lambda *a, **k: None                              # noqa: E731


def date_sintetice(ny=128, nx=972, an=2021):
    rng = np.random.default_rng(0)
    zile = np.arange(np.datetime64(f"{an}-01-01"), np.datetime64(f"{an + 1}-01-01"))
    t = np.arange(len(zile))[:, None, None]
    tmax = (15 + 12 * np.sin(2 * np.pi * (t - 110) / 365) + rng.normal(0, 4, (len(zile), ny, nx))).astype("float32")
    tmin = (tmax - 9 - rng.random((len(zile), ny, nx)) * 4).astype("float32")
    p = np.where(rng.random((len(zile), ny, nx)) < 0.3, rng.gamma(0.8, 8, (len(zile), ny, nx)), 0).astype("float32")
    return {"max_temp": tmax, "min_temp": tmin, "precipitation": p}, zile


def ctx_sintetic(ind, ny, nx):
    f = ind.functie
    if f in (zc.i_pct_zile, zc.i_wsdi, zc.i_csdi):
        return {"prag": np.full((365, ny, nx), 25.0, "float32")}
    if f in (zc.i_rnnp, zc.i_rnnptot):
        return {"prag": np.full((ny, nx), 15.0, "float32")}
    lat = np.linspace(48, 43.6, ny)
    if f is zc.i_spi:
        return {"lat": lat, "par": {"alfa": np.full((ny, nx), 3.0), "beta": np.full((ny, nx), 50.0), "q": np.zeros((ny, nx))}}
    if f is zc.i_spei:
        return {"lat": lat, "par": {"xi": np.full((ny, nx), -250.0), "alfa": np.full((ny, nx), 40.0), "k": np.full((ny, nx), -0.1)}}
    return {"lat": lat}


def main():
    d, zile = date_sintetice()
    nt, ny, nx = d["max_temp"].shape
    pixeli_zile = nt * ny * nx
    tabel = {}
    for cod in sorted(ri.REGISTRU):
        ind = ri.construieste(cod)
        if ind.pregatire is not None:
            ind.ctx = ctx_sintetic(ind, ny, nx)
        dd = {v: d[v] for v in ind.variabile}
        ind.calculeaza(dd, zile)                            # încălzire
        t0 = time.perf_counter(); ind.calculeaza(dd, zile); zc._numar_valide(dd, ind.variabile); s = time.perf_counter() - t0
        tabel[cod] = round(s / pixeli_zile * 1e9, 2)
        print(f"{cod:14s} {tabel[cod]:8.2f} ns / pixel-zi")
    # citirea + decompresia: un an de Tmax pe toată țara, din cubul de test (local, deci fără rețea)
    rez = {"ns_pixel_zi": tabel, "masurat_pe": f"{os.cpu_count()} nuclee", "data": time.strftime("%Y-%m-%d")}
    cub_test = RAD / ".pixi" / "cub_test.zarr"
    if cub_test.exists():
        cub, fr = zc.deschide(str(cub_test))
        g = zc.grila_zonei(cub, zc.Zona.tara())
        d0, d1 = np.datetime64("2021-01-01"), np.datetime64("2021-12-31")
        _, mb = zc.estimeaza_cost(cub, "max_temp", d0, d1, g)
        t0 = time.perf_counter(); zc.citeste(cub, ("max_temp",), d0, d1, g); s = time.perf_counter() - t0
        rez["citire_s_per_gb"] = round(s / (mb / 1000), 2)
        print(f"citire + decompresie: {rez['citire_s_per_gb']} s / GB comprimat")
    f = RAD / "clima" / "cost_indicatori.json"
    f.write_text(json.dumps(rez, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {f}")


if __name__ == "__main__":
    main()
