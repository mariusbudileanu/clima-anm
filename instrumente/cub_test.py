# -*- coding: utf-8 -*-
"""
cub_test.py — construiește un cub Zarr SINTETIC cu structura exactă a store-ului anm-daily-grids (EOCube.ro)
==========================================================================================================
Pentru teste fără internet (dezvoltare, verificarea rețetelor). Valorile sunt INVENTATE, nu date ANM.

  * aceeași grilă (483 × 972, 0,01°, y descrescător), aceleași chunk-uri [90, 161, 324], Blosc/LZ4, fill_value NaN;
  * timp: 2014-01-01 … 2026-12-31 („days since 2014-01-01”), frontiera last_*_time = 2026-11-18;
  * date doar în sectorul (2, 1) — sudul Munteniei, cu Bucureștiul — într-un dreptunghi; restul = chunk-uri lipsă (NaN);
  * zilele de după frontieră conțin 0,0 (ca în cubul real: capcana pre-alocării).

Utilizare:
    pixi run python instrumente/cub_test.py [folder]          (implicit: .pixi/cub_test.zarr)
    set ZARR_ANM_URL=<folder>   → toate analizele citesc cubul sintetic
"""
import sys
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc

DEST = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / ".pixi" / "cub_test.zarr")
T0, T1, FRONTIERA = np.datetime64("2014-01-01"), np.datetime64("2026-12-31"), np.datetime64("2026-11-18")
NT = int((T1 - T0).astype(int)) + 1
NY, NX, CH = 483, 972, (90, 161, 324)
Y0, Y1, X0, X1 = 340, 470, 500, 640          # dreptunghiul cu date (indici), în sectorul (2, 1)
x = np.round(20.135 + 0.01 * np.arange(NX), 3)
y = np.round(48.355 - 0.01 * np.arange(NY), 3)
zile = T0 + np.arange(NT)
i_fr = int((FRONTIERA - T0).astype(int))
rng = np.random.default_rng(42)


def camp_neted(n, ny, nx, scala=0.6):
    """Anomalii zilnice netede spațial (câmp aleator de joasă frecvență, interpolat)."""
    g = rng.normal(0, 1, (n, 4, 5)).astype("float32")
    yy = np.linspace(0, 3, ny); xx = np.linspace(0, 4, nx)
    iy = np.clip(yy.astype(int), 0, 2); ix = np.clip(xx.astype(int), 0, 3)
    fy = (yy - iy)[None, :, None]; fx = (xx - ix)[None, None, :]
    a = g[:, iy][:, :, ix]; b = g[:, iy][:, :, ix + 1]; c = g[:, iy + 1][:, :, ix]; d = g[:, iy + 1][:, :, ix + 1]
    return scala * ((a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy)


def bloc(t0, t1):
    n = t1 - t0
    z = zile[t0:t1]
    doy = (z - z.astype("datetime64[Y]")).astype(int)
    ani = (z.astype("datetime64[Y]").astype(int) + 1970 - 2014).astype("float32")
    ny, nx = Y1 - Y0, X1 - X0
    relief = np.linspace(0, -1.5, ny)[:, None] + np.linspace(-0.5, 0.5, nx)[None, :]   # nordul mai rece
    sezon = (16 + 13 * np.sin(2 * np.pi * (doy - 110) / 365.25) + 0.04 * ani)[:, None, None]
    sinoptic = camp_neted(n, ny, nx, 4.0) + rng.normal(0, 3, (n, 1, 1)).astype("float32")
    tmax = sezon + relief + sinoptic
    tmin = tmax - 9.5 - np.abs(camp_neted(n, ny, nx, 1.5))
    umed = (camp_neted(n, ny, nx, 1.0) + rng.normal(0, 1, (n, 1, 1))) > 0.55
    p = np.where(umed, rng.gamma(0.8, 7.0, (n, ny, nx)), 0.0)
    out = {}
    for k, v in (("max_temp", tmax), ("min_temp", tmin), ("precipitation", p)):
        v = np.round(v, 1).astype("float32")
        v[np.arange(t0, t1) > i_fr] = 0.0                       # după frontieră: zerouri (capcana cubului real)
        out[k] = v
    return out


def main():
    if DEST.exists():
        import shutil
        shutil.rmtree(DEST)
    g = zarr.open_group(str(DEST), mode="w", zarr_format=2)
    g.attrs.update(institution="TEST — cub sintetic, valori inventate", source="cub_test.py (nu sunt date ANM)")
    comp = Blosc(cname="lz4", clevel=5, shuffle=Blosc.SHUFFLE)
    for nume, val, attrs in (
        ("x", x, {"_ARRAY_DIMENSIONS": ["x"], "units": "degrees_east", "standard_name": "longitude"}),
        ("y", y, {"_ARRAY_DIMENSIONS": ["y"], "units": "degrees_north", "standard_name": "latitude"}),
    ):
        a = g.create_array(nume, shape=val.shape, dtype="f8", chunks=val.shape, compressors=None, fill_value=None)
        a[:] = val; a.attrs.update(attrs)
    t = g.create_array("time", shape=(NT,), dtype="i8", chunks=((NT + 1) // 2,), compressors=None, fill_value=None)
    t[:] = np.arange(NT); t.attrs.update(_ARRAY_DIMENSIONS=["time"], units="days since 2014-01-01 00:00:00",
                                         calendar="proleptic_gregorian")
    sr = g.create_array("spatial_ref", shape=(), dtype="i8", compressors=None, fill_value=None)
    sr[...] = 0
    sr.attrs.update(_ARRAY_DIMENSIONS=[], grid_mapping_name="latitude_longitude", crs_wkt='GEOGCS["WGS 84"]')
    for v, u in (("max_temp", "degree Celsius"), ("min_temp", "degree Celsius"), ("precipitation", "mm")):
        a = g.create_array(v, shape=(NT, NY, NX), dtype="<f4", chunks=CH, compressors=comp, fill_value=np.nan)
        a.attrs.update(_ARRAY_DIMENSIONS=["time", "y", "x"], units=u, grid_mapping="spatial_ref")
        s = g.create_array(f"last_{v}_time", shape=(), dtype="i8", compressors=None, fill_value=None)
        s[...] = i_fr
        s.attrs.update(_ARRAY_DIMENSIONS=[], units="days since 2014-01-01 00:00:00", calendar="proleptic_gregorian")
    # sectorul (2, 1): rândurile 322–482, coloanele 324–647; scriem chunk cu chunk (memorie mică)
    for t0 in range(0, NT, CH[0]):
        t1 = min(t0 + CH[0], NT)
        b = bloc(t0, t1)
        for v, val in b.items():
            plin = np.full((t1 - t0, NY - 322, 648 - 324), np.nan, dtype="float32")
            plin[:, Y0 - 322:Y1 - 322, X0 - 324:X1 - 324] = val
            g[v][t0:t1, 322:NY, 324:648] = plin
        print(f"\r  timp {t1}/{NT}", end="", flush=True)
    zarr.consolidate_metadata(str(DEST))
    print(f"\nCub sintetic scris: {DEST}  (frontiera {FRONTIERA}, date în lon {x[X0]}–{x[X1 - 1]}, lat {y[Y1 - 1]}–{y[Y0]})")


if __name__ == "__main__":
    main()
