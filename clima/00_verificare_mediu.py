# -*- coding: utf-8 -*-
"""
00_verificare_mediu.py — PASUL 0: verifică tot ce trebuie înainte de scripturile 01–14
=====================================================================================
Rulare:
  * OSGeo4W Shell:           python 00_verificare_mediu.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\00_verificare_mediu.py", encoding="utf-8").read())

Verifică: versiunea Python, bibliotecile (cu versiuni), GDAL (drivere COG/GPKG/MEM), compatibilitatea
numpy ↔ scipy, accesul la store-ul Zarr și la catalogul STAC, scrierea în folderul de rezultate și
un mini-test de calcul (o zi, o hartă). La final afișează comanda exactă de instalare pentru ce lipsește.

Mediul portabil (porneste.bat) conține deja tot ce trebuie; scriptul confirmă că totul funcționează.
Doar dacă rulați scripturile din OSGeo4W, pachetele lipsă se instalează din OSGeo4W Shell:
    python -m pip install --user <pachete>
"""
import importlib
import sys
import time
from pathlib import Path

# ----------------------------------------------------------------------------------------------
# Folderul cu scripturile (zarr_clima.py). În consola QGIS __file__ nu există, deci se folosește:
FOLDER = Path(__file__).resolve().parent if "__file__" in globals() else Path(r"C:\ClimaANM\clima")   # <-- doar pentru consola QGIS: folderul clima al programului
DATE_VECTOR = FOLDER.parent / "date"     # fișierele vectoriale ale programului (date/)
try:
    FOLDER = Path(__file__).resolve().parent
except NameError:
    pass
FOLDER_REZULTATE = FOLDER / "rezultate"                                       # <-- MODIFICABIL
TEST_RETEA = True        # <-- MODIFICABIL: False = nu testează accesul la EOCube.ro
# ----------------------------------------------------------------------------------------------

OK, ATENTIE, EROARE = "✔", "!", "✘"
probleme, lipsa_pip = [], []


def rand(stare, text):
    print(f"  [{stare}] {text}", flush=True)


print("=" * 78)
print("PASUL 0 · verificarea mediului pentru scripturile Zarr ANM")
print("=" * 78)

# 1. Python ---------------------------------------------------------------------------------
print("\n1. Python")
v = sys.version_info
rand(OK if v >= (3, 10) else EROARE, f"Python {v.major}.{v.minor}.{v.micro} · {sys.executable}")
if v < (3, 10):
    probleme.append("Python ≥ 3.10 necesar")
try:
    from qgis.utils import iface  # noqa: F401
    rand(OK, "rulează în QGIS: straturile rezultate se vor încărca automat în proiect")
except Exception:  # noqa: BLE001
    rand(OK, "rulează în afara QGIS (OSGeo4W Shell / Python)")

# 2. Biblioteci ------------------------------------------------------------------------------
print("\n2. Biblioteci")
NECESARE = [  # (modul, nume pip, minim, la ce folosește)
    ("numpy", "numpy", "1.24", "calcule"),
    ("xarray", "xarray", "2023.1", "cubul de date"),
    ("zarr", "zarr", "2.14", "formatul Zarr"),
    ("fsspec", "fsspec", "2023.1", "acces HTTPS"),
    ("aiohttp", "aiohttp", "3.8", "cereri HTTP paralele"),
    ("requests", "requests", "2.28", "STAC / test rețea"),
    ("dask", "dask", "2023.1", "citire paralelă pe chunk-uri"),
    ("matplotlib", "matplotlib", "3.6", "hărți și grafice PNG, GIF"),
]
OPTIONALE = [
    ("netCDF4", "netCDF4", "1.6", "script 12 (export NetCDF pentru Temporal Controller)"),
    ("PIL", "pillow", "9.0", "script 12 (animație GIF)"),
]


def ver(m):
    return getattr(m, "__version__", "?")


def mai_mare(a, b):
    def t(x):
        return tuple(int(p) for p in "".join(c if c.isdigit() or c == "." else " " for c in x).split()[0].split(".")[:2])
    try:
        return t(a) >= t(b)
    except Exception:  # noqa: BLE001
        return True


for mod, pip_nume, minim, rol in NECESARE + OPTIONALE:
    opt = (mod, pip_nume, minim, rol) in OPTIONALE
    try:
        m = importlib.import_module(mod)
        vv = ver(m)
        if mai_mare(vv, minim):
            rand(OK, f"{mod} {vv} — {rol}")
        else:
            rand(ATENTIE, f"{mod} {vv} (recomandat ≥ {minim}) — {rol}")
    except Exception as e:  # noqa: BLE001
        rand(ATENTIE if opt else EROARE, f"{mod} lipsește — {rol}" + (" (opțional)" if opt else "") + f" · {type(e).__name__}")
        lipsa_pip.append(pip_nume)
        if not opt:
            probleme.append(f"lipsește {mod}")

# numpy: o copie instalată cu --user (AppData\\Roaming\\Python) umbrește numpy-ul din OSGeo4W / QGIS
try:
    if str(FOLDER) not in sys.path:
        sys.path.insert(0, str(FOLDER))
    import mediu_numpy
    dn = mediu_numpy.diagnostic()
    for d_, v_ in mediu_numpy.copii_numpy():
        rand(OK if dn["stare"] == "ok" else ATENTIE, f"numpy {v_} în {d_}")
    if dn["stare"] == "ok":
        rand(OK, "nicio copie de numpy din folderul utilizatorului nu umbrește numpy-ul din OSGeo4W / QGIS")
    else:
        rand(EROARE if dn["stare"] == "eroare" else ATENTIE, dn["mesaj"])
        if dn["stare"] == "eroare":
            probleme.append("numpy 2.x din folderul utilizatorului umbrește numpy 1.x din OSGeo4W")
except Exception as e:  # noqa: BLE001
    rand(ATENTIE, f"nu am putut verifica sursele de numpy ({type(e).__name__}: {e}); lipsește mediu_numpy.py din {FOLDER}?")

# numpy ↔ scipy (scipy nu e necesar, dar un scipy vechi lângă numpy 2.x strică importurile altor pachete)
try:
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import scipy  # noqa: F401
    msg = [str(x.message) for x in w if "NumPy" in str(x.message)]
    if msg:
        rand(ATENTIE, f"scipy {scipy.__version__} nu e compatibil cu numpy instalat. Scripturile NU folosesc scipy, "
                      f"dar pentru liniște: python -m pip install --user --upgrade scipy")
    else:
        rand(OK, f"scipy {scipy.__version__} (nefolosit de scripturi, compatibil)")
except Exception:  # noqa: BLE001
    rand(OK, "scipy absent (nu este necesar)")

# 3. GDAL ----------------------------------------------------------------------------------------
print("\n3. GDAL / OGR")
try:
    from osgeo import gdal, ogr, osr  # noqa: F401
    rand(OK, f"GDAL {gdal.__version__}")
    for drv in ("COG", "GTiff", "MEM"):
        rand(OK if gdal.GetDriverByName(drv) else EROARE, f"driver raster {drv}")
        if not gdal.GetDriverByName(drv):
            probleme.append(f"driverul GDAL {drv} lipsește")
    # GDAL ≥ 3.11: driverul vectorial în memorie este MEM (vechiul „Memory” e depreciat)
    _m = ogr.GetDriverByName("MEM")
    for drv in ("GPKG", "MEM" if _m is not None and _m.GetMetadataItem(gdal.DCAP_VECTOR) == "YES" else "Memory"):
        rand(OK if ogr.GetDriverByName(drv) else EROARE, f"driver vector {drv}")
    try:
        from osgeo import gdal_array  # noqa: F401
        rand(OK, "gdal_array (puntea GDAL ↔ numpy) funcționează")
    except Exception:  # noqa: BLE001
        rand(ATENTIE, "gdal_array nu se încarcă (GDAL compilat pentru altă versiune de numpy). Scripturile NU îl folosesc, "
                      "dar alte unelte (ex. unele algoritmi QGIS Processing) pot fi afectate. Cauza tipică: un numpy "
                      "instalat cu --user care umbrește numpy-ul din OSGeo4W (vezi verificarea numpy de mai sus).")
    if not mai_mare(gdal.__version__, "3.1"):
        probleme.append("GDAL ≥ 3.1 necesar pentru COG")
except Exception as e:  # noqa: BLE001
    rand(EROARE, f"GDAL indisponibil ({e}). Folosiți OSGeo4W Shell sau consola QGIS, care îl includ.")
    probleme.append("GDAL indisponibil")

# 4. zarr_clima.py ---------------------------------------------------------------------------------
print("\n4. Nucleul comun")
if (FOLDER / "zarr_clima.py").exists():
    rand(OK, f"zarr_clima.py găsit în {FOLDER}")
else:
    rand(EROARE, f"zarr_clima.py NU este în {FOLDER} — corectați FOLDER sau copiați fișierul")
    probleme.append("zarr_clima.py lipsește")

# 5. Scriere -------------------------------------------------------------------------------------
print("\n5. Folderul de rezultate")
try:
    FOLDER_REZULTATE.mkdir(parents=True, exist_ok=True)
    t = FOLDER_REZULTATE / "_test_scriere.txt"; t.write_text("ok", encoding="utf-8"); t.unlink()
    rand(OK, f"se poate scrie în {FOLDER_REZULTATE}")
except Exception as e:  # noqa: BLE001
    rand(EROARE, f"nu se poate scrie în {FOLDER_REZULTATE}: {e}"); probleme.append("folder rezultate")

# 6. Rețea + mini-test --------------------------------------------------------------------------
if TEST_RETEA and not probleme:
    print("\n6. Acces la date (EOCube.ro)")
    try:
        import requests
        r = requests.get("https://stac.eocube.ro/collections/anm-daily-grids", timeout=30)
        rand(OK if r.ok else ATENTIE, f"catalog STAC: HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        rand(ATENTIE, f"catalog STAC inaccesibil ({type(e).__name__}) — scripturile nu depind de el")
    try:
        sys.path.insert(0, str(FOLDER))
        import zarr_clima as zc
        importlib.reload(zc)
        t0 = time.perf_counter()
        cub, fr = zc.deschide()
        rand(OK, f"store Zarr deschis în {time.perf_counter() - t0:.1f} s · dimensiuni {dict(cub.sizes)}")
        g = zc.grila_zonei(cub, zc.Zona.tara())
        zi = fr["max_temp"]
        t0 = time.perf_counter()
        d, _ = zc.citeste(cub, ("max_temp",), zi, zi, g)
        a = d["max_temp"][0]
        rand(OK, f"harta zilei {zi}: {int((a == a).sum())} pixeli valizi, Tmax medie {float(a[a == a].mean()):.1f} °C "
                 f"(9 chunk-uri în {time.perf_counter() - t0:.1f} s)")
        p = zc.scrie_cog(FOLDER_REZULTATE / "_test_cog.tif", a, g, ["test"], "°C")
        rand(OK, f"COG de test scris ({p.stat().st_size / 1e6:.1f} MB)"); p.unlink()
    except Exception as e:  # noqa: BLE001
        rand(EROARE, f"test eșuat: {type(e).__name__}: {e}")
        probleme.append("accesul la date / mini-testul a eșuat")

# Concluzie ---------------------------------------------------------------------------------------
print("\n" + "=" * 78)
MEDIU_PORTABIL = bool(__import__("os").environ.get("PIXI_PROJECT_ROOT"))
if lipsa_pip and MEDIU_PORTABIL:
    print("Mediul portabil este incomplet. Reinstalați-l:  porneste.bat -Reinstaleaza   (Linux/macOS: rm -rf .pixi/envs)")
elif lipsa_pip:
    print("Instalați din OSGeo4W Shell (NU din consola QGIS):")
    print(f"    python -m pip install --user {' '.join(sorted(set(lipsa_pip)))}")
if probleme:
    print(f"{EROARE} MEDIUL NU ESTE GATA: " + "; ".join(probleme))
else:
    print(f"{OK} MEDIUL ESTE GATA. Puteți rula scripturile 01–14.")
print("=" * 78)
