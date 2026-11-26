# -*- coding: utf-8 -*-
"""
00b_inspecteaza_vector.py — ce conține un fișier vectorial, ca să știți ce scrieți în Zona.poligoane(...)
=======================================================================================================
Afișează, pentru fișierul ales (GPKG, SHP, GeoJSON… orice citește GDAL):
  * straturile cu geometrie (tip, număr de entități, sistemul de coordonate);
  * coloanele fiecărui strat, cu tipul, numărul de valori distincte și câteva exemple;
  * dacă dați și COLOANA: toate valorile ei (de copiat în valori=[...]);
  * la final, liniile gata de lipit în scripturi.

Rulare:
  * OSGeo4W Shell:           python 00b_inspecteaza_vector.py
  * Consola Python din QGIS: exec(open(r"C:\\...\\00b_inspecteaza_vector.py", encoding="utf-8").read())
Modificați DOAR secțiunea PARAMETRI.
"""
import sys
from pathlib import Path

# ================================================================================================
# PARAMETRI
# ================================================================================================
FOLDER = Path(__file__).resolve().parent if "__file__" in globals() else Path(r"C:\ClimaANM\clima")   # <-- doar pentru consola QGIS: folderul clima al programului
DATE_VECTOR = FOLDER.parent / "date"     # fișierele vectoriale ale programului (date/)
FISIER = str(DATE_VECTOR / "ro_judete_poligon.gpkg")   # <-- MODIFICABIL
STRAT = None        # None = toate straturile cu geometrie; sau numele unui strat                  <-- MODIFICABIL
COLOANA = None      # None = doar exemple; sau numele unei coloane → se listează TOATE valorile ei  <-- MODIFICABIL
EXEMPLE = 5         # câte valori-exemplu pe coloană                                              <-- MODIFICABIL

# ================================================================================================
# RULARE
# ================================================================================================
try:
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning, message=".*UseExceptions.*")
    from osgeo import ogr
except ImportError:
    sys.exit("Nu găsesc GDAL (osgeo). Rulați scriptul din OSGeo4W Shell sau din consola Python a QGIS.")

if not Path(FISIER).exists():
    sys.exit(f"Fișierul nu există: {FISIER}")
ds = ogr.Open(FISIER)
if ds is None:
    sys.exit(f"GDAL nu poate deschide {FISIER} ca fișier vectorial.")

straturi = [ds.GetLayer(i) for i in range(ds.GetLayerCount()) if ds.GetLayer(i).GetGeomType() != ogr.wkbNone]
fara_geom = [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount()) if ds.GetLayer(i).GetGeomType() == ogr.wkbNone]
print(f"\nFIȘIER: {FISIER}")
print(f"Straturi cu geometrie: {len(straturi)}" + (f"   (tabele fără geometrie, ignorate: {', '.join(fara_geom)})" if fara_geom else ""))
if STRAT:
    straturi = [l for l in straturi if l.GetName() == STRAT]
    if not straturi:
        sys.exit(f"Stratul „{STRAT}” nu există sau nu are geometrie.")


def valori(lyr, col, n=None):
    vazute, out = set(), []
    lyr.ResetReading()
    for f in lyr:
        v = f.GetField(col)
        if v is None:
            continue
        k = str(v)
        if k not in vazute:
            vazute.add(k); out.append(k)
            if n and len(out) >= n:
                break
    lyr.ResetReading()
    return out


sugestii = []
for lyr in straturi:
    srs = lyr.GetSpatialRef()
    crs = "necunoscut (se presupune WGS 84)"
    if srs is not None:
        cod = srs.GetAuthorityCode(None)
        crs = (f"EPSG:{cod} — " if cod else "") + (srs.GetName() or "")
    n = lyr.GetFeatureCount()
    tip = ogr.GeometryTypeToName(lyr.GetGeomType())
    poligon = ogr.GT_Flatten(lyr.GetGeomType()) in (ogr.wkbPolygon, ogr.wkbMultiPolygon)
    print("\n" + "=" * 100)
    print(f"STRAT „{lyr.GetName()}”: {tip}, {n} entități · CRS: {crs}")
    if not poligon:
        print("   (nu conține poligoane: nu se poate folosi ca zonă de analiză; poate fi folosit ca CONTUR_HARTI)")
    print("=" * 100)
    d = lyr.GetLayerDefn()
    coloane = [(d.GetFieldDefn(i).GetName(), d.GetFieldDefn(i).GetTypeName()) for i in range(d.GetFieldCount())]
    print(f"   {'COLOANA':<22}{'TIP':<10}{'DISTINCTE':>10}   EXEMPLE")
    unice = None
    for c, t in coloane:
        toate = valori(lyr, c)
        ex = ", ".join(toate[:EXEMPLE]) + (" …" if len(toate) > EXEMPLE else "")
        marcaj = "  ← un nume pe entitate" if len(toate) == n and n > 1 and t == "String" else ""
        print(f"   {c:<22}{t:<10}{len(toate):>10}   {ex}{marcaj}")
        if unice is None and marcaj:
            unice = c
    if COLOANA:
        if COLOANA not in [c for c, _ in coloane]:
            print(f"\n   Coloana „{COLOANA}” nu există în acest strat.")
        else:
            toate = valori(lyr, COLOANA)
            print(f"\n   Toate valorile coloanei „{COLOANA}” ({len(toate)}):")
            for i in range(0, len(toate), 6):
                print("      " + " · ".join(toate[i:i + 6]))
    if poligon:
        col = COLOANA or unice or (coloane[0][0] if coloane else None)
        ex = valori(lyr, col, 2) if col else []
        s = f', strat="{lyr.GetName()}"' if len(straturi) > 1 or STRAT else ""
        cale = FISIER
        sugestii.append(f'# stratul „{lyr.GetName()}”:')
        if col:
            sugestii.append(f'ZONA = zc.Zona.poligoane(r"{cale}"{s}, coloana="{col}")                    # toate, fiecare separat')
            if ex:
                lista = ", ".join(f'"{v}"' for v in ex)
                sugestii.append(f'ZONA = zc.Zona.poligoane(r"{cale}"{s}, coloana="{col}", valori=[{lista}])   # doar acestea')
                sugestii.append(f'ZONA = zc.Zona.poligoane(r"{cale}"{s}, coloana="{col}", valori=[{lista}], unite=True)   # unite într-o zonă')
        sugestii.append(f'ZONA = zc.Zona.poligoane(r"{cale}"{s}, unite=True, nume="{lyr.GetName()}")   # tot stratul = o singură zonă')

if sugestii:
    print("\n" + "=" * 100)
    print("DE LIPIT ÎN SCRIPTURI (alegeți o linie; coloana marcată „← un nume pe entitate” e de obicei cea potrivită):")
    print("=" * 100)
    print("\n".join(sugestii))
print()
