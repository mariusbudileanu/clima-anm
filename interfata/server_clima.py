# -*- coding: utf-8 -*-
"""
server_clima.py — interfața locală pentru scripturile de analiză climatică (cubul Zarr anm-daily-grids)
=====================================================================================================
Pornire:   python interfata/server_clima.py            (sau porneste.bat)
Se deschide browserul la http://127.0.0.1:8765 . Oprire: Ctrl+C în fereastra serverului.

Ce face:
  * citește din fiecare script din clima/ descrierea FORMULAR (fără să-l ruleze) și construiește formularul;
  * la „Rulează”, scrie parametrii în rezultate/_joburi/<id>.json și pornește
        python <script> --parametri <id>.json
    cu același interpretor Python cu care rulează serverul;
  * trimite paginii jurnalul live și lista fișierelor produse; le servește pentru previzualizare.

Doar biblioteca standard. GDAL (osgeo.ogr) e folosit, dacă există, pentru a afișa straturile, coloanele și
valorile fișierelor vectoriale. Serverul ascultă numai pe 127.0.0.1, iar cererile API cer jetonul sesiunii.
"""
from __future__ import annotations

import ast
import warnings
import json
import re
import shutil
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

warnings.filterwarnings("ignore", category=FutureWarning, message=".*UseExceptions.*")   # GDAL 4.0, vezi zarr_clima.py

AICI = Path(__file__).resolve().parent
RADACINA = AICI.parent                                   # folderul programului
SCRIPTURI = Path(os.environ.get("CLIMA_SCRIPTURI", RADACINA / "clima"))
DATE = Path(os.environ.get("CLIMA_DATE", RADACINA / "date"))
REZULTATE = Path(os.environ.get("CLIMA_REZULTATE", RADACINA / "rezultate"))
RETETE_UTILIZATOR = RADACINA / "retete" / "utilizator"
JOBURI = REZULTATE / "_joburi"
PORT = int(os.environ.get("CLIMA_PORT", "8765"))
JETON = secrets.token_urlsafe(16)
EXT_VECTOR = (".gpkg", ".shp", ".geojson", ".json", ".fgb", ".kml")
EXT_REZULTAT = (".png", ".gif", ".tif", ".gpkg", ".csv", ".html", ".md", ".json", ".nc", ".jpg", ".svg")


# =====================================================================================
# Catalogul analizelor: FORMULAR + valorile implicite citite din antetul scriptului (cu ast, fără rulare)
# =====================================================================================
def _literal(nod):
    """Valoarea unei atribuiri din antet, dacă e literală (inclusiv dict(a=…, b=…))."""
    try:
        return ast.literal_eval(nod)
    except Exception:  # noqa: BLE001
        pass
    if isinstance(nod, ast.Call) and isinstance(nod.func, ast.Name) and nod.func.id == "dict" and not nod.args:
        try:
            return {k.arg: ast.literal_eval(k.value) for k in nod.keywords}
        except Exception:  # noqa: BLE001
            return None
    return None


def _json_ok(v):
    if isinstance(v, tuple):
        return [_json_ok(x) for x in v]
    if isinstance(v, list):
        return [_json_ok(x) for x in v]
    if isinstance(v, dict):
        return {k: _json_ok(x) for k, x in v.items()}
    return v


def citeste_formular(cale: Path):
    arbore = ast.parse(cale.read_text(encoding="utf-8"))
    formular, valori = None, {}
    for nod in arbore.body:
        if isinstance(nod, ast.Assign) and len(nod.targets) == 1:
            t = nod.targets[0]
            nume = t.id if isinstance(t, ast.Name) else (
                t.attr if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "zc" else None)
            if nume is None:
                continue
            v = _literal(nod.value)
            if nume == "FORMULAR":
                formular = v
            elif v is not None or isinstance(nod.value, ast.Constant):
                valori[nume] = v
    if not isinstance(formular, dict):
        return None
    for c in formular.get("campuri", []):
        if "implicit" not in c and c["nume"] in valori:
            c["implicit"] = _json_ok(valori[c["nume"]])
    formular["script"] = cale.name
    formular["id"] = cale.stem
    return formular


def _env_copil():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", MPLBACKEND="Agg", PYTHONNOUSERSITE="1",
               CLIMA_REZULTATE=str(REZULTATE))           # ruleaza.py creează aici folderul fiecărei rulări
    for k in ("PYTHONPATH", "PYTHONHOME"):        # căile OSGeo4W / QGIS nu au ce căuta în mediul programului
        env.pop(k, None)
    return env


def _ruleaza_scurt(argumente, timeout=60):
    """Rulează ruleaza.py (catalog, export) într-un proces separat: o eroare în nucleu nu oprește serverul."""
    r = subprocess.run([sys.executable, str(SCRIPTURI / "ruleaza.py"), *argumente], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=_env_copil(), cwd=str(SCRIPTURI), timeout=timeout)
    return r


def catalog():
    """Rețetele (retete/*.json, rulate prin ruleaza.py) + scripturile vechi care au încă FORMULAR."""
    lista, erori, indicatori, pasi, metode = [], [], {}, [], {}
    r = _ruleaza_scurt(["--catalog"])
    if r.returncode == 0:
        c = json.loads(r.stdout)
        lista += c["retete"]; erori += c["erori"]; indicatori = c["indicatori"]; pasi = c.get("pasi_comuni", []); metode = c.get("metode", {})
    else:
        erori.append("ruleaza.py --catalog a eșuat: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    for cale in sorted(SCRIPTURI.glob("[0-9]*.py")):
        try:
            f = citeste_formular(cale)
            if f:
                f["tip"] = "script"
                lista.append(f)
        except Exception as e:  # noqa: BLE001
            erori.append(f"{cale.name}: {e}")
    return {"analize": lista, "erori": erori, "indicatori": indicatori, "pasi_comuni": pasi, "metode": metode}


# =====================================================================================
# Fișierele vectoriale (pentru formularul zonei)
# =====================================================================================
def lista_vectori():
    if not DATE.exists():
        return []
    return [str(p.relative_to(RADACINA)).replace("\\", "/") for p in sorted(DATE.rglob("*"))
            if p.suffix.lower() in EXT_VECTOR and p.is_file()]


def _cale_program(v):
    p = Path(str(v)).expanduser()
    return p if p.is_absolute() else (RADACINA / p).resolve()


def inspecteaza_vector(cale, strat=None, coloana=None):
    try:
        from osgeo import ogr
    except Exception:  # noqa: BLE001
        return {"eroare": "GDAL (osgeo) nu este disponibil în acest mediu: scrieți manual coloana și valorile."}
    p = _cale_program(cale)
    ds = ogr.Open(str(p))
    if ds is None:
        return {"eroare": f"Nu pot deschide «{p}»."}
    straturi = [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())
                if ds.GetLayer(i).GetGeomType() != ogr.wkbNone]
    if not straturi:
        return {"eroare": "Fișierul nu are straturi cu geometrie."}
    lyr = ds.GetLayerByName(strat) if strat in straturi else ds.GetLayerByName(straturi[0])
    defn = lyr.GetLayerDefn()
    coloane = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    rez = {"straturi": straturi, "strat": lyr.GetName(), "coloane": coloane, "n_entitati": lyr.GetFeatureCount()}
    if coloana in coloane:
        valori = set()
        lyr.ResetReading()
        for f in lyr:
            v = f.GetField(coloana)
            if v is not None:
                valori.add(str(v))
            if len(valori) > 2000:
                break
        rez["coloana"], rez["valori"] = coloana, sorted(valori)
    return rez


# =====================================================================================
# Joburile: un singur proces de analiză odată
# =====================================================================================
class Job:
    def __init__(self, analiza: str, script: str, parametri: dict, mod: str, reteta: str | None = None):
        self.id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + (reteta or script).split("/")[-1].split("_")[0]
        self.analiza, self.script, self.parametri, self.mod, self.reteta = analiza, script, parametri, mod, reteta
        self.linii: list[str] = []
        self.stare = "pornire"
        self.cod = None
        self.t0 = time.time()
        self.t1 = None
        self.proc = None
        self.fisiere: list[dict] = []
        self.folder: Path | None = None                 # rezultate/<data_ora>_<analiza>, anunțat de ruleaza.py

    def rezumat(self):
        return {"id": self.id, "analiza": self.analiza, "script": self.script, "reteta": self.reteta, "mod": self.mod,
                "folder": str(self.folder.relative_to(REZULTATE)).replace("\\", "/") if self.folder else None,
                "stare": self.stare, "cod": self.cod, "durata": round((self.t1 or time.time()) - self.t0, 1),
                "pornit": datetime.fromtimestamp(self.t0).strftime("%Y-%m-%d %H:%M:%S")}


JOB: Job | None = None
ISTORIC: list[dict] = []
LACAT = threading.Lock()


def _fisiere_noi(dupa: float):
    rez = []
    if not REZULTATE.exists():
        return rez
    for p in REZULTATE.rglob("*"):
        rel = p.relative_to(REZULTATE)
        if not p.is_file() or rel.parts[0].startswith(EXCLUSE):
            continue
        if p.suffix.lower() in EXT_REZULTAT and p.stat().st_mtime >= dupa - 1:
            rez.append({"cale": str(rel).replace("\\", "/"), "marime": p.stat().st_size, "tip": p.suffix.lower()[1:]})
    return sorted(rez, key=lambda f: f["cale"])


def _ruleaza(job: Job):
    cale_json = JOBURI / f"{job.id}.json"
    if job.reteta:                                  # rețetă: ruleaza.py job.json
        p = {"reteta": job.reteta, "parametri": job.parametri, "_radacina": str(RADACINA)}
        cmd = [sys.executable, "-u", str(SCRIPTURI / "ruleaza.py"), str(cale_json)]
        afisat = f"$ python ruleaza.py _joburi/{cale_json.name}"
    else:                                           # script vechi cu FORMULAR: script.py --parametri job.json
        p = dict(job.parametri, _radacina=str(RADACINA))
        cmd = [sys.executable, "-u", str(SCRIPTURI / job.script), "--parametri", str(cale_json)]
        afisat = f"$ python {job.script} --parametri _joburi/{cale_json.name}"
    try:
        JOBURI.mkdir(parents=True, exist_ok=True)
        cale_json.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as err:
        job.stare, job.cod, job.t1 = "eroare", 1, time.time()
        job.linii.append(f"[server] Nu pot salva parametrii în {JOBURI}: {err}")
        return
    if job.mod == "verifica":
        cmd.append("--verifica"); afisat += " --verifica"
    env = _env_copil()
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    job.linii.append(afisat)
    try:
        job.proc = subprocess.Popen(cmd, cwd=str(SCRIPTURI), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, creationflags=flags, text=True, encoding="utf-8",
                                    errors="replace", bufsize=1)
        job.stare = "ruleaza"
        for linie in job.proc.stdout:
            linie = linie.rstrip("\r\n")
            if linie.startswith("[[titlu]] "):           # ce calculează efectiv rularea (istoric, fișe)
                job.analiza = linie[10:].strip() or job.analiza
            if linie.startswith("[[folder]] "):
                f = Path(linie[11:].strip())
                try:                                     # doar în interiorul folderului rezultatelor
                    f.resolve().relative_to(REZULTATE.resolve()); job.folder = f
                except ValueError:
                    pass
            job.linii.append(linie)
        job.cod = job.proc.wait()
        if job.stare != "oprit":
            job.stare = "gata" if job.cod == 0 else "eroare"
    except Exception as e:  # noqa: BLE001
        job.linii.append(f"[server] nu am putut porni scriptul: {e}")
        job.stare = "eroare"
    job.t1 = time.time()
    job.fisiere = _fisiere_noi(job.t0) if job.mod != "verifica" else []
    try:
        (JOBURI / f"{job.id}.log").write_text("\n".join(job.linii), encoding="utf-8")
    except OSError as err:
        job.linii.append(f"[server] Nu pot salva jurnalul: {err}")
    if job.folder is not None and job.folder.is_dir():      # jurnalul complet, lângă rezultate
        try:
            (job.folder / "jurnal.txt").write_text("\n".join(l for l in job.linii if not l.startswith("[[")), encoding="utf-8")
        except OSError as err:
            job.linii.append(f"[server] Nu pot salva jurnalul în folderul rulării: {err}")
    r = job.rezumat()
    r["parametri"] = job.parametri
    try:
        (JOBURI / f"{job.id}.rezumat.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as err:
        job.linii.append(f"[server] Nu pot salva rezumatul: {err}")
    ISTORIC.insert(0, r)


def porneste_job(d: dict):
    global JOB
    with LACAT:
        if JOB and JOB.stare in ("pornire", "ruleaza"):
            return {"eroare": "O analiză rulează deja. Așteptați sau opriți-o."}
        reteta = d.get("reteta")
        script = d.get("script", "") if not reteta else "ruleaza.py"
        if not reteta and (not (SCRIPTURI / script).is_file() or "/" in script or "\\" in script
                           or citeste_formular(SCRIPTURI / script) is None):
            return {"eroare": f"Script necunoscut sau fără FORMULAR: {script}"}
        parametri = dict(d.get("parametri", {}))
        parametri.pop("OUT", None)
        if not reteta:                                   # scripturile vechi scriu direct în rezultate/
            parametri["OUT"] = str(REZULTATE)
        JOB = Job(d.get("analiza", script), script, parametri, d.get("mod", "ruleaza"), reteta)
        threading.Thread(target=_ruleaza, args=(JOB,), daemon=True).start()
        return {"id": JOB.id}


# =====================================================================================
# Harta: rastere (GeoTIFF / COG) și contururi vectoriale, pentru vizualizatorul din interfață
# =====================================================================================
MAX_PIXELI = 1600            # latura maximă trimisă browserului (rasterele mai mari se citesc micșorat)
_CACHE_RASTER: dict = {}     # (cale, mtime) → {"info": …, "benzi": {nr: bytes}}
_CACHE_CONTUR: dict = {}


def _finit(x):
    import math
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def _fara_nan(o):
    """JSON strict: NaN / ±inf → null (browserul refuză „NaN” în JSON)."""
    if isinstance(o, float):
        return _finit(o)
    if isinstance(o, dict):
        return {k: _fara_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_fara_nan(v) for v in o]
    return o


DEM_REL = "_date/dem_grila_zarr.tif"          # DEM-ul coregistrat, arătat în tabul Hartă lângă rezultate


_TITLURI = {}


def titlu_rulare(folder: Path):
    """Titlul rulării din fișa de reproducere (cu cache după data modificării)."""
    f = folder / "reproducere.json"
    try:
        m = f.stat().st_mtime
    except OSError:
        return None
    if _TITLURI.get(f, (None,))[0] != m:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            _TITLURI[f] = (m, d.get("titlu"), d.get("stare"))
        except (OSError, ValueError):
            _TITLURI[f] = (m, None, None)
    return _TITLURI[f][1:]


EXCLUSE = ("_joburi", "cache", "_cache", "_scripturi", "_cos")


def lista_rastere():
    rez = []
    dem = RADACINA / "date" / "dem_grila_zarr.tif"
    if dem.exists():
        st = dem.stat()
        rez.append({"cale": DEM_REL, "marime": st.st_size, "mtime": 0, "folder": "relief (DEM pe grila Zarr)",
                    "data": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    if not REZULTATE.exists():
        return rez
    for p in REZULTATE.rglob("*"):
        if p.suffix.lower() not in (".tif", ".tiff") or not p.is_file():
            continue
        rel = p.relative_to(REZULTATE)
        if rel.parts[0].startswith(EXCLUSE):
            continue
        st = p.stat()
        rulare = rel.parts[0] if len(rel.parts) > 1 else ""
        t = titlu_rulare(REZULTATE / rulare) if rulare else None
        rez.append({"cale": rel.as_posix(), "marime": st.st_size, "mtime": st.st_mtime,
                    "data": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "folder": rel.parent.as_posix() if rel.parent.as_posix() != "." else "",
                    "rulare": rulare, "rulare_titlu": t[0] if t else None,
                    "fisa": bool(rulare) and (REZULTATE / rulare / "index.html").exists()})
    return sorted(rez, key=lambda r: (r["cale"] == DEM_REL, -r["mtime"]))


_RULARE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}_")


def miniatura(tif: Path, folder: str):
    """O imagine mică a rasterului (banda 1, paleta din metadate), pentru rulările fără PNG. → calea relativă sau None."""
    dest = REZULTATE / "_cache" / "miniaturi" / f"{folder}.png"
    try:
        if dest.exists() and dest.stat().st_mtime >= tif.stat().st_mtime:
            return dest.relative_to(REZULTATE).as_posix()
        import numpy as np
        from osgeo import gdal
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ds = gdal.Open(str(tif)); b = ds.GetRasterBand(1)
        f = max(1, int(max(ds.RasterXSize, ds.RasterYSize) / 520))
        w, h = ds.RasterXSize // f, ds.RasterYSize // f
        a = np.frombuffer(b.ReadRaster(buf_xsize=w, buf_ysize=h, buf_type=gdal.GDT_Float32), dtype="<f4").reshape(h, w).copy()
        nd = b.GetNoDataValue()
        if nd is not None and np.isfinite(nd):
            a[a == nd] = np.nan
        v = a[np.isfinite(a)]
        if not v.size:
            return None
        gt = ds.GetGeoTransform(); lat = gt[3] + gt[5] * ds.RasterYSize / 2
        cols = np.round(np.linspace(0, w - 1, max(2, int(w * np.cos(np.radians(lat)))))).astype(int)   # corecția cos(φ)
        a = a[:, cols]
        m = {**(ds.GetMetadata() or {}), **(b.GetMetadata() or {})}
        cmap = m.get("CMAP") or "viridis"
        lo, hi = np.percentile(v, 2), np.percentile(v, 98)
        if m.get("DIVERGENT") == "1":
            c = float(m.get("CENTRU") or 0); r = max(abs(lo - c), abs(hi - c)); lo, hi = c - r, c + r
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            plt.imsave(dest, np.ma.masked_invalid(a), cmap=cmap, vmin=lo, vmax=hi if hi > lo else lo + 1)
        except ValueError:                                # paletă necunoscută lui matplotlib
            plt.imsave(dest, np.ma.masked_invalid(a), cmap="viridis", vmin=lo, vmax=hi if hi > lo else lo + 1)
        return dest.relative_to(REZULTATE).as_posix()
    except Exception:  # noqa: BLE001  (miniatura e un lux: fără ea, cartea arată doar „GeoTIFF”)
        return None


def galerie(n=24):
    """Ultimele rulări (folderele rezultate/<data_ora>_<analiza>/), pentru pagina de start: titlul, imaginea
    reprezentativă (aceeași ca în fișa vizuală), rasterele și dacă au o serie pe ani pentru animație."""
    if not REZULTATE.is_dir():
        return []
    rez = []
    for d in sorted((x for x in REZULTATE.iterdir() if x.is_dir() and _RULARE.match(x.name)), key=lambda x: x.name, reverse=True)[:n]:
        try:
            fis = [f for f in d.rglob("*") if f.is_file()]
        except OSError:
            continue
        png = [f for f in fis if f.suffix.lower() == ".png" and not f.name.startswith(".")]
        harti = [f for f in png if f.name.endswith("_harta.png")]
        png.sort(key=lambda f: (0 if "an_record" in f.name else 1 if f in harti else 2 if "clasament" in f.name
                                else 3 if "disponibilitate" in f.name else 4, f.name))
        tif = sorted((f for f in fis if f.suffix.lower() in (".tif", ".tiff")), key=lambda f: (not f.stem.endswith("_pe_ani"), f.name))
        t = titlu_rulare(d) or (None, None)
        m = _RULARE.match(d.name).group(0)
        rez.append({"folder": d.name, "titlu": t[0] or d.name[len(m):].replace("_", " "), "stare": t[1],
                    "data": f"{m[8:10]}.{m[5:7]}.{m[0:4]} {m[11:13]}:{m[13:15]}",
                    "imagine": png[0].relative_to(REZULTATE).as_posix() if png else
                               (miniatura(next((f for f in tif if not f.stem.endswith("_pe_ani")), tif[0]), d.name) if tif else None),
                    "n_png": len(png), "n_tif": len(tif), "fisa": (d / "index.html").exists(),
                    "tif": tif[0].relative_to(REZULTATE).as_posix() if tif else None,
                    "animatie": any(f.stem.endswith("_pe_ani") for f in tif)})
    return rez


def _cale_rezultat(rel):
    if rel == DEM_REL:
        p = RADACINA / "date" / "dem_grila_zarr.tif"
        if not p.is_file():
            raise FileNotFoundError(rel)
        return p
    p = (REZULTATE / rel).resolve()
    p.relative_to(REZULTATE.resolve())                    # ValueError = în afara folderului rezultatelor
    if not p.is_file():
        raise FileNotFoundError(rel)
    return p


def _elibereaza_rasterele(folder: Path):
    """Închide fișierele GDAL deschise din `folder` (cache-ul hărții, contururile): pe Windows, un fișier deschis
    nu se poate muta sau șterge (WinError 32)."""
    import gc
    pref = str(folder.resolve())
    for cache in (_CACHE_RASTER, globals().get("_CACHE_CONTUR", {})):
        for k in [k for k in list(cache) if str(k[0] if isinstance(k, tuple) else k).startswith(pref)]:
            intr = cache.pop(k, None)
            if isinstance(intr, dict):
                intr.clear()
    gc.collect()


def _deschide_raster(rel):
    """→ (intrare din cache, set de date GDAL în EPSG:4326, eventual micșorat)."""
    from osgeo import gdal, osr
    p = _cale_rezultat(rel)
    cheie = (str(p), p.stat().st_mtime)
    if cheie in _CACHE_RASTER:
        return _CACHE_RASTER[cheie]
    ds = gdal.Open(str(p))
    if ds is None:
        raise ValueError(f"GDAL nu poate deschide {rel}")
    srs = osr.SpatialReference(wkt=ds.GetProjection()) if ds.GetProjection() else None
    e_4326 = srs is not None and srs.GetAuthorityCode(None) == "4326"
    f = max(1.0, max(ds.RasterXSize, ds.RasterYSize) / MAX_PIXELI)
    if not e_4326 or f > 1:                               # reproiectare / micșorare, în memorie
        opt = gdal.WarpOptions(format="MEM", dstSRS="EPSG:4326", resampleAlg="near",
                               width=int(ds.RasterXSize / f) if e_4326 else 0,
                               height=int(ds.RasterYSize / f) if e_4326 else 0)
        ds = gdal.Warp("", ds, options=opt)
        if ds is None:
            raise ValueError("reproiectarea în EPSG:4326 a eșuat")
        if max(ds.RasterXSize, ds.RasterYSize) > MAX_PIXELI:
            f2 = max(ds.RasterXSize, ds.RasterYSize) / MAX_PIXELI
            ds = gdal.Warp("", ds, options=gdal.WarpOptions(format="MEM", width=int(ds.RasterXSize / f2),
                                                            height=int(ds.RasterYSize / f2), resampleAlg="near"))
    gt = ds.GetGeoTransform()
    meta_ds = ds.GetMetadata() or {}
    benzi = []
    for i in range(1, ds.RasterCount + 1):
        b = ds.GetRasterBand(i)
        m = dict(meta_ds); m.update(b.GetMetadata() or {})
        benzi.append({"nr": i, "descriere": b.GetDescription() or f"banda {i}", "unitate": b.GetUnitType() or "",
                      "nodata": _finit(b.GetNoDataValue()), "cmap": m.get("CMAP"), "divergent": m.get("DIVERGENT") == "1",
                      "centru": float(m["CENTRU"]) if m.get("CENTRU") else None,
                      "clase": [float(x) for x in m["CLASE"].split(",")] if m.get("CLASE") else None})
    intrare = {"ds": ds, "benzi": {}, "info": {
        "cale": rel, "latime": ds.RasterXSize, "inaltime": ds.RasterYSize, "x0": gt[0], "y0": gt[3],
        "dx": gt[1], "dy": -gt[5], "reproiectat": not e_4326, "micsorat": round(f, 2) if f > 1 else 1, "benzi": benzi,
        "ani": _ani_raster(meta_ds, benzi), "titlu": meta_ds.get("TITLU"),
        "scara": [float(x) for x in meta_ds["SCARA"].split(",")] if meta_ds.get("SCARA") else None}}
    if len(_CACHE_RASTER) > 12:
        _CACHE_RASTER.pop(next(iter(_CACHE_RASTER)))
    _CACHE_RASTER[cheie] = intrare
    return intrare


def _ani_raster(meta, benzi):
    """Anii benzilor, dacă rasterul e o serie pe ani (metadatele ANI sau descrieri de forma „2016”, „2016 · JJA”)."""
    if meta.get("ANI"):
        ani = [int(x) for x in meta["ANI"].split(",") if x.strip().isdigit()]
        if len(ani) == len(benzi):
            return ani
    if len(benzi) < 2:
        return None
    ani = [b["descriere"][:4] for b in benzi]
    return [int(a) for a in ani] if all(a.isdigit() for a in ani) else None


def info_raster(rel):
    import numpy as np
    intrare = _deschide_raster(rel)
    info = intrare["info"]
    for b in info["benzi"]:
        if "p02" not in b:                                # statistici pentru întinderea implicită a culorilor
            a = np.frombuffer(banda_raster(rel, b["nr"]), dtype="<f4")
            v = a[np.isfinite(a)]
            b.update(n_valide=int(v.size), min=float(v.min()) if v.size else None, max=float(v.max()) if v.size else None,
                     p02=float(np.percentile(v, 2)) if v.size else None, p98=float(np.percentile(v, 98)) if v.size else None,
                     p98abs=None if not v.size else float(np.percentile(np.abs(v - (b["centru"] or 0.0)), 98)))
    return info


def banda_raster(rel, nr):
    """Banda ca float32 little-endian, rând cu rând de la nord; NoData → NaN."""
    import numpy as np
    from osgeo import gdal
    intrare = _deschide_raster(rel)
    if nr not in intrare["benzi"]:
        b = intrare["ds"].GetRasterBand(int(nr))
        a = np.frombuffer(b.ReadRaster(buf_type=gdal.GDT_Float32), dtype="<f4").copy()
        nd = b.GetNoDataValue()
        if nd is not None and np.isfinite(nd):
            a[a == nd] = np.nan
        intrare["benzi"][nr] = a.astype("<f4").tobytes()
    return intrare["benzi"][nr]


def contur_geojson(cale, toleranta=0.003):
    """Conturul unui fișier vectorial, în EPSG:4326, simplificat (doar pentru desen)."""
    from osgeo import ogr, osr
    p = _cale_program(cale)
    cheie = (str(p), p.stat().st_mtime, toleranta)
    if cheie in _CACHE_CONTUR:
        return _CACHE_CONTUR[cheie]
    ds = ogr.Open(str(p))
    if ds is None:
        raise FileNotFoundError(cale)
    lyr = next((ds.GetLayer(i) for i in range(ds.GetLayerCount()) if ds.GetLayer(i).GetGeomType() != ogr.wkbNone), None)
    if lyr is None:
        raise ValueError("fișierul nu are geometrii")
    tinta = osr.SpatialReference(); tinta.ImportFromEPSG(4326)
    tinta.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    sursa = lyr.GetSpatialRef()
    tr = None
    if sursa is not None:
        sursa.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        if not sursa.IsSame(tinta):
            tr = osr.CoordinateTransformation(sursa, tinta)
    def_ = lyr.GetLayerDefn()
    col = next((def_.GetFieldDefn(i).GetName() for i in range(def_.GetFieldCount())
                if def_.GetFieldDefn(i).GetName().lower() in ("name", "nume", "denumire", "eticheta")), None)
    linii = []
    for f in lyr:
        g = f.GetGeometryRef()
        if g is None:
            continue
        g = g.Clone()
        if tr:
            g.Transform(tr)
        g = g.SimplifyPreserveTopology(toleranta)
        linii.append({"type": "Feature", "properties": {"nume": f.GetField(col) if col else None},
                      "geometry": json.loads(g.ExportToJson())})
    rez = {"type": "FeatureCollection", "features": linii}
    _CACHE_CONTUR[cheie] = rez
    return rez


FRONTIERE = {"stare": "necunoscut", "t": 0}
ZARR_INFO = {"stare": "necunoscut", "t": 0}


def actualizeaza_zarr_info(fortat=False):
    """Metadatele store-ului (tabul „Zarr info”), citite cu ruleaza.py --zarr-info; cache 10 min.
    Dicționarul nu se modifică pe loc: se înlocuiește întreg (atribuire atomică), ca un fir HTTP care îl
    serializează în același timp să vadă fie versiunea veche, fie pe cea nouă, niciodată una pe jumătate."""
    global ZARR_INFO
    if not fortat and time.time() - ZARR_INFO["t"] < 600 and ZARR_INFO["stare"] not in ("necunoscut",):
        return ZARR_INFO
    ZARR_INFO = dict(ZARR_INFO, stare="se verifică", t=time.time())
    try:
        r = _ruleaza_scurt(["--zarr-info"], timeout=120)
        linie = [l for l in r.stdout.splitlines() if l.startswith("[[zarr]] ")]
        d = json.loads(linie[-1][len("[[zarr]] "):]) if linie else {"ok": False, "eroare": (r.stderr or "?").strip()[-300:]}
    except Exception as e:  # noqa: BLE001
        d = {"ok": False, "eroare": str(e)}
    ZARR_INFO = dict(d, stare="ok" if d.get("ok") else "eroare", t=time.time())
    return ZARR_INFO


def actualizeaza_frontiere(fortat=False):
    """Frontierele datelor (last_*_time) din store; cache 10 min. Arată și dacă EOCube e accesibil.
    Înlocuire atomică a dicționarului, ca la actualizeaza_zarr_info."""
    global FRONTIERE
    if not fortat and time.time() - FRONTIERE["t"] < 600 and FRONTIERE["stare"] != "necunoscut":
        return FRONTIERE
    FRONTIERE = dict(FRONTIERE, stare="se verifică", t=time.time())
    try:
        r = _ruleaza_scurt(["--frontiere"], timeout=90)
        linie = [l for l in r.stdout.splitlines() if l.startswith("[[frontiere]] ")]
        d = json.loads(linie[-1][len("[[frontiere]] "):]) if linie else {"ok": False, "eroare": (r.stderr or "?").strip()[-300:]}
    except Exception as e:  # noqa: BLE001
        d = {"ok": False, "eroare": str(e)}
    FRONTIERE = dict(d, stare="ok" if d.get("ok") else "eroare", t=time.time())
    return FRONTIERE


def exporta_python(d: dict):
    JOBURI.mkdir(parents=True, exist_ok=True)
    cale = JOBURI / "_export.json"
    p = dict(d.get("parametri", {}), OUT=str(REZULTATE))
    cale.write_text(json.dumps({"reteta": d.get("reteta"), "parametri": p, "_radacina": str(RADACINA)},
                               ensure_ascii=False), encoding="utf-8")
    r = _ruleaza_scurt([str(cale), "--exporta"])
    if r.returncode != 0:
        return {"eroare": (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "export eșuat"}
    dest = (r.stderr.strip().splitlines() or [""])[-1].replace("# --- salvat în ", "")
    return {"cod": r.stdout, "cale": dest}


def _slug(t):
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:60] or "reteta"


def salveaza_reteta(d: dict):
    """O rulare devine rețetă proprie: motorul și modul rețetei de bază + valorile din formular."""
    baza_id = d.get("reteta", "")
    baza = None
    for folder in (RADACINA / "retete", RETETE_UTILIZATOR):
        f = folder / f"{baza_id.split('/')[-1]}.json"
        if f.is_file() and (folder == RETETE_UTILIZATOR) == baza_id.startswith("utilizator/"):
            baza = json.loads(f.read_text(encoding="utf-8"))
    titlu = (d.get("titlu") or "").strip()
    if not baza or not titlu:
        return {"eroare": "Lipsește titlul sau rețeta de bază."}
    p = dict(d.get("parametri", {}))
    p.update(p.pop("_setari", {}))
    for k in ("_zone", "OUT", "NUME"):
        p.pop(k, None)
    noua = {k: v for k, v in baza.items() if k in ("motor", "mod_indicatori", "grupuri_indicatori", "ascunse", "cost", "etichete")}
    noua.update(titlu=titlu, grup="Rețetele mele", descriere=(d.get("descriere") or "").strip(),
                parametri=p, bazata_pe=baza_id, creata=datetime.now().strftime("%Y-%m-%d %H:%M"))
    RETETE_UTILIZATOR.mkdir(parents=True, exist_ok=True)
    f = RETETE_UTILIZATOR / f"{_slug(titlu)}.json"
    f.write_text(json.dumps(noua, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"id": "utilizator/" + f.stem, "cale": str(f)}


def sterge_reteta(d: dict):
    rid = d.get("reteta", "")
    if not rid.startswith("utilizator/"):
        return {"eroare": "Doar rețetele proprii se pot șterge."}
    f = RETETE_UTILIZATOR / f"{Path(rid).name}.json"
    if not f.is_file():
        return {"eroare": "Rețeta nu există."}
    f.unlink()
    return {"ok": True}


def opreste_job():
    if not JOB or not JOB.proc or JOB.proc.poll() is not None:
        return {"eroare": "Nicio analiză nu rulează."}
    JOB.stare = "oprit"
    JOB.linii.append("[server] analiza a fost oprită de utilizator.")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(JOB.proc.pid), "/T", "/F"], capture_output=True)
    else:
        JOB.proc.terminate()
    return {"ok": True}


def incarca_istoric():
    if not JOBURI.exists():
        return
    for p in sorted(JOBURI.glob("*.rezumat.json"), reverse=True)[:50]:
        try:
            ISTORIC.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass


def deschide_folder(cale: Path):
    cale.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(cale))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(cale)])
    else:
        subprocess.Popen(["xdg-open", str(cale)])


# =====================================================================================
# HTTP
# =====================================================================================
class Cereri(BaseHTTPRequestHandler):
    server_version = "ClimaANM/0.1"

    def log_message(self, fmt, *args):  # liniște în consolă, cu excepția erorilor
        if args and str(args[1]).startswith(("4", "5")):
            sys.stderr.write("[http] " + (fmt % args) + "\n")

    def _trimite(self, cod, corp: bytes, tip="application/json; charset=utf-8"):
        self.send_response(cod)
        self.send_header("Content-Type", tip)
        self.send_header("Content-Length", str(len(corp)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corp)

    def _json(self, obj, cod=200):
        self._trimite(cod, json.dumps(_fara_nan(obj), ensure_ascii=False, allow_nan=False).encode("utf-8"))

    def _host_ok(self):
        """Contra DNS rebinding: o pagină web străină care și-a „mutat” domeniul pe 127.0.0.1 trimite antetul Host
        cu domeniul ei. Acceptăm doar adresele locale (cu orice port)."""
        h = (self.headers.get("Host") or "").strip().lower()
        nume = h.rsplit(":", 1)[0] if not h.startswith("[") else h.split("]")[0] + "]"
        if nume in ("127.0.0.1", "localhost", "[::1]"):
            return True
        self._json({"eroare": "Host nepermis"}, 403)
        return False

    def _jeton_ok(self):
        if self.headers.get("X-Jeton") == JETON:
            return True
        self._json({"eroare": "jeton invalid — reîncărcați pagina"}, 403)
        return False

    def do_GET(self):
        if not self._host_ok():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            html = (AICI / "index.html").read_text(encoding="utf-8").replace("__JETON__", JETON)
            return self._trimite(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if u.path in ("/harta.js", "/indicatori.js", "/zarr_info.js", "/alegator.js"):
            return self._fisier(AICI, u.path.lstrip("/"))
        if u.path.startswith("/zarr/"):                   # simulatorul: doar din interfata/zarr/
            return self._fisier(AICI / "zarr", unquote(u.path[len("/zarr/"):]))
        if u.path.startswith("/rezultate/"):
            return self._fisier(REZULTATE, unquote(u.path[len("/rezultate/"):]))
        if not u.path.startswith("/api/") or not self._jeton_ok():
            return self._json({"eroare": "negăsit"}, 404) if not u.path.startswith("/api/") else None
        if u.path == "/api/catalog":
            c = catalog()
            c.update(vectori=lista_vectori(), radacina=str(RADACINA), rezultate=str(REZULTATE),
                     python=sys.executable, gdal=_are_gdal(),
                     dem=(RADACINA / "date" / "dem_grila_zarr.tif").exists() or bool(os.environ.get("CLIMA_DEM")))
            return self._json(c)
        if u.path == "/api/vector":
            return self._json(inspecteaza_vector(q.get("cale", ""), q.get("strat"), q.get("coloana")))
        if u.path == "/api/job":
            if not JOB:
                return self._json({"stare": "niciunul"})
            de_la = int(q.get("de_la", 0))
            r = JOB.rezumat()
            r.update(linii=JOB.linii[de_la:], total=len(JOB.linii), fisiere=JOB.fisiere)
            return self._json(r)
        if u.path == "/api/galerie":
            return self._json({"rulari": galerie()})
        if u.path == "/api/rastere":
            cos = REZULTATE / "_cos"
            return self._json({"rastere": lista_rastere(), "gdal": _are_gdal(),
                               "cos": len(list(cos.iterdir())) if cos.is_dir() else 0})
        if u.path in ("/api/raster", "/api/raster_banda", "/api/contur"):
            try:
                if u.path == "/api/raster":
                    return self._json(info_raster(q.get("cale", "")))
                if u.path == "/api/raster_banda":
                    return self._trimite(200, banda_raster(q.get("cale", ""), int(q.get("banda", 1))), "application/octet-stream")
                return self._json(contur_geojson(q.get("cale", "")))
            except Exception as e:  # noqa: BLE001
                return self._json({"eroare": f"{type(e).__name__}: {e}"}, 400)
        if u.path == "/api/zarr_info":
            if q.get("reincearca") or ZARR_INFO["stare"] == "necunoscut":
                threading.Thread(target=actualizeaza_zarr_info, args=(bool(q.get("reincearca")),), daemon=True).start()
                time.sleep(0.05)
            return self._json(ZARR_INFO)
        if u.path == "/api/frontiere":
            if q.get("reincearca"):
                threading.Thread(target=actualizeaza_frontiere, args=(True,), daemon=True).start()
            r = dict(FRONTIERE)
            f = Path(os.environ.get("CLIMA_CACHE_ANALIZE", REZULTATE / "_cache")) / "integritate" / "ultimul.json"
            try:                                         # ultima verificare a datelor (butonul „Verifică datele”)
                r["integritate"] = json.loads(f.read_text(encoding="utf-8"))
                r["integritate"].pop("variabile", None)
            except (OSError, ValueError):
                pass
            return self._json(r)
        if u.path == "/api/istoric":
            return self._json(ISTORIC[:50])
        if u.path == "/api/job_vechi":
            p = JOBURI / f"{Path(q.get('id', '')).name}.rezumat.json"
            return self._json(json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"eroare": "negăsit"})
        return self._json({"eroare": "negăsit"}, 404)

    def do_POST(self):
        if not self._host_ok() or not self._jeton_ok():
            return
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return self._json({"eroare": "Content-Length invalid"}, 400)
        if n > 2_000_000:                                  # un formular are câțiva KB
            return self._json({"eroare": "cerere prea mare"}, 413)
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json({"eroare": "JSON invalid"}, 400)
        if not isinstance(d, dict):
            return self._json({"eroare": "JSON invalid"}, 400)
        p = urlparse(self.path).path
        if p == "/api/ruleaza":
            return self._json(porneste_job(d))
        if p == "/api/opreste":
            return self._json(opreste_job())
        if p == "/api/exporta":
            return self._json(exporta_python(d))
        if p == "/api/salveaza_reteta":
            return self._json(salveaza_reteta(d))
        if p == "/api/sterge_reteta":
            return self._json(sterge_reteta(d))
        if p == "/api/la_cos":                          # mută o rulare în rezultate/_cos (se golește explicit)
            f = (REZULTATE / str(d.get("folder", ""))).resolve()
            try:
                rel = f.relative_to(REZULTATE.resolve())
            except ValueError:
                return self._json({"eroare": "cale în afara folderului rezultatelor"}, 400)
            if len(rel.parts) != 1 or rel.parts[0].startswith(EXCLUSE) or not f.is_dir():
                return self._json({"eroare": "se pot muta doar folderele rulărilor"}, 400)
            cos = REZULTATE / "_cos"; cos.mkdir(exist_ok=True)
            tinta = cos / f.name
            k = 2
            while tinta.exists():
                tinta = cos / f"{f.name}_{k}"; k += 1
            _elibereaza_rasterele(f)
            try:
                shutil.move(str(f), str(tinta))
            except PermissionError as e:
                return self._json({"eroare": f"un fișier din rulare e deschis în alt program (QGIS, Excel …): {e}"}, 409)
            return self._json({"ok": True})
        if p == "/api/goleste_cosul":
            cos = REZULTATE / "_cos"
            n = len(list(cos.iterdir())) if cos.is_dir() else 0
            if cos.is_dir():
                _elibereaza_rasterele(cos)
                shutil.rmtree(cos, ignore_errors=True)
            return self._json({"ok": True, "sterse": n})
        if p == "/api/deschide_folder":
            tinta = REZULTATE
            if d.get("folder"):                              # folderul unei rulări, doar în interiorul rezultatelor
                f = (REZULTATE / str(d["folder"])).resolve()
                try:
                    f.relative_to(REZULTATE.resolve())
                except ValueError:
                    return self._json({"eroare": "cale în afara folderului rezultatelor"}, 400)
                tinta = f
            deschide_folder(tinta)
            return self._json({"ok": True})
        return self._json({"eroare": "negăsit"}, 404)

    def _fisier(self, baza: Path, rel: str):
        try:
            p = (baza / rel).resolve()
            p.relative_to(baza.resolve())
        except Exception:  # noqa: BLE001
            return self._json({"eroare": "cale interzisă"}, 403)
        if not p.is_file():
            return self._json({"eroare": "negăsit"}, 404)
        tip = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".js":
            tip = "text/javascript"
        if tip.startswith("text/") or tip in ("application/json",):
            tip += "; charset=utf-8"
        self._trimite(200, p.read_bytes(), tip)


def _are_gdal():
    try:
        from osgeo import gdal
        return gdal.__version__
    except Exception:  # noqa: BLE001
        return None


def main():
    REZULTATE.mkdir(parents=True, exist_ok=True)
    incarca_istoric()
    port = PORT
    for incercare in range(10):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Cereri)
            break
        except OSError:
            port += 1
    else:
        sys.exit("Nu găsesc un port liber între 8765 și 8774.")
    url = f"http://127.0.0.1:{port}/"
    print("=" * 70)
    print(f"  Clima ANM — interfața rulează la {url}")
    print(f"  Scripturi: {SCRIPTURI}")
    print(f"  Rezultate: {REZULTATE}")
    print(f"  Python:    {sys.executable}")
    print("  Oprire: Ctrl+C (sau închideți această fereastră)")
    print("=" * 70, flush=True)
    threading.Thread(target=actualizeaza_frontiere, daemon=True).start()      # antetul: până când sunt date?
    if "--fara-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nServer oprit.")
        if JOB and JOB.proc and JOB.proc.poll() is None:
            opreste_job()


if __name__ == "__main__":
    main()
