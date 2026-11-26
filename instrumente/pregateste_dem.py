# -*- coding: utf-8 -*-
"""
pregateste_dem.py — Copernicus DEM GLO-30 coregistrat pe grila cubului Zarr anm-daily-grids
=========================================================================================
Se rulează O SINGURĂ DATĂ (de profesor); rezultatul, date/dem_grila_zarr.tif (câțiva MB), se distribuie
cu programul. Studenții nu descarcă DEM-ul.

  Windows:      instrumente\\pregateste_dem.bat
  Linux/macOS:  instrumente/pixi run --manifest-path pixi.toml python instrumente/pregateste_dem.py

Opțiuni:  --sursa DIR_SAU_URL   folder local cu tile-uri sau șablon URL cu {id} (implicit: EOCube, apoi AWS)
          --pastreaza            nu șterge tile-urile descărcate (cache_date/dem_tile/) la final
          --bloc 30              mărimea blocului de procesare, în pixeli Zarr

DE CE NU UN SIMPLU „RESAMPLE”
  Grila Zarr: EPSG:4326, pas 0,01° = 36″, marginile pixelilor la multipli de 0,01° (vest 20,13°, nord 48,36°).
  Copernicus DEM GLO-30: EPSG:4326, pas 1″, CENTRELE pixelilor pe secunde întregi (originea unui tile este la
  −0,5″ față de gradul întreg). Marginile pixelilor Zarr trec deci prin MIJLOCUL unor pixeli DEM: fiecare pixel
  Zarr acoperă 35 de pixeli DEM întregi și 2 jumătăți pe fiecare axă. Media corectă e ponderată cu aria comună
  (ponderi 0,5 – 1 – … – 1 – 0,5), iar scriptul calculează ponderile din geometria reală, oricare ar fi decalajul.

  Panta se calculează pe DEM-ul de 30 m și ABIA APOI se mediază pe pixelul Zarr. Panta calculată din altitudinea
  deja mediată la 1 km ar fi mult subestimată (relieful fin dispare înainte de derivare).

  Atenție: Copernicus DEM este un model al SUPRAFEȚEI (DSM): include pădurea și clădirile (de ordinul a 10–25 m).

Benzile rezultatului:  1 altitudinea medie (m) · 2 minimă · 3 maximă · 4 abaterea standard (energia reliefului)
                       5 panta medie (°) · 6 fracția cu valori DSM valide (0–1; include apa cu cotă validă)
"""
from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
RAD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAD / "clima"))

IESIRE = RAD / "date" / "dem_grila_zarr.tif"
TILE = RAD / "cache_date" / "dem_tile"
SURSE = [
    "https://storage.svc.uvt-01.eocube.ro/copernicus-dem-30m/{id}/{id}.tif",          # EOCube (UVT)
    "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/{id}/{id}.tif",          # AWS Open Data
]
PAS = 0.01
# grila cubului (verificată la rulare din store, dacă e accesibil)
GRILA_IMPLICITA = dict(vest=20.13, nord=48.36, nx=972, ny=483)


JURNAL = RAD / "dem_jurnal.txt"


def log(t):
    linie = f"[{time.strftime('%H:%M:%S')}] {t}"
    print(linie, flush=True)
    with open(JURNAL, "a", encoding="utf-8") as f:              # jurnalul rămâne și după închiderea ferestrei
        f.write(linie + "\n")


def id_tile(lat, lon):
    return (f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
            f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")


# ------------------------------------------------------------------ grila țintă
def grila_tinta():
    """Marginile grilei Zarr, citite din coordonatele cubului (centre ± pas/2)."""
    g = dict(GRILA_IMPLICITA)
    try:
        import zarr_clima as zc
        cub, _ = zc.deschide()
        x = cub["x"].values; y = cub["y"].values
    except Exception as e:
        log(f"[atenție] Nu pot citi grila cubului ({e}). Folosesc geometria distribuită {g}.")
    else:
        if (not np.allclose(np.diff(x), PAS, rtol=0, atol=1e-6)
                or not np.allclose(np.diff(y), -PAS, rtol=0, atol=1e-6)):
            raise ValueError("Cubul citit are o grilă incompatibilă cu pasul de 0,01°.")
        g = dict(vest=round(float(x[0]) - PAS / 2, 6), nord=round(float(y[0]) + PAS / 2, 6), nx=len(x), ny=len(y))
        log(f"Grila citită din cub: {g}")
    g["est"] = round(g["vest"] + g["nx"] * PAS, 6); g["sud"] = round(g["nord"] - g["ny"] * PAS, 6)
    return g


# ------------------------------------------------------------------ descărcarea tile-urilor
def _descarca(url, dest, incercari=4):
    """True = descărcat; False = tile inexistent (404/403 pe mare); excepție = eroare de rețea persistentă."""
    tmp = dest.with_suffix(".part")
    for k in range(1, incercari + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            tmp.replace(dest)
            return True
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return False
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            err = e
        log(f"   reîncercare {k}/{incercari} pentru {dest.name}: {err}")
        time.sleep(2 * k)
    raise RuntimeError(f"nu pot descărca {url}: {err}")


def _tile_ok(p):
    try:
        ds = gdal.Open(str(p)); ok = ds.RasterXSize > 0; ds = None
        return ok
    except Exception:  # noqa: BLE001
        return False


def tile_uri(g, sursa):
    lat0, lat1 = math.floor(g["sud"]), math.floor(g["nord"] - 1e-9)
    lon0, lon1 = math.floor(g["vest"]), math.floor(g["est"] - 1e-9)
    ids = [id_tile(la, lo) for la in range(lat0, lat1 + 1) for lo in range(lon0, lon1 + 1)]
    log(f"tile-uri necesare: {len(ids)} (lat {lat0}…{lat1}, lon {lon0}…{lon1}); cele de pe mare pot lipsi")
    if sursa and Path(sursa).is_dir():                                   # tile-uri deja descărcate
        gasite = [p for i in ids for p in (Path(sursa) / i / f"{i}.tif", Path(sursa) / f"{i}.tif") if p.exists()]
        log(f"sursa locală {sursa}: {len(gasite)} tile-uri găsite")
        return gasite
    TILE.mkdir(parents=True, exist_ok=True)
    surse = [sursa] if sursa else SURSE
    proba = id_tile(45, 26)                                              # un tile sigur pe uscat
    alesa = None
    for s in surse:
        dest = TILE / f"{proba}.tif"
        try:
            if (dest.exists() and _tile_ok(dest)) or _descarca(s.format(id=proba), dest, 2):
                alesa = s; break
            log(f"   {s.split('/')[2]}: tile-ul de probă nu există")
        except RuntimeError as e:
            log(f"   {s.split('/')[2]} indisponibil: {e}")
    if not alesa:
        raise SystemExit("[eroare] Nicio sursă DEM accesibilă. Verificați internetul sau dați --sursa (folder / URL cu {id}).")
    log(f"sursa: {alesa.split('/')[2]}")
    out, lipsa = [], 0
    for n, i in enumerate(ids, 1):
        dest = TILE / f"{i}.tif"
        if dest.exists() and _tile_ok(dest):
            out.append(dest); continue
        t0 = time.time()
        if _descarca(alesa.format(id=i), dest):
            out.append(dest)
            log(f"   {n}/{len(ids)} {i}: {dest.stat().st_size / 1e6:.0f} MB în {time.time() - t0:.0f} s")
        else:
            lipsa += 1
            log(f"   {n}/{len(ids)} {i}: nu există (mare / în afara uscatului)")
    log(f"tile-uri disponibile: {len(out)}, lipsă: {lipsa}")
    return out


# ------------------------------------------------------------------ ponderile de arie
def ponderi(marg_tinta, marg_sursa):
    """Matricea (n_tinta × n_sursa): fracția din fiecare pixel-sursă care cade în fiecare pixel-țintă.
    Marginile trebuie să fie monotone în același sens (crescătoare sau descrescătoare)."""
    a0, a1 = marg_tinta[:-1, None], marg_tinta[1:, None]
    b0, b1 = marg_sursa[None, :-1], marg_sursa[None, 1:]
    if marg_tinta[1] < marg_tinta[0]:                                     # axa y: descrescătoare
        a0, a1, b0, b1 = -a0, -a1, -b0, -b1
    supr = np.clip(np.minimum(a1, b1) - np.maximum(a0, b0), 0, None)
    return (supr / (b1 - b0)).astype("float64")


def panta_horn(z, lat_centru, rez):
    """Panta (°) cu operatorul Horn, pe grila geografică (dx în metri depinde de latitudinea rândului)."""
    phi = np.radians(np.asarray(lat_centru, dtype="float64"))[1:-1, None]
    f_wgs = 1 / 298.257223563
    e2 = f_wgs * (2 - f_wgs)
    den = 1 - e2 * np.sin(phi) ** 2
    arc = np.radians(rez) * 6378137.0
    dy = arc * (1 - e2) / den ** 1.5
    dx = arc * np.cos(phi) / np.sqrt(den)
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g_, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g_)) / (8 * dx)
    dzdy = ((g_ + 2 * h + i) - (a + 2 * b + c)) / (8 * dy)
    s = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    out = np.full(z.shape, np.nan, "float64")
    out[1:-1, 1:-1] = np.where(np.isfinite(z[1:-1, 1:-1]), s, np.nan)
    return out


# ------------------------------------------------------------------ procesarea
def proceseaza(g, tile, bloc):
    vrt = gdal.BuildVRT("/vsimem/dem_tile.vrt", [str(t) for t in tile], VRTNodata=-32768)
    gt = vrt.GetGeoTransform(); rez = gt[1]
    nd = vrt.GetRasterBand(1).GetNoDataValue()
    ds0 = gdal.Open(str(tile[0])); src_nd = ds0.GetRasterBand(1).GetNoDataValue(); ds0 = None
    # decalajul dintre grile, în secunde de arc: unde cad marginile Zarr față de pixelii DEM
    dec_x = ((g["vest"] - gt[0]) / rez) % 1; dec_y = ((gt[3] - g["nord"]) / rez) % 1
    log(f"DEM: pas {rez * 3600:.4f}″, origine {gt[0]:.6f}° / {gt[3]:.6f}°, {vrt.RasterXSize} × {vrt.RasterYSize} pixeli")
    log(f"aliniere: marginile Zarr cad la {dec_x:.3f} / {dec_y:.3f} din pixelul DEM "
        f"(0 = margine pe margine; 0,5 = prin mijlocul pixelului DEM) → ponderi de arie pe margini")
    raport = PAS / rez
    if abs(raport - round(raport)) > 1e-6:
        log(f"[atenție] pasul Zarr nu e multiplu întreg al pasului DEM ({raport:.4f}); ponderile o tratează oricum")

    ny, nx = g["ny"], g["nx"]
    rez_b = {k: np.full((ny, nx), np.nan, "float32") for k in ("medie", "min", "max", "std", "panta", "acop")}
    mz_x = g["vest"] + PAS * np.arange(nx + 1)
    mz_y = g["nord"] - PAS * np.arange(ny + 1)
    t0 = time.time(); nb = math.ceil(ny / bloc) * math.ceil(nx / bloc); kb = 0
    for r0 in range(0, ny, bloc):
        r1 = min(ny, r0 + bloc)
        for c0 in range(0, nx, bloc):
            c1 = min(nx, c0 + bloc); kb += 1
            # fereastra DEM care acoperă blocul + 1 pixel de margine (pentru pantă)
            j0 = math.floor((mz_x[c0] - gt[0]) / rez) - 1; j1 = math.ceil((mz_x[c1] - gt[0]) / rez) + 1
            i0 = math.floor((gt[3] - mz_y[r0]) / rez) - 1; i1 = math.ceil((gt[3] - mz_y[r1]) / rez) + 1
            J0, J1 = max(j0, 0), min(j1, vrt.RasterXSize); I0, I1 = max(i0, 0), min(i1, vrt.RasterYSize)
            if J1 <= J0 or I1 <= I0:
                continue
            z = vrt.ReadAsArray(J0, I0, J1 - J0, I1 - I0).astype("float64")
            inv = (z == nd) | ~np.isfinite(z)
            if src_nd is not None:
                inv |= z == src_nd
            z[inv] = np.nan
            if inv.all():
                continue
            v = (~inv).astype("float64"); z0 = np.where(inv, 0.0, z)
            mx = gt[0] + rez * np.arange(J0, J1 + 1); my = gt[3] - rez * np.arange(I0, I1 + 1)
            Wx = ponderi(mz_x[c0:c1 + 1], mx); Wy = ponderi(mz_y[r0:r1 + 1], my)
            lat = gt[3] - rez * (np.arange(I0, I1) + 0.5)
            s = panta_horn(z, lat, rez)
            vs = np.isfinite(s).astype("float64"); s0 = np.where(vs > 0, s, 0.0)
            arie = (PAS / rez) ** 2                                          # aria unui pixel Zarr, în pixeli DEM
            sv = Wy @ v @ Wx.T
            with np.errstate(invalid="ignore", divide="ignore"):
                m = (Wy @ (z0 * v) @ Wx.T) / sv
                m2 = (Wy @ (z0 * z0 * v) @ Wx.T) / sv
                pm = (Wy @ (s0 * vs) @ Wx.T) / (Wy @ vs @ Wx.T)
            sl = (slice(r0, r1), slice(c0, c1))
            rez_b["medie"][sl] = m; rez_b["std"][sl] = np.sqrt(np.clip(m2 - m * m, 0, None))
            rez_b["panta"][sl] = pm; rez_b["acop"][sl] = sv / arie
            # min / max: pixelii DEM cu suprapunere > 0
            for a in range(r1 - r0):
                ri = np.flatnonzero(Wy[a] > 0)
                if ri.size == 0:
                    continue
                zr = z[ri[0]:ri[-1] + 1]
                if np.isnan(zr).all():
                    continue
                with np.errstate(all="ignore"):
                    cmin = np.nanmin(np.where(np.isnan(zr), np.inf, zr), axis=0)
                    cmax = np.nanmax(np.where(np.isnan(zr), -np.inf, zr), axis=0)
                for b in range(c1 - c0):
                    ci = np.flatnonzero(Wx[b] > 0)
                    if ci.size:
                        lo, hi = cmin[ci[0]:ci[-1] + 1].min(), cmax[ci[0]:ci[-1] + 1].max()
                        if np.isfinite(lo):
                            rez_b["min"][r0 + a, c0 + b] = lo; rez_b["max"][r0 + a, c0 + b] = hi
            if kb % 25 == 0 or kb == nb:
                log(f"   bloc {kb}/{nb} · {time.time() - t0:.0f} s")
    gol = rez_b["acop"] <= 0
    for k in rez_b:
        rez_b[k][gol | ~np.isfinite(rez_b["acop"])] = np.nan
    return rez_b, vrt, gt


def verifica(rez_b, vrt, g):
    """Control independent: media cu gdal.Warp (average, ponderată cu aria în GDAL ≥ 3.1) pe toată grila.
    overviewLevel="NONE": altfel Warp folosește prezentările generale interne ale COG-urilor Copernicus
    (o versiune deja micșorată a DEM-ului) și controlul ar fi el însuși aproximativ."""
    w = gdal.Warp("", vrt, format="MEM", overviewLevel="NONE", outputBounds=(g["vest"], g["sud"], g["est"], g["nord"]),
                  width=g["nx"], height=g["ny"], resampleAlg="average", dstNodata=np.nan, outputType=gdal.GDT_Float64)
    ref = w.ReadAsArray(); ok = np.isfinite(ref) & np.isfinite(rez_b["medie"]) & (rez_b["acop"] > 0.999)
    if not ok.any():
        log("control gdal.Warp: niciun pixel complet comparabil"); return
    d = np.abs(ref[ok] - rez_b["medie"][ok])
    log(f"control gdal.Warp(average) pe {ok.sum()} pixeli compleți: diferența medie {d.mean():.4f} m, maximă {d.max():.4f} m")


def scrie(rez_b, g, sursa_txt):
    IESIRE.parent.mkdir(parents=True, exist_ok=True)
    benzi = [("medie", "Altitudinea medie (m)", "m"), ("min", "Altitudinea minimă (m)", "m"),
             ("max", "Altitudinea maximă (m)", "m"), ("std", "Abaterea standard a altitudinii (m)", "m"),
             ("panta", "Panta medie, calculată la 30 m (°)", "deg"), ("acop", "Fracție cu valori DSM valide, inclusiv apă", "1")]
    mem = gdal.GetDriverByName("MEM").Create("", g["nx"], g["ny"], len(benzi), gdal.GDT_Float32)
    mem.SetGeoTransform((g["vest"], PAS, 0, g["nord"], 0, -PAS)); mem.SetProjection("EPSG:4326")
    for k, (cod, descr, u) in enumerate(benzi, 1):
        b = mem.GetRasterBand(k); b.WriteArray(rez_b[cod]); b.SetNoDataValue(float("nan"))
        b.SetDescription(descr); b.SetUnitType(u)
    mem.SetMetadata({"SURSA": sursa_txt, "PRODUS": "Copernicus DEM GLO-30 (DSM), © DLR e.V. 2010-2014 și © Airbus 2014-2018, "
                     "furnizat sub programul Copernicus; licență ESA",
                     "METODA": "medie ponderată cu aria comună pe grila Zarr 0,01°; panta Horn la 30 m, apoi mediată",
                     "GRILA": f"anm-daily-grids: vest {g['vest']}, nord {g['nord']}, {g['nx']}x{g['ny']}, pas {PAS}",
                     "GENERAT": time.strftime("%Y-%m-%d %H:%M")})
    tmp = IESIRE.with_suffix(".tmp.tif")
    gdal.Translate(str(tmp), mem, format="COG", creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=YES", "OVERVIEWS=NONE"])
    tmp.replace(IESIRE)
    log(f"scris: {IESIRE} ({IESIRE.stat().st_size / 1e6:.1f} MB)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--sursa"); ap.add_argument("--pastreaza", action="store_true"); ap.add_argument("--bloc", type=int, default=30)
    a = ap.parse_args(argv)
    gdal.SetConfigOption("GDAL_CACHEMAX", "512")
    t0 = time.time()
    JURNAL.write_text(f"pregateste_dem.py {' '.join(argv or sys.argv[1:])}\n", encoding="utf-8")
    g = grila_tinta()
    tile = tile_uri(g, a.sursa)
    if not tile:
        raise SystemExit("[eroare] Niciun tile DEM disponibil.")
    rez_b, vrt, _ = proceseaza(g, tile, a.bloc)
    verifica(rez_b, vrt, g)
    m = rez_b["medie"]
    log(f"altitudine: {np.nanmin(m):.0f} … {np.nanmax(m):.0f} m (medie pe pixeli), maxim absolut {np.nanmax(rez_b['max']):.0f} m · "
        f"panta medie maximă {np.nanmax(rez_b['panta']):.1f}° · pixeli cu date {np.isfinite(m).sum()} din {m.size}")
    # unde cad extremele (verificare de bun-simț: Făgăraș, Retezat, Bucegi; Delta Dunării)
    def unde(a, f):
        i, j = np.unravel_index(f(a), a.shape)
        return f"{g['nord'] - PAS * (i + 0.5):.3f}° N, {g['vest'] + PAS * (j + 0.5):.3f}° E"
    pz = rez_b["panta"]
    log(f"   altitudinea medie maximă la {unde(m, np.nanargmax)} · minimă la {unde(m, np.nanargmin)}")
    log(f"   panta medie maximă la {unde(pz, np.nanargmax)} · percentilele pantei: p50 {np.nanpercentile(pz, 50):.1f}°, "
        f"p99 {np.nanpercentile(pz, 99):.1f}°, p99,9 {np.nanpercentile(pz, 99.9):.1f}°")
    scrie(rez_b, g, a.sursa or "EOCube / AWS (copernicus-dem-30m)")
    vrt = None
    if not a.pastreaza and not (a.sursa and Path(a.sursa).is_dir()) and TILE.exists():
        shutil.rmtree(TILE, ignore_errors=True)
        log("tile-urile descărcate au fost șterse (folosiți --pastreaza ca să le păstrați)")
    log(f"gata în {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
