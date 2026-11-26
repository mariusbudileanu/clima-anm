# -*- coding: utf-8 -*-
"""
zarr_clima.py — nucleul comun al scripturilor de analiză climatică pe cubul `anm-daily-grids`
=============================================================================================
NU se rulează direct. Este importat de scripturile 01_… – 14_…, care conțin doar parametrii.

Ce face:
  * deschide cubul Zarr de pe EOCube.ro (HTTPS) și citește frontierele `last_*_time`;
  * taie spațiul (toată țara / dreptunghi / poligoane dintr-un GeoPackage) și timpul (ani, sezoane);
  * calculează indicatori climatici an cu an (definiții ETCCDI, notate la fiecare funcție);
  * scrie rezultatele alese: COG (GeoTIFF), PNG (hartă), grafic PNG, GeoPackage, CSV, NetCDF, GIF;
  * dacă rulează în consola Python din QGIS, încarcă automat straturile în proiect.

Rulează identic în OSGeo4W Shell (`python 02_zile_tropicale.py`) și în consola Python din QGIS
(`exec(open(r"C:\\...\\02_zile_tropicale.py", encoding="utf-8").read())`).

Reguli de calcul aplicate peste tot (vezi slide-urile 21–23 ale cursului):
  1. timpul se taie la frontiera `last_*_time` (minimul variabilelor folosite);
  2. o perioadă care depășește frontiera este parțială → se exclude (dacă ACCEPTA_PARTIAL = False);
  3. un pixel dintr-o perioadă cu prea multe zile lipsă (< PRAG_VALID) devine NaN;
  4. y (latitudinea) este stocat de la Nord la Sud: tăieturile se fac cu slice(lat_max, lat_min).
"""
from __future__ import annotations

import csv
import json
import math
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

# Înainte de numpy: o copie instalată cu `pip install --user` poate umbri numpy-ul din OSGeo4W/QGIS (vezi mediu_numpy.py)
try:
    import mediu_numpy as _mn
    _dn = _mn.diagnostic()
    if _dn["stare"] != "ok":
        print(f"[atenție] {_dn['mesaj']}", flush=True)
except Exception:  # noqa: BLE001
    pass

import numpy as np

warnings.filterwarnings("ignore", message=".*NumPy version.*SciPy.*")
# Nu apelăm gdal.UseExceptions(): în unele instalări încarcă gdal_array, care cade dacă numpy-ul
# nu corespunde celui cu care a fost compilat GDAL. Verificăm explicit rezultatele apelurilor GDAL.
warnings.filterwarnings("ignore", category=FutureWarning, message=".*UseExceptions.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*(Mean of empty|All-NaN|invalid value|Degrees of freedom).*")

# =====================================================================================
# CONSTANTE (se schimbă doar dacă se mută datele)
# =====================================================================================
import os
URL = os.environ.get("ZARR_ANM_URL", "https://storage.svc.uvt-01.eocube.ro/meteo/cube/open-v1")
VARIABILE = ("max_temp", "min_temp", "precipitation")
UNITATI = {"max_temp": "°C", "min_temp": "°C", "precipitation": "mm"}
ATRIBUIRE = "Date: ANM / MeteoRomania · procesare: UVT – EOCube.Ro · CC-BY-4.0"
PAS = 0.01                                  # rezoluția grilei (grade)
X_VEST, Y_NORD = 20.13, 48.36               # marginile grilei (nu centrele pixelilor)
# Copernicus DEM GLO-30 adus pe grila cubului (instrumente/pregateste_dem.py): benzile 1 medie, 2 min, 3 max,
# 4 abaterea standard, 5 panta (°), 6 acoperirea. Pixel cu pixel aceeași grilă ca datele climatice.
DEM_FISIER = os.environ.get("CLIMA_DEM", str(Path(__file__).resolve().parent.parent / "date" / "dem_grila_zarr.tif"))
DEM_BENZI = {"medie": 1, "min": 2, "max": 3, "std": 4, "panta": 5, "acoperire": 6}

# Setări generale (pot fi suprascrise din script: zc.PRAG_VALID = 0.8 etc.)
PRAG_VALID = 0.90          # fracția minimă de zile valide într-o perioadă, per pixel
ACCEPTA_PARTIAL = False    # True = acceptă perioade care depășesc frontiera (ex. 2026 incomplet)
REINCERCARI = 6            # reîncercări la erori de rețea (pe fiecare chunk, nu pe tot anul)
CERERI_SIMULTANE = int(os.environ.get("CLIMA_CONCURENTA", "8"))   # cereri HTTP paralele; în laborator: 4
# Cache-ul local al chunk-urilor ÎNCHEIATE (imuabile): o a doua analiză pe aceeași perioadă nu mai descarcă nimic,
# iar o eroare de rețea nu pierde chunk-urile deja aduse. Nu se păstrează niciodată metadatele (.zmetadata),
# frontierele (last_*_time) și chunk-urile de lângă frontieră, care se schimbă zilnic.
CACHE_DATE = os.environ.get("CLIMA_CACHE_DATE", str(Path(__file__).resolve().parent.parent / "cache_date"))
CACHE_GB = float(os.environ.get("CLIMA_CACHE_GB", "5"))
# Cache-ul ANALIZELOR (serii zonale, ferestrele episoadelor, valori anuale ale indicatorilor), comun tuturor rulărilor:
# fiecare rulare are acum folderul ei (rezultate/<data_ora>_<analiza>), dar seriile calculate o dată se refolosesc.
CACHE_ANALIZE = os.environ.get("CLIMA_CACHE_ANALIZE", str(Path(os.environ.get(
    "CLIMA_REZULTATE", Path(__file__).resolve().parent.parent / "rezultate")) / "_cache"))


FRONTIERE_ULTIME = None
STORE_ULTIM = None


def dir_cache(tip):
    """Folderul comun de cache pentru un tip de date derivate („serii”, „episod”, „praguri”…)."""
    d = Path(CACHE_ANALIZE) / tip
    d.mkdir(parents=True, exist_ok=True)
    return d            # limita; peste ea se șterg cele mai vechi
CACHE_ZILE = float(os.environ.get("CLIMA_CACHE_ZILE", "30"))       # după atâtea zile, un chunk se reîmprospătează
DPI = 200                  # rezoluția imaginilor PNG
# Conturul desenat pe hărțile PNG (pe lângă poligoanele zonei, dacă există):
#   None                                         → fără contur
#   r"C:\date\romania.gpkg"                     → primul strat din fișier (GPKG, SHP, GeoJSON…; orice CRS)
#   (r"C:\date\limite.gpkg", "judete")          → un strat anume
#   (r"C:\date\limite.gpkg", "judete", "cod = 'IS'") → cu filtru SQL
CONTUR_HARTI = None
CONTUR_GROSIME = 0.6       # grosimea liniei conturului (puncte)
CONTUR_CULOARE = "#333333"
INCARCA_IN_QGIS = True     # dacă rulează în QGIS: adaugă automat COG și GPKG în proiect

SEZOANE = {
    "anual": (1, 12), "DJF": (12, 2), "MAM": (3, 5), "JJA": (6, 8), "SON": (9, 11),
    "vara_agricola": (4, 9), "iarna_extinsa": (11, 3),
}



# =====================================================================================
# Utilitare de afișare
# =====================================================================================
_T0 = time.perf_counter()


def log(msg):
    print(f"[{time.perf_counter() - _T0:7.1f} s] {msg}", flush=True)


def ro(x, dec=1):
    """Număr în format românesc: 1.234,5"""
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    s = f"{x:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def in_qgis():
    try:
        from qgis.utils import iface  # noqa: F401
        return iface is not None
    except Exception:  # noqa: BLE001
        return False


# =====================================================================================
# Zona de interes
# =====================================================================================
class Zona:
    """Zona analizei. Patru forme, fiecare cu numele ei:

    Zona.tara()                                              → toată grila (România)
    Zona.dreptunghi(lon_min, lat_min, lon_max, lat_max)      → un dreptunghi (grade, WGS 84)
    Zona.punct(lon, lat, nume="București")                  → pixelul cel mai apropiat (serii de timp)
    Zona.poligoane(r"C:\\...\\judete.gpkg", coloana="name", valori=["Ilfov", "Prahova"])
        → poligoane dintr-un fișier vectorial (GPKG, SHP, GeoJSON…), în orice CRS (se reproiectează în EPSG:4326)
          coloana = coloana din care se iau numele zonelor (o alegeți voi; vezi 00b_inspecteaza_vector.py)
          valori  = ce poligoane se păstrează (după coloana); None = toate. Comparația ignoră majusculele și
                    diacriticele („Iasi” = „Iași”)
          strat   = stratul din fișier; necesar doar dacă fișierul are mai multe straturi cu geometrie
          unite   = True: poligoanele selectate devin O SINGURĂ zonă (ex. „Ilfov + Prahova”);
                    False: fiecare valoare a coloanei e o zonă separată (tabel pe zone)

    Forma veche Zona(gpkg=…, camp=…, filtru=…), Zona(bbox=…), Zona(punct=…) funcționează în continuare.
    """

    def __init__(self, gpkg=None, strat=None, camp=None, filtru=None, bbox=None, punct=None, nume=None,
                 marja=0.02, *, coloana=None, valori=None, unite=False, _forma_noua=False):
        # Greșeli frecvente: un NUME pus în locul fișierului (Zona("Eforie")) sau un punct dat greșit
        if gpkg is not None and not Path(str(gpkg)).exists():
            raise FileNotFoundError(
                f"Fișierul vectorial nu există: «{gpkg}».\n"
                f"   Pentru un punct folosiți Zona.punct(lon, lat, nume=\"…\"); pentru toată țara, Zona.tara().")
        if punct is not None:
            ok = isinstance(punct, (tuple, list)) and len(punct) == 2 and all(isinstance(v, (int, float)) for v in punct)
            if not ok:
                raise ValueError(f"punctul trebuie să fie (lon, lat), de exemplu Zona.punct(28.64, 44.04); am primit {punct!r}")
        if bbox is not None:
            ok = isinstance(bbox, (tuple, list)) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox)
            if not ok or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                raise ValueError(f"dreptunghiul trebuie dat ca (lon_min, lat_min, lon_max, lat_max), cu min < max; "
                                 f"am primit {bbox!r}")
        if isinstance(valori, (str, int, float)):
            valori = [valori]
        if camp and not coloana:
            coloana = camp                        # forma veche: camp = coloana etichetelor
        if valori is not None and not coloana:
            raise ValueError("valori=[…] cere și coloana=\"…\" (coloana în care se caută valorile).")
        self.gpkg, self.strat, self.coloana, self.filtru = (str(gpkg) if gpkg is not None else None), strat, coloana, filtru
        self.valori = list(valori) if valori is not None else None
        self.unite = bool(unite)
        self.bbox = tuple(bbox) if bbox is not None else None
        self.punct = tuple(punct) if punct is not None else None
        self.nume, self.marja = nume, marja
        self._forma_noua = _forma_noua
        self.altitudine = None                     # (min, max) în m sau None: filtru pe altitudinea medie a pixelului
        # completate automat la citire
        self.poligoane = []                        # [(eticheta, geometrie_wkt_4326)]
        self._id = None                            # grila cu id-ul poligonului (0 = în afara)

    # ---------------------------------------------------------------- constructorii clari
    @classmethod
    def tara(cls, nume=None):
        return cls(nume=nume, _forma_noua=True)

    @classmethod
    def dreptunghi(cls, lon_min, lat_min, lon_max, lat_max, nume=None):
        return cls(bbox=(lon_min, lat_min, lon_max, lat_max), nume=nume, _forma_noua=True)

    @classmethod
    def punct(cls, lon, lat, nume=None):
        return cls(punct=(lon, lat), nume=nume, _forma_noua=True)

    @classmethod
    def poligoane(cls, fisier, coloana=None, valori=None, strat=None, unite=False, nume=None):
        if fisier is None:
            raise ValueError("Zona.poligoane(…) cere calea fișierului vectorial.")
        return cls(gpkg=fisier, strat=strat, coloana=coloana, valori=valori, unite=unite, nume=nume, _forma_noua=True)

    def cu_altitudine(self, minim=None, maxim=None):
        """Păstrează doar pixelii cu altitudinea medie (DEM pe grila Zarr) între minim și maxim (m; None = fără limită).
        Ex.: Zona.tara().cu_altitudine(1500, None) → doar pixelii de peste 1500 m."""
        if minim is None and maxim is None:
            self.altitudine = None
            return self
        if self.punct:
            raise ValueError("Filtrul altitudinal cere o zonă cu suprafață.")
        if minim is not None and maxim is not None and float(minim) >= float(maxim):
            raise ValueError(f"filtrul de altitudine cere minim < maxim; am primit {minim} … {maxim} m")
        self.altitudine = (None if minim is None else float(minim), None if maxim is None else float(maxim))
        return self

    def _text_altitudine(self):
        if not self.altitudine:
            return ""
        a, b = self.altitudine
        f = lambda v: f"{v:g}".replace(".", ",")  # noqa: E731
        return (f" · altitudine {f(a)}–{f(b)} m" if a is not None and b is not None
                else f" · peste {f(a)} m" if a is not None else f" · sub {f(b)} m")

    # compatibilitate: `camp` era numele vechi al coloanei
    @property
    def camp(self):
        return self.coloana

    def __repr__(self):
        return f"Zona({self.descriere()})"

    def descriere(self):
        return self._descriere_baza() + self._text_altitudine()

    def _descriere_baza(self):
        if self.punct:
            return self.nume or f"punct {self.punct[0]:.3f}°E, {self.punct[1]:.3f}°N"
        if self.gpkg:
            if self.nume:
                return self.nume
            sel = ""
            if self.valori:
                v = ", ".join(map(str, self.valori[:4])) + ("…" if len(self.valori) > 4 else "")
                sel = f" ({self.coloana}: {v})"
            elif self.filtru:
                sel = f" ({self.filtru})"
            n = len(self.poligoane)
            return f"{Path(self.gpkg).stem}{sel}" + (" — zonă unită" if self.unite else f": {n} zone" if n else "")
        if self.bbox:
            return self.nume or "dreptunghi " + ", ".join(f"{v:g}" for v in self.bbox)
        return self.nume or "România (toată grila)"


def _norm_text(s):
    """Text pentru comparații: fără diacritice (ș/ş, ț/ţ, ă, â, î), litere mici, spații simple."""
    import unicodedata
    s = str(s).strip().casefold().replace("ş", "s").replace("ţ", "t")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(s.split())


def _straturi_vector(ds):
    """[(nume, tip_geometrie, nr_entitati)] doar pentru straturile cu geometrie."""
    from osgeo import ogr
    out = []
    for i in range(ds.GetLayerCount()):
        l = ds.GetLayer(i)
        if l.GetGeomType() != ogr.wkbNone:
            out.append((l.GetName(), ogr.GeometryTypeToName(l.GetGeomType()), l.GetFeatureCount()))
    return out


def _valori_coloanei(lyr, coloana, n=None):
    """Valorile distincte (în ordinea apariției) dintr-o coloană."""
    vazute, out = set(), []
    lyr.ResetReading()
    for f in lyr:
        v = f.GetField(coloana)
        if v is None:
            continue
        k = str(v)
        if k not in vazute:
            vazute.add(k); out.append(k)
            if n and len(out) >= n:
                break
    lyr.ResetReading()
    return out


def _citeste_poligoane(z: Zona):
    import difflib
    from osgeo import ogr, osr
    ds = ogr.Open(str(z.gpkg))
    if ds is None:
        raise FileNotFoundError(f"Nu pot deschide {z.gpkg} (nu este un fișier vectorial citibil de GDAL).")
    fisier = Path(z.gpkg).name
    straturi = _straturi_vector(ds)
    # ---------------------------------------------------------------- stratul
    if z.strat:
        lyr = ds.GetLayerByName(z.strat)
        if lyr is None:
            raise ValueError(f"Stratul „{z.strat}” nu există în {fisier}. Straturi cu geometrie: "
                             + ", ".join(f"„{s}” ({t}, {n})" for s, t, n in straturi))
    elif len(straturi) == 1:
        lyr = ds.GetLayerByName(straturi[0][0])
    elif not straturi:
        raise ValueError(f"{fisier} nu are niciun strat cu geometrie.")
    elif not z._forma_noua:
        lyr = ds.GetLayerByName(straturi[0][0])         # forma veche: primul strat, ca până acum
        log(f"   [forma veche] {fisier} are {len(straturi)} straturi; folosesc primul, „{straturi[0][0]}” (setați strat=\"…\")")
    else:
        raise ValueError(f"{fisier} are {len(straturi)} straturi cu geometrie; alegeți unul cu strat=\"…\": "
                         + ", ".join(f"„{s}” ({t}, {n} entități)" for s, t, n in straturi))
    tip = ogr.GT_Flatten(lyr.GetGeomType())
    if tip not in (ogr.wkbPolygon, ogr.wkbMultiPolygon, ogr.wkbUnknown, ogr.wkbGeometryCollection):
        raise ValueError(f"Stratul „{lyr.GetName()}” conține {ogr.GeometryTypeToName(tip)}, nu poligoane.")
    defn = lyr.GetLayerDefn()
    coloane = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    n_total = lyr.GetFeatureCount()

    def _lista_coloane():
        r = []
        for c in coloane:
            ex = _valori_coloanei(lyr, c, 3)
            r.append(f"      {c:<20} ex.: {', '.join(ex)}")
        return "\n".join(r)

    # ---------------------------------------------------------------- coloana etichetelor
    if z.coloana and z.coloana not in coloane:
        apropiate = [c for c in coloane if c.casefold() == z.coloana.casefold()]
        if len(apropiate) == 1:                     # „NAME” vs „name”: aceeași coloană, alt fel de scriere
            log(f"   coloana „{z.coloana}” → „{apropiate[0]}” (majusculele diferă în {Path(str(fisier)).name})")
            z.coloana = apropiate[0]
    if z.coloana and z.coloana not in coloane:
        apropiate = [c for c in coloane if c.casefold() == z.coloana.casefold()]
        sug = f" Poate „{apropiate[0]}”? (contează majusculele)" if apropiate else ""
        raise ValueError(f"Coloana „{z.coloana}” nu există în stratul „{lyr.GetName()}”.{sug}\n"
                         f"   Coloanele disponibile, cu exemple de valori:\n{_lista_coloane()}")
    if not z.coloana and not z._forma_noua:
        # forma veche, fără camp: păstrăm alegerea automată de până acum, dar spunem ce să scrie
        text = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())
                if defn.GetFieldDefn(i).GetType() == ogr.OFTString]
        pref = [c for c in text if c.lower() in ("nume", "name", "denumire", "judet", "județ", "county", "name_ro", "nume_judet")]
        z.coloana = (pref or text or [None])[0]
        if z.coloana:
            log(f"   [forma veche] eticheta zonelor: coloana „{z.coloana}”, aleasă automat. Scrieți explicit:\n"
                f"      Zona.poligoane(r\"{z.gpkg}\", coloana=\"{z.coloana}\""
                + (f", strat=\"{lyr.GetName()}\"" if len(straturi) > 1 else "") + ")")
    if not z.coloana and n_total > 1 and not z.unite:
        raise ValueError(f"Stratul „{lyr.GetName()}” are {n_total} poligoane: spuneți din ce coloană se iau numele zonelor, "
                         f"cu coloana=\"…\" (sau unite=True pentru o singură zonă).\n"
                         f"   Coloanele disponibile, cu exemple de valori:\n{_lista_coloane()}")
    if z.filtru:
        if lyr.SetAttributeFilter(z.filtru) != 0:
            raise ValueError(f"Filtrul SQL „{z.filtru}” nu este valid pentru stratul „{lyr.GetName()}”. "
                             f"Coloane: {', '.join(coloane)}")
    # ---------------------------------------------------------------- selecția după valori
    dorite = None
    if z.valori is not None:
        existente = _valori_coloanei(lyr, z.coloana)
        harta = {}
        for v in existente:
            harta.setdefault(_norm_text(v), v)
        lipsa = [v for v in z.valori if _norm_text(v) not in harta]
        if lipsa:
            rand = []
            for v in lipsa:
                s = difflib.get_close_matches(_norm_text(v), list(harta), n=3, cutoff=0.6)
                rand.append(f"      «{v}»" + (f" → poate: {', '.join(harta[k] for k in s)}" if s else " → nimic asemănător"))
            raise ValueError(f"Valori care nu există în coloana „{z.coloana}”:\n" + "\n".join(rand) + "\n"
                             f"   Valorile coloanei ({len(existente)}): {', '.join(existente[:40])}"
                             + (" …" if len(existente) > 40 else ""))
        z.valori = [harta[_norm_text(v)] for v in z.valori]      # scrierea din tabelă (pentru titluri și etichete)
        dorite = {_norm_text(v) for v in z.valori}
    # ---------------------------------------------------------------- reproiectarea în EPSG:4326
    src = lyr.GetSpatialRef()
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = None
    if src is None:
        log(f"   [atenție] stratul „{lyr.GetName()}” nu are sistem de coordonate: presupun WGS 84 (EPSG:4326)")
    else:
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        if not src.IsSame(dst):
            tr = osr.CoordinateTransformation(src, dst)
    # ---------------------------------------------------------------- citirea, grupată pe etichete
    grupe, ordine, reparate = {}, [], 0
    lyr.ResetReading()
    for f in lyr:
        g = f.GetGeometryRef()
        if g is None or g.IsEmpty():
            continue
        et = str(f.GetField(z.coloana)) if z.coloana else str(f.GetFID())
        if dorite is not None and _norm_text(et) not in dorite:
            continue
        g = g.Clone()
        if tr:
            g.Transform(tr)
        if not g.IsValid():
            g = g.Buffer(0); reparate += 1
        if et not in grupe:
            grupe[et] = []; ordine.append(et)
        grupe[et].append(g)
    if not grupe:
        raise ValueError("Niciun poligon selectat" + (f" (filtrul „{z.filtru}”)." if z.filtru else "."))
    if reparate:
        log(f"   {reparate} geometrii invalide reparate (buffer 0)")

    def _uneste(lista):
        u = lista[0]
        for h in lista[1:]:
            u = u.Union(h)
        return u

    if z.unite:
        eticheta = z.nume or (" + ".join(ordine[:4]) + (f" + încă {len(ordine) - 4}" if len(ordine) > 4 else "")
                              if z.coloana else Path(z.gpkg).stem)
        out = [(eticheta, _uneste([g for et in ordine for g in grupe[et]]).ExportToWkt())]
    else:
        out = [(et, _uneste(grupe[et]).ExportToWkt()) for et in ordine]
    n_ent = sum(len(v) for v in grupe.values())
    log(f"   zona: {fisier} · strat „{lyr.GetName()}” · {n_ent} entități"
        + (f" · coloana „{z.coloana}”" if z.coloana else "")
        + (f" → o singură zonă: {out[0][0]}" if z.unite else f" → {len(out)} zone"))
    z.poligoane = out
    env = [math.inf, math.inf, -math.inf, -math.inf]
    for _, w in out:
        e = ogr.CreateGeometryFromWkt(w).GetEnvelope()  # minx, maxx, miny, maxy
        env = [min(env[0], e[0]), min(env[1], e[2]), max(env[2], e[1]), max(env[3], e[3])]
    z.bbox = (env[0] - z.marja, env[1] - z.marja, env[2] + z.marja, env[3] + z.marja)


def potriveste_zona(eticheta, etichete):
    """Indicele etichetei în listă, cu aceeași comparație tolerantă (majuscule, diacritice); None dacă lipsește."""
    n = _norm_text(eticheta)
    for i, e in enumerate(etichete):
        if _norm_text(e) == n:
            return i
    return None


# =====================================================================================
# Cubul și grila
# =====================================================================================
@dataclass
class Grila:
    """Fereastra din grila cubului corespunzătoare zonei (indici și georeferențiere)."""
    iy0: int
    iy1: int
    ix0: int
    ix1: int
    x: np.ndarray
    y: np.ndarray

    @property
    def transform(self):
        return (X_VEST + self.ix0 * PAS, PAS, 0.0, Y_NORD - self.iy0 * PAS, 0.0, -PAS)

    @property
    def extent(self):
        return [X_VEST + self.ix0 * PAS, X_VEST + self.ix1 * PAS, Y_NORD - self.iy1 * PAS, Y_NORD - self.iy0 * PAS]

    @property
    def forma(self):
        return (self.iy1 - self.iy0, self.ix1 - self.ix0)


def _store_cu_cache(store, folder):
    """Înveliș zarr 3 peste store-ul HTTP: (1) fiecare citire de chunk se reîncearcă separat la erori de rețea;
    (2) chunk-urile încheiate ale variabilelor de date se păstrează pe disc (vezi CACHE_DATE)."""
    import asyncio
    from zarr.storage import WrapperStore

    class StoreCuCache(WrapperStore):
        ct_frontiera: dict = {}                       # variabilă → indicele chunk-ului de timp care conține frontiera

        def _supports_sync_io(self):                  # forțează calea asincronă: altfel get_sync ar ocoli cache-ul
            return False

        def _cale(self, key):
            if folder is None:
                return None
            v, _, idx = key.partition("/")
            if v not in VARIABILE or not idx or v not in self.ct_frontiera or idx.startswith("."):
                return None
            try:
                ct = int(idx.split(".")[0])
            except ValueError:
                return None
            if ct >= self.ct_frontiera[v] - 1:        # chunk-ul curent și cel dinainte: încă se pot schimba
                return None
            return Path(folder) / v / idx

        async def get(self, key, prototype, byte_range=None):
            buf = await self._get(key, prototype, byte_range)
            if buf is None:                           # chunk inexistent: Zarr ar întoarce valoarea de umplere (0?)
                _inregistreaza_lipsa(key)
            return buf

        async def _get(self, key, prototype, byte_range=None):
            cale = self._cale(key) if byte_range is None else None
            if cale is not None and cale.exists() and time.time() - cale.stat().st_mtime < CACHE_ZILE * 86400:
                return prototype.buffer.from_bytes(cale.read_bytes())
            for inc in range(1, REINCERCARI + 1):
                try:
                    buf = await self._store.get(key, prototype, byte_range)
                    break
                except (KeyError, FileNotFoundError):
                    raise
                except Exception as e:  # noqa: BLE001  (aiohttp: ClientPayloadError, timeout, conexiune întreruptă)
                    if inc == REINCERCARI:
                        raise
                    log(f"   rețea: {type(e).__name__} la {key}; reîncerc în {2 ** inc} s ({inc}/{REINCERCARI - 1})")
                    await asyncio.sleep(2 ** inc)
            if cale is not None and buf is not None and not getattr(self, "_scriere_oprita", False):
                tmp = cale.with_name(f"{cale.name}.{os.getpid()}.{id(buf)}.tmp")
                try:
                    cale.parent.mkdir(parents=True, exist_ok=True)
                    tmp.write_bytes(buf.to_bytes())
                    os.replace(tmp, cale)
                except OSError as err:
                    if not getattr(self, "_scriere_oprita", False):
                        log(f"   [atenție] Cache local indisponibil ({err}). Continui din rețea.")
                    self._scriere_oprita = True
                finally:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
            return buf

    return StoreCuCache(store)


# ------------------------------------------------------------------ integritatea datelor (v5.1)
# Două defecte posibile ale cubului, mai ales la zilele recente:
#  (1) chunk-uri care LIPSESC: Zarr întoarce valoarea de umplere (0 dacă fill_value e 0 / null), deci 0 °C sau 0 mm false;
#  (2) chunk-uri existente dar NEACTUALIZATE: blocul are exact 0 în zilele încă nescrise.
# Protecția: (1) cheile lipsă sunt înregistrate de store la citire și blocurile lor devin NaN; (2) la temperaturi, o zi în
# care tot blocul (≥ 50 de pixeli valizi) are exact 0,0 devine NaN; la precipitații (unde 0 e real), în zilele recente
# se folosește masca găsită pe Tmax în același bloc. Raportul complet: clima/integritate.py (butonul „Verifică datele”).
CHUNKURI_LIPSA = set()          # (variabilă, chunk timp, chunk y, chunk x)
ZILE_SUSPECTE = {}              # (variabilă, chunk y, chunk x) → set de zile (datetime64[D]) cu blocul la exact 0
_MASCA_RECENTA = {}             # (chunk timp, cy, cx) → vector bool pe zilele chunk-ului (din Tmax)
MIN_PIXELI_BLOC = 50
_CORECTII = {"lipsa": 0, "zero": 0}


def _inregistreaza_lipsa(key):
    v, _, idx = str(key).partition("/")
    try:
        t, y, x = (int(c) for c in idx.replace("/", ".").split("."))
    except ValueError:
        return
    CHUNKURI_LIPSA.add((v, t, y, x))


def _blocuri_spatiale(g, cy_n=161, cx_n=324):
    """Blocurile de chunk (cy, cx) care intersectează fereastra g, cu feliile lor în coordonatele ferestrei."""
    for cy in range(g.iy0 // cy_n, (g.iy1 - 1) // cy_n + 1):
        for cx in range(g.ix0 // cx_n, (g.ix1 - 1) // cx_n + 1):
            r0, r1 = max(cy * cy_n, g.iy0) - g.iy0, min((cy + 1) * cy_n, g.iy1) - g.iy0
            c0, c1 = max(cx * cx_n, g.ix0) - g.ix0, min((cx + 1) * cx_n, g.ix1) - g.ix0
            yield cy, cx, slice(r0, r1), slice(c0, c1)


def zile_bloc_zero(bloc):
    """bloc (t, y, x): zilele în care TOȚI pixelii valizi (cel puțin MIN_PIXELI_BLOC) sunt exact 0."""
    fin = np.isfinite(bloc)
    nv = fin.sum(axis=(1, 2))
    nz = (bloc == 0).sum(axis=(1, 2))
    return (nv >= MIN_PIXELI_BLOC) & (nz == nv)


def _corecteaza_bucata(cub, v, arr, zile, ct, g, chunks):
    """NaN pe blocurile lipsă și pe zilele-bloc cu exact 0 (temperaturi; la precipitații: masca recentă din Tmax)."""
    _, cy_n, cx_n = chunks
    for cy, cx, rs, cs in _blocuri_spatiale(g, cy_n, cx_n):
        if (v, ct, cy, cx) in CHUNKURI_LIPSA:
            if np.isfinite(arr[:, rs, cs]).any():
                _CORECTII["lipsa"] += 1
            arr[:, rs, cs] = np.nan
            continue
        if v in ("max_temp", "min_temp"):
            z = zile_bloc_zero(arr[:, rs, cs])
        elif v == "precipitation" and _e_recent(cub, ct):
            z = _masca_recenta(cub, ct, cy, cx, zile, chunks)
        else:
            continue
        if z.any():
            arr[z, rs, cs] = np.nan
            _CORECTII["zero"] += int(z.sum())
            ZILE_SUSPECTE.setdefault((v, cy, cx), set()).update(zile[z].tolist())


def _e_recent(cub, ct):
    fr = FRONTIERE_ULTIME or {}
    if not fr:
        return False
    t0 = np.datetime64(str(cub.time.values[0])[:10], "D")
    ct_fr = int((min(fr.values()) - t0).astype(int)) // 90
    return ct >= ct_fr - 1                             # ultimele două chunk-uri de timp (~3–6 luni)


def _masca_recenta(cub, ct, cy, cx, zile, chunks):
    """Zilele în care blocul (cy, cx) al Tmax e exact 0 în chunk-ul de timp ct (citit o singură dată pe proces)."""
    ctn, cy_n, cx_n = chunks
    cheie = (ct, cy, cx)
    if cheie not in _MASCA_RECENTA:
        if ("max_temp", ct, cy, cx) in CHUNKURI_LIPSA:
            _MASCA_RECENTA[cheie] = None
        else:
            da = cub["max_temp"].isel(time=slice(ct * ctn, (ct + 1) * ctn), y=slice(cy * cy_n, (cy + 1) * cy_n),
                                      x=slice(cx * cx_n, (cx + 1) * cx_n))
            b = np.asarray(da.values, dtype="float32")
            _MASCA_RECENTA[cheie] = (da.time.values.astype("datetime64[D]"), zile_bloc_zero(b))
    m = _MASCA_RECENTA[cheie]
    if m is None:
        return np.ones(len(zile), bool)
    zl, z = m
    return np.isin(zile, zl[z])


def raport_corectii():
    """Textul pentru jurnal, dacă la citire s-au găsit date lipsă / blocuri la zero (o singură dată pe rulare)."""
    if not (_CORECTII["lipsa"] or _CORECTII["zero"]):
        return None
    zile = sorted({str(d) for zz in ZILE_SUSPECTE.values() for d in zz})
    t = (f"[atenție] datele cubului au goluri: {_CORECTII['lipsa']} bucăți de chunk lipsă și {_CORECTII['zero']} zile-bloc "
         f"cu valori exact 0 (nescrise); le-am tratat ca DATE LIPSĂ, nu ca 0.")
    if zile:
        t += f" Zile afectate: {zile[0]} … {zile[-1]} ({len(zile)}). Detalii: butonul „Verifică datele”."
    return t


def curata_cache(folder=None, limita_gb=None):
    """Ține cache-ul sub limită: șterge cele mai vechi chunk-uri până la 80 % din limită. → (GB rămași, fișiere șterse)"""
    folder = Path(folder or CACHE_DATE)
    limita = (CACHE_GB if limita_gb is None else limita_gb) * 1e9
    if not folder.exists():
        return 0.0, 0
    import re
    fis = []
    for f in folder.rglob("*"):
        if f.parent.name not in VARIABILE or not re.fullmatch(r"\d+\.\d+\.\d+", f.name):
            continue
        try:
            if f.is_file():
                st = f.stat()
                fis.append((st.st_mtime, st.st_size, f))
        except FileNotFoundError:
            continue
    total = sum(x[1] for x in fis)
    sterse = 0
    if total > limita:
        for _, m, f in sorted(fis):
            f.unlink(missing_ok=True); total -= m; sterse += 1
            if total <= 0.8 * limita:
                break
    return total / 1e9, sterse


def deschide(url: str = URL):
    """Deschide cubul (metadate consolidate) și returnează (cub, frontiere).
    Peste HTTP(S): reîncercări la deschidere, reîncercări pe chunk și cache-ul local al chunk-urilor încheiate."""
    import fsspec
    import xarray as xr
    try:
        import zarr
        zarr.config.set({"async.concurrency": CERERI_SIMULTANE})
    except Exception:  # noqa: BLE001
        pass
    t0 = time.perf_counter()
    store = None
    if "://" not in url:                               # cubul local (de test): același înveliș, fără cache
        try:
            from zarr.storage import LocalStore
            store = _store_cu_cache(LocalStore(url, read_only=True), None)
        except Exception:  # noqa: BLE001
            store = None
    if "://" in url:
        from zarr.storage import FsspecStore
        try:
            import aiohttp
            ck = {"timeout": aiohttp.ClientTimeout(total=300, sock_connect=30, sock_read=90)}
        except ImportError:
            ck = {}
        baza = FsspecStore.from_url(url, storage_options={"client_kwargs": ck} if ck else None, read_only=True)
        import hashlib
        namespace = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        store = _store_cu_cache(baza, Path(CACHE_DATE) / namespace) if CACHE_GB > 0 else baza
    for inc in range(1, REINCERCARI + 1):              # deschiderea: DNS / TLS / server ocupat → reîncearcă
        try:
            cub = xr.open_zarr(store if store is not None else url, consolidated=True)
            break
        except (FileNotFoundError, KeyError):
            raise
        except Exception as e:  # noqa: BLE001
            if inc == REINCERCARI:
                raise
            log(f"   nu pot deschide cubul ({type(e).__name__}); reîncerc în {5 * inc} s ({inc}/{REINCERCARI - 1})")
            time.sleep(5 * inc)
    fr = {v: np.datetime64(cub[f"last_{v}_time"].values, "D") for v in VARIABILE if f"last_{v}_time" in cub}
    if store is not None and hasattr(store, "ct_frontiera") and "://" in url:
        t0_cub = np.datetime64(str(cub.time.values[0])[:10], "D")
        store.ct_frontiera = {v: int((fr[v] - t0_cub).astype(int)) // int((cub[v].encoding.get("chunks") or (90,))[0])
                              for v in fr}
        gb, sterse = curata_cache()
        log(f"   cache local: {CACHE_DATE} · {gb:.1f} GB" + (f" (am șters {sterse} chunk-uri vechi)" if sterse else ""))
    log(f"Cub deschis în {time.perf_counter() - t0:.1f} s · frontiere: " + ", ".join(f"{k} {v}" for k, v in fr.items()))
    global FRONTIERE_ULTIME, STORE_ULTIM
    FRONTIERE_ULTIME = dict(fr)                       # pentru fișa de reproducere a rulării
    STORE_ULTIM = store                               # pentru verificarea existenței chunk-urilor (integritate.py)
    return cub, fr


def grila_zonei(cub, zona: Zona) -> Grila:
    x, y = cub.x.values, cub.y.values
    if zona.gpkg and not zona.poligoane:
        _citeste_poligoane(zona)
    if zona.punct:
        ix = int(np.abs(x - zona.punct[0]).argmin()); iy = int(np.abs(y - zona.punct[1]).argmin())
        return Grila(iy, iy + 1, ix, ix + 1, x[ix:ix + 1], y[iy:iy + 1])
    if zona.bbox:
        lo0, la0, lo1, la1 = zona.bbox
        ix0 = max(0, int(math.floor((lo0 - X_VEST) / PAS))); ix1 = min(len(x), int(math.ceil((lo1 - X_VEST) / PAS)))
        iy0 = max(0, int(math.floor((Y_NORD - la1) / PAS))); iy1 = min(len(y), int(math.ceil((Y_NORD - la0) / PAS)))
        if ix1 <= ix0 or iy1 <= iy0:
            raise ValueError("Zona nu intersectează grila României.")
    else:
        iy0, iy1, ix0, ix1 = 0, len(y), 0, len(x)
    g = Grila(iy0, iy1, ix0, ix1, x[ix0:ix1], y[iy0:iy1])
    zona._id = _rasterizeaza(zona, g) if zona.poligoane else None
    if zona.altitudine:
        _aplica_altitudine(zona, g)
    return g


RELIEF_HARTI = True          # umbrirea reliefului sub hărțile PNG (setare avansată)
RELIEF_FORTA = 0.45          # cât de mult întunecă umbrirea culorile (0 = deloc)


def umbrire(g: Grila):
    """Umbrirea reliefului (0…1) pe fereastra grilei g, din DEM-ul coregistrat: lumină din nord-vest la 45°,
    exagerare verticală 2 (pixelii de ~1 km aplatizează relieful). None dacă DEM-ul lipsește."""
    try:
        z = altitudine(g, "medie").astype("float64")
    except (FileNotFoundError, ValueError, RuntimeError):
        return None
    if not np.isfinite(z).any():
        return None
    from matplotlib.colors import LightSource
    z = np.where(np.isfinite(z), z, np.nanmean(z))
    lat = float(np.mean(g.y))
    dx, dy = PAS * 111320 * math.cos(math.radians(lat)), PAS * 110574
    return LightSource(azdeg=315, altdeg=45).hillshade(z, vert_exag=2, dx=dx, dy=dy)


def altitudine(g: Grila, banda="medie"):
    """Altitudinea (sau altă bandă a DEM-ului coregistrat) pe fereastra grilei g, pixel cu pixel aliniată cu cubul."""
    from osgeo import gdal
    if not Path(DEM_FISIER).exists():
        raise FileNotFoundError(f"Lipsește DEM-ul coregistrat: {DEM_FISIER}. Se generează o singură dată cu "
                                f"instrumente/pregateste_dem.bat (sau pregateste_dem.py).")
    ds = gdal.Open(DEM_FISIER)
    gt = ds.GetGeoTransform()
    if (not np.allclose(gt, (X_VEST, PAS, 0, Y_NORD, 0, -PAS), atol=1e-9, rtol=0)
            or not np.allclose(g.x, gt[0] + (np.arange(g.ix0, g.ix1) + 0.5) * PAS, atol=1e-6, rtol=0)
            or not np.allclose(g.y, gt[3] - (np.arange(g.iy0, g.iy1) + 0.5) * PAS, atol=1e-6, rtol=0)
            or g.ix1 > ds.RasterXSize or g.iy1 > ds.RasterYSize):
        raise ValueError(f"DEM-ul {Path(DEM_FISIER).name} nu e pe grila cubului (geotransform {gt}); "
                         f"regenerați-l cu instrumente/pregateste_dem.py.")
    b = ds.GetRasterBand(DEM_BENZI[banda] if isinstance(banda, str) else int(banda))
    a = b.ReadAsArray(g.ix0, g.iy0, g.ix1 - g.ix0, g.iy1 - g.iy0).astype("float32")
    nd = b.GetNoDataValue()
    if nd is not None and np.isfinite(nd):
        a[a == nd] = np.nan
    ds = None
    return a


def _aplica_altitudine(zona: Zona, g: Grila):
    a, b = zona.altitudine
    alt = altitudine(g)
    ok = np.isfinite(alt)
    if a is not None:
        ok &= alt >= a
    if b is not None:
        ok &= alt <= b
    inainte = int((zona._id > 0).sum()) if zona._id is not None else int(np.isfinite(alt).sum())
    zona._id = np.where(ok, zona._id, 0).astype("int32") if zona._id is not None else ok.astype("int32")
    n = int((zona._id > 0).sum())
    log(f"   filtru de altitudine ({zona._text_altitudine()[3:]}): {n} pixeli din {inainte} "
        f"({100 * n / max(inainte, 1):.0f} %)")
    if n == 0:
        raise ValueError(f"Niciun pixel al zonei nu respectă filtrul ({zona._text_altitudine()[3:]}). "
                         f"Lărgiți intervalul de altitudine sau alegeți altă zonă.")


def _driver_vector_memorie():
    """GDAL ≥ 3.11: „MEM” are și capacitate vectorială („Memory” e depreciat); în GDAL mai vechi, MEM e doar raster."""
    from osgeo import gdal, ogr
    d = ogr.GetDriverByName("MEM")
    if d is not None and d.GetMetadataItem(gdal.DCAP_VECTOR) == "YES":
        return d
    return ogr.GetDriverByName("Memory")


def _rasterizeaza(zona: Zona, g: Grila) -> np.ndarray:
    """Grila de id-uri (1…N) ale poligoanelor; regula „centrul pixelului”, cu ALL_TOUCHED pentru poligoanele mici."""
    from osgeo import gdal, ogr, osr
    ny, nx = g.forma
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326); srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    def ras(indici, all_touched):
        mem = _driver_vector_memorie().CreateDataSource("z")
        lyr = mem.CreateLayer("z", srs, ogr.wkbMultiPolygon)
        lyr.CreateField(ogr.FieldDefn("zid", ogr.OFTInteger))
        for i in indici:
            f = ogr.Feature(lyr.GetLayerDefn()); f.SetField("zid", i + 1)
            f.SetGeometry(ogr.CreateGeometryFromWkt(zona.poligoane[i][1])); lyr.CreateFeature(f)
        ds = gdal.GetDriverByName("MEM").Create("", nx, ny, 1, gdal.GDT_Int32)
        ds.SetGeoTransform(g.transform)
        gdal.RasterizeLayer(ds, [1], lyr, options=["ATTRIBUTE=zid"] + (["ALL_TOUCHED=TRUE"] if all_touched else []))
        # ReadRaster (octeți brute) în loc de ReadAsArray: nu depinde de gdal_array / versiunea numpy
        buf = ds.GetRasterBand(1).ReadRaster(0, 0, nx, ny, buf_type=gdal.GDT_Int32)
        return np.frombuffer(buf, dtype="<i4").reshape(ny, nx).copy()

    zid = ras(range(len(zona.poligoane)), False)
    lipsa = [i for i in range(len(zona.poligoane)) if not (zid == i + 1).any()]
    if lipsa:
        extra = ras(lipsa, True)
        zid = np.where((zid == 0) & (extra > 0), extra, zid)
        log(f"   {len(lipsa)} poligoane mai mici decât un pixel: rasterizate cu ALL_TOUCHED")
    return zid


# =====================================================================================
# Timp: perioade, frontieră, citire
# =====================================================================================
def perioada(an: int, sezon) -> tuple[np.datetime64, np.datetime64, str]:
    """(început, sfârșit inclusiv, etichetă). Sezonul poate fi un nume din SEZOANE,
    o pereche de luni (4, 9) sau o pereche de date ("04-01", "09-30")."""
    if isinstance(sezon, str) and sezon in SEZOANE:
        sezon_luni = SEZOANE[sezon]; et = f"{an} {sezon}"
    else:
        sezon_luni = sezon; et = f"{an} {sezon[0]}–{sezon[1]}"
    a, b = sezon_luni
    if isinstance(a, str):
        d0 = np.datetime64(f"{an}-{a}"); d1 = np.datetime64(f"{an}-{b}")
        if d1 < d0:
            d0 = np.datetime64(f"{an - 1}-{a}")
        return d0, d1, et
    an0 = an - 1 if a > b else an          # sezon peste Anul Nou (DJF): decembrie din anul precedent
    d0 = np.datetime64(f"{an0}-{a:02d}-01")
    d1 = (np.datetime64(f"{an}-{b:02d}", "M") + 1).astype("datetime64[D]") - 1
    return d0, d1, et


def estimeaza_cost(cub, var, d0, d1, g: Grila):
    """Câte chunk-uri și câți MB (aprox.) se vor citi — utilitate didactică."""
    ct, cy, cx = cub[var].encoding.get("chunks", (90, 161, 324))
    t0 = int((d0 - np.datetime64(str(cub.time.values[0])[:10])).astype(int))
    t1 = int((d1 - np.datetime64(str(cub.time.values[0])[:10])).astype(int))
    nt = t1 // ct - t0 // ct + 1
    ny = (g.iy1 - 1) // cy - g.iy0 // cy + 1
    nx = (g.ix1 - 1) // cx - g.ix0 // cx + 1
    mb = {"max_temp": 5.4, "min_temp": 5.4, "precipitation": 2.3}.get(var, 5.0)
    return nt * ny * nx, nt * ny * nx * mb


def citeste(cub, variabile, d0, d1, g: Grila) -> tuple[dict, np.ndarray]:
    """Citește variabilele pe [d0, d1] × fereastra grilei, cu reîncercări la erori de rețea.
    Returnează ({var: ndarray float32 (t, y, x)}, zile datetime64[D])."""
    # Citire pe bucăți aliniate la chunk-urile de timp, direct într-o matrice alocată o singură dată: vârful de memorie
    # e datele + un chunk, nu dublul datelor (cât cerea asamblarea dask a întregii perioade; măsurat în v5.1).
    out = {}
    zile = None
    t_cub = cub.time.values.astype("datetime64[D]")
    for v in variabile:
        da = cub[v].sel(time=slice(str(d0), str(d1))).isel(y=slice(g.iy0, g.iy1), x=slice(g.ix0, g.ix1))
        zile = da.time.values.astype("datetime64[D]")
        nt = len(zile)
        arr = np.empty((nt,) + tuple(da.shape[1:]), dtype="float32")
        ct = int((cub[v].encoding.get("chunks") or (90,))[0])
        i0 = int(np.searchsorted(t_cub, zile[0])) if nt else 0
        pos = 0
        while pos < nt:
            fin = min(nt, pos + ct - (i0 + pos) % ct)
            bucata = da.isel(time=slice(pos, fin))
            for inc in range(1, REINCERCARI + 1):
                try:
                    arr[pos:fin] = bucata.values
                    break
                except Exception as e:  # noqa: BLE001
                    if inc == REINCERCARI:
                        raise
                    log(f"   eroare de rețea ({type(e).__name__}); reîncerc în {10 * inc} s ({inc}/{REINCERCARI - 1})")
                    time.sleep(10 * inc)
            _corecteaza_bucata(cub, v, arr[pos:fin], zile[pos:fin], (i0 + pos) // ct, g,
                               (ct, *[int(c) for c in (cub[v].encoding.get("chunks") or (90, 161, 324))[1:]]))
            pos = fin
        out[v] = arr
    return out, zile


# =====================================================================================
# INDICATORI (funcții pe o perioadă: {var: (t, y, x)} → hartă 2D)
# Definițiile urmează indicii ETCCDI (Expert Team on Climate Change Detection and Indices).
# =====================================================================================
def _valid(arr):
    return np.isfinite(arr)


def i_medie(d, zile, var):
    """Media zilnică a variabilei pe perioadă (ex. Tmax medie a verii)."""
    return np.nanmean(d[var], axis=0)


def i_suma(d, zile, var):
    """Suma pe perioadă (ex. precipitații totale, mm). ETCCDI PRCPTOT folosește doar zilele ≥ 1 mm; aici: toate zilele."""
    return np.nansum(d[var], axis=0) * np.where(_valid(d[var]).any(axis=0), 1, np.nan)


def i_tmedie(d, zile):
    """Temperatura medie zilnică aproximată: (Tmax + Tmin) / 2."""
    return np.nanmean((d["max_temp"] + d["min_temp"]) / 2, axis=0)


def i_zile_peste(d, zile, var, prag, strict=False):
    """Numărul de zile cu var ≥ prag (sau > prag dacă strict=True).
    Tmax ≥ 30 °C = zi tropicală (ANM) · Tmax ≥ 35 °C = zi caniculară · Tmax > 25 °C = SU25 (ETCCDI)."""
    a = d[var]
    n = (a > prag) if strict else (a >= prag)
    return np.where(_valid(a).any(axis=0), n.sum(axis=0).astype("float32"), np.nan)


def i_zile_sub(d, zile, var, prag, strict=True):
    """Numărul de zile cu var < prag (ex. Tmin < 0 °C = zi de îngheț, FD în ETCCDI)."""
    a = d[var]
    n = (a < prag) if strict else (a <= prag)
    return np.where(_valid(a).any(axis=0), n.sum(axis=0).astype("float32"), np.nan)


def i_amplitudine_medie(d, zile):
    """Amplitudinea termică diurnă medie: media(Tmax − Tmin) (DTR în ETCCDI)."""
    return np.nanmean(d["max_temp"] - d["min_temp"], axis=0)


def i_amplitudine_absoluta(d, zile):
    """Amplitudinea extremă a perioadei: max(Tmax) − min(Tmin) (ETCCDI: TXx − TNn)."""
    return np.nanmax(d["max_temp"], axis=0) - np.nanmin(d["min_temp"], axis=0)


def i_gdd(d, zile, baza=10.0):
    """Grade-zile de creștere: Σ max((Tmax + Tmin)/2 − bază, 0). Baza: 10 °C porumb, vița-de-vie; 5 °C păioase."""
    tm = (d["max_temp"] + d["min_temp"]) / 2
    g = np.clip(tm - baza, 0, None)
    return np.where(_valid(tm).any(axis=0), np.nansum(g, axis=0), np.nan)


def _prima_ultima(mask, zile, valid):
    """Indicii primei și ultimei zile True pe axa timpului (NaN dacă nu există)."""
    nt = mask.shape[0]
    are = mask.any(axis=0)
    prima = np.where(are, mask.argmax(axis=0), -1)
    ultima = np.where(are, nt - 1 - mask[::-1].argmax(axis=0), -1)
    return prima, ultima, are & valid.any(axis=0)


def _doy(zile, idx):
    an = zile.astype("datetime64[Y]")
    doy = (zile - an.astype("datetime64[D]")).astype(int) + 1
    return np.where(idx >= 0, doy[np.clip(idx, 0, len(zile) - 1)], np.nan).astype("float32")


def i_ultimul_inghet(d, zile, prag=0.0):
    """Ziua din an (DOY) a ultimului îngheț de primăvară: ultima zi cu Tmin < prag între 1 ianuarie și 30 iunie.
    NaN = fără îngheț în acest interval. Perioada trebuie să înceapă cel târziu la 1 ianuarie (SEZON = "anual")."""
    a = d["min_temp"]
    jum = (zile.astype("datetime64[M]").astype(int) % 12) < 6
    m = (a < prag) & jum[:, None, None]
    _, ultima, ok = _prima_ultima(m, zile, _valid(a))
    return np.where(ok, _doy(zile, ultima), np.nan)


def i_primul_inghet(d, zile, prag=0.0):
    """Ziua din an a primului îngheț de toamnă: prima zi cu Tmin < prag între 1 iulie și 31 decembrie."""
    a = d["min_temp"]
    jum2 = (zile.astype("datetime64[M]").astype(int) % 12) >= 6
    m = (a < prag) & jum2[:, None, None]
    prima, _, ok = _prima_ultima(m, zile, _valid(a))
    return np.where(ok, _doy(zile, prima), np.nan)


def i_sezon_fara_inghet(d, zile, prag=0.0):
    """Durata sezonului fără îngheț (zile) = zilele STRICT dintre ultimul îngheț de primăvară și primul de toamnă:
    primul îngheț − ultimul îngheț − 1 (ex. îngheț în ziua 100 și în ziua 101 → 0 zile fără îngheț).
    Un semestru fără niciun îngheț NU înseamnă date lipsă: sezonul începe la 1 ianuarie (ultimul îngheț = ziua 0)
    sau ține până la 31 decembrie (primul îngheț = ziua 366/367). Altfel, anii cei mai calzi ar fi excluși din medie
    și durata medie ar ieși subestimată exact în zonele calde (bias de cenzurare)."""
    a = d["min_temp"]
    an = zile[0].astype("datetime64[Y]")
    calendar = np.arange(an.astype("datetime64[D]"), (an + np.timedelta64(1, "Y")).astype("datetime64[D]"))
    if not np.array_equal(zile, calendar):
        return np.full(a.shape[1:], np.nan, dtype="float32")
    are_date = _valid(a).any(axis=0)
    ult = i_ultimul_inghet(d, zile, prag)
    prm = i_primul_inghet(d, zile, prag)
    ult = np.where(np.isfinite(ult), ult, 0.0)
    prm = np.where(np.isfinite(prm), prm, float(len(zile)) + 1.0)
    doy = np.arange(1, len(zile) + 1)[:, None, None]
    # Un îngheț într-o zi lipsă dintre cele două borne ar scurta sezonul.
    necunoscut = (~np.isfinite(a) & (doy > ult) & (doy < prm)).any(axis=0)
    return np.where(are_date & ~necunoscut, np.maximum(prm - ult - 1, 0), np.nan).astype("float32")


def i_cdd(d, zile, prag=1.0):
    """CDD (ETCCDI): cel mai lung șir de zile consecutive cu precipitații < prag (1 mm)."""
    p = d["precipitation"]
    sec = (p < prag) & _valid(p)
    cur = np.zeros(p.shape[1:], dtype="int32"); best = np.zeros_like(cur)
    for t in range(p.shape[0]):
        cur = np.where(sec[t], cur + 1, 0)
        best = np.maximum(best, cur)
    return np.where(_valid(p).any(axis=0), best.astype("float32"), np.nan)


def i_cwd(d, zile, prag=1.0):
    """CWD (ETCCDI): cel mai lung șir de zile consecutive cu precipitații ≥ prag (1 mm). O zi lipsă rupe șirul."""
    p = d["precipitation"]
    ud = (p >= prag) & _valid(p)
    cur = np.zeros(p.shape[1:], dtype="int32"); best = np.zeros_like(cur)
    for t in range(p.shape[0]):
        cur = np.where(ud[t], cur + 1, 0)
        best = np.maximum(best, cur)
    return np.where(_valid(p).any(axis=0), best.astype("float32"), np.nan)


def i_sdii(d, zile, prag=1.0):
    """SDII (ETCCDI): intensitatea medie a unei zile ploioase = suma P în zilele cu P ≥ prag / numărul acestor zile (mm/zi).
    Fără nicio zi ploioasă indicele este nedefinit (NaN), nu 0: „nu a plouat” nu înseamnă „a plouat cu 0 mm/zi”."""
    p = d["precipitation"]
    ud = (p >= prag) & _valid(p)
    w = ud.sum(axis=0)
    s = np.where(ud, p, 0.0).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(w > 0, s / w, np.nan).astype("float32")


def i_prcptot(d, zile, prag=1.0):
    """PRCPTOT (ETCCDI): suma precipitațiilor din zilele ploioase (P ≥ prag). Zilele sub prag (urme, 0,3 mm) nu intră."""
    p = d["precipitation"]
    ud = (p >= prag) & _valid(p)
    return np.where(_valid(p).any(axis=0), np.where(ud, p, 0.0).sum(axis=0), np.nan).astype("float32")


def i_rxnday(d, zile, n=1):
    """Rx1day / Rx5day (ETCCDI): cantitatea maximă de precipitații în n zile consecutive (mm)."""
    if not isinstance(n, (int, np.integer)) or n < 1:
        raise ValueError("RxNday cere un număr întreg pozitiv de zile.")
    if n > len(zile):
        return np.full(d["precipitation"].shape[1:], np.nan, dtype="float32")
    P = d["precipitation"]
    T = P.shape[0] - n + 1
    out = np.full(P.shape[1:], np.nan, dtype="float32")
    for r0 in range(0, P.shape[1], 64):        # pe benzi de rânduri: temporarele rămân mici (v5.1: −1,5 GB pe țară)
        p = np.nan_to_num(P[:, r0:r0 + 64], nan=0.0)
        s = p[:T].copy()                       # sumele ferestrelor de n zile, prin deplasări (fără sumă cumulată)
        for k in range(1, n):
            s += p[k:k + T]
        out[r0:r0 + 64] = np.where(np.isfinite(P[:, r0:r0 + 64]).any(axis=0), s.max(axis=0), np.nan)
    return out


def i_de_martonne(d, zile):
    """Indicele de ariditate De Martonne: I = P_an / (T + 10).
    P_an = precipitațiile perioadei aduse la un an (× 365,25 / nr. zile), T = (Tmax + Tmin)/2 medie.
    Clase: < 10 arid · 10–20 semiarid · 20–24 mediteranean · 24–28 semiumed · 28–35 umed · > 35 foarte umed.
    Aceleași zile valide pentru P și T (intersecția celor 3 variabile). Pentru T ≤ −10 °C numitorul e ≤ 0 și indicele
    nu are sens (ar ieși negativ și ar fi clasat „arid”): acolo rezultatul este NaN."""
    tm = (d["max_temp"] + d["min_temp"]) / 2
    ok = np.isfinite(d["precipitation"]) & np.isfinite(tm)
    nz = ok.sum(axis=0)
    p_an = np.where(ok, d["precipitation"], 0.0).sum(axis=0) * 365.25 / np.maximum(nz, 1)
    t = np.where(ok, tm, 0.0).sum(axis=0) / np.maximum(nz, 1)
    numitor = np.where((nz > 0) & (t > -10.0), t + 10.0, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (p_an / numitor).astype("float32")


# =====================================================================================
# INDICATORI CU PERIOADĂ DE BAZĂ (v5.0 livrarea B): percentile ETCCDI și SPI / SPEI
# Au nevoie de date din afara anului calculat: praguri pe zi calendaristică sau parametrii unei distribuții,
# estimate pe perioada de bază (implicit normala OMM 1991–2020). Le pregătește `pregatire`, o singură dată pe
# grilă și sezon (cu cache pe disc), iar funcția indicatorului le primește în argumentul `_ctx`.
# Toată statistica e scrisă de mână (mediul nu include scipy) și verificată în instrumente/teste_cunoscute.py.
# =====================================================================================
_ZILE_CUMULATE = np.array([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334])


def zi_365(zile):
    """Indicele zilei într-un an de 365 de zile (0 = 1 ianuarie … 364 = 31 decembrie).
    29 februarie primește indicele lui 28 februarie (pragul acelei zile)."""
    z = np.asarray(zile, dtype="datetime64[D]")
    luna_m = z.astype("datetime64[M]")
    luna = luna_m.astype(int) % 12
    zi = (z - luna_m.astype("datetime64[D]")).astype(int)
    return np.minimum(_ZILE_CUMULATE[luna] + zi, np.where(luna == 1, 58, 364))


def _e_29_februarie(zile):
    z = np.asarray(zile, dtype="datetime64[D]")
    luna_m = z.astype("datetime64[M]")
    return (luna_m.astype(int) % 12 == 1) & ((z - luna_m.astype("datetime64[D]")).astype(int) == 28)


def cuantila_t8(x, q):
    """Cuantila q (0…1) pe axa 0, ignorând NaN, după definiția 8 din Hyndman & Fan (1996) — aceeași ca în
    climdex.pcic / ClimPACT (ETCCDI) și ca np.percentile(method="median_unbiased"). Poziția (de la 1):
    h = (n + 1/3)·q + 1/3; sub 1 → minimul, peste n → maximul, altfel interpolare liniară între vecini."""
    x = np.asarray(x)
    if not np.issubdtype(x.dtype, np.floating):
        x = x.astype("float64")
    s = np.sort(x, axis=0)            # NaN ajung la sfârșit; sortarea în tipul datelor (float32: o copie, nu trei)
    n = np.isfinite(s).sum(axis=0)
    h = (n + 1.0 / 3.0) * q + 1.0 / 3.0
    j = np.floor(h).astype(int)
    ult = np.maximum(n - 1, 0)
    lo = np.clip(j - 1, 0, ult); hi = np.clip(j, 0, ult)
    f64 = lambda a: a.astype("float64")                       # noqa: E731  (interpolarea rămâne în float64)
    xl = f64(np.take_along_axis(s, lo[None], 0)[0]); xh = f64(np.take_along_axis(s, hi[None], 0)[0])
    xmax = f64(np.take_along_axis(s, ult[None], 0)[0])
    v = np.where(h < 1, f64(s[0]), np.where(h >= n, xmax, xl + (h - j) * (xh - xl)))
    return np.where(n > 0, v, np.nan)


def praguri_zilnice(X, zile, q, fereastra=5, minim=0.9):
    """Pragul percentilei q pentru fiecare zi calendaristică (365), pe o fereastră de `fereastra` zile centrată pe ea,
    din toți anii de bază: X (zile consecutive ale anilor de bază, pixeli) → (365, pixeli).
    29 februarie se scoate (28 februarie și 1 martie devin vecine). Pixelii cu mai puțin de `minim` din
    valorile ferestrei (de ex. 0,9 × 150) primesc NaN."""
    ne29 = ~_e_29_februarie(zile)
    X = np.asarray(X)[ne29]
    T = X.shape[0]
    if T % 365:
        raise ValueError("Perioada de bază trebuie să conțină ani întregi.")
    n_ani, jum = T // 365, fereastra // 2
    out = np.full((365,) + X.shape[1:], np.nan, dtype="float32")
    for d in range(365):
        idx = (np.arange(n_ani)[:, None] * 365 + d + np.arange(-jum, jum + 1)[None, :]).ravel()
        idx = idx[(idx >= 0) & (idx < T)]                      # la capetele bazei fereastra e trunchiată
        sub = X[idx]
        n = np.isfinite(sub).sum(axis=0)
        out[d] = np.where(n >= minim * len(idx), cuantila_t8(sub, q), np.nan)
    return out


def _verifica_baza(cub, fr, variabile, baza):
    a, b = int(baza[0]), int(baza[1])
    inceput = int(str(cub.time.values[0])[:4])
    frontiera = min(fr[v] for v in variabile)
    ultim = int(str(frontiera)[:4]) - (0 if str(frontiera)[5:] == "12-31" else 1)
    if b - a + 1 < 10:
        raise ValueError(f"Perioada de bază {a}–{b} e prea scurtă: sunt necesari cel puțin 10 ani (OMM recomandă 30).")
    if a < inceput or b > ultim:
        raise ValueError(f"Perioada de bază {a}–{b} nu este acoperită complet de date ({inceput}–{ultim}). "
                         f"Alegeți ani între {inceput} și {ultim}.")


def _cheie_baza(*parti):
    import hashlib
    return hashlib.md5(json.dumps([*parti, PRAG_VALID, URL], default=str).encode()).hexdigest()[:12]


def _blocuri(g: Grila, ty=161, tx=81):
    """Ferestre de lucru aliniate la chunk-urile cubului (161 × 324): memoria rămâne sub ~0,6 GB pe bloc."""
    for gy in range(g.iy0 // ty * ty, g.iy1, ty):
        for gx in range(g.ix0 // tx * tx, g.ix1, tx):
            y0, y1, x0, x1 = max(gy, g.iy0), min(gy + ty, g.iy1), max(gx, g.ix0), min(gx + tx, g.ix1)
            yield Grila(y0, y1, x0, x1, g.x[x0 - g.ix0:x1 - g.ix0], g.y[y0 - g.iy0:y1 - g.iy0])


def _salveaza_npy(fis, a):
    tmp = fis.with_name(fis.name + f".{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        np.save(f, a)
    os.replace(tmp, fis)


def praguri_percentila(cub, fr, var, q, baza, g: Grila, fereastra=5):
    """Pragurile (365, y, x) ale percentilei q pe zi calendaristică, pentru fereastra grilei g, din perioada de bază.
    Calculate o singură dată și păstrate în rezultate/_cache/praguri/ (citite apoi direct de pe disc, cu memmap)."""
    _verifica_baza(cub, fr, (var,), baza)
    fis = dir_cache("praguri") / (f"{var}_p{q * 100:g}_{baza[0]}-{baza[1]}_"
                                  f"{_cheie_baza(var, q, list(baza), fereastra, g.iy0, g.iy1, g.ix0, g.ix1)}.npy")
    if fis.exists():
        log(f"   praguri p{q * 100:g} {VAR_SCURT.get(var, var)} {baza[0]}–{baza[1]}: din cache ({fis.name})")
        return np.load(fis, mmap_mode="r")
    d0, d1 = np.datetime64(f"{baza[0]}-01-01"), np.datetime64(f"{baza[1]}-12-31")
    ny, nx = g.forma
    out = np.full((365, ny, nx), np.nan, dtype="float32")
    blocuri = list(_blocuri(g))
    log(f"   praguri p{q * 100:g} {VAR_SCURT.get(var, var)} pe zi calendaristică, baza {baza[0]}–{baza[1]}, "
        f"fereastră de {fereastra} zile: {len(blocuri)} blocuri (o singură dată; apoi din cache)")
    t0 = time.perf_counter()
    for k, b in enumerate(blocuri, 1):
        d, zile = citeste(cub, (var,), d0, d1, b)
        X = d[var].reshape(len(zile), -1); del d
        P = praguri_zilnice(X, zile, q, fereastra, PRAG_VALID); del X
        out[:, b.iy0 - g.iy0:b.iy1 - g.iy0, b.ix0 - g.ix0:b.ix1 - g.ix0] = P.reshape(365, b.iy1 - b.iy0, b.ix1 - b.ix0)
        log(f"      bloc {k}/{len(blocuri)} în {time.perf_counter() - t0:.0f} s")
    _salveaza_npy(fis, out)
    del out
    return np.load(fis, mmap_mode="r")                       # mapat de pe disc, nu ținut în RAM (v5.1)


def prag_zile_umede(cub, fr, q, baza, g: Grila, zi_uda=1.0):
    """Percentila q a precipitațiilor zilelor ploioase (≥ zi_uda mm) din perioada de bază, pe pixel (R95p, R99p).
    Sub 20 de zile ploioase în bază → NaN."""
    var = "precipitation"
    _verifica_baza(cub, fr, (var,), baza)
    fis = dir_cache("praguri") / (f"p_umed_p{q * 100:g}_{baza[0]}-{baza[1]}_"
                                  f"{_cheie_baza(q, list(baza), zi_uda, g.iy0, g.iy1, g.ix0, g.ix1)}.npy")
    if fis.exists():
        log(f"   prag p{q * 100:g} al zilelor ploioase {baza[0]}–{baza[1]}: din cache")
        return np.load(fis)
    d0, d1 = np.datetime64(f"{baza[0]}-01-01"), np.datetime64(f"{baza[1]}-12-31")
    out = np.full(g.forma, np.nan, dtype="float32")
    blocuri = list(_blocuri(g, tx=54))
    log(f"   prag p{q * 100:g} al zilelor ploioase (≥ {zi_uda:g} mm), baza {baza[0]}–{baza[1]}: {len(blocuri)} blocuri")
    for b in blocuri:
        d, zile = citeste(cub, (var,), d0, d1, b)
        X = d[var]; del d
        X[~(X >= zi_uda)] = np.nan                                 # doar zilele ploioase (NaN rămân NaN)
        n = np.isfinite(X).sum(axis=0)
        out[b.iy0 - g.iy0:b.iy1 - g.iy0, b.ix0 - g.ix0:b.ix1 - g.ix0] = np.where(n >= 20, cuantila_t8(X, q), np.nan)
        del X
    _salveaza_npy(fis, out)
    return out


# ------------------------------------------------------------------ indicatorii pe percentile (ETCCDI)
INDICI_PCT = {"tx90p": ("max_temp", "peste", 0.9), "tx10p": ("max_temp", "sub", 0.1),
              "tn90p": ("min_temp", "peste", 0.9), "tn10p": ("min_temp", "sub", 0.1)}
VAR_SCURT = {"max_temp": "Tmax", "min_temp": "Tmin", "precipitation": "P"}


def _depasiri(d, zile, var, sens, prag):
    a = d[var]
    thr = np.asarray(prag[zi_365(zile)])                   # pragul fiecărei zile din calendar → (t, y, x)
    ok = np.isfinite(a) & np.isfinite(thr)
    with np.errstate(invalid="ignore"):
        e = ((a > thr) if sens == "peste" else (a < thr)) & ok
    return e, ok


def i_pct_zile(d, zile, indice, baza_de, baza_pana, _ctx=None):
    """TX90p / TX10p / TN90p / TN10p (ETCCDI): procentul zilelor în care Tmax (Tmin) depășește percentila 90
    (coboară sub percentila 10) a zilei calendaristice respective, estimată pe perioada de bază."""
    var, sens, _ = INDICI_PCT[indice]
    e, ok = _depasiri(d, zile, var, sens, _ctx["prag"])
    n = ok.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, 100.0 * e.sum(axis=0) / np.maximum(n, 1), np.nan)


def _zile_in_siruri(e, durata):
    """Numărul zilelor care fac parte din șiruri de cel puțin `durata` zile consecutive cu e adevărat."""
    run = np.zeros(e.shape[1:], dtype="int32"); tot = np.zeros(e.shape[1:], dtype="float32")
    for k in range(e.shape[0]):
        run = np.where(e[k], run + 1, 0)
        tot += np.where(run == durata, durata, 0) + np.where(run > durata, 1, 0)
    return tot


def i_wsdi(d, zile, durata, baza_de, baza_pana, _ctx=None):
    """WSDI (ETCCDI): zilele aflate în șiruri de cel puțin `durata` (6) zile consecutive cu Tmax > p90 al zilei."""
    e, ok = _depasiri(d, zile, "max_temp", "peste", _ctx["prag"])
    return np.where(ok.any(axis=0), _zile_in_siruri(e, int(durata)), np.nan)


def i_csdi(d, zile, durata, baza_de, baza_pana, _ctx=None):
    """CSDI (ETCCDI): zilele aflate în șiruri de cel puțin `durata` (6) zile consecutive cu Tmin < p10 al zilei."""
    e, ok = _depasiri(d, zile, "min_temp", "sub", _ctx["prag"])
    return np.where(ok.any(axis=0), _zile_in_siruri(e, int(durata)), np.nan)


def i_rnnp(d, zile, percentila, baza_de, baza_pana, _ctx=None):
    """R95p / R99p (ETCCDI): suma precipitațiilor din zilele cu P > percentila 95 (99) a zilelor ploioase din bază."""
    p = d["precipitation"]; thr = _ctx["prag"]
    with np.errstate(invalid="ignore"):
        s = np.where(p > thr[None], p, 0.0).sum(axis=0)
    return np.where(np.isfinite(p).any(axis=0) & np.isfinite(thr), s, np.nan)


def i_rnnptot(d, zile, percentila, baza_de, baza_pana, _ctx=None):
    """R95pTOT (ETCCDI): 100 · R95p / PRCPTOT — ce parte din precipitațiile zilelor ploioase vine din zilele extreme.
    Fără nicio zi ≥ 1 mm (PRCPTOT = 0), raportul nu e definit → NaN."""
    p = d["precipitation"]; thr = _ctx["prag"]
    with np.errstate(invalid="ignore", divide="ignore"):
        extrem = np.where(p > thr[None], p, 0.0).sum(axis=0)
        tot = np.where(p >= 1.0, p, 0.0).sum(axis=0)
        return np.where(np.isfinite(p).any(axis=0) & np.isfinite(thr) & (tot > 0), 100.0 * extrem / tot, np.nan)


def _preg_pct(cub, fr, g, sezon, ind):
    var, _, q = INDICI_PCT[ind.params["indice"]] if "indice" in ind.params else \
        (("max_temp", "peste", 0.9) if ind.functie is i_wsdi else ("min_temp", "sub", 0.1))
    return {"prag": praguri_percentila(cub, fr, var, q, (ind.params["baza_de"], ind.params["baza_pana"]), g)}


def _preg_umed(cub, fr, g, sezon, ind):
    q = float(ind.params["percentila"]) / 100.0
    return {"prag": prag_zile_umede(cub, fr, q, (ind.params["baza_de"], ind.params["baza_pana"]), g)}


# ------------------------------------------------------------------ evapotranspirația și bilanțul hidric
def radiatia_extraterestra(lat_grade, zi_an):
    """Ra (MJ m⁻² zi⁻¹), FAO-56 ec. 21–25: din latitudine și ziua din an (1…366)."""
    phi = np.deg2rad(np.asarray(lat_grade, dtype="float64"))
    J = np.asarray(zi_an, dtype="float64")
    dr = 1 + 0.033 * np.cos(2 * np.pi * J / 365)
    dl = 0.409 * np.sin(2 * np.pi * J / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dl), -1, 1))
    return 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dl) + np.cos(phi) * np.cos(dl) * np.sin(ws))


def pet_hargreaves(tmax, tmin, zile, lat):
    """PET zilnică (mm/zi), Hargreaves–Samani (FAO-56 ec. 52): 0,0023 · (Tmed + 17,8) · √(Tmax − Tmin) · Ra,
    cu Ra exprimată în mm/zi (× 0,408). tmax, tmin: (t, y, x); lat: latitudinile rândurilor (y,)."""
    z = np.asarray(zile, dtype="datetime64[D]")
    J = (z - z.astype("datetime64[Y]").astype("datetime64[D]")).astype(int) + 1
    Ra = radiatia_extraterestra(np.asarray(lat)[None, :, None], J[:, None, None])
    tm = (tmax + tmin) / 2.0
    with np.errstate(invalid="ignore"):
        pet = 0.0023 * 0.408 * Ra * (tm + 17.8) * np.sqrt(np.maximum(tmax - tmin, 0.0))
    return np.maximum(pet, 0.0)


def i_pet(d, zile, _ctx=None):
    """Evapotranspirația potențială pe perioadă (Hargreaves, mm): suma valorilor zilnice."""
    pet = pet_hargreaves(d["max_temp"], d["min_temp"], zile, _ctx["lat"])
    return np.where(np.isfinite(pet).any(axis=0), np.nansum(pet, axis=0), np.nan)


def i_bilant(d, zile, _ctx=None):
    """Bilanțul climatic al apei pe perioadă: Σ (P − PET) (mm). Negativ = cererea atmosferei depășește precipitațiile."""
    D = d["precipitation"] - pet_hargreaves(d["max_temp"], d["min_temp"], zile, _ctx["lat"])
    return np.where(np.isfinite(D).any(axis=0), np.nansum(D, axis=0), np.nan)


def _preg_lat(cub, fr, g, sezon, ind):
    return {"lat": np.asarray(g.y, dtype="float64")}


# ------------------------------------------------------------------ distribuții (fără scipy)
def gamma_inc(a, x, iteratii=400):
    """Funcția gamma incompletă inferioară regularizată P(a, x), vectorizată (Numerical Recipes 6.2:
    seria pentru x < a + 1, fracția continuă pentru rest)."""
    a = np.asarray(a, dtype="float64"); x = np.asarray(x, dtype="float64")
    a, x = np.broadcast_arrays(a, x)
    out = np.full(x.shape, np.nan)
    ok = np.isfinite(a) & np.isfinite(x) & (a > 0)
    out[ok & (x <= 0)] = 0.0
    m = ok & (x > 0)
    if not m.any():
        return out
    a, x = a[m], x[m]
    lg = np.vectorize(math.lgamma, otypes=[float])(a)
    fata = np.exp(-x + a * np.log(x) - lg)
    serie = x < a + 1
    # seria: P = fata · Σ xⁿ / (a (a+1) … (a+n))
    ap = a.copy(); dl = 1.0 / a; s = dl.copy()
    for _ in range(iteratii):
        ap += 1; dl *= x / ap; s += dl
        if np.all(np.abs(dl) < np.abs(s) * 1e-15):
            break
    p_serie = s * fata
    # fracția continuă (Lentz) pentru Q = 1 − P
    MIC = 1e-300
    b = x + 1 - a; c = np.full(x.shape, 1 / MIC); dd = 1 / np.where(np.abs(b) < MIC, MIC, b); h = dd.copy()
    for i in range(1, iteratii + 1):
        an = -i * (i - a); b = b + 2
        dd = an * dd + b; dd = np.where(np.abs(dd) < MIC, MIC, dd)
        c = b + an / c; c = np.where(np.abs(c) < MIC, MIC, c)
        dd = 1 / dd; dl2 = dd * c; h = h * dl2
        if np.all(np.abs(dl2 - 1) < 1e-15):
            break
    out[m] = np.where(serie, p_serie, 1 - fata * h)
    return np.clip(out, 0.0, 1.0)


def normala_inversa(p):
    """Φ⁻¹(p): inversa funcției de repartiție normale standard (algoritmul lui Acklam, eroare relativă < 1,2·10⁻⁹)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    dd = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    p = np.asarray(p, dtype="float64")
    out = np.full(p.shape, np.nan)
    pl = 0.02425
    with np.errstate(invalid="ignore", divide="ignore"):
        jos = (p > 0) & (p < pl); sus = (p > 1 - pl) & (p < 1); mij = (p >= pl) & (p <= 1 - pl)
        q = np.sqrt(-2 * np.log(np.where(jos, p, 0.5)))
        out = np.where(jos, (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
                       ((((dd[0] * q + dd[1]) * q + dd[2]) * q + dd[3]) * q + 1), out)
        q = p - 0.5; r = q * q
        out = np.where(mij, (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
                       (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1), out)
        q = np.sqrt(-2 * np.log(np.where(sus, 1 - p, 0.5)))
        out = np.where(sus, -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
                       ((((dd[0] * q + dd[1]) * q + dd[2]) * q + dd[3]) * q + 1), out)
    return out


SPI_LIMITA = 1e-6        # probabilitățile se limitează la [10⁻⁶, 1 − 10⁻⁶] → indicele rămâne în ±4,75


def ajusteaza_gamma(X, minim=10):
    """Parametrii distribuției gamma cu zerouri pe axa 0 (anii de bază), pentru SPI (McKee et al. 1993; Edwards &
    McKee 1997): q = proporția anilor cu total 0; α, β prin estimatorul de verosimilitate maximă al lui Thom (1958)
    pe valorile pozitive. Sub `minim` valori pozitive → NaN."""
    X = np.asarray(X, dtype="float64")
    ok = np.isfinite(X); n = ok.sum(axis=0)
    poz = ok & (X > 0); m = poz.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        xm = np.where(poz, X, 0).sum(axis=0) / m
        lnm = np.where(poz, np.log(np.where(poz, X, 1)), 0).sum(axis=0) / m
        A = np.log(xm) - lnm
        alfa = (1 + np.sqrt(1 + 4 * A / 3)) / (4 * A)
        beta = xm / alfa
        q = (n - m) / n
    bun = (m >= minim) & (A > 0) & np.isfinite(alfa)
    return {"alfa": np.where(bun, alfa, np.nan), "beta": np.where(bun, beta, np.nan), "q": np.where(bun, q, np.nan),
            "n": n}


def spi_din(x, par):
    """SPI = Φ⁻¹(H(x)), H(x) = q + (1 − q) · G(x; α, β)."""
    H = par["q"] + (1 - par["q"]) * gamma_inc(par["alfa"], np.asarray(x, dtype="float64") / par["beta"])
    return normala_inversa(np.clip(H, SPI_LIMITA, 1 - SPI_LIMITA))


def l_momente(X):
    """Primele trei L-momente pe axa 0 (anii), din momentele ponderate în probabilitate NEDEPLASATE
    (Hosking & Wallis 1997): b_r = (1/n) Σ [(i−1)…(i−r)] / [(n−1)…(n−r)] · x_(i), valorile ordonate crescător.
    NaN (ani lipsă) se exclud pixel cu pixel. → (λ1, λ2, λ3, n)."""
    X = np.asarray(X, dtype="float64")
    s = np.sort(X, axis=0); n = np.isfinite(X).sum(axis=0).astype("float64")
    i = np.arange(1, X.shape[0] + 1, dtype="float64").reshape((-1,) + (1,) * (X.ndim - 1))
    v = np.where(i <= n, s, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        b0 = v.sum(axis=0) / n
        b1 = ((i - 1) / (n - 1) * v).sum(axis=0) / n
        b2 = ((i - 1) * (i - 2) / ((n - 1) * (n - 2)) * v).sum(axis=0) / n
    return b0, 2 * b1 - b0, 6 * b2 - 6 * b1 + b0, n


def ajusteaza_loglogistica(X, minim=10):
    """Log-logistica cu trei parametri pentru SPEI, în forma logisticii generalizate a lui Hosking (ξ, α, κ), ajustată
    prin L-momente nedeplasate — metoda pachetului de referință SPEI (Beguería et al. 2014), care a arătat că formula
    cu poziții de reprezentare din articolul original (Vicente-Serrano et al. 2010) e deplasată pe serii scurte.
    τ3 = λ3/λ2 · κ = −τ3 · α = λ2 · sin(κπ)/(κπ) · ξ = λ1 − α (1/κ − π/sin(κπ)). Necesită |κ| < 1."""
    l1, l2, l3, n = l_momente(X)
    with np.errstate(invalid="ignore", divide="ignore"):
        k = -l3 / l2
        mic = np.abs(k) < 1e-6
        kp = np.where(mic, 1.0, k * np.pi)
        alfa = l2 * np.where(mic, 1.0, np.sin(kp) / kp)
        xi = l1 - alfa * np.where(mic, 0.0, 1 / np.where(mic, 1.0, k) - np.pi / np.sin(kp))
    bun = (n >= minim) & (np.abs(k) < 1) & (alfa > 0) & np.isfinite(xi)
    return {"xi": np.where(bun, xi, np.nan), "alfa": np.where(bun, alfa, np.nan), "k": np.where(bun, k, np.nan), "n": n}


def spei_din(x, par):
    """SPEI = Φ⁻¹(F(x)), F(x) = 1 / (1 + e^(−y)), y = −ln(1 − κ(x − ξ)/α) / κ (y = (x − ξ)/α pentru κ = 0).
    În afara domeniului (sub limita inferioară când κ < 0, peste cea superioară când κ > 0) F = 0, respectiv 1."""
    x = np.asarray(x, dtype="float64")
    k, a, xi = par["k"], par["alfa"], par["xi"]
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        arg = 1 - k * (x - xi) / a
        mic = np.abs(k) < 1e-6
        y = np.where(mic, (x - xi) / a, -np.log(np.where(arg > 0, arg, 1.0)) / np.where(mic, 1.0, k))
        F = np.where(arg > 0, 1 / (1 + np.exp(-y)), np.where(k < 0, 0.0, 1.0))
        F = np.where(np.isfinite(a) & np.isfinite(x), F, np.nan)
    return normala_inversa(np.clip(F, SPI_LIMITA, 1 - SPI_LIMITA))


def i_spi(d, zile, baza_de, baza_pana, _ctx=None):
    """SPI pe perioada aleasă (sezonul dă scara: anual = SPI-12, iunie–august = SPI-3, o lună = SPI-1):
    totalul precipitațiilor transformat prin distribuția gamma a acelorași perioade din anii de bază."""
    p = d["precipitation"]
    x = np.where(np.isfinite(p).any(axis=0), np.nansum(p, axis=0), np.nan)
    return spi_din(x, _ctx["par"])


def i_spei(d, zile, baza_de, baza_pana, _ctx=None):
    """SPEI pe perioada aleasă: bilanțul Σ (P − PET Hargreaves) transformat prin log-logistica anilor de bază."""
    return spei_din(i_bilant(d, zile, _ctx), _ctx["par"])


def _preg_standardizat(cub, fr, g, sezon, ind):
    """Totalurile perioadei (P sau P − PET) în fiecare an de bază, apoi parametrii distribuției pe pixel; cache."""
    spei = ind.functie is i_spei
    baza = (int(ind.params["baza_de"]), int(ind.params["baza_pana"]))
    variabile = ("precipitation", "max_temp", "min_temp") if spei else ("precipitation",)
    _verifica_baza(cub, fr, variabile, baza)
    tip = "spei" if spei else "spi"
    fis = dir_cache(tip) / f"{tip}_{baza[0]}-{baza[1]}_{_cheie_baza(tip, list(baza), sezon, g.iy0, g.iy1, g.ix0, g.ix1)}.npz"
    ctx = {"lat": np.asarray(g.y, dtype="float64")}
    if fis.exists():
        with np.load(fis) as z:
            ctx["par"] = {k: z[k] for k in z.files}
        log(f"   {tip.upper()}: parametrii distribuției {baza[0]}–{baza[1]} din cache")
        return ctx
    import indicatori as _reg
    aux = _reg.construieste("bilant") if spei else _reg.construieste("suma", var="precipitation")
    log(f"   {tip.upper()}: totalurile perioadei în anii de bază {baza[0]}–{baza[1]} (o singură dată; apoi din cache)")
    ani_b, st, _ = harti_anuale(cub, fr, [aux], baza, sezon, g, "bază ")
    if len(ani_b) < 10:
        raise ValueError(f"Doar {len(ani_b)} ani compleți în perioada de bază; {tip.upper()} cere cel puțin 10.")
    par = ajusteaza_loglogistica(st[aux.cod]) if spei else ajusteaza_gamma(st[aux.cod])
    nevalid = int((~np.isfinite(par["alfa"]) & (par["n"] > 0)).sum())
    if nevalid:
        log(f"   [atenție] {nevalid} pixeli fără distribuție ajustabilă (prea puține valori sau formă nepotrivită) → NoData")
    tmp = fis.with_name(fis.name + f".{os.getpid()}.tmp.npz")
    np.savez(tmp, **par); os.replace(tmp, fis)
    ctx["par"] = par
    return ctx


BANDA = 64        # rânduri pe bandă la calculul indicatorilor (memorie: v5.1)


def _felie_ctx(x, r0, r1, ny):
    """Taie contextul unui indicator pe rândurile [r0, r1): matricile cu axa y pe penultima poziție (praguri, parametri)
    și vectorii de lungime ny (latitudini). Restul rămâne neschimbat."""
    if isinstance(x, dict):
        return {k: _felie_ctx(v, r0, r1, ny) for k, v in x.items()}
    if isinstance(x, np.ndarray):
        if x.ndim >= 2 and x.shape[-2] == ny:
            return x[..., r0:r1, :]
        if x.ndim == 1 and x.shape[0] == ny:
            return x[r0:r1]
    return x


def _numar_valide(d, variabile):
    """Câte zile au valori pentru TOATE variabilele, pe pixel (pe benzi: fără măști booleene pe tot anul)."""
    ref = d[variabile[0]]
    nr = np.empty(ref.shape[1:], dtype="int32")
    for r0 in range(0, ref.shape[1], BANDA):
        nr[r0:r0 + BANDA] = np.logical_and.reduce([np.isfinite(d[v][:, r0:r0 + BANDA]) for v in variabile]).sum(axis=0)
    return nr


@dataclass
class Indicator:
    cod: str
    titlu: str
    functie: object
    variabile: tuple
    unitate: str
    cmap: str = "viridis"
    params: dict = field(default_factory=dict)
    pregatire: object = None         # f(cub, fr, g, sezon, ind) → context (praguri, parametrii unei distribuții)
    ctx: object = field(default=None, repr=False, compare=False)
    ctx_cheie: object = field(default=None, repr=False, compare=False)

    def _calc(self, d, zile, ctx):
        if self.pregatire is not None:
            return np.asarray(self.functie(d, zile, _ctx=ctx, **self.params)).astype("float32")
        return np.asarray(self.functie(d, zile, **self.params)).astype("float32")

    def calculeaza(self, d, zile):
        """Pe benzi de BANDA rânduri: toți indicatorii sunt per pixel, deci rezultatul e identic, iar temporarele
        funcțiilor (măști, copii, sume) rămân mici. Pragurile / parametrii din context se taie pe aceeași bandă."""
        ny = next(iter(d.values())).shape[1]
        if ny <= BANDA:
            return self._calc(d, zile, self.ctx)
        out = None
        for r0 in range(0, ny, BANDA):
            r1 = min(ny, r0 + BANDA)
            h = self._calc({k: v[:, r0:r1] for k, v in d.items()}, zile, _felie_ctx(self.ctx, r0, r1, ny))
            if out is None:
                out = np.empty((ny,) + h.shape[1:], dtype="float32")
            out[r0:r1] = h
        return out

    def pregateste(self, cub, fr, g, sezon):
        """O singură dată pe grilă și sezon (perioada de bază e în parametri, deci în identitatea indicatorului)."""
        if self.pregatire is None:
            return
        cheie = (g.iy0, g.iy1, g.ix0, g.ix1, json.dumps(sezon, default=str), URL)
        if self.ctx_cheie != cheie:
            self.ctx = self.pregatire(cub, fr, g, sezon, self)
            self.ctx_cheie = cheie


def indicator(cod: str, **params) -> Indicator:
    """Un indicator din registru (indicatori.py), cu parametrii lui: zc.indicator("zile_peste", var="max_temp", prag=30).
    Lista completă și parametrii fiecăruia: python ruleaza.py --indicatori"""
    import indicatori as _reg          # import întârziat: indicatori.py importă la rândul lui zarr_clima
    return _reg.construieste(cod, **params)


# =====================================================================================
# Calculul an cu an
# =====================================================================================
def harti_anuale(cub, fr, indicatori, ani, sezon, g: Grila, mesaj=""):
    """Pentru fiecare an: citește o singură dată variabilele necesare tuturor indicatorilor și îi calculează.
    Returnează (lista_ani, {cod_indicator: ndarray (n_ani, y, x)}, raport)."""
    variabile = tuple(sorted({v for ind in indicatori for v in ind.variabile}))
    frontiera = min(fr[v] for v in variabile)
    inceput = np.datetime64(str(cub.time.values[0])[:10], "D")       # 1961-01-01 pe cubul EOCube
    rez = {ind.cod: [] for ind in indicatori}
    for ind in indicatori:                   # praguri / distribuții din perioada de bază (o singură dată, cu cache)
        ind.pregateste(cub, fr, g, sezon)
    ani_ok, raport = [], []
    total_mb = 0.0
    lista = list(range(ani[0], ani[1] + 1))
    for k, an in enumerate(lista, 1):
        d0, d1, et = perioada(an, sezon)
        n_nominal = int((d1 - d0).astype(int)) + 1               # zilele sezonului, nu cele returnate de cub
        if d0 > frontiera or d1 < inceput:
            raport.append(f"{et}: exclus (în afara datelor {inceput} … {frontiera})")
            log(f"   {et}: exclus — în afara datelor ({inceput} … {frontiera})")
            continue
        if (d1 > frontiera or d0 < inceput) and not ACCEPTA_PARTIAL:
            # ex. DJF 1961 începe la 1960-12-01, înaintea cubului: fără decembrie, iarna ar fi trunchiată la 59 de zile
            motiv = f"depășește frontiera {frontiera}" if d1 > frontiera else f"începe înaintea datelor ({inceput})"
            raport.append(f"{et}: exclus ({motiv})")
            log(f"   {et}: exclus — {motiv} (ACCEPTA_PARTIAL = False)")
            continue
        d0, d1 = max(d0, inceput), min(d1, frontiera)
        nch = mb = 0
        for v in variabile:
            a, b = estimeaza_cost(cub, v, d0, d1, g); nch += a; mb += b
        total_mb += mb
        t0 = time.perf_counter()
        # Variabilele se încarcă abia când le cere primul indicator și se eliberează când niciun indicator rămas nu le
        # mai folosește: fiecare se citește tot o singură dată, dar în memorie stau doar cele necesare (v5.1).
        ordine = sorted(indicatori, key=lambda i: tuple(sorted(i.variabile)))
        d, zile, detalii = {}, None, {}
        for j, ind in enumerate(ordine):
            lipsa = [v for v in ind.variabile if v not in d]
            if lipsa:
                dd, zile = citeste(cub, tuple(lipsa), d0, d1, g)
                d.update(dd); del dd
            durata = len(zile) if ACCEPTA_PARTIAL else n_nominal
            nr = _numar_valide(d, ind.variabile)
            ok = (nr > 0) & (nr >= PRAG_VALID * durata)
            h = ind.calculeaza(d, zile)
            rez[ind.cod].append(np.where(ok, h, np.nan)); del h
            detalii[ind.cod] = f"{ind.cod}: {int(((nr > 0) & ~ok).sum())} pixeli sub prag"
            ramase = {v for i in ordine[j + 1:] for v in i.variabile}
            for v in [v for v in d if v not in ramase]:
                del d[v]
        detalii = [detalii[i.cod] for i in indicatori]
        del d                     # altfel anul acesta rămâne în memorie cât se citește următorul (v5.1: vârf × 2)
        ani_ok.append(an)
        nota = " · " + ", ".join(detalii)
        raport.append(f"{et}: {len(zile)} zile, {nch} chunk-uri (~{mb:.0f} MB){nota}")
        log(f"   {mesaj}{et}: {nch} chunk-uri ~{mb:.0f} MB în {time.perf_counter() - t0:.1f} s ({k}/{len(lista)}){nota}")
    if not ani_ok:
        an_max = int(str(frontiera)[:4]) - (0 if sezon != "anual" else 1)
        raise ValueError(f"Niciun an complet în intervalul {ani[0]}–{ani[1]} (datele merg până la {frontiera}). "
                         f"Alegeți ani până la {an_max}, sau bifați „Acceptă perioade incomplete” în Setări avansate "
                         f"(rezultatul va acoperi doar zilele existente).")
    log(f"   total citit: ~{total_mb / 1000:.2f} GB pentru {len(ani_ok)} perioade")
    return ani_ok, {c: np.stack(v) for c, v in rez.items()}, raport


def _masca_zona(h, zona: Zona):
    return np.where(zona._id > 0, h, np.nan) if zona._id is not None else h


def medie_zona(h, zona: Zona):
    return float(np.nanmean(_masca_zona(h, zona)))


def statistici_zonale(h, zona: Zona, raport=None):
    """[(eticheta, medie, min, max, n_pixeli)] pentru fiecare poligon.
    `raport` = (ht, hr): h este un raport în % (ht / hr); atunci „medie” = 100 · media(ht) / media(hr) pe aceiași pixeli
    (raportul mediilor zonale, ca la seriile pe zone), nu media rapoartelor pixelilor, care supraponderează pixelii
    cu numitor mic (câmpia, la precipitații)."""
    out = []
    for i, (et, _) in enumerate(zona.poligoane, 1):
        sel = zona._id == i
        v = h[sel]; ok = np.isfinite(v); v = v[ok]
        if raport is not None and v.size:
            m = 100.0 * float(np.mean(raport[0][sel][ok])) / float(np.mean(raport[1][sel][ok]))
        else:
            m = float(v.mean()) if v.size else math.nan
        out.append((et, m, float(v.min()) if v.size else math.nan, float(v.max()) if v.size else math.nan, int(v.size)))
    return out


def medie_raport_zona(ht, hr, zona: Zona):
    """100 · media(ht) / media(hr) pe pixelii zonei unde ambele există și hr > 0 (raportul mediilor)."""
    a = _masca_zona(ht, zona); b = _masca_zona(hr, zona)
    ok = np.isfinite(a) & np.isfinite(b) & (b > 0)
    return 100.0 * float(a[ok].mean()) / float(b[ok].mean()) if ok.any() else math.nan


def _beta_inc(a, b, x, iteratii=300):
    """Funcția beta incompletă regularizată I_x(a, b), vectorizată (fracția continuă Lentz, Numerical Recipes 6.4).
    Scrisă de mână pentru că mediul nu include scipy; verificată în teste cu valori din tabele."""
    a = np.asarray(a, dtype="float64"); b = np.asarray(b, dtype="float64"); x = np.asarray(x, dtype="float64")
    a, b, x = np.broadcast_arrays(a, b, x)
    out = np.full(x.shape, np.nan)
    ok = np.isfinite(x) & np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0)
    out[ok & (x <= 0)] = 0.0; out[ok & (x >= 1)] = 1.0
    m = ok & (x > 0) & (x < 1)
    if not m.any():
        return out
    a, b, x = a[m], b[m], x[m]
    sim = x > (a + 1) / (a + b + 2)                       # simetria I_x(a,b) = 1 − I_{1−x}(b,a): converge repede
    a, b, x = np.where(sim, b, a), np.where(sim, a, b), np.where(sim, 1 - x, x)
    lg = np.vectorize(math.lgamma)
    ln_fata = lg(a + b) - lg(a) - lg(b) + a * np.log(x) + b * np.log1p(-x)
    MIC = 1e-300
    c = np.ones_like(x); d = 1 - (a + b) * x / (a + 1)
    d = np.where(np.abs(d) < MIC, MIC, d); d = 1 / d; h = d.copy()
    for k in range(1, iteratii + 1):
        for num in (k * (b - k) * x / ((a + 2 * k - 1) * (a + 2 * k)),
                    -(a + k) * (a + b + k) * x / ((a + 2 * k) * (a + 2 * k + 1))):
            d = 1 + num * d; d = np.where(np.abs(d) < MIC, MIC, d)
            c = 1 + num / c; c = np.where(np.abs(c) < MIC, MIC, c)
            d = 1 / d; h = h * d * c
        if np.all(np.abs(d * c - 1) < 1e-14):
            break
    r = np.exp(ln_fata) * h / a
    out[m] = np.where(sim, 1 - r, r)
    return out


def p_student(t, df):
    """p-valoarea bilaterală a testului t: P(|T| ≥ |t|) cu df grade de libertate = I_{df/(df+t²)}(df/2, 1/2)."""
    t = np.asarray(t, dtype="float64"); df = np.asarray(df, dtype="float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        return _beta_inc(df / 2, 0.5, df / (df + t * t))


def panta_deceniu(ani, stiva):
    """Panta regresiei liniare (unitate/deceniu) și p-valoarea testului t (distribuția Student, n − 2 grade de libertate)
    per pixel. Până în v5.0 p-valoarea folosea aproximarea normală, optimistă pentru serii scurte (sub ~30 de ani)."""
    x = np.asarray(ani, dtype="float64")
    y = stiva.astype("float64")
    ok = np.isfinite(y)
    n = ok.sum(axis=0)
    xm = np.where(ok, x[:, None, None], np.nan)
    mx = np.nanmean(xm, axis=0); my = np.nanmean(y, axis=0)
    sxx = np.nansum((xm - mx) ** 2, axis=0); sxy = np.nansum((xm - mx) * (y - my), axis=0)
    b = sxy / np.where(sxx > 0, sxx, np.nan)
    res = y - (my + b * (xm - mx))
    se = np.sqrt(np.nansum(res ** 2, axis=0) / np.maximum(n - 2, 1) / np.where(sxx > 0, sxx, np.nan))
    t = b / se
    p = p_student(t, n - 2)
    b = np.where(n >= 10, b * 10, np.nan)
    return b.astype("float32"), np.where(n >= 10, p, np.nan).astype("float32")


def sen_mk_deceniu(ani, stiva, bloc=8000):
    """Panta Theil–Sen (unitate/deceniu) și p-valoarea testului Mann–Kendall (bilateral), per pixel.
    Theil–Sen = mediana pantelor tuturor perechilor de ani (robustă la un an excepțional și la valori extreme).
    Mann–Kendall = testul nonparametric al monotoniei: S = Σ semn(y_j − y_i), varianța corectată pentru valori egale
    (frecvente la indicatorii de numărare: zile), aproximare normală cu corecție de continuitate.
    Ani lipsă (NaN): perechile lor nu intră; n = anii valizi ai pixelului; sub 10 ani → NaN.
    Atenție: ca și testul t, MK presupune ani independenți; autocorelarea pozitivă îi face prea optimiști."""
    x = np.asarray(ani, dtype="float64")
    n_t = len(x)
    forma = stiva.shape[1:]
    Y = stiva.reshape(n_t, -1).astype("float64")
    I, J = np.triu_indices(n_t, 1)
    dx = (x[J] - x[I])[:, None]
    b_out = np.full(Y.shape[1], np.nan); p_out = np.full(Y.shape[1], np.nan)
    for c0 in range(0, Y.shape[1], bloc):
        y = Y[:, c0:c0 + bloc]
        n = np.isfinite(y).sum(axis=0)
        dy = y[J] - y[I]                                          # (perechi, pixeli); NaN dacă un an lipsește
        with np.errstate(invalid="ignore", all="ignore"):
            panta = np.nanmedian(dy / dx, axis=0) if dy.size else np.full(y.shape[1], np.nan)
        S = np.nansum(np.sign(dy), axis=0)
        # corecția pentru grupuri de valori egale: Σ t(t−1)(2t+5)
        ys = np.sort(y, axis=0)                                   # NaN la sfârșit
        egal = (ys[1:] == ys[:-1])
        run = np.ones(y.shape[1]); cor = np.zeros(y.shape[1])
        for k in range(egal.shape[0]):
            run = np.where(egal[k], run + 1, run)
            final = ~egal[k]
            cor += np.where(final & (run > 1), run * (run - 1) * (2 * run + 5), 0.0)
            run = np.where(final, 1.0, run)
        cor += np.where(run > 1, run * (run - 1) * (2 * run + 5), 0.0)
        var = (n * (n - 1) * (2 * n + 5) - cor) / 18.0
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.where(S > 0, S - 1, np.where(S < 0, S + 1, 0.0)) / np.sqrt(np.where(var > 0, var, np.nan))
        p = np.array([math.erfc(abs(v) / math.sqrt(2)) if np.isfinite(v) else np.nan for v in z])
        b_out[c0:c0 + bloc] = np.where(n >= 10, panta * 10, np.nan)
        p_out[c0:c0 + bloc] = np.where(n >= 10, p, np.nan)
    return b_out.reshape(forma).astype("float32"), p_out.reshape(forma).astype("float32")


def tendinta_deceniu(ani, stiva, metoda="ols"):
    """Panta pe deceniu + p-valoarea: „ols” (regresie liniară, test t) sau „sen” (Theil–Sen + Mann–Kendall)."""
    return sen_mk_deceniu(ani, stiva) if metoda == "sen" else panta_deceniu(ani, stiva)


METODE_TREND = {"ols": "regresie liniară (OLS), test t", "sen": "Theil–Sen, test Mann–Kendall"}


# =====================================================================================
# IEȘIRI
# =====================================================================================
def _gata(cale):
    cale = Path(cale); cale.parent.mkdir(parents=True, exist_ok=True)
    return cale


def scrie_cog(cale, benzi, g: Grila, descrieri=None, unitate="", cmap=None, divergent=False, centru=None, clase=None,
              meta=None):
    """GeoTIFF optimizat pentru cloud (COG), float32, NoData = NaN, EPSG:4326.
    cmap / divergent / centru / clase: cum trebuie colorată harta (le citește vizualizatorul din interfață)."""
    from osgeo import gdal, osr
    cale = _gata(cale)
    benzi = [b.astype("float32") for b in (benzi if isinstance(benzi, (list, tuple)) else [benzi])]
    ny, nx = benzi[0].shape
    mem = gdal.GetDriverByName("MEM").Create("", nx, ny, len(benzi), gdal.GDT_Float32)
    mem.SetGeoTransform(g.transform)
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326); mem.SetProjection(srs.ExportToWkt())
    for i, b in enumerate(benzi, 1):
        bd = mem.GetRasterBand(i)
        # WriteRaster (octeți brute) în loc de WriteArray: nu depinde de gdal_array / versiunea numpy
        bd.WriteRaster(0, 0, nx, ny, np.ascontiguousarray(b, dtype="<f4").tobytes(), buf_type=gdal.GDT_Float32)
        bd.SetNoDataValue(float("nan"))
        if descrieri:
            bd.SetDescription(descrieri[i - 1])
        # unitatea: o listă = câte una pe bandă; un text = doar pentru banda 1 (benzile suplimentare — perioade,
        # p-valori, ranguri — au alte unități: mai bine fără unitate decât cu una greșită)
        u = unitate[i - 1] if isinstance(unitate, (list, tuple)) else (unitate if i == 1 else "")
        if u:
            bd.SetUnitType(u)
        if i == 1:                                   # culorile: ale benzii principale (vizualizatorul din interfață)
            for k, v in (("CMAP", cmap), ("DIVERGENT", "1" if divergent else None),
                         ("CENTRU", None if not divergent else str(0.0 if centru is None else float(centru))),
                         ("CLASE", ",".join(f"{float(c):g}" for c in clase) if clase else None)):
                if v:
                    bd.SetMetadataItem(k, v)
    mem.SetMetadataItem("SURSA", ATRIBUIRE)
    for k, v in (meta or {}).items():               # ex. ANI = „2016,2017,…”: seria pe ani, pentru animația din Hartă
        if v is not None:
            mem.SetMetadataItem(k, str(v))
    gdal.GetDriverByName("COG").CreateCopy(str(cale), mem, options=["COMPRESS=DEFLATE", "PREDICTOR=3", "OVERVIEWS=AUTO"])
    log(f"   COG: {cale}")
    return cale


def scrie_gpkg_zone(cale, zona: Zona, tabel: dict, strat="rezultate"):
    """Poligoanele zonei cu atributele calculate. tabel = {nume_camp: [valori în ordinea poligoanelor]}."""
    from osgeo import ogr, osr
    cale = _gata(cale)
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.Open(str(cale), 1) if cale.exists() else drv.CreateDataSource(str(cale))
    if ds.GetLayerByName(strat):
        ds.DeleteLayer(strat)
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer(strat, srs, ogr.wkbMultiPolygon)
    lyr.CreateField(ogr.FieldDefn("eticheta", ogr.OFTString))
    text = {c for c, vals in tabel.items() if any(isinstance(v, str) for v in vals)}     # câmpuri text (ex. data recordului)
    for c in tabel:
        lyr.CreateField(ogr.FieldDefn(c[:60], ogr.OFTString if c in text else
                                      (ogr.OFTInteger if c in ("n_pixeli", "an_record") else ogr.OFTReal)))
    lyr.StartTransaction()
    for i, (et, wkt) in enumerate(zona.poligoane):
        f = ogr.Feature(lyr.GetLayerDefn()); f.SetField("eticheta", et)
        for c, vals in tabel.items():
            v = vals[i]
            if c in text:
                if v is not None:
                    f.SetField(c[:60], str(v))
            elif v is not None and np.isfinite(v):
                f.SetField(c[:60], int(v) if c in ("n_pixeli", "an_record") else float(round(v, 4)))
        g = ogr.CreateGeometryFromWkt(wkt); f.SetGeometry(ogr.ForceToMultiPolygon(g)); lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None
    log(f"   GPKG (poligoane): {cale} · strat „{strat}”")
    return cale


def scrie_gpkg_puncte(cale, harti: dict, g: Grila, strat="rezultate"):
    """Centrele pixelilor valizi, cu valorile tuturor hărților ca atribute."""
    from osgeo import ogr, osr
    cale = _gata(cale)
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.Open(str(cale), 1) if cale.exists() else drv.CreateDataSource(str(cale))
    if ds.GetLayerByName(strat):
        ds.DeleteLayer(strat)
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer(strat, srs, ogr.wkbPoint)
    for c in harti:
        lyr.CreateField(ogr.FieldDefn(c[:60], ogr.OFTReal))
    prima = next(iter(harti.values()))
    iy, ix = np.where(np.isfinite(prima))
    lyr.StartTransaction()
    for a, b in zip(iy, ix):
        f = ogr.Feature(lyr.GetLayerDefn())
        for c, h in harti.items():
            if np.isfinite(h[a, b]):
                f.SetField(c[:60], float(round(h[a, b], 4)))
        p = ogr.Geometry(ogr.wkbPoint); p.AddPoint_2D(float(g.x[b]), float(g.y[a])); f.SetGeometry(p); lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None
    log(f"   GPKG (puncte, {len(iy)} pixeli): {cale} · strat „{strat}”")
    return cale


def scrie_csv(cale, antet, randuri):
    cale = _gata(cale)
    with open(cale, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(antet)
        for r in randuri:
            w.writerow([ro(v, 3) if isinstance(v, float) else v for v in r])
    log(f"   CSV: {cale}")
    return cale


def _plt():
    import matplotlib
    if not in_qgis():
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlelocation": "left",
                         "savefig.bbox": "tight", "savefig.facecolor": "white", "figure.facecolor": "white"})
    return plt


_CACHE_CONTUR = {}


def _linii_geometrie(geom):
    """Toate liniile (inele de poligon, linii) unei geometrii OGR, ca tablouri (n, 2)."""
    out = []
    n = geom.GetGeometryCount()
    if n == 0:
        pts = geom.GetPoints()
        if pts and len(pts) > 1:
            out.append(np.array(pts)[:, :2])
    else:
        for i in range(n):
            out += _linii_geometrie(geom.GetGeometryRef(i))
    return out


def _citeste_contur(spec):
    """Liniile unui vector (orice CRS → EPSG:4326). spec = cale | (cale, strat) | (cale, strat, filtru)."""
    from osgeo import ogr, osr
    if isinstance(spec, (str, Path)):
        spec = (str(spec),)
    cheie = tuple(str(x) for x in spec)
    if cheie in _CACHE_CONTUR:
        return _CACHE_CONTUR[cheie]
    cale, strat, filtru = (list(spec) + [None, None])[:3]
    ds = ogr.Open(str(cale))
    if ds is None:
        log(f"   [atenție] CONTUR_HARTI: nu pot deschide {cale}; hărțile se fac fără contur")
        _CACHE_CONTUR[cheie] = []; return []
    lyr = ds.GetLayerByName(strat) if strat else ds.GetLayer(0)
    if lyr is None:
        log(f"   [atenție] CONTUR_HARTI: stratul „{strat}” nu există; straturi: "
            f"{[ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]}")
        _CACHE_CONTUR[cheie] = []; return []
    if filtru:
        lyr.SetAttributeFilter(filtru)
    src = lyr.GetSpatialRef()
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326); dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = None
    if src is not None:
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        if not src.IsSame(dst):
            tr = osr.CoordinateTransformation(src, dst)
    linii = []
    for f in lyr:
        geom = f.GetGeometryRef()
        if geom is None:
            continue
        geom = geom.Clone()
        if tr:
            geom.Transform(tr)
        linii += _linii_geometrie(geom)
    _CACHE_CONTUR[cheie] = linii
    log(f"   contur pe hărți: {Path(cale).name}{' / ' + strat if strat else ''} ({len(linii)} linii)")
    return linii


def _contururi(ax, zona: Zona | None, g: Grila):
    """Desenează poligoanele zonei (dacă există) și conturul din CONTUR_HARTI (dacă e setat)."""
    from matplotlib.collections import LineCollection
    if zona is not None and zona.poligoane:
        from osgeo import ogr
        linii = []
        for _, w in zona.poligoane:
            linii += _linii_geometrie(ogr.CreateGeometryFromWkt(w))
        ax.add_collection(LineCollection(linii, colors=CONTUR_CULOARE, linewidths=CONTUR_GROSIME))
    if CONTUR_HARTI:
        linii = _citeste_contur(CONTUR_HARTI)
        if linii:
            ax.add_collection(LineCollection(linii, colors=CONTUR_CULOARE, linewidths=CONTUR_GROSIME * 1.4))
    e = g.extent
    ax.set_xlim(e[0], e[1]); ax.set_ylim(e[2], e[3])


def png_harta(cale, h, g: Grila, titlu, unitate, cmap="viridis", vmin=None, vmax=None, divergent=False,
              zona: Zona | None = None, subtitlu="", hasura=None, clase=None, puncte=None, etichete_clase=None, centru=None,
              statistici=True):
    """Hartă PNG cu legendă, contururi și atribuire. `hasura` = mască booleană pentru hașurare (ex. nesemnificativ).
    `clase` = listă de limite pentru o legendă în trepte (ex. clasele De Martonne)."""
    plt = _plt()
    import matplotlib
    from matplotlib.colors import BoundaryNorm, TwoSlopeNorm
    cale = _gata(cale)
    vals = h[np.isfinite(h)]
    if vals.size == 0:
        log("   [atenție] harta e goală (doar NaN) — PNG nescris"); return None
    if divergent:
        if vmin is not None and vmax is not None:
            norm = TwoSlopeNorm(vcenter=centru if centru is not None else (vmin + vmax) / 2, vmin=vmin, vmax=vmax)
        else:
            m = float(np.nanpercentile(np.abs(vals), 98)) or 1.0
            norm = TwoSlopeNorm(vcenter=0.0, vmin=-m, vmax=m)
    elif clase:
        import matplotlib
        norm = BoundaryNorm(clase, matplotlib.colormaps[cmap].N, extend="both")
    else:
        lo = vmin if vmin is not None else float(np.nanpercentile(vals, 2))
        hi = vmax if vmax is not None else float(np.nanpercentile(vals, 98))
        norm = plt.Normalize(lo, hi if hi > lo else lo + 1)
    lat_m = (g.extent[2] + g.extent[3]) / 2
    fig, ax = plt.subplots(figsize=(10, 6.4))
    umbra = umbrire(g) if RELIEF_HARTI else None
    if umbra is None:
        im = ax.imshow(h, extent=g.extent, cmap=cmap, norm=norm, interpolation="nearest")
    else:
        # relieful: culorile datelor înmulțite cu umbrirea (lumină din NV, 45°); în afara datelor, relieful în gri
        # deschis, ca fundal. Legenda rămâne cea a culorilor neumbrite (imaginea invizibilă `im`).
        im = ax.imshow(h, extent=g.extent, cmap=cmap, norm=norm, interpolation="nearest", alpha=0)
        rgba = matplotlib.colormaps[cmap](norm(np.ma.masked_invalid(h))) if isinstance(cmap, str) else im.to_rgba(h)
        rgba = np.array(rgba, dtype="float64")
        fact = (1 - RELIEF_FORTA) + RELIEF_FORTA * umbra
        rgba[..., :3] *= fact[..., None]
        fundal = np.dstack([np.full(h.shape, 0.94) * (0.80 + 0.20 * umbra)] * 3 + [np.full(h.shape, 1.0)])
        rgba = np.where(np.isfinite(h)[..., None], rgba, fundal)
        ax.imshow(np.clip(rgba, 0, 1), extent=g.extent, interpolation="nearest")
        im = matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap)       # legenda: culorile neumbrite
    if hasura is not None and hasura.any():
        ax.contourf(g.x, g.y, hasura.astype(float), levels=[0.5, 1.5], colors="none", hatches=["...."])
    _contururi(ax, zona, g)
    for px, py, et in (puncte or []):
        ax.plot(px, py, marker="*", ms=13, mfc="#ffd400", mec="#0b0b0b", mew=0.8, zorder=5)
        if et:
            ax.annotate(et, (px, py), xytext=(6, 6), textcoords="offset points", fontsize=8.5, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8))
    ax.set_aspect(1 / math.cos(math.radians(lat_m)))
    ax.set_xlabel("Longitudine (°E)"); ax.set_ylabel("Latitudine (°N)")
    ax.set_title(titlu + (f"\n{subtitlu}" if subtitlu else ""), fontsize=11)
    cb = plt.colorbar(im, ax=ax, shrink=0.8, pad=0.02, extend="both" if clase else "neither")
    cb.set_label(unitate); cb.outline.set_visible(False)
    if clase and etichete_clase:
        cb.set_ticks([(a + b) / 2 for a, b in zip(clase[:-1], clase[1:])]); cb.set_ticklabels(etichete_clase)
    st = f"min {ro(float(vals.min()))} · medie {ro(float(vals.mean()))} · max {ro(float(vals.max()))} {unitate}  ·  "
    fig.text(0.0, -0.02, f"{st if statistici else ''}{ATRIBUIRE}", fontsize=8, color="#555555")   # fără statistici: ani, date, ranguri
    fig.savefig(cale, dpi=DPI, bbox_inches="tight", pad_inches=0.15); plt.close(fig)
    log(f"   PNG hartă: {cale}")
    return cale


def png_serie(cale, ani, valori, titlu, unitate, medie=True, tendinta=True, bare=False, culoare="#2a78d6", subtitlu=""):
    plt = _plt()
    cale = _gata(cale)
    x = np.asarray(ani, float); y = np.asarray(valori, float)
    ok = np.isfinite(y)
    if ok.sum() < 2:
        log("   [atenție] prea puțini ani pentru grafic"); return None
    fig, ax = plt.subplots(figsize=(10, 4.2))
    if bare:
        ax.bar(x[ok], y[ok], color=culoare, width=0.75)
    else:
        ax.plot(x[ok], y[ok], color=culoare, lw=1.6, marker="o", ms=3)
    if medie:
        m = float(np.nanmean(y)); ax.axhline(m, color="#008300", lw=1.2)
        ax.text(x[ok][0], m, f" media {ro(m, 2)} {unitate}", color="#008300", va="bottom", fontsize=9)
    if tendinta and ok.sum() >= 10:
        b, a = np.polyfit(x[ok], y[ok], 1)
        ax.plot(x[ok], a + b * x[ok], color="#555555", lw=1, ls="--")
        ax.text(x[ok][-1], a + b * x[ok][-1], f" {'+' if b >= 0 else '−'}{ro(abs(b) * 10, 2)} {unitate}/deceniu",
                fontsize=9, color="#333333", va="bottom", ha="right")
    ax.set_ylabel(unitate); ax.grid(axis="y", color="#e6e5e0")
    ax.set_title(titlu + (f"\n{subtitlu}" if subtitlu else ""), fontsize=11)
    fig.text(0.0, -0.03, ATRIBUIRE, fontsize=8, color="#555555")
    fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG grafic: {cale}")
    return cale


def png_bare_zone(cale, etichete, valori, titlu, unitate, n_max=25, cmap="viridis"):
    plt = _plt()
    import matplotlib
    cale = _gata(cale)
    pereche = sorted([(v, e) for e, v in zip(etichete, valori) if np.isfinite(v)], reverse=True)[:n_max]
    if not pereche:
        return None
    v = [p[0] for p in pereche][::-1]; e = [p[1] for p in pereche][::-1]
    norm = plt.Normalize(min(v), max(v) if max(v) > min(v) else min(v) + 1)
    fig, ax = plt.subplots(figsize=(9, 0.32 * len(v) + 1.5))
    ax.barh(e, v, color=matplotlib.colormaps[cmap](norm(v)))
    for i, val in enumerate(v):
        ax.text(val, i, f" {ro(val, 1)}", va="center", fontsize=8.5)
    ax.set_xlabel(unitate); ax.set_title(titlu, fontsize=11)
    fig.text(0.0, -0.02, ATRIBUIRE, fontsize=8, color="#555555")
    fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG grafic zone: {cale}")
    return cale


def png_dungi(cale, ani, valori, titlu, ref=(1971, 2000), cmap="RdBu_r", baza=None):
    """„Dungile încălzirii” (Ed Hawkins): o bandă colorată pe an, centrată pe media perioadei de referință."""
    plt = _plt()
    cale = _gata(cale)
    x = np.asarray(ani); y = np.asarray(valori, float)
    m = (x >= ref[0]) & (x <= ref[1]) & np.isfinite(y)
    if baza is None:
        baza = float(np.mean(y[m])) if m.any() else np.nan
    if not np.isfinite(baza):
        log(f"   [atenție] {titlu}: referință fără valori valide, grafic omis")
        return None
    an = y - baza
    lim = float(np.nanmax(np.abs(an))) or 1.0
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.imshow(an[None, :], aspect="auto", cmap=cmap, vmin=-lim, vmax=lim, extent=[x[0] - 0.5, x[-1] + 0.5, 0, 1])
    ax.set_yticks([]); ax.set_xticks([a for a in x if a % 10 == 0])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(titlu, fontsize=11)
    fig.text(0.0, -0.08, f"Anomalia față de media {ref[0]}–{ref[1]} ({ro(baza, 2)}) · {ATRIBUIRE}", fontsize=8, color="#555555")
    fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG dungi: {cale}")
    return cale


def incarca_in_qgis(fisiere, grup="Zarr ANM"):
    """Dacă scriptul rulează în QGIS, adaugă COG-urile și GPKG-urile în proiect, într-un grup."""
    if not (INCARCA_IN_QGIS and in_qgis()):
        return
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
    pr = QgsProject.instance()
    root = pr.layerTreeRoot()
    gr = root.findGroup(grup) or root.insertGroup(0, grup)
    for f in fisiere:
        if f is None:
            continue
        f = str(f)
        if f.endswith(".tif"):
            lyr = QgsRasterLayer(f, Path(f).stem)
        elif f.endswith(".gpkg"):
            lyr = QgsVectorLayer(f + "|layername=rezultate", Path(f).stem, "ogr")
        else:
            continue
        if lyr.isValid():
            pr.addMapLayer(lyr, False); gr.addLayer(lyr)
    log(f"   straturi încărcate în QGIS (grupul „{grup}”)")


# =====================================================================================
# RULARE: funcțiile apelate de scripturi
# =====================================================================================
def _iesiri_harta(out, nume, h, g, zona, ind, titlu, subtitlu, iesiri, serie=None, ani=None,
                  divergent=False, vmin=None, vmax=None, hasura=None, clase=None, benzi_extra=None, raport=None, centru=None):
    h = _masca_zona(h, zona)
    if centru is None and divergent and vmin is not None and vmax is not None:
        centru = (vmin + vmax) / 2
    fisiere = []
    if iesiri.get("cog"):
        benzi = [h] + ([_masca_zona(b, zona) for b, _ in benzi_extra] if benzi_extra else [])
        descr = [titlu] + ([d for _, d in benzi_extra] if benzi_extra else [])
        fisiere.append(scrie_cog(out / f"{nume}.tif", benzi, g, descr, ind.unitate, cmap=ind.cmap, divergent=divergent,
                                 centru=centru,
                                 clase=clase))
    if iesiri.get("png"):
        png_harta(out / f"{nume}_harta.png", h, g, titlu, ind.unitate, ind.cmap, vmin, vmax, divergent, zona, subtitlu, hasura, clase)
    if iesiri.get("gpkg"):
        if zona.poligoane:
            st = statistici_zonale(h, zona, raport)
            fisiere.append(scrie_gpkg_zone(out / f"{nume}.gpkg", zona, {
                ("raport_mediilor_pct" if raport is not None else "medie"): [s[1] for s in st], "minim": [s[2] for s in st], "maxim": [s[3] for s in st],
                "n_pixeli": [s[4] for s in st]}))
        else:
            fisiere.append(scrie_gpkg_puncte(out / f"{nume}.gpkg", {"valoare": h}, g))
    if iesiri.get("grafic"):
        if zona.poligoane and len(zona.poligoane) > 1:
            st = statistici_zonale(h, zona, raport)
            png_bare_zone(out / f"{nume}_zone.png", [s[0] for s in st], [s[1] for s in st], titlu, ind.unitate, cmap=ind.cmap)
        if serie is not None and len(ani) > 1:
            png_serie(out / f"{nume}_serie.png", ani, serie, f"{titlu} · media zonei, pe ani", ind.unitate,
                      subtitlu=zona.descriere(), bare=ind.unitate == "zile")
    if iesiri.get("csv"):
        if zona.poligoane:
            st = statistici_zonale(h, zona, raport)
            scrie_csv(out / f"{nume}_zone.csv", ["zona", "raport_mediilor_pct" if raport is not None else "medie",
                                                 "minim", "maxim", "n_pixeli"], st)
        if serie is not None:
            scrie_csv(out / f"{nume}_serie.csv", ["an", "valoare_medie_zona"], list(zip(ani, serie)))
    return fisiere


def scrie_cog_ani(cale, stiva, ani, g, zona, ind, sezon, clase=None, vmin=None, vmax=None, divergent=False, centru=None):
    """Câte o bandă pe an (descrierea benzii = anul), pentru animația din tabul Hartă și pentru QGIS (Temporal Controller
    poate folosi benzile ca pași). Paleta și scara comună sunt în metadatele setului, valabile pentru toate benzile."""
    benzi = [_masca_zona(b, zona) for b in stiva]
    toate = np.concatenate([b[np.isfinite(b)] for b in benzi]) if any(np.isfinite(b).any() for b in benzi) else np.array([0.0])
    lo = float(np.percentile(toate, 2)) if vmin is None else float(vmin)
    hi = float(np.percentile(toate, 98)) if vmax is None else float(vmax)
    if divergent:
        c = 0.0 if centru is None else float(centru)
        m = max(abs(lo - c), abs(hi - c)); lo, hi = c - m, c + m
    eticheta = (lambda a: f"{a}") if sezon in ("anual", None) else (lambda a: f"{a} · {sezon}")
    return scrie_cog(cale, benzi, g, [eticheta(a) for a in ani], [ind.unitate] * len(benzi), cmap=ind.cmap,
                     divergent=divergent, centru=centru, clase=clase,
                     meta={"ANI": ",".join(str(a) for a in ani), "TITLU": ind.titlu, "SEZON": sezon,
                           "SCARA": f"{lo:.6g},{hi:.6g}", "CMAP": ind.cmap,
                           "DIVERGENT": "1" if divergent else None, "CLASE": ",".join(f"{float(c):g}" for c in clase) if clase else None})


def ruleaza_harta(indicatori, ani, sezon, zona: Zona, iesiri: dict, out, nume, clase=None, vmin=None, vmax=None):
    """Media pe ani a unuia sau mai multor indicatori (ex. numărul mediu de zile tropicale pe an, 2016–2025).
    `indicatori` = un Indicator sau o listă; toți se calculează din aceeași citire a datelor."""
    out = Path(out)
    lista_ind = [indicatori] if isinstance(indicatori, Indicator) else list(indicatori)
    log(f"== {nume}: {' + '.join(i.titlu for i in lista_ind)} · {ani[0]}–{ani[1]} · sezon {sezon}")
    cub, fr = deschide()
    g = grila_zonei(cub, zona)
    log(f"   zona: {zona.descriere()} · fereastra {g.forma[0]} × {g.forma[1]} pixeli")
    lista, st, _ = harti_anuale(cub, fr, lista_ind, ani, sezon, g)
    per = f"{lista[0]}–{lista[-1]}" if len(lista) > 1 else f"{lista[0]}"
    fis, harti = [], {}
    for ind in lista_ind:
        stiva = st[ind.cod]
        h = _masca_zona(np.nanmean(stiva, axis=0), zona); harti[ind.cod] = h
        serie = [medie_zona(s, zona) for s in stiva]
        titlu = ind.titlu + (" · medie anuală" if len(lista) > 1 else "")
        sub = f"{per} · sezon: {sezon} · {zona.descriere()}"
        n = nume if len(lista_ind) == 1 else f"{nume}_{ind.cod}"
        kw = dict(clase=clase, vmin=vmin, vmax=vmax)
        if e_standardizat(ind):                          # SPI / SPEI: 0 = normal, scala fixă ±3 (clasele OMM)
            kw.update(divergent=True, centru=0.0, vmin=-3.0 if vmin is None else vmin, vmax=3.0 if vmax is None else vmax)
        fis += _iesiri_harta(out, n, h, g, zona, ind, titlu, sub, iesiri, serie, lista, **kw)
        if iesiri.get("ani") and len(lista) > 1:
            fis.append(scrie_cog_ani(out / f"{n}_pe_ani.tif", stiva, lista, g, zona, ind, sezon, **kw))
        log(f"   {ind.titlu}: medie pe zonă {ro(medie_zona(h, zona), 2)} {ind.unitate}")
    incarca_in_qgis(fis)
    log(f"== gata: {nume}")
    return harti, g


def _cmap_petrol():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("petrol", ["#e3f0f4", "#7cc4dc", "#0f6b8c", "#073a4d"])


def png_altitudine(cale, alt, val, reg, trepte, titlu, unitate, subtitlu=""):
    """Dispersia indicator ~ altitudine, pixel cu pixel (densitate hexagonală, scară log), dreapta regresiei
    și media pe trepte de altitudine (cu ± o abatere standard)."""
    plt = _plt()
    from matplotlib.colors import LogNorm
    cale = _gata(cale)
    fig, ax = plt.subplots(figsize=(9.5, 6))
    hb = ax.hexbin(alt, val, gridsize=70, cmap=_cmap_petrol(), norm=LogNorm(), mincnt=1, linewidths=0)
    cb = fig.colorbar(hb, ax=ax, pad=0.01); cb.set_label("pixeli (scară log)")
    xs = np.array([np.nanmin(alt), np.nanmax(alt)])
    ax.plot(xs, reg["a"] + reg["b"] * xs, color="#b4540a", lw=2,
            label=f"regresie: {'+' if reg['b'] >= 0 else '−'}{ro(abs(reg['b']) * 100, 2)} {unitate} / 100 m · R² = {ro(reg['r2'], 2)}")
    t = trepte
    if t:
        ax.errorbar([r["alt_medie"] for r in t], [r["medie"] for r in t], yerr=[r["std"] for r in t], fmt="o", ms=5,
                    color="#172634", mfc="white", mew=1.5, elinewidth=1, capsize=2, label="media pe treaptă ± o abatere standard")
    ax.set_xlabel("altitudinea medie a pixelului (m)"); ax.set_ylabel(unitate)
    ax.grid(color="#e8edf0", lw=0.8); ax.set_axisbelow(True)
    ax.legend(loc="best", fontsize=9, frameon=False)
    ax.set_title(titlu + (f"\n{subtitlu}" if subtitlu else ""), fontsize=11, loc="left")
    fig.text(0.0, -0.02, ATRIBUIRE + " · DEM: Copernicus GLO-30 (© DLR, Airbus), coregistrat pe grila Zarr", fontsize=8, color="#555555")
    fig.savefig(cale, dpi=DPI, bbox_inches="tight"); plt.close(fig)
    log(f"   PNG grafic: {cale}")
    return cale


def ruleaza_altitudine(indicatori, ani, sezon, zona: Zona, iesiri: dict, out, nume, treapta=200.0, alt_min_treapta=5):
    """Indicatorul față de altitudine, pixel cu pixel: regresia liniară (gradientul pe 100 m), media pe trepte de
    altitudine și harta valorilor observate minus predicția liniară. Reziduurile sugerează ipoteze de verificat.
    Altitudinea vine din DEM-ul coregistrat pe grila cubului (date/dem_grila_zarr.tif)."""
    out = Path(out)
    lista_ind = [indicatori] if isinstance(indicatori, Indicator) else list(indicatori)
    log(f"== {nume}: {' + '.join(i.titlu for i in lista_ind)} față de altitudine · {ani[0]}–{ani[1]} · sezon {sezon}")
    cub, fr = deschide()
    g = grila_zonei(cub, zona)
    alt_t = altitudine(g)
    log(f"   zona: {zona.descriere()} · fereastra {g.forma[0]} × {g.forma[1]} pixeli")
    lista, st, _ = harti_anuale(cub, fr, lista_ind, ani, sezon, g)
    per = f"{lista[0]}–{lista[-1]}" if len(lista) > 1 else f"{lista[0]}"
    rezultat = {}
    for ind in lista_ind:
        n = nume if len(lista_ind) == 1 else f"{nume}_{ind.cod}"
        h = _masca_zona(np.nanmean(st[ind.cod], axis=0), zona)
        ok = np.isfinite(h) & np.isfinite(alt_t)
        if ok.sum() < 10:
            raise ValueError(f"Prea puțini pixeli cu date și altitudine ({int(ok.sum())}) pentru o regresie.")
        x, y = alt_t[ok].astype("float64"), h[ok].astype("float64")
        if np.ptp(x) == 0:
            raise ValueError("Altitudinea este constantă în zona selectată. Gradientul este nedefinit.")
        b, a = np.polyfit(x, y, 1)
        rez = y - (a + b * x)
        r2 = 1 - float(np.sum(rez ** 2)) / float(np.sum((y - y.mean()) ** 2)) if np.ptp(y) > 0 else float("nan")
        se_b = math.sqrt(float(np.sum(rez ** 2)) / max(len(x) - 2, 1) / float(np.sum((x - x.mean()) ** 2)))
        rmse = float(np.sqrt(np.mean(rez ** 2)))
        reg = dict(a=float(a), b=float(b), r2=float(r2), se_b=se_b, rmse=rmse, n=int(ok.sum()))
        log(f"   {ind.titlu}: gradient {ro(b * 100, 3)} {ind.unitate}/100 m · R² {ro(r2, 2)} · "
            f"RMSE {ro(rmse, 2)} {ind.unitate} · {reg['n']} pixeli · {ro(x.min(), 0)}–{ro(x.max(), 0)} m. "
            "Pixelii vecini pot avea reziduuri corelate. Eroarea OLS din CSV presupune independență.")
        if ind.unitate == "°C" and b < 0:
            log(f"      (gradientul termic vertical „standard” în atmosferă e ≈ −0,65 °C / 100 m; la suprafață, "
                f"pe medii anuale, valorile tipice sunt −0,4 … −0,7)")
        # trepte de altitudine
        k = np.floor(x / treapta).astype(int)
        trepte = []
        for t in np.unique(k):
            m = k == t; v = y[m]
            trepte.append(dict(de_la=float(t * treapta), pana_la=float((t + 1) * treapta), n=int(m.sum()),
                               alt_medie=float(x[m].mean()), medie=float(v.mean()), std=float(v.std()),
                               p10=float(np.percentile(v, 10)), p90=float(np.percentile(v, 90))))
        sub = f"{per} · sezon: {sezon} · {zona.descriere()}\n{len(x)} pixeli · RMSE {ro(rmse, 2)} {ind.unitate} · regresie descriptivă"
        fis = []
        if iesiri.get("grafic"):
            fis.append(png_altitudine(out / f"{n}_altitudine.png", x, y, reg, [t for t in trepte if t["n"] >= alt_min_treapta],
                                      f"{ind.titlu} față de altitudine", ind.unitate, sub))
        if iesiri.get("csv"):
            fis.append(scrie_csv(out / f"{n}_trepte_altitudine.csv",
                                 ["altitudine_de_la_m", "altitudine_pana_la_m", "n_pixeli", "altitudine_medie_m",
                                  f"medie_{ind.cod}", "abatere_standard", "p10", "p90"],
                                 [[t["de_la"], t["pana_la"], t["n"], t["alt_medie"], t["medie"], t["std"], t["p10"], t["p90"]]
                                  for t in trepte]))
            scrie_csv(out / f"{n}_regresie.csv", ["indicator", "unitate", "gradient_pe_100m", "SE_OLS_iid_pe_100m",
                                                  "interceptie", "R2", "n_pixeli", "ani", "sezon", "zona", "RMSE"],
                      [[ind.cod, ind.unitate, b * 100, se_b * 100, a, r2, reg["n"], per, sezon, zona.descriere(), rmse]])
        if iesiri.get("csv_pixeli"):
            iy, ix = np.nonzero(ok)
            fis.append(scrie_csv(out / f"{n}_pixeli.csv", ["lon", "lat", "altitudine_m", ind.cod, "rezidual"],
                                 [[float(g.x[j]), float(g.y[i]), float(alt_t[i, j]), float(h[i, j]), float(r)]
                                  for i, j, r in zip(iy, ix, rez)]))
        if iesiri.get("cog") or iesiri.get("png"):
            hr = np.full(h.shape, np.nan, "float32"); hr[ok] = rez
            lim = float(np.nanpercentile(np.abs(rez), 98)) or 1.0
            ind_r = Indicator(ind.cod, ind.titlu, ind.functie, ind.variabile, ind.unitate, "RdBu_r", ind.params)
            fis += _iesiri_harta(out, f"{n}_rezidual_altitudine", hr, g, zona, ind_r,
                                 f"{ind.titlu}: abaterea față de dreapta altitudinii", sub,
                                 {"cog": iesiri.get("cog"), "png": iesiri.get("png")}, divergent=True, vmin=-lim, vmax=lim)
        rezultat[ind.cod] = dict(regresie=reg, trepte=trepte)
    log(f"== gata: {nume}")
    return rezultat


def ruleaza_anomalie(ind: Indicator, ani_tinta, ani_referinta, sezon, zona: Zona, iesiri: dict, out, nume, mod="diferenta"):
    """Anomalia = indicator(perioada țintă) − indicator(perioada de referință), sau raportul în % (mod="procent")."""
    out = Path(out)
    log(f"== {nume}: anomalia {ind.titlu} · {ani_tinta} față de {ani_referinta} · sezon {sezon}")
    cub, fr = deschide()
    g = grila_zonei(cub, zona)
    la, st_t, _ = harti_anuale(cub, fr, [ind], ani_tinta, sezon, g, "țintă ")
    lr, st_r, _ = harti_anuale(cub, fr, [ind], ani_referinta, sezon, g, "referință ")
    ht = np.nanmean(st_t[ind.cod], axis=0); hr = np.nanmean(st_r[ind.cod], axis=0)
    if mod == "procent":
        h = 100.0 * ht / np.where(hr > 0, hr, np.nan)
        unit = "% din normală"
    else:
        h = ht - hr
        unit = ind.unitate
    ind2 = Indicator(ind.cod, ind.titlu, ind.functie, ind.variabile, unit, ind.cmap, ind.params)
    per_t = f"{la[0]}–{la[-1]}" if len(la) > 1 else f"{la[0]}"
    per_r = f"{lr[0]}–{lr[-1]}"
    titlu = f"Anomalie: {ind.titlu}" if mod != "procent" else f"{ind.titlu} în % din normală"
    sub = f"{per_t} față de {per_r} · sezon: {sezon} · {zona.descriere()}"
    if mod == "procent":
        kw = dict(divergent=True, vmin=0.0, vmax=200.0, centru=100.0, raport=(ht, hr))   # 100 % = normal
        ind2.cmap = "BrBG"
    else:
        kw = dict(divergent=True)
        ind2.cmap = "RdBu_r" if ind.unitate in ("°C", "zile", "°C·zile") else "BrBG"
    serie_t = [medie_zona(s, zona) for s in st_t[ind.cod]]
    fis = _iesiri_harta(out, nume, h, g, zona, ind2, titlu, sub, iesiri, None, None,
                        benzi_extra=[(ht, f"{ind.titlu} {per_t}"), (hr, f"{ind.titlu} {per_r} (referință)")], **kw)
    if iesiri.get("png_perioade"):
        for hh, per in ((ht, per_t), (hr, per_r)):
            png_harta(out / f"{nume}_{per.replace('–', '_')}_harta.png", _masca_zona(hh, zona), g, f"{ind.titlu} · {per}",
                      ind.unitate, ind.cmap, zona=zona, subtitlu=f"sezon: {sezon} · {zona.descriere()}")
    if iesiri.get("grafic") and len(la) > 1:
        png_serie(out / f"{nume}_serie_tinta.png", la, serie_t, f"{ind.titlu} · perioada țintă", ind.unitate, subtitlu=zona.descriere())
    incarca_in_qgis(fis)
    if mod == "procent":
        log(f"== gata: {nume} · pe toată zona: {ro(medie_raport_zona(ht, hr, zona), 1)} % din normală "
            f"(raportul mediilor; media rapoartelor pixelilor: {ro(medie_zona(h, zona), 1)} %)")
    else:
        log(f"== gata: {nume} · anomalia medie pe zonă {ro(medie_zona(h, zona), 2)} {unit}")
    return _masca_zona(h, zona), g


def ruleaza_trend(ind: Indicator, ani, sezon, zona: Zona, iesiri: dict, out, nume, alfa=0.05, metoda="ols"):
    """Panta (unitate/deceniu) a indicatorului an de an, per pixel; hașurat = nesemnificativ (p ≥ alfa).
    metoda: „ols” (regresie liniară + test t) sau „sen” (Theil–Sen + Mann–Kendall, robustă la anii excepționali)."""
    out = Path(out)
    log(f"== {nume}: tendința {ind.titlu} · {ani[0]}–{ani[1]} · sezon {sezon} · {METODE_TREND[metoda]}")
    cub, fr = deschide()
    g = grila_zonei(cub, zona)
    lista, st, _ = harti_anuale(cub, fr, [ind], ani, sezon, g)
    b, p = tendinta_deceniu(lista, st[ind.cod], metoda)
    ind2 = Indicator(ind.cod, ind.titlu, ind.functie, ind.variabile, f"{ind.unitate}/deceniu", _cmap_anomalie(ind), ind.params)
    titlu = f"Tendința: {ind.titlu}"
    sub = (f"{lista[0]}–{lista[-1]} ({len(lista)} ani) · sezon: {sezon} · {METODE_TREND[metoda]} · "
           f"hașurat: nesemnificativ (p ≥ {alfa})")
    if metoda == "sen":
        b_ols, _ = panta_deceniu(lista, st[ind.cod])
        dif = _masca_zona(b - b_ols, zona)
        if np.isfinite(dif).any():
            log(f"   Theil–Sen față de OLS: diferența medie {ro(float(np.nanmean(dif)), 3)}, la 95 % din pixeli sub "
                f"{ro(float(np.nanpercentile(np.abs(dif), 95)), 3)} {ind.unitate}/deceniu")
    serie = [medie_zona(s, zona) for s in st[ind.cod]]
    fis = _iesiri_harta(out, nume, b, g, zona, ind2, titlu, sub, iesiri, None, None, divergent=True,
                        hasura=_masca_zona(p, zona) >= alfa, benzi_extra=[(p, "p-valoare")])
    if iesiri.get("grafic"):
        png_serie(out / f"{nume}_serie.png", lista, serie, f"{ind.titlu} · media zonei, pe ani", ind.unitate, subtitlu=zona.descriere())
    if iesiri.get("csv"):
        scrie_csv(out / f"{nume}_serie.csv", ["an", "valoare_medie_zona"], list(zip(lista, serie)))
    incarca_in_qgis(fis)
    log(f"== gata: {nume} · panta medie pe zonă {ro(medie_zona(b, zona), 3)} {ind.unitate}/deceniu")
    return _masca_zona(b, zona), _masca_zona(p, zona), g


def ruleaza_atlas(indicatori: dict, ani, sezon, zona: Zona, iesiri: dict, out, nume):
    """Statistici zonale pentru mai mulți indicatori deodată (o singură citire pe an). indicatori = {nume_camp: Indicator}."""
    out = Path(out)
    if not zona.gpkg:
        raise ValueError("Atlasul are nevoie de poligoane: Zona.poligoane(r\"…\\judete.gpkg\", coloana=\"…\")")
    log(f"== {nume}: atlas zonal · {len(indicatori)} indicatori · {ani[0]}–{ani[1]} · sezon {sezon}")
    cub, fr = deschide()
    g = grila_zonei(cub, zona)
    lista, st, _ = harti_anuale(cub, fr, list(indicatori.values()), ani, sezon, g)
    tabel, harti = {}, {}
    for camp, ind in indicatori.items():
        h = _masca_zona(np.nanmean(st[ind.cod], axis=0), zona); harti[camp] = h
        tabel[camp] = [s[1] for s in statistici_zonale(h, zona)]
    tabel["n_pixeli"] = [s[4] for s in statistici_zonale(next(iter(harti.values())), zona)]
    fis = []
    per = f"{lista[0]}–{lista[-1]}" if len(lista) > 1 else f"{lista[0]}"
    if iesiri.get("gpkg"):
        fis.append(scrie_gpkg_zone(out / f"{nume}.gpkg", zona, tabel))
    for camp, ind in indicatori.items():
        if iesiri.get("cog"):
            fis.append(scrie_cog(out / f"{nume}_{camp}.tif", harti[camp], g, [ind.titlu], ind.unitate, cmap=ind.cmap))
        if iesiri.get("png"):
            png_harta(out / f"{nume}_{camp}_harta.png", _zone_ca_harta(tabel[camp], zona), g, ind.titlu + " · medie pe zone",
                      ind.unitate, ind.cmap, zona=zona, subtitlu=f"{per} · sezon: {sezon} · {zona.descriere()}")
        if iesiri.get("grafic"):
            png_bare_zone(out / f"{nume}_{camp}_zone.png", [p[0] for p in zona.poligoane], tabel[camp],
                          f"{ind.titlu} · {per}", ind.unitate, cmap=ind.cmap)
    if iesiri.get("csv"):
        scrie_csv(out / f"{nume}.csv", ["zona"] + list(tabel),
                  [[zona.poligoane[i][0]] + [tabel[c][i] for c in tabel] for i in range(len(zona.poligoane))])
    incarca_in_qgis(fis)
    log(f"== gata: {nume}")
    return tabel


def _zone_ca_harta(valori, zona):
    h = np.full(zona._id.shape, np.nan, dtype="float32")
    for i, v in enumerate(valori, 1):
        h[zona._id == i] = v
    return h


def ruleaza_dungi(var, ani, zona: Zona, iesiri: dict, out, nume, ref=(1971, 2000), sezon="anual"):
    """Seria anuală pe zonă/punct + „dungile încălzirii”, pentru o variabilă („max_temp”…) sau pentru orice
    indicator (zile tropicale, zile de îngheț, CDD…), pe tot anul sau pe un sezon. Culorile urmează sensul
    indicatorului: mai cald / mai uscat = roșu sau maro."""
    out = Path(out)
    if isinstance(var, Indicator):
        ind = var
    else:
        ind = indicator("tmedie") if var == "tmedie" else indicator("suma" if var == "precipitation" else "medie", var=var)
    sez_txt = "" if sezon == "anual" else f" · sezon {sezon}"
    log(f"== {nume}: dungile încălzirii · {ind.titlu}{sez_txt} · {ani[0]}–{ani[1]} · {zona.descriere() if zona.punct else ''}")
    cub, fr = deschide()
    g = grila_zonei(cub, zona)
    lista, st, _ = harti_anuale(cub, fr, [ind], ani, sezon, g)
    if zona.poligoane and len(zona.poligoane) > 1:
        etichete = [p[0] for p in zona.poligoane]
        serii = {et: [] for et in etichete}
        for s in st[ind.cod]:
            for et, m, *_ in statistici_zonale(s, zona):
                serii[et].append(m)
    else:
        et = zona.nume or zona.descriere()
        serii = {et: [medie_zona(s, zona) for s in st[ind.cod]]}
    baze = {}
    if iesiri.get("png"):
        if ani[0] <= ref[0] and ref[1] <= ani[1]:
            valori_ref = {et: [v for a, v in zip(lista, valori) if ref[0] <= a <= ref[1]] for et, valori in serii.items()}
        else:
            _, sr, _ = harti_anuale(cub, fr, [ind], ref, sezon, g)
            valori_ref = {et: [] for et in serii}
            for h in sr[ind.cod]:
                if len(serii) > 1:
                    for et, media, *_ in statistici_zonale(h, zona):
                        valori_ref[et].append(media)
                else:
                    valori_ref[next(iter(serii))].append(medie_zona(h, zona))
        for et, valori in valori_ref.items():
            bune = np.asarray(valori)[np.isfinite(valori)]
            baze[et] = float(bune.mean()) if bune.size else np.nan
    fis = []
    for et, serie in serii.items():
        sl = "".join(c if c.isalnum() else "_" for c in et)[:40]
        if iesiri.get("png"):
            png_dungi(out / f"{nume}_{sl}_dungi.png", lista, serie, f"{et} · {ind.titlu}{sez_txt} · {lista[0]}–{lista[-1]}", ref,
                      cmap=_cmap_anomalie(ind), baza=baze[et])
        if iesiri.get("grafic"):
            png_serie(out / f"{nume}_{sl}_serie.png", lista, serie, f"{et} · {ind.titlu}{sez_txt} · valoarea anuală", ind.unitate,
                      bare=ind.unitate == "zile")
    if iesiri.get("csv"):
        scrie_csv(out / f"{nume}.csv", ["an"] + list(serii), [[a] + [serii[e][i] for e in serii] for i, a in enumerate(lista)])
    if iesiri.get("gpkg") and zona.poligoane:
        fis.append(scrie_gpkg_zone(out / f"{nume}.gpkg", zona, {f"a{a}": [serii[e][i] for e in serii] for i, a in enumerate(lista)}))
    incarca_in_qgis(fis)
    log(f"== gata: {nume}")
    return lista, serii


def ruleaza_episod(var, start, sfarsit, zona: Zona, iesiri: dict, out, nume, vmin=None, vmax=None, fps=4):
    """Sub-cub zilnic pentru un episod (NetCDF CF pentru QGIS Temporal Controller) + animație GIF."""
    import xarray as xr
    out = Path(out)
    log(f"== {nume}: episod {var} {start} → {sfarsit}")
    cub, fr = deschide()
    g = grila_zonei(cub, zona)
    d1 = min(np.datetime64(sfarsit), fr[var])
    if np.datetime64(start) > d1:
        raise ValueError(f"Perioada {start} → {sfarsit} începe după ultima zi cu date ({fr[var]}).")
    nch, mb = estimeaza_cost(cub, var, np.datetime64(start), d1, g)
    log(f"   se citesc ~{nch} chunk-uri (~{mb:.0f} MB)")
    d, zile = citeste(cub, (var,), np.datetime64(start), d1, g)
    a = d[var]
    if zona._id is not None:
        a = np.where(zona._id[None] > 0, a, np.nan)
    fis = []
    if iesiri.get("netcdf"):
        ds = xr.Dataset({var: (("time", "lat", "lon"), a, {"units": "degC" if var != "precipitation" else "mm",
                                                         "grid_mapping": "crs", "long_name": var})},
                        coords={"time": zile.astype("datetime64[ns]"),
                                "lat": ("lat", g.y, {"units": "degrees_north", "standard_name": "latitude"}),
                                "lon": ("lon", g.x, {"units": "degrees_east", "standard_name": "longitude"})})
        ds["crs"] = ((), 0, {"grid_mapping_name": "latitude_longitude", "epsg_code": "EPSG:4326",
                             "semi_major_axis": 6378137.0, "inverse_flattening": 298.257223563})
        ds.attrs = {"Conventions": "CF-1.8", "source": ATRIBUIRE, "title": f"{var} {start} – {d1}"}
        cale = _gata(out / f"{nume}.nc")
        for motor in ("netcdf4", "h5netcdf", "scipy"):
            try:
                ds.to_netcdf(cale, engine=motor); log(f"   NetCDF ({motor}): {cale}"); fis.append(cale); break
            except Exception as e:  # noqa: BLE001
                log(f"   motorul NetCDF „{motor}” indisponibil ({type(e).__name__})")
    if iesiri.get("cog"):
        fis.append(scrie_cog(out / f"{nume}_zile.tif", [a[i] for i in range(a.shape[0])], g, [str(z) for z in zile],
                             UNITATI[var]))
    if iesiri.get("gif") or iesiri.get("png"):
        plt = _plt()
        from matplotlib.animation import FuncAnimation, PillowWriter
        vals = a[np.isfinite(a)]
        lo = vmin if vmin is not None else float(np.nanpercentile(vals, 2))
        hi = vmax if vmax is not None else float(np.nanpercentile(vals, 98))
        cmap = "Blues" if var == "precipitation" else "RdYlBu_r"
        fig, ax = plt.subplots(figsize=(9, 5.8))
        im = ax.imshow(a[0], extent=g.extent, cmap=cmap, vmin=lo, vmax=hi, interpolation="nearest")
        _contururi(ax, zona, g)
        ax.set_aspect(1 / math.cos(math.radians((g.extent[2] + g.extent[3]) / 2)))
        cb = plt.colorbar(im, ax=ax, shrink=0.8); cb.set_label(UNITATI[var])
        tt = ax.set_title(f"{var} · {zile[0]}")
        if iesiri.get("png"):
            fig.savefig(_gata(out / f"{nume}_prima_zi.png"), dpi=DPI)
        if iesiri.get("gif"):
            def cadru(i):
                im.set_data(a[i]); tt.set_text(f"{var} · {zile[i]}"); return im, tt
            FuncAnimation(fig, cadru, frames=a.shape[0]).save(_gata(out / f"{nume}.gif"), writer=PillowWriter(fps=fps), dpi=100)
            log(f"   GIF: {out / f'{nume}.gif'}")
        plt.close(fig)
    incarca_in_qgis(fis)
    log(f"== gata: {nume}")
    return a, zile, g


# =====================================================================================
# SERII ZONALE ȘI GRAFICE COMPLEXE (scriptul 15)
# Principiu: datele zilnice se reduc ÎNTÂI la seria zilnică medie a fiecărei zone (zone × zile),
# care se păstrează în cache. Toate graficele se construiesc din aceste serii mici.
# =====================================================================================
LUNI = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi", "dec"]
GRAFICE_ZILNICE = {"serie_zilnica": "seria zilnică", "anomalii_lunare": "anomaliile lunare"}
PALETA_ZONE = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e87ba4", "#008300"]   # categorială, în ordine fixă


def _valoare_zilnica(d, var):
    return (d["max_temp"] + d["min_temp"]) / 2 if var == "tmedie" else d[var]


def _variabile_pentru(var):
    return ("max_temp", "min_temp") if var == "tmedie" else (var,)


def _coloane_zone(zona: Zona, g: Grila):
    ny, nx = g.forma
    if zona._id is not None and len(zona.poligoane) > 0:
        ids = zona._id.ravel()
        et = [p[0] for p in zona.poligoane]
        cols = [np.flatnonzero(ids == i + 1) for i in range(len(et))]
        tot = np.flatnonzero(ids > 0)
    else:
        tot = np.flatnonzero(zona._id.ravel() > 0) if zona._id is not None else np.arange(ny * nx)
        et, cols = [], []
    return et, cols, tot


def _medii_zone(v, coloane, prag=0.5):
    """v: (t, y, x) → (n_zone, t): media zilnică pe pixelii valizi ai fiecărei zone (NaN sub `prag` pixeli valizi).
    `prag` e o acoperire în SPAȚIU (fracția pixelilor zonei într-o zi), diferită de PRAG_VALID (fracția zilelor),
    care se aplică la agregarea pe ani/luni (`_agregat`)."""
    v2 = v.reshape(v.shape[0], -1)
    out = np.full((len(coloane), v.shape[0]), np.nan, dtype="float32")
    for k, c in enumerate(coloane):
        if c.size == 0:
            continue
        sub = v2[:, c]
        fin = np.isfinite(sub)
        n = fin.sum(axis=1)
        s = np.where(fin, sub, 0).sum(axis=1)
        ok = n >= max(1, prag * c.size)
        out[k] = np.where(ok, s / np.maximum(n, 1), np.nan)
    return out


def _semnatura(var, zona: Zona, g: Grila, etichete):
    import hashlib
    # Seriile din cache sunt zilnice, brute (PRAG_VALID se aplică abia la agregare, deci nu intră în cheie).
    # Data și dimensiunea fișierului vectorial intră în cheie: un GPKG modificat sub același nume refac seriile.
    try:
        st = Path(zona.gpkg).stat() if zona.gpkg else None
        semn_fis = [st.st_mtime_ns, st.st_size] if st else None
    except OSError:
        semn_fis = None
    cheie = ["zone-v2", URL, var, str(zona.gpkg), semn_fis, zona.strat, zona.coloana, zona.filtru, zona.bbox, zona.punct,
             g.iy0, g.iy1, g.ix0, g.ix1, etichete]
    if zona._id is not None:
        cheie.append(hashlib.sha256(np.ascontiguousarray(zona._id)).hexdigest())
    if zona.altitudine:
        cheie.append(["altitudine", list(zona.altitudine), _semn_dem()])
    if zona.valori is not None or zona.unite:            # doar pentru forma nouă: cache-ul vechi rămâne valabil
        cheie += [sorted(_norm_text(v) for v in (zona.valori or [])), zona.unite]
    j = json.dumps(cheie, ensure_ascii=False, default=str)
    return hashlib.md5(j.encode("utf-8")).hexdigest()[:10]


def _salveaza_cache(cale, *, comprimat=False, **benzi):
    import tempfile
    with tempfile.NamedTemporaryFile(dir=cale.parent, delete=False) as f:
        tmp = Path(f.name)
    try:
        with tmp.open("wb") as f:
            (np.savez_compressed if comprimat else np.savez)(f, **benzi)
        tmp.replace(cale)
    finally:
        tmp.unlink(missing_ok=True)

def serii_zonale(cub, fr, var, ani_necesari, zona: Zona, g: Grila, total_nume, cache_dir):
    """Seriile zilnice ale zonelor pentru anii ceruți (cu cache incremental, salvat după fiecare an).
    Returnează (etichete, {an: ndarray (n_zone, zile)}); ultima zonă = totalul."""
    et, cols, tot = _coloane_zone(zona, g)
    if len(et) == 1:
        etichete, coloane = et, cols
    else:
        etichete, coloane = et + [total_nume], cols + [tot]
    frontiera = min(fr[v] for v in _variabile_pentru(var))
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    fis = cache_dir / f"serii_{var}_{_semnatura(var, zona, g, etichete)}.npz"
    serii = {}
    if fis.exists():
        with np.load(fis, allow_pickle=False) as z:
            if list(z["etichete"]) == etichete:
                serii = {int(k[1:]): z[k] for k in z.files if k.startswith("a")}
                log(f"   cache: {len(serii)} ani deja calculați ({fis.name})")
    lipsa = []
    for an in sorted(ani_necesari):
        d0 = np.datetime64(f"{an}-01-01")
        if d0 > frontiera:
            continue
        d1 = min(np.datetime64(f"{an}-12-31"), frontiera)
        n_asteptat = int((d1 - d0).astype(int)) + 1
        if an not in serii or serii[an].shape[1] != n_asteptat:
            lipsa.append((an, d0, d1))
    if lipsa:
        mb_total = sum(sum(estimeaza_cost(cub, v, a0, a1, g)[1] for v in _variabile_pentru(var)) for _, a0, a1 in lipsa)
        log(f"   de citit: {len(lipsa)} ani, ~{mb_total / 1000:.1f} GB (o singură dată; apoi din cache)")
    for k, (an, d0, d1) in enumerate(lipsa, 1):
        t0 = time.perf_counter()
        d, _ = citeste(cub, _variabile_pentru(var), d0, d1, g)
        serii[an] = _medii_zone(_valoare_zilnica(d, var), coloane)
        del d                                         # un singur an în memorie (v5.1)
        _salveaza_cache(fis, etichete=np.array(etichete), **{f"a{a}": serii[a] for a in serii})
        log(f"   {an}: {serii[an].shape[1]} zile × {len(etichete)} zone în {time.perf_counter() - t0:.1f} s ({k}/{len(lipsa)})")
    return etichete, serii, frontiera


def _agregat(v, var, minim=None):
    """Agregarea unei bucăți de serie zilnică (… , zile): medie (temperaturi) sau sumă (precipitații),
    NaN dacă sub `minim` zile valide (implicit PRAG_VALID, din Setări avansate); suma se corectează
    proporțional pentru zilele lipsă."""
    if minim is None:
        minim = PRAG_VALID
    n = v.shape[-1]
    fin = np.isfinite(v); nv = fin.sum(axis=-1)
    s = np.where(fin, v, 0).sum(axis=-1)
    ok = nv >= minim * n
    if var == "precipitation":
        return np.where(ok, s * n / np.maximum(nv, 1), np.nan)
    return np.where(ok, s / np.maximum(nv, 1), np.nan)


def _anuale(serii, var, ani, frontiera):
    """(n_zone, n_ani): media/suma fiecărui an complet; anul care conține frontiera e exclus."""
    lista = [a for a in range(ani[0], ani[1] + 1) if a in serii and np.datetime64(f"{a}-12-31") <= frontiera]
    if not lista:
        raise RuntimeError("Niciun an complet în interval.")
    return lista, np.stack([_agregat(serii[a], var) for a in lista], axis=1)


def _lunare(serii, var, an, frontiera):
    """(n_zone, 12) pentru un an; lunile incomplete (după frontieră) = NaN."""
    v = serii[an]; z = v.shape[0]
    out = np.full((z, 12), np.nan)
    zi0 = np.datetime64(f"{an}-01-01")
    for m in range(12):
        a = int((np.datetime64(f"{an}-{m + 1:02d}-01") - zi0).astype(int))
        b = int(((np.datetime64(f"{an}-{m + 1:02d}", "M") + 1).astype("datetime64[D]") - zi0).astype(int))
        if b > v.shape[1]:
            continue
        out[:, m] = _agregat(v[:, a:b], var)
    return out


_METODA_SERII = "ols"            # metoda tendinței în graficele seriilor; o fixează ruleaza_serii pe durata rulării


def _panta(ani, y, metoda=None):
    metoda = metoda or _METODA_SERII
    if metoda == "sen":
        b, p = sen_mk_deceniu(ani, np.asarray(y, float)[:, None])
        return float(b[0]), float(p[0])
    x = np.asarray(ani, float); y = np.asarray(y, float); ok = np.isfinite(y)
    if ok.sum() < 10:
        return np.nan, np.nan
    x, y = x[ok], y[ok]
    b, a = np.polyfit(x, y, 1)
    res = y - (a + b * x); sxx = ((x - x.mean()) ** 2).sum()
    se = math.sqrt((res ** 2).sum() / (len(x) - 2) / sxx) if sxx > 0 else np.nan
    p = float(p_student(b / se, len(x) - 2)) if se and np.isfinite(se) and se > 0 else np.nan
    return b * 10, p


def _rulant(y, n=11):
    y = np.asarray(y, float); out = np.full_like(y, np.nan); h = n // 2
    for i in range(len(y)):
        w = y[max(0, i - h): i + h + 1]
        if np.isfinite(w).sum() >= h + 1:
            out[i] = np.nanmean(w)
    return out


def _doy_366(an):
    """Indicii zilelor unui an pe o axă de 366 de zile (29 februarie are poziția 59; în anii nebisecți lipsește)."""
    n = 366 if (an % 4 == 0 and (an % 100 != 0 or an % 400 == 0)) else 365
    i = np.arange(n)
    return i if n == 366 else np.where(i >= 59, i + 1, i)


def _climatologie_zilnica(serii, k, referinta, frontiera, cumulat_de_la=None, netezire=15):
    """Media, p10 și p90 pe ziua din an (axa de 366 de zile), din anii de referință, netezite circular."""
    ani = [a for a in range(referinta[0], referinta[1] + 1) if a in serii and np.datetime64(f"{a}-12-31") <= frontiera]
    if not ani:
        return None
    m = np.full((len(ani), 366), np.nan)
    for j, a in enumerate(ani):
        v = serii[a][k]
        if cumulat_de_la is not None:
            v = np.nancumsum(np.where(np.arange(len(v)) >= cumulat_de_la, v, 0))
        m[j, _doy_366(a)[:len(v)]] = v
    m[:, 59] = np.where(np.isnan(m[:, 59]), (m[:, 58] + m[:, 60]) / 2, m[:, 59])
    med, p10, p90 = np.nanmean(m, 0), np.nanpercentile(m, 10, 0), np.nanpercentile(m, 90, 0)
    if cumulat_de_la is None and netezire > 1:
        ker = np.ones(netezire) / netezire
        f = lambda z: np.convolve(np.r_[z[-netezire:], z, z[:netezire]], ker, "same")[netezire:-netezire]  # noqa: E731
        med, p10, p90 = f(med), f(p10), f(p90)
    return dict(med=med, p10=p10, p90=p90, ani=ani)


def _runs(mask):
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(int))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


# Graficele de mai jos primesc fie o VARIABILĂ zilnică ("max_temp", "precipitation"…), fie un INDICATOR din registru
# (zile tropicale, CDD, GDD…). Funcțiile următoare dau unitatea, titlul și sensul culorilor pentru oricare dintre ele.
def _unit(var, agregat=True):
    if isinstance(var, Indicator):
        return var.unitate
    if var == "precipitation":
        return "mm/an" if agregat else "mm/zi"
    return "°C"


def _titlu_var(var):
    if isinstance(var, Indicator):
        return var.titlu
    return {"max_temp": "Temperatura maximă", "min_temp": "Temperatura minimă", "tmedie": "Temperatura medie (Tmax+Tmin)/2",
            "precipitation": "Precipitații"}[var]


def _e_procent(var):
    """Anomalia în % din normală (în loc de diferență): doar pentru cantitățile de precipitații (sume / medii)."""
    if isinstance(var, Indicator):
        return var.functie in (i_suma, i_medie) and var.params.get("var") == "precipitation"
    return var == "precipitation"


_CMAP_RECI = ("PuBu", "Blues", "BuPu", "GnBu", "YlGnBu", "PuBuGn", "Purples")
_CMAP_CALDE = ("YlOrRd", "YlOrBr", "Oranges", "Reds", "OrRd", "RdYlBu_r", "inferno", "magma", "hot")


def e_standardizat(ind):
    """SPI / SPEI: valori adimensionale centrate pe 0 (abateri standardizate)."""
    return isinstance(ind, Indicator) and ind.functie in (i_spi, i_spei)


def _cmap_anomalie(var):
    """Paleta divergentă a anomaliilor, cu sensul ales după indicator: mai cald / mai uscat = roșu sau maro.
    Ex.: zilele de îngheț în plus sunt albastre (RdBu), zilele tropicale în plus sunt roșii (RdBu_r),
    precipitațiile în plus sunt verzi-albastre (BrBG), zilele secetoase (CDD) în plus sunt maro (BrBG_r)."""
    if not isinstance(var, Indicator):
        return "BrBG" if var == "precipitation" else "RdBu_r"
    if var.functie in (i_de_martonne, i_spi, i_spei, i_bilant):
        return "BrBG"                                    # mai mare = mai umed
    if var.functie is i_pet:
        return "BrBG_r"                                  # mai multă evapotranspirație = mai uscat
    if var.functie is i_ultimul_inghet:
        return "RdBu"
    if var.functie is i_zile_sub and var.params.get("var") == "precipitation":
        return "BrBG_r"
    precip = "precipitation" in var.variabile and not any(v in var.variabile for v in ("max_temp", "min_temp"))
    if _e_procent(var):
        return "BrBG"
    if precip:
        return "BrBG_r" if var.cmap in _CMAP_CALDE else "BrBG"
    return "RdBu" if var.cmap in _CMAP_RECI else "RdBu_r"


def _eticheta_an(var):
    if isinstance(var, Indicator):
        return "valoarea anuală"
    return "suma anuală" if var == "precipitation" else "media anuală"


def var_simpla(ind):
    """Întoarce variabila utilizabilă în graficele zilnice și lunare, dacă există."""
    if not isinstance(ind, Indicator):
        return ind
    v = ind.params.get("var")
    if ind.functie is i_tmedie:
        return "tmedie"
    if ind.functie is i_medie and v in ("max_temp", "min_temp"):
        return v
    if ind.functie is i_suma and v == "precipitation":
        return "precipitation"
    return None


def anuale_indicator(cub, fr, ind, ani, sezon, zona: Zona, g: Grila, total_nume, cache_dir):
    """Valoarea anuală a unui indicator pe fiecare zonă: indicatorul se calculează PER PIXEL și per an
    (harti_anuale), apoi se mediază pe pixelii zonei. Cache incremental pe an (un fișier per indicator + zonă).
    Returnează (etichete, ani, A[n_zone, n_ani]); ultima zonă = totalul (media tuturor pixelilor zonelor)."""
    et, cols, tot = _coloane_zone(zona, g)
    if len(et) == 1:
        etichete, coloane = et, cols
    elif et:
        etichete, coloane = et + [total_nume], cols + [tot]
    else:
        etichete, coloane = [total_nume], [tot if zona._id is None else np.flatnonzero(zona._id.ravel() > 0)]
    spec = json.dumps([ind.functie.__name__, ind.params, sezon, PRAG_VALID, ACCEPTA_PARTIAL], sort_keys=True, default=str)
    import hashlib
    h = hashlib.md5((spec + _semnatura("ind", zona, g, etichete)).encode()).hexdigest()[:10]
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    fis = cache_dir / f"anual_{ind.cod}_{h}.npz"
    val = {}
    if fis.exists():
        with np.load(fis, allow_pickle=False) as z:
            if list(z["etichete"]) == etichete:
                val = {int(k[1:]): z[k] for k in z.files if k.startswith("a")}
                log(f"   cache: {len(val)} ani ai indicatorului deja calculați ({fis.name})")
    frontiera = min(fr[v] for v in ind.variabile)
    inceput = np.datetime64(str(cub.time.values[0])[:10], "D")
    def complet(an):
        d0, d1, _ = perioada(an, sezon)
        return inceput <= d0 and d1 <= frontiera
    val = {a: v for a, v in val.items() if complet(a)}
    lipsa = [a for a in range(ani[0], ani[1] + 1) if a not in val]
    if lipsa:
        log(f"   de calculat: {len(lipsa)} ani ({ind.titlu}, per pixel, apoi media pe zone)")
    for a in lipsa:
        d0, d1, _ = perioada(a, sezon)
        if d0 > frontiera or d1 < inceput or (not ACCEPTA_PARTIAL and not complet(a)):
            continue
        lst, st, _ = harti_anuale(cub, fr, [ind], (a, a), sezon, g)
        v2 = st[ind.cod][0].ravel()
        rez = np.full(len(coloane), np.nan, "float32")
        acoperire = []
        for k, c in enumerate(coloane):
            if c.size:
                x = v2[c]; x = x[np.isfinite(x)]
                acoperire.append(x.size / c.size)
                if x.size >= max(1, 0.5 * c.size):
                    rez[k] = x.mean()
            else:
                acoperire.append(0.0)
        log(f"   {a}: {etichete[-1]} · {acoperire[-1]:.1%} pixeli valizi; "
            f"{sum(v < 0.5 for v in acoperire[:len(et)])} zone individuale sub 50 %")
        val[a] = rez
        if complet(a):
            _salveaza_cache(fis, etichete=np.array(etichete), **{f"a{x}": v for x, v in val.items() if complet(x)})
    lista = [a for a in range(ani[0], ani[1] + 1) if a in val]
    if not lista:
        raise ValueError(f"Niciun an cu date pentru {ind.titlu} în {ani[0]}–{ani[1]}.")
    return etichete, lista, np.stack([val[a] for a in lista], axis=1)


def d1_complet(an, sezon, frontiera):
    """Sezonul anului `an` s-a încheiat înainte de frontiera datelor?"""
    return perioada(an, sezon)[1] <= frontiera



# ---------------------------------------------------------------------------------- graficele
def g_serie_zilnica(cale, eticheta, k, serii, var, fereastra, frontiera, referinta, zerouri=None):
    """Seria zilnică a unei zone pe o fereastră: climatologia de referință (medie, p10–p90), golurile NaN,
    frontiera last_*_time și, opțional, zilele pre-alocate (0,0) de după ea."""
    plt = _plt()
    import matplotlib.dates as mdates
    a0, a1 = np.datetime64(fereastra[0]), np.datetime64(fereastra[1])
    zile, val = [], []
    for an in range(int(str(a0)[:4]), int(str(min(a1, frontiera))[:4]) + 1):
        if an not in serii:
            continue
        v = serii[an][k]; z = np.datetime64(f"{an}-01-01") + np.arange(len(v))
        m = (z >= a0) & (z <= a1); zile.append(z[m]); val.append(v[m])
    if not zile:
        log("   [atenție] fereastra zilnică nu are date"); return None
    zile = np.concatenate(zile); val = np.concatenate(val).astype(float)
    if zerouri is not None:
        zile = np.concatenate([zile, zerouri[0]]); val = np.concatenate([val, zerouri[1][k]])
    doy = np.array([_doy_366(int(str(z)[:4]))[int((z - np.datetime64(str(z)[:4] + "-01-01")).astype(int))] for z in zile])
    dz = zile.astype("datetime64[ms]").astype(object)
    precip = var == "precipitation"
    fig, (a, b) = plt.subplots(2, 1, figsize=(12, 7.6), sharex=True, gridspec_kw={"height_ratios": [1.6, 1]})
    dupa = zile > frontiera
    for ax in (a, b):
        for i, j in _runs(np.isnan(val) & ~dupa):
            ax.axvspan(dz[i], dz[j - 1], color="#8a8986", alpha=0.25, lw=0)
        if dupa.any():
            ax.axvspan(dz[np.argmax(dupa)], dz[-1], color="#e34948", alpha=0.08, lw=0)
            ax.axvline(frontiera.astype("datetime64[ms]").astype(object), color="#0b0b0b", ls=":", lw=1.3)
        ax.grid(axis="y", color="#e6e5e0")
    if not precip:
        cl = _climatologie_zilnica(serii, k, referinta, frontiera)
        if cl:
            a.fill_between(dz, cl["p10"][doy], cl["p90"][doy], color="#2a78d6", alpha=0.13, lw=0,
                           label=f"p10–p90 {referinta[0]}–{referinta[1]}")
            a.plot(dz, cl["med"][doy], color="#2a78d6", lw=1, ls="--", label=f"media zilnică {referinta[0]}–{referinta[1]}")
            real = ~dupa                                        # zilele pre-alocate (0,0) nu sunt „extreme”
            peste = np.where(real & (val > cl["p90"][doy]), val, np.nan)
            sub = np.where(real & (val < cl["p10"][doy]), val, np.nan)
            an_ = np.where(real, val - cl["med"][doy], np.nan)
            b.bar(dz, np.where(an_ >= 0, an_, 0), width=1.0, color="#e34948", lw=0)
            b.bar(dz, np.where(an_ < 0, an_, 0), width=1.0, color="#2a78d6", lw=0)
            b.axhline(0, color="#52514e", lw=0.8)
            b.set_ylabel(f"anomalie zilnică ({_unit(var, False)})")
            b.set_title(f"B. Abaterea zilnică față de media {referinta[0]}–{referinta[1]}", fontsize=10.5)
        a.plot(dz, np.where(dupa, np.nan, val), color="#0b0b0b", lw=1.1, label="valoarea zilnică")
        if dupa.any():
            a.plot(dz, np.where(dupa, val, np.nan), color="#e34948", lw=1.8, label="citit după frontieră (0,0)")
        if cl:
            a.scatter(dz, peste, s=9, color="#e34948", zorder=3, label="peste p90")
            a.scatter(dz, sub, s=9, color="#2a78d6", zorder=3, label="sub p10")
        a.set_ylabel(f"{var} ({_unit(var, False)})")
    else:
        a.bar(dz, np.nan_to_num(val), width=1.0, color="#2a78d6", lw=0, label="precipitații zilnice")
        a.set_ylabel("mm/zi")
        cum = np.where(dupa, np.nan, np.nancumsum(np.where(dupa, 0, val)))
        # climatologia cumulatului: pentru fiecare an de referință, aceeași zi de start (lună-zi), aceeași lungime
        n = len(val); md = str(zile[0])[5:]
        bucati = []
        for y in range(referinta[0], referinta[1] + 1):
            try:
                s0 = np.datetime64(f"{y}-{md}")
            except ValueError:
                s0 = np.datetime64(f"{y}-02-28")
            vals, zi_ = [], s0
            while len(vals) < n:
                an_ = int(str(zi_)[:4])
                if an_ not in serii or np.datetime64(f"{an_}-12-31") > frontiera:
                    break
                v_ = serii[an_][k]; i_ = int((zi_ - np.datetime64(f"{an_}-01-01")).astype(int))
                vals += list(v_[i_:i_ + (n - len(vals))]); zi_ = np.datetime64(f"{an_ + 1}-01-01")
            if len(vals) == n:
                bucati.append(np.nancumsum(np.asarray(vals, float)))
        if bucati:
            B_ = np.stack(bucati)
            b.fill_between(dz, np.percentile(B_, 10, 0), np.percentile(B_, 90, 0), color="#2a78d6", alpha=0.13, lw=0,
                           label=f"p10–p90 {referinta[0]}–{referinta[1]} ({len(bucati)} ani)")
            b.plot(dz, B_.mean(0), color="#2a78d6", ls="--", lw=1.1, label=f"media {referinta[0]}–{referinta[1]}")
        b.plot(dz, cum, color="#0b0b0b", lw=1.6, label="cumulat în fereastră")
        b.set_ylabel("mm cumulați")
        b.set_title("B. Precipitațiile cumulate față de climatologie (aceeași zi de start)", fontsize=10.5)
        b.legend(loc="upper left", fontsize=8.5, ncol=3, frameon=False)
    if dupa.any():
        a.text(dz[np.argmax(dupa)], a.get_ylim()[1], "  după frontieră: 0,0 (pre-alocat)", va="top", fontsize=8.5,
               color="#e34948", fontweight="bold")
    ok = np.isfinite(val) & ~dupa
    if ok.any() and not precip:
        i, j = np.nanargmax(np.where(ok, val, np.nan)), np.nanargmin(np.where(ok, val, np.nan))
        a.annotate(f"max {ro(val[i])} ({str(zile[i])})", (dz[i], val[i]), xytext=(4, 6), textcoords="offset points", fontsize=8.5)
        a.annotate(f"min {ro(val[j])} ({str(zile[j])})", (dz[j], val[j]), xytext=(4, -12), textcoords="offset points", fontsize=8.5)
    a.set_title(f"A. {eticheta} · {_titlu_var(var)} zilnică · {str(zile[0])} → {str(zile[-1])}", fontsize=11)
    a.legend(loc="best", fontsize=8.5, ncol=2, framealpha=0.85, edgecolor="none")
    b.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.text(0.0, -0.01, f"Gri: zile fără date (NaN) · linia punctată: frontiera last_*_time {frontiera} · {ATRIBUIRE}",
             fontsize=8, color="#555555")
    fig.tight_layout(h_pad=1.5)
    cale = _gata(cale); fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG serie zilnică: {cale}")
    return cale


def g_serii_anuale(cale, etichete, ani, A, var, detaliu, total_idx):
    """Toate zonele (linii subțiri gri), totalul (negru, cu media mobilă pe 11 ani) și zonele de detaliu (colorate)."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(12, 5.6))
    for k in range(len(etichete)):
        if k != total_idx and etichete[k] not in detaliu:
            ax.plot(ani, A[k], color="#c3c2b7", lw=0.7, zorder=1)
    for c, (k, et) in zip(PALETA_ZONE, [(etichete.index(e), e) for e in detaliu if e in etichete]):
        b, p = _panta(ani, A[k])
        ax.plot(ani, A[k], color=c, lw=1.6, zorder=3, label=f"{et}  ({'+' if b >= 0 else '−'}{ro(abs(b), 2)} {_unit(var)}/deceniu)")
    if total_idx is not None:
        b, p = _panta(ani, A[total_idx])
        ax.plot(ani, A[total_idx], color="#0b0b0b", lw=1.4, marker="o", ms=2.5, zorder=4,
                label=f"{etichete[total_idx]}  ({'+' if b >= 0 else '−'}{ro(abs(b), 2)} {_unit(var)}/deceniu, p={ro(p, 3)})")
        ax.plot(ani, _rulant(A[total_idx]), color="#0b0b0b", lw=2.6, alpha=0.45, zorder=4, label="media mobilă pe 11 ani")
    ax.plot([], [], color="#c3c2b7", lw=0.7, label="celelalte zone")
    ax.set_ylabel(f"{_titlu_var(var)} · {_eticheta_an(var)} ({_unit(var)})")
    ax.grid(axis="y", color="#e6e5e0")
    ax.set_title(f"{_titlu_var(var)} · serii anuale pe zone · {ani[0]}–{ani[-1]}", fontsize=11)
    ax.legend(loc="upper left", fontsize=8.5, frameon=False)
    fig.text(0.0, -0.02, ATRIBUIRE, fontsize=8, color="#555555")
    cale = _gata(cale); fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG serii anuale: {cale}")
    return cale


def g_multiple_mici(cale, etichete, ani, A, var, total_idx, coloane=6):
    """Câte un mini-grafic pe zonă (aceeași scară), cu tendința și panta colorată după semn."""
    plt = _plt()
    idx = [k for k in range(len(etichete)) if k != total_idx]
    idx = sorted(idx, key=lambda k: etichete[k]) + ([total_idx] if total_idx is not None else [])
    n = len(idx); nc = min(coloane, n); nr = math.ceil(n / nc)
    lo, hi = np.nanmin(A[idx]), np.nanmax(A[idx]); pad = 0.05 * (hi - lo or 1)
    fig, axs = plt.subplots(nr, nc, figsize=(2.3 * nc, 1.55 * nr + 0.8), sharex=True, sharey=True, squeeze=False)
    for ax in axs.flat:
        ax.set_visible(False)
    for ax, k in zip(axs.flat, idx):
        ax.set_visible(True)
        b, p = _panta(ani, A[k])
        x = np.asarray(ani, float); y = A[k]; ok = np.isfinite(y)
        ax.plot(x, y, color="#0b0b0b" if k == total_idx else "#2a78d6", lw=0.9)
        if np.isfinite(b):
            bb = b / 10                                        # aceeași pantă ca în etichetă (OLS sau Theil–Sen)
            aa = float(np.median(y[ok] - bb * x[ok])) if _METODA_SERII == "sen" else float(np.mean(y[ok] - bb * x[ok]))
            col = "#e34948" if b > 0 else "#2a78d6"
            ax.plot(x[ok], aa + bb * x[ok], color=col, lw=1.2, ls="-" if p < 0.05 else "--")
            ax.text(0.97, 0.06, f"{'+' if b >= 0 else '−'}{ro(abs(b), 2)}", transform=ax.transAxes, ha="right", fontsize=8,
                    color=col, fontweight="bold" if p < 0.05 else "normal")
        ax.set_title(etichete[k], fontsize=8.5, fontweight="bold" if k == total_idx else "normal", loc="left")
        ax.set_ylim(lo - pad, hi + pad); ax.tick_params(labelsize=7); ax.grid(axis="y", color="#eeeeea")
        from matplotlib.ticker import MaxNLocator
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
    fig.suptitle(f"{_titlu_var(var)} · {ani[0]}–{ani[-1]} · panta în {_unit(var)}/deceniu (linie plină și bold: p < 0,05)",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.text(0.0, 0.0, ATRIBUIRE, fontsize=8, color="#555555")
    cale = _gata(cale); fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG multiple mici: {cale}")
    return cale


def g_bare_zone(cale, etichete, stat, var, recent, referinta, total_idx, alfa=0.05):
    """Trei panouri aliniate pe zone: media perioadei recente, anomalia față de referință, tendința (± semnificație)."""
    plt = _plt()
    import matplotlib
    ordine = sorted(range(len(etichete)), key=lambda k: (-1e9 if k == total_idx else stat["medie"][k]) if np.isfinite(stat["medie"][k]) else -1e10)
    y = np.arange(len(ordine))
    et = [etichete[k] for k in ordine]
    fig, axs = plt.subplots(1, 3, figsize=(14, 0.27 * len(ordine) + 2.2), sharey=True)
    procent = _e_procent(var)
    # (a) media recentă
    # (a) media recentă: puncte (nu bare: axa nu pornește de la zero), referința ca semn gri
    v = np.array([stat["medie"][k] for k in ordine]); vb = np.array([stat["baza"][k] for k in ordine])
    norm = plt.Normalize(np.nanmin(v), np.nanmax(v))
    cm = matplotlib.colormaps["Blues" if procent else "YlOrRd"]
    for i, (x, xb) in enumerate(zip(v, vb)):
        axs[0].plot([xb, x], [i, i], color="#c3c2b7", lw=1.5, zorder=1)
        axs[0].scatter([xb], [i], s=18, color="#8a8986", zorder=2)
        axs[0].scatter([x], [i], s=46, zorder=3, edgecolor="#0b0b0b", linewidth=0.6,
                       color="#0b0b0b" if ordine[i] == total_idx else cm(0.25 + 0.75 * norm(x)))
        axs[0].text(x, i, f"  {ro(x, 1)}", va="center", fontsize=7.5)
    span = (np.nanmax(np.r_[v, vb]) - np.nanmin(np.r_[v, vb])) or 1
    axs[0].set_xlim(np.nanmin(np.r_[v, vb]) - 0.05 * span, np.nanmax(np.r_[v, vb]) + 0.15 * span)
    axs[0].scatter([], [], s=18, color="#8a8986", label=f"{referinta[0]}–{referinta[1]}")
    axs[0].scatter([], [], s=46, color=cm(0.8), edgecolor="#0b0b0b", label=f"{recent[0]}–{recent[1]}")
    axs[0].legend(loc="upper center", bbox_to_anchor=(0.5, -0.045 * 30 / max(len(ordine), 8)), ncol=2, fontsize=7.5, frameon=False)
    axs[0].set_title(f"Media pe perioadă ({_unit(var)})", fontsize=10.5)
    # (b) anomalia
    an = np.array([stat["anomalie"][k] for k in ordine])
    m = np.nanmax(np.abs(an)) or 1
    cmd = matplotlib.colormaps[_cmap_anomalie(var)]
    axs[1].barh(y, an, color=[cmd(0.5 + 0.5 * x / m) for x in an], height=0.75, edgecolor=["#0b0b0b" if k == total_idx else "none" for k in ordine])
    axs[1].axvline(0, color="#52514e", lw=0.8)
    axs[1].set_title((f"Abaterea relativă față de {referinta[0]}–{referinta[1]} (%)" if procent
                      else f"Anomalia față de {referinta[0]}–{referinta[1]} ({_unit(var)})"), fontsize=10.5)
    for i, x in enumerate(an):
        axs[1].text(x, i, f" {'+' if x >= 0 else ''}{ro(x, 1)}", va="center", fontsize=7.5, ha="left" if x >= 0 else "right")
    axs[1].set_xlim(-1.25 * m if np.nanmin(an) < 0 else 0, 1.25 * m)
    # (c) tendința
    tr = np.array([stat["tendinta"][k] for k in ordine]); pv = np.array([stat["p"][k] for k in ordine])
    mt = np.nanmax(np.abs(tr)) or 1
    for i, (x, p) in enumerate(zip(tr, pv)):
        col = cmd(0.5 + 0.5 * x / mt)
        axs[2].barh(i, x, color=col if p < alfa else "white", edgecolor=col, hatch=None if p < alfa else "////", height=0.75, lw=1)
        axs[2].text(x, i, f" {'+' if x >= 0 else ''}{ro(x, 2)}{'' if p < alfa else ' (ns)'}", va="center", fontsize=7.5,
                    ha="left" if x >= 0 else "right")
    axs[2].axvline(0, color="#52514e", lw=0.8)
    axs[2].set_xlim(-1.35 * mt if np.nanmin(tr) < 0 else 0, 1.35 * mt)
    axs[2].set_title(f"Tendința {stat['ani'][0]}–{stat['ani'][-1]} ({_unit(var)}/deceniu)", fontsize=10.5)
    axs[0].set_yticks(y, et, fontsize=8)
    for lab, k in zip(axs[0].get_yticklabels(), ordine):
        if k == total_idx:
            lab.set_fontweight("bold")
    for ax in axs:
        ax.grid(axis="x", color="#e6e5e0"); ax.invert_yaxis() if ax is axs[0] else None
    fig.suptitle(f"{_titlu_var(var)} pe zone", x=0.01, ha="left", fontsize=12, fontweight="bold")
    fig.text(0.0, 0.0, f"Hașurat / (ns): tendință nesemnificativă (p ≥ {alfa}) · {ATRIBUIRE}", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    cale = _gata(cale); fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG bare pe zone: {cale}")
    return cale


def g_dungi_zone(cale, etichete, ani, A, var, referinta, total_idx, sortare, stat, centre_lat=None):
    """„Dungile încălzirii” pentru toate zonele: rânduri = zone, coloane = ani, culoarea = anomalia față de referință."""
    plt = _plt()
    procent = _e_procent(var)
    baza = stat["baza"][:, None]
    an = 100 * (A / np.where(baza > 0, baza, np.nan) - 1) if procent else A - baza
    idx = [k for k in range(len(etichete)) if k != total_idx]
    if sortare == "tendinta":
        idx.sort(key=lambda k: -np.nan_to_num(stat["tendinta"][k], nan=-1e9))
    elif sortare == "medie":
        idx.sort(key=lambda k: -np.nan_to_num(stat["medie"][k], nan=-1e9))
    elif sortare == "lat" and centre_lat is not None:
        idx.sort(key=lambda k: -centre_lat[k])
    else:
        idx.sort(key=lambda k: etichete[k])
    if total_idx is not None:
        idx = [total_idx] + idx
    m = np.nanpercentile(np.abs(an[idx]), 98) or 1
    fig, ax = plt.subplots(figsize=(13, 0.26 * len(idx) + 1.8))
    im = ax.imshow(an[idx], aspect="auto", cmap=_cmap_anomalie(var), vmin=-m, vmax=m,
                   extent=[ani[0] - 0.5, ani[-1] + 0.5, len(idx) - 0.5, -0.5], interpolation="nearest")
    ax.set_yticks(range(len(idx)), [etichete[k] for k in idx], fontsize=8)
    if total_idx is not None:
        ax.get_yticklabels()[0].set_fontweight("bold"); ax.axhline(0.5, color="white", lw=2.5)
    ax.set_xticks([a for a in ani if a % 10 == 0])
    for s in ax.spines.values():
        s.set_visible(False)
    cb = plt.colorbar(im, ax=ax, pad=0.01, shrink=0.9)
    cb.set_label((f"abatere relativă față de normală (%)" if procent else f"anomalie ({_unit(var)})")); cb.outline.set_visible(False)
    ax.set_title(f"Dungile încălzirii pe zone · {_titlu_var(var)} · anomalia față de {referinta[0]}–{referinta[1]} · "
                 f"sortare: {sortare}", fontsize=11)
    fig.text(0.0, -0.02, ATRIBUIRE, fontsize=8, color="#555555")
    cale = _gata(cale); fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG dungi pe zone: {cale}")
    return cale


def sensibilitate_un_an(ani, y, recent):
    """Ce se întâmplă cu media perioadei recente și cu tendința dacă scoatem, pe rând, câte un an?
    Returnează (rânduri pentru CSV, rezumat). Nu e un interval de încredere: arată doar cât de mult atârnă
    concluzia de un singur an excepțional."""
    x = np.asarray(ani); y = np.asarray(y, float)
    mrec = (x >= recent[0]) & (x <= recent[1]) & np.isfinite(y)
    med = float(np.mean(y[mrec])) if mrec.any() else np.nan
    t_all, p_all = _panta(x, y)
    rand = []
    for i, a in enumerate(x):
        if not np.isfinite(y[i]):
            continue
        keep = np.ones(len(x), bool); keep[i] = False
        m2 = mrec & keep
        med_f = float(np.mean(y[m2])) if (mrec[i] and m2.any()) else med
        t_f, p_f = _panta(x[keep], y[keep])
        rand.append(dict(an=int(a), valoare=float(y[i]), medie_fara=med_f, tendinta_fara=t_f, p_fara=p_f))
    if not rand:
        return [], None
    imp_t = max(rand, key=lambda r: abs(r["tendinta_fara"] - t_all) if np.isfinite(r["tendinta_fara"]) else -1)
    imp_m = max((r for r in rand if recent[0] <= r["an"] <= recent[1]), key=lambda r: abs(r["medie_fara"] - med), default=None)
    rez = dict(medie=med, tendinta=t_all, p=p_all, an_tendinta=imp_t, an_medie=imp_m,
               tend_min=float(np.nanmin([r["tendinta_fara"] for r in rand])), tend_max=float(np.nanmax([r["tendinta_fara"] for r in rand])),
               semn_schimbat=any(np.sign(r["tendinta_fara"]) != np.sign(t_all) for r in rand if np.isfinite(r["tendinta_fara"])),
               semnif_schimbata=any((r["p_fara"] < 0.05) != (p_all < 0.05) for r in rand if np.isfinite(r["p_fara"])),
               # aceeași regulă ca în calculatorul din tabul Indicatori: fără anul cel mai influent, panta se schimbă
               # cu peste jumătate din valoarea ei (semnul și verdictul pot rămâne, dar mărimea atârnă de un an)
               marime_schimbata=bool(np.isfinite(imp_t["tendinta_fara"]) and np.isfinite(t_all)
                                     and abs(imp_t["tendinta_fara"] - t_all) > 0.5 * abs(t_all)))
    return rand, rez


def g_sensibilitate(cale, eticheta, ani, y, var, recent, rand, rez):
    """Două panouri: media perioadei recente și tendința, recalculate fără câte un an (punctele); linia = toți anii."""
    plt = _plt()
    cale = _gata(cale)
    u = _unit(var)
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 4.2), gridspec_kw={"width_ratios": [1, 1.6]})
    rr = [r for r in rand if recent[0] <= r["an"] <= recent[1]]
    a.axhline(rez["medie"], color="#0b0b0b", lw=1.5, label=f"toți anii: {ro(rez['medie'], 2)} {u}")
    a.scatter([r["an"] for r in rr], [r["medie_fara"] for r in rr], s=28, color="#2a78d6", zorder=3, label="fără anul de pe axă")
    if rez["an_medie"]:
        r = rez["an_medie"]
        a.annotate(f"fără {r['an']}: {ro(r['medie_fara'], 2)}", (r["an"], r["medie_fara"]), xytext=(6, 6),
                   textcoords="offset points", fontsize=8.5)
    a.set_title(f"Media {recent[0]}–{recent[1]} fără câte un an", loc="left", fontsize=10.5)
    a.set_ylabel(u); a.grid(color="#e6e5e0"); a.ticklabel_format(axis="y", useOffset=False)
    a.legend(fontsize=8.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2)
    b.axhline(rez["tendinta"], color="#0b0b0b", lw=1.5,
              label=f"toți anii: {'+' if rez['tendinta'] >= 0 else '−'}{ro(abs(rez['tendinta']), 3)} {u}/deceniu (p = {ro(rez['p'], 3)})")
    b.axhline(0, color="#9a9a94", lw=0.8)
    col = ["#e34948" if (np.isfinite(r["p_fara"]) and r["p_fara"] < 0.05) else "#9fb1bf" for r in rand]
    b.scatter([r["an"] for r in rand], [r["tendinta_fara"] for r in rand], s=22, c=col, zorder=3)
    r = rez["an_tendinta"]
    b.annotate(f"fără {r['an']}: {ro(r['tendinta_fara'], 3)}", (r["an"], r["tendinta_fara"]), xytext=(6, 6),
               textcoords="offset points", fontsize=8.5)
    b.set_title(f"Tendința fără câte un an ({METODE_TREND[_METODA_SERII]}) · roșu: p < 0,05", loc="left", fontsize=10.5)
    b.set_ylabel(f"{u}/deceniu"); b.grid(color="#e6e5e0"); b.ticklabel_format(axis="y", useOffset=False)
    b.legend(fontsize=8.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    fig.suptitle(f"{eticheta} · {_titlu_var(var)} · cât depinde concluzia de un singur an?", x=0.01, ha="left", fontsize=12)
    fig.text(0.0, -0.1, "Fiecare punct = rezultatul recalculat fără anul de pe axă. Nu este un interval de încredere: "
             "arată doar sensibilitatea la un an excepțional. " + ATRIBUIRE, fontsize=8, color="#555555")
    fig.tight_layout()
    fig.savefig(cale, dpi=DPI, bbox_inches="tight"); plt.close(fig)
    log(f"   PNG grafic: {cale}")
    return cale


def g_dungi_detaliu(cale, eticheta, ani, y, var, referinta, baza=None):
    """Dungile clasice + barele anomaliei anuale + media mobilă, pentru o zonă."""
    plt = _plt()
    import matplotlib
    procent = _e_procent(var)
    x = np.asarray(ani); ref = (x >= referinta[0]) & (x <= referinta[1])
    if baza is None:
        baza = float(np.nanmean(y[ref])) if ref.any() else np.nan
    if not np.isfinite(baza) or (procent and baza <= 0):
        log(f"   [atenție] {eticheta}: referință indisponibilă pentru dungi")
        return None
    an = 100 * (y / baza - 1) if procent else y - baza
    m = float(np.nanmax(np.abs(an))) or 1
    cmap = matplotlib.colormaps[_cmap_anomalie(var)]
    fig, (a, b) = plt.subplots(2, 1, figsize=(12, 5.4), sharex=True, gridspec_kw={"height_ratios": [1, 1.25]})
    a.imshow(an[None, :], aspect="auto", cmap=cmap, vmin=-m, vmax=m, extent=[x[0] - 0.5, x[-1] + 0.5, 0, 1])
    a.set_yticks([])
    for s in a.spines.values():
        s.set_visible(False)
    a.set_title(f"{eticheta} · {_titlu_var(var)} · {x[0]}–{x[-1]} · referința {referinta[0]}–{referinta[1]} = {ro(baza, 2)} {_unit(var)}",
                fontsize=11)
    b.bar(x, an, color=[cmap(0.5 + 0.5 * v / m) for v in np.nan_to_num(an)], width=0.85)
    b.plot(x, _rulant(an), color="#0b0b0b", lw=1.8, label="media mobilă pe 11 ani")
    bb, p = _panta(ani, y)
    b.axhline(0, color="#52514e", lw=0.8)
    b.set_ylabel((f"abatere relativă față de normală (%)" if procent else f"anomalie ({_unit(var)})")); b.grid(axis="y", color="#e6e5e0")
    b.legend(loc="upper left", fontsize=8.5, frameon=False,
             title=f"tendință {'+' if bb >= 0 else '−'}{ro(abs(bb), 2)} {_unit(var)}/deceniu (p = {ro(p, 3)})", title_fontsize=8.5)
    fig.text(0.0, -0.02, ATRIBUIRE, fontsize=8, color="#555555")
    fig.tight_layout(h_pad=0.6)
    cale = _gata(cale); fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG dungi (detaliu): {cale}")
    return cale


def g_anomalii_lunare(cale, eticheta, k, serii, var, ani, referinta, frontiera):
    """Harta termică an × lună a anomaliilor față de climatologia lunară de referință (+ ciclul anual)."""
    plt = _plt()
    procent = _e_procent(var)
    toti = [a for a in range(ani[0], ani[1] + 1) if a in serii]
    if not toti:
        return None
    M = np.stack([_lunare(serii, var, a, frontiera)[k] for a in toti])
    ref = [a for a in sorted(serii) if referinta[0] <= a <= referinta[1]]
    if not ref:
        log(f"   [atenție] {eticheta}: referință lunară indisponibilă")
        return None
    clim = np.nanmean([_lunare(serii, var, a, frontiera)[k] for a in ref], axis=0)
    an = 100 * (M / np.where(clim > 0, clim, np.nan) - 1) if procent else M - clim
    m = np.nanpercentile(np.abs(an), 98) or 1
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 0.13 * len(toti) + 2.6), gridspec_kw={"width_ratios": [2.4, 1]})
    im = a.imshow(an, aspect="auto", cmap=_cmap_anomalie(var), vmin=-m, vmax=m,
                  extent=[0.5, 12.5, toti[-1] + 0.5, toti[0] - 0.5], interpolation="nearest")
    a.set_xticks(range(1, 13), LUNI); a.set_ylabel("an")
    cb = plt.colorbar(im, ax=a, pad=0.01); cb.set_label((f"abatere relativă față de normală (%)" if procent else f"anomalie ({_unit(var, False)})")); cb.outline.set_visible(False)
    a.set_title(f"{eticheta} · anomalia lunară față de {referinta[0]}–{referinta[1]}", fontsize=10.5)
    # ciclul anual: referința vs ultimii 10 ani compleți
    recent = [i for i, an_ in enumerate(toti) if an_ >= toti[-1] - 9]
    luni = np.arange(1, 13)
    unit = "mm/lună" if procent else _unit(var, False)
    if procent:
        b.bar(luni - 0.2, clim, width=0.4, color="#c3c2b7", label=f"{referinta[0]}–{referinta[1]}")
        b.bar(luni + 0.2, np.nanmean(M[recent], 0), width=0.4, color="#2a78d6", label=f"{toti[recent[0]]}–{toti[-1]}")
    else:
        b.plot(luni, clim, color="#8a8986", lw=2, marker="o", ms=3, label=f"{referinta[0]}–{referinta[1]}")
        b.plot(luni, np.nanmean(M[recent], 0), color="#e34948", lw=2, marker="o", ms=3, label=f"{toti[recent[0]]}–{toti[-1]}")
    b.set_xticks(luni, [l[0].upper() for l in LUNI]); b.set_ylabel(unit); b.grid(axis="y", color="#e6e5e0")
    b.set_title("Ciclul anual", fontsize=10.5); b.legend(fontsize=8.5, frameon=False)
    fig.text(0.0, -0.02, ATRIBUIRE, fontsize=8, color="#555555")
    fig.tight_layout()
    cale = _gata(cale); fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG anomalii lunare: {cale}")
    return cale


def g_harta_zone(cale, zona: Zona, valori, titlu, unitate, divergent=True, procent=False, p=None, alfa=0.05, cmap_div=None,
                 cmap_secv=None):
    """Hartă coropletă: poligoanele colorate după valoare, etichetate; hașurat = nesemnificativ (dacă p e dat)."""
    plt = _plt()
    import matplotlib
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Polygon as MPoly
    from osgeo import ogr
    v = np.asarray(valori, float)
    if divergent:
        m = float(np.nanpercentile(np.abs(v), 98)) or 1; norm = plt.Normalize(-m, m)
        cmap = matplotlib.colormaps[cmap_div or ("BrBG" if procent else "RdBu_r")]
    else:
        norm = plt.Normalize(np.nanmin(v), np.nanmax(v)); cmap = matplotlib.colormaps[cmap_secv or ("BrBG" if procent else "YlOrRd")]
    geoms = [ogr.CreateGeometryFromWkt(w) for _, w in zona.poligoane]
    ordine = sorted(range(len(geoms)), key=lambda i: -geoms[i].GetArea())     # cele mici deasupra (ex. București în Ilfov)
    fig, ax = plt.subplots(figsize=(11, 7.2))
    for i in ordine:
        g_ = geoms[i]
        parti = [g_.GetGeometryRef(j) for j in range(g_.GetGeometryCount())] if g_.GetGeometryType() in (
            ogr.wkbMultiPolygon, ogr.wkbMultiPolygon25D) else [g_]
        patches = [MPoly(np.array(pp.GetGeometryRef(0).GetPoints())[:, :2], closed=True) for pp in parti if pp.GetGeometryCount()]
        col = cmap(norm(v[i])) if np.isfinite(v[i]) else "#eeeeea"
        nesemn = p is not None and np.isfinite(p[i]) and p[i] >= alfa
        ax.add_collection(PatchCollection(patches, facecolor=col, edgecolor="white", linewidth=0.7,
                                          hatch="////" if nesemn else None))
    for i, g_ in enumerate(geoms):
        c = g_.PointOnSurface()
        if np.isfinite(v[i]):
            lum = sum(cmap(norm(v[i]))[:3]) / 3
            ax.text(c.GetX(), c.GetY(), f"{zona.poligoane[i][0]}\n{'+' if divergent and v[i] >= 0 else ''}{ro(v[i], 2 if abs(v[i]) < 10 else 0)}",
                    ha="center", va="center", fontsize=6.3, color="white" if lum < 0.45 else "#0b0b0b")
    if CONTUR_HARTI:
        from matplotlib.collections import LineCollection
        linii = _citeste_contur(CONTUR_HARTI)
        if linii:
            ax.add_collection(LineCollection(linii, colors=CONTUR_CULOARE, linewidths=CONTUR_GROSIME * 1.6))
    env = [min(g_.GetEnvelope()[0] for g_ in geoms), max(g_.GetEnvelope()[1] for g_ in geoms),
           min(g_.GetEnvelope()[2] for g_ in geoms), max(g_.GetEnvelope()[3] for g_ in geoms)]
    ax.set_xlim(env[0] - 0.1, env[1] + 0.1); ax.set_ylim(env[2] - 0.1, env[3] + 0.1)
    ax.set_aspect(1 / math.cos(math.radians((env[2] + env[3]) / 2)))
    ax.set_xlabel("Longitudine (°E)"); ax.set_ylabel("Latitudine (°N)")
    sm = matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap)
    cb = plt.colorbar(sm, ax=ax, shrink=0.8, pad=0.02); cb.set_label(unitate); cb.outline.set_visible(False)
    ax.set_title(titlu, fontsize=11)
    fig.text(0.0, -0.01, (f"Hașurat: nesemnificativ (p ≥ {alfa}) · " if p is not None else "") + ATRIBUIRE, fontsize=8, color="#555555")
    cale = _gata(cale); fig.savefig(cale, dpi=DPI); plt.close(fig)
    log(f"   PNG hartă pe zone: {cale}")
    return cale


def ruleaza_serii(var, ani, referinta, recent, zona: Zona, grafice: dict, iesiri: dict, out, nume,
                  detaliu=(), fereastra=None, zile_dupa=0, sortare="tendinta", harta_valoare="tendinta",
                  total_nume=None, alfa=0.05, sezon="anual", metoda_trend="ols"):
    """Serii pe zone pentru o VARIABILĂ ("max_temp", "precipitation"…) sau pentru orice INDICATOR din registru
    (zc.indicator("zile_peste", var="max_temp", prag=30), CDD, GDD, De Martonne…), pe tot anul sau pe un sezon.
    Valorile anuale sunt calculate per pixel pentru toate variabilele. Seriile zilnice zonale
    alimentează graficele zilnice și lunare pentru variabilele simple."""
    global _METODA_SERII
    _METODA_SERII = metoda_trend
    try:
        return _ruleaza_serii(var, ani, referinta, recent, zona, grafice, iesiri, out, nume, detaliu, fereastra, zile_dupa,
                              sortare, harta_valoare, total_nume, alfa, sezon, metoda_trend)
    finally:
        _METODA_SERII = "ols"


def _ruleaza_serii(var, ani, referinta, recent, zona, grafice, iesiri, out, nume, detaliu, fereastra, zile_dupa,
                   sortare, harta_valoare, total_nume, alfa, sezon, metoda_trend):
    out = Path(out)
    q = var
    if isinstance(q, str):
        q = indicator("tmedie") if q == "tmedie" else indicator("suma" if q == "precipitation" else "medie", var=q)
    simplu = var_simpla(q) if sezon == "anual" else None
    qp = simplu or q                                                 # ce primesc graficele (unități, titluri, culori)
    sez_txt = "" if sezon == "anual" else f" · sezon {sezon}"
    log(f"== {nume}: {_titlu_var(qp)}{sez_txt} · serii {ani[0]}–{ani[1]} · referința {referinta[0]}–{referinta[1]} · "
        f"tendința: {METODE_TREND[metoda_trend]}")
    cub, fr = deschide()
    g = grila_zonei(cub, zona)
    log(f"   zona: {zona.descriere()} · fereastra {g.forma[0]} × {g.forma[1]} pixeli")
    if zona.punct:                                   # un punct are o singură serie: poartă numele punctului
        total_nume = zona.nume or zona.descriere()
    total_nume = total_nume or ("Toate zonele" if zona.poligoane else "România")
    variabile = _variabile_pentru(simplu) if simplu else tuple(q.variabile)
    frontiera = min(fr[v] for v in variabile)
    an_fr = int(str(frontiera)[:4])
    if fereastra is None:
        fereastra = (f"{an_fr - 1}-01-01", str(frontiera))
    f0 = np.datetime64(fereastra[0]); f1 = min(np.datetime64(fereastra[1] or str(frontiera)), frontiera)
    ani_nec = set(range(ani[0], ani[1] + 1)) | set(range(referinta[0], referinta[1] + 1)) | set(range(recent[0], recent[1] + 1))
    serii = None
    ani_anuali = set(ani_nec)
    if simplu and (grafice.get("serie_zilnica") or grafice.get("anomalii_lunare")):
        if grafice.get("serie_zilnica"):
            ani_nec |= set(range(int(str(f0)[:4]), int(str(f1)[:4]) + 1))
        _, serii, frontiera = serii_zonale(cub, fr, simplu, ani_nec, zona, g, total_nume, dir_cache("serii"))
    elif not simplu and any(grafice.get(k) for k in GRAFICE_ZILNICE):
        log("   Graficele zilnice și lunare cer o variabilă zilnică simplă.")
    etichete, lista_t, A_t = anuale_indicator(cub, fr, q, (min(ani_anuali), max(ani_anuali)),
                                              sezon, zona, g, total_nume, dir_cache("serii"))
    total_idx = etichete.index(total_nume) if total_nume in etichete else None
    if len(etichete) == 1:
        total_idx = 0
    # potrivire tolerantă (majuscule, diacritice): „iasi” găsește „Iași”; se folosește scrierea din tabelă
    gasite = [(d, potriveste_zona(d, etichete)) for d in detaliu]
    necunoscute = [d for d, k in gasite if k is None]
    if necunoscute:
        import difflib
        sug = {d: difflib.get_close_matches(_norm_text(d), [_norm_text(e) for e in etichete], n=1, cutoff=0.6) for d in necunoscute}
        log("   [atenție] zone de detaliu inexistente: " + ", ".join(
            f"«{d}»" + (f" (poate {etichete[[_norm_text(e) for e in etichete].index(sug[d][0])]}?)" if sug[d] else "")
            for d in necunoscute))
    detaliu = [etichete[k] for _, k in gasite if k is not None] or [etichete[total_idx if total_idx is not None else 0]]
    sel = [i for i, a in enumerate(lista_t) if ani[0] <= a <= ani[1]]
    if not sel:
        raise ValueError(f"Niciun an cu date în {ani[0]}–{ani[1]}.")
    lista, A = [lista_t[i] for i in sel], A_t[:, sel]
    log(f"   ani folosiți: {lista[0]}–{lista[-1]} ({len(lista)}); perioade parțiale permise: {ACCEPTA_PARTIAL}")
    # statistici pe zone
    x = np.asarray(lista)
    procent = _e_procent(qp)
    def media_intervalului(interval):
        idx = [i for i, a in enumerate(lista_t) if interval[0] <= a <= interval[1]]
        if not idx:
            raise ValueError(f"Niciun an disponibil pentru intervalul {interval}.")
        return np.nanmean(A_t[:, idx], axis=1)
    medie = media_intervalului(recent)
    baza = media_intervalului(referinta)
    anomalie = 100 * (medie / np.where(baza > 0, baza, np.nan) - 1) if procent else medie - baza
    tp = [_panta(lista, A[k]) for k in range(len(etichete))]
    stat = dict(ani=lista, medie=medie, baza=baza, anomalie=anomalie, tendinta=np.array([t[0] for t in tp]), p=np.array([t[1] for t in tp]))
    col_an = "abatere_relativa_pct" if procent else "anomalie"   # precipitații: 100·(P/P_ref − 1), 0 = normal
    et_an = "abatere relativă" if procent else "anomalie"
    for k in range(len(etichete)):
        if k == total_idx or k < 0:
            log(f"   {etichete[k]}: media {recent[0]}–{recent[1]} {ro(medie[k], 2)} · {et_an} {ro(anomalie[k], 2)}"
                f"{' %' if procent else ''} · "
                f"tendință {ro(stat['tendinta'][k], 3)}/deceniu (p={ro(stat['p'][k], 3)})")
    sl = lambda s: "".join(c if c.isalnum() else "_" for c in s)[:40]  # noqa: E731
    mai_multe = len(etichete) > 1
    if grafice.get("serie_zilnica") and simplu:
        var = simplu
        zer = None
        if zile_dupa > 0:
            z0 = frontiera + 1; z1 = frontiera + zile_dupa
            d, zz = citeste(cub, _variabile_pentru(var), z0, z1, g)
            et_, cols_, tot_ = _coloane_zone(zona, g)
            col = cols_ + [tot_] if len(et_) > 1 else (cols_ or [tot_])
            zer = (zz, _medii_zone(_valoare_zilnica(d, var), col))
        for et in detaliu:
            g_serie_zilnica(out / f"{nume}_{sl(et)}_zilnic.png", et, etichete.index(et), serii, var, (str(f0), str(f1)),
                            frontiera, referinta, zer)
    if grafice.get("serii_anuale") and mai_multe:
        g_serii_anuale(out / f"{nume}_serii_anuale.png", etichete, lista, A, qp, detaliu, total_idx)
    if grafice.get("multiple_mici") and mai_multe:
        g_multiple_mici(out / f"{nume}_multiple_mici.png", etichete, lista, A, qp, total_idx)
    if grafice.get("bare_zone") and mai_multe:
        g_bare_zone(out / f"{nume}_bare_zone.png", etichete, stat, qp, recent, referinta, total_idx, alfa)
    if grafice.get("dungi_zone") and mai_multe:
        lat = None
        if zona.poligoane:
            from osgeo import ogr
            lat = [ogr.CreateGeometryFromWkt(w).Centroid().GetY() for _, w in zona.poligoane] + [99.0]
        g_dungi_zone(out / f"{nume}_dungi_zone.png", etichete, lista, A, qp, referinta, total_idx, sortare, stat, lat)
    if grafice.get("dungi_detaliu"):
        for et in detaliu:
            k = etichete.index(et)
            g_dungi_detaliu(out / f"{nume}_{sl(et)}_dungi.png", et, lista, A[k], qp, referinta, baza[k])
    if grafice.get("sensibilitate"):
        for et in detaliu:
            k = etichete.index(et)
            rand, rez = sensibilitate_un_an(lista, A[k], recent)
            if not rez:
                continue
            g_sensibilitate(out / f"{nume}_{sl(et)}_sensibilitate.png", et, lista, A[k], qp, recent, rand, rez)
            if iesiri.get("csv"):
                scrie_csv(out / f"{nume}_{sl(et)}_sensibilitate.csv",
                          ["an_omis", "valoarea_anului", f"medie_{recent[0]}_{recent[1]}_fara", "tendinta_deceniu_fara", "p_fara"],
                          [[r["an"], r["valoare"], r["medie_fara"], r["tendinta_fara"], r["p_fara"]] for r in rand])
            ra = rez["an_tendinta"]
            log(f"   {et}: tendința {ro(rez['tendinta'], 3)} {_unit(qp)}/deceniu; fără câte un an, între "
                f"{ro(rez['tend_min'], 3)} și {ro(rez['tend_max'], 3)}; cel mai influent: {ra['an']}"
                + (" · ATENȚIE: scoaterea unui singur an schimbă semnul tendinței" if rez["semn_schimbat"] else "")
                + (" · scoaterea unui singur an schimbă verdictul de semnificație (p < 0,05)" if rez["semnif_schimbata"] else "")
                + (f" · atenție: fără {ra['an']}, panta se schimbă cu peste jumătate ({ro(ra['tendinta_fara'], 3)})"
                   if rez["marime_schimbata"] and not rez["semn_schimbat"] else ""))
    if grafice.get("anomalii_lunare") and simplu:
        var = simplu
        for et in detaliu:
            g_anomalii_lunare(out / f"{nume}_{sl(et)}_lunar.png", et, etichete.index(et), serii, var, ani, referinta, frontiera)
    if grafice.get("harta_zone") and zona.poligoane and len(zona.poligoane) > 1:
        n = len(zona.poligoane)
        kw = dict(cmap_div=_cmap_anomalie(qp), cmap_secv=qp.cmap if isinstance(qp, Indicator) else None)
        if harta_valoare == "medie":
            g_harta_zone(out / f"{nume}_harta_medie.png", zona, medie[:n], f"{_titlu_var(qp)} · media {recent[0]}–{recent[1]}",
                         _unit(qp), divergent=False, procent=procent, **kw)
        elif harta_valoare == "anomalie":
            g_harta_zone(out / f"{nume}_harta_anomalie.png", zona, anomalie[:n],
                         f"{_titlu_var(qp)} · {et_an} {recent[0]}–{recent[1]} față de {referinta[0]}–{referinta[1]}",
                         "%" if procent else _unit(qp), procent=procent, **kw)
        else:
            g_harta_zone(out / f"{nume}_harta_tendinta.png", zona, stat["tendinta"][:n],
                         f"{_titlu_var(qp)} · tendința {lista[0]}–{lista[-1]}", f"{_unit(qp)}/deceniu",
                         procent=procent, p=stat["p"][:n], alfa=alfa, **kw)
    fis = []
    if iesiri.get("csv"):
        scrie_csv(out / f"{nume}_anual.csv", ["an"] + etichete, [[a] + [float(A[k, i]) for k in range(len(etichete))] for i, a in enumerate(lista)])
        scrie_csv(out / f"{nume}_statistici.csv", ["zona", f"medie_{recent[0]}_{recent[1]}", col_an, "tendinta_deceniu", "p_valoare"],
                  [[etichete[k], float(medie[k]), float(anomalie[k]), float(stat["tendinta"][k]), float(stat["p"][k])] for k in range(len(etichete))])
    if iesiri.get("gpkg") and zona.poligoane:
        n = len(zona.poligoane)
        tab = {f"medie_{recent[0]}_{recent[1]}": list(medie[:n]), col_an: list(anomalie[:n]),
               "tendinta_deceniu": list(stat["tendinta"][:n]), "p_valoare": list(stat["p"][:n])}
        tab.update({f"a{a}": list(A[:n, i]) for i, a in enumerate(lista)})
        fis.append(scrie_gpkg_zone(out / f"{nume}.gpkg", zona, tab))
    incarca_in_qgis(fis)
    log(f"== gata: {nume}")
    return etichete, lista, A, stat


# =====================================================================================
# PARAMETRI DIN INTERFAȚĂ (server_clima.py): python 02_….py --parametri job.json [--verifica]
# =====================================================================================
# Fără argumente, scripturile rulează exact ca înainte, cu parametrii din antet.
CHEI_CALE = ("OUT", "DATE_VECTOR")


def _cale(v, radacina):
    """Calea relativă se socotește față de folderul programului (portabil între calculatoare)."""
    if v in (None, ""):
        return None
    p = Path(str(v)).expanduser()
    return p if p.is_absolute() else (Path(radacina) / p).resolve()


def zona_din_dict(d, radacina="."):
    """{"tip": "tara" | "dreptunghi" | "punct" | "poligoane", …, "altitudine": [min, max]} → Zona"""
    if isinstance(d, Zona):
        return d
    z = _zona_din_dict(d, radacina)
    alt = d.get("altitudine") or [None, None]
    _n = lambda v: None if v in (None, "") else float(v)  # noqa: E731
    if not z.punct and (_n(alt[0]) is not None or _n(alt[1]) is not None):
        z.cu_altitudine(_n(alt[0]), _n(alt[1]))
    return z


def _semn_dem():
    try:
        st = Path(DEM_FISIER).stat()
        return [str(Path(DEM_FISIER).resolve()), st.st_mtime_ns, st.st_size]
    except OSError:
        return None


def _zona_din_dict(d, radacina="."):
    tip, nume = d.get("tip", "tara"), (d.get("nume") or None)
    if tip == "tara":
        return Zona.tara(nume=nume)
    if tip == "dreptunghi":
        return Zona.dreptunghi(*[float(d[k]) for k in ("lon_min", "lat_min", "lon_max", "lat_max")], nume=nume)
    if tip == "punct":
        return Zona.punct(float(d["lon"]), float(d["lat"]), nume=nume)
    if tip == "poligoane":
        valori = d.get("valori") or None
        return Zona.poligoane(str(_cale(d.get("fisier"), radacina)), coloana=d.get("coloana") or None,
                              valori=valori, strat=d.get("strat") or None, unite=bool(d.get("unite")), nume=nume)
    raise ValueError(f"tip de zonă necunoscut: {tip!r}")


def _din_json(v):
    """Listele JSON devin tupluri (scripturile folosesc tupluri pentru perioade, ani, praguri)."""
    if isinstance(v, list):
        return tuple(_din_json(x) for x in v)
    if isinstance(v, dict):
        return {k: _din_json(x) for k, x in v.items()}
    return v


def afiseaza(v):
    """Valoarea unui parametru în jurnal, pentru oameni: căi cu separatorul sistemului, fără repr()."""
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, Zona):
        return v.descriere()
    if isinstance(v, dict) and v and all(isinstance(x, bool) for x in v.values()):
        return ", ".join(k for k, x in v.items() if x) or "(niciuna)"
    if isinstance(v, (list, tuple)):
        if len(v) == 2 and all(isinstance(x, int) for x in v):
            return f"{v[0]}–{v[1]}"
        return ", ".join(afiseaza(x) for x in v) if v else "(nimic)"
    return "—" if v is None else str(v)


def parametri_externi(g: dict) -> bool:
    """Se apelează la sfârșitul secțiunii PARAMETRI: zc.parametri_externi(globals()).
    Dacă scriptul a fost pornit de interfață, suprascrie parametrii din antet cu cei din job.json.
    Cu --verifica: afișează parametrii rezultați și se oprește (nu descarcă nimic)."""
    import sys
    if "--parametri" not in sys.argv:
        return False
    cale = Path(sys.argv[sys.argv.index("--parametri") + 1])
    d = json.loads(cale.read_text(encoding="utf-8"))
    radacina = Path(d.pop("_radacina", cale.parent))
    setari = d.pop("_setari", {})
    zone = set(d.pop("_zone", ()))
    for k, v in d.items():
        if k in zone and v is not None:
            g[k] = zona_din_dict(v, radacina)
        elif k in CHEI_CALE:
            g[k] = _cale(v, radacina)
        else:
            g[k] = _din_json(v)
    mod = sys.modules[__name__]
    for k, v in setari.items():
        if k == "CONTUR_HARTI" and isinstance(v, str):
            v = str(_cale(v, radacina)) if v else None
        setattr(mod, k, _din_json(v))
    log("Parametri primiți de la interfață:")
    for k in list(d) + list(setari):
        val = g.get(k) if k in d else getattr(mod, k)
        log(f"   {k} = {afiseaza(val)}")
    if "--verifica" in sys.argv:
        for k in zone:
            z = g.get(k)
            if isinstance(z, Zona) and z.gpkg:
                _citeste_poligoane(z)
                log(f"   {k}: {z.descriere()} · {len(z.poligoane)} poligoane citite")
        log("Verificare încheiată: parametrii sunt corecți (nu s-a descărcat nimic).")
        raise SystemExit(0)
    return True
