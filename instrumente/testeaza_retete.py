# -*- coding: utf-8 -*-
"""
testeaza_retete.py — rulează TOATE rețetele (retete/ și retete/utilizator/) pe cubul sintetic de test
=====================================================================================================
După orice modificare în nucleu, în indicatori sau în motoare:

    instrumente\\pixi.exe run python instrumente\\testeaza_retete.py            (Linux / macOS: instrumente/pixi …)
    … testeaza_retete.py 02 16                                                  doar rețetele care încep așa
    … testeaza_retete.py --verifica                                             doar „Verifică” + estimarea costului

Fără internet: construiește la nevoie cubul sintetic (instrumente/cub_test.py, ~30 s, ~370 MB în .pixi/) și rulează
fiecare rețetă cap-coadă (calcul + exportul Python), cu perioade din 2014–2026 și zone în partea cu date a cubului.
Suprascrierile de test sunt PE MOTOR, deci o rețetă nouă este acoperită automat.
"""
import json
import warnings
import os
import subprocess
import sys
import time
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning, message=".*UseExceptions.*")   # GDAL 4.0, vezi zarr_clima.py

RAD = Path(__file__).resolve().parents[1]
CUB = RAD / ".pixi" / "cub_test.zarr"
OUT = RAD / ".pixi" / "test_retete"
sys.path.insert(0, str(RAD / "clima"))

DR = {"tip": "dreptunghi", "lon_min": 25.3, "lat_min": 43.8, "lon_max": 26.4, "lat_max": 44.8, "nume": "test"}
PCT = {"tip": "punct", "lon": 26.1025, "lat": 44.4268, "nume": "București"}
POL = {"tip": "poligoane", "fisier": ".pixi/test_judete_v2.gpkg", "coloana": "NAME", "valori": ["Ilfov", "Giurgiu"]}

COMUN = {"ANI": [2020, 2022], "ANI_TINTA": [2024, 2025], "ANI_REFERINTA": [2015, 2019], "REFERINTA": [2014, 2020],
         "PERIOADA_RECENTA": [2022, 2025], "CLIMATOLOGIE": [2014, 2023], "ZONA": DR}
PE_MOTOR = {
    "trend": {"ANI": [2014, 2025]},
    "episod_zilnic": {"PERIOADA": ["2024-07-10", "2024-07-15"]},
    "atlas": {"ZONA": POL},
    "dungi": {"ANI": [2014, 2025], "ZONA": PCT},
    "serii": {"ANI": [2014, 2025], "ZONA": POL, "ZONE_DETALIU": ["Ilfov"], "FEREASTRA_ZILNICA": ["2026-06-01", None]},
    "analiza_episod": {"PERIOADA": ["2026-10-26", None], "REFERINTA": ["climatologie", 2014, 2023], "ZONA": PCT, "HARTI_ZONA": DR},
    "statistici": {"PERIOADA": ["2020-01-01", "2024-12-31"]},
    "superlative": {"ANI": [2014, 2025], "ZONA": PCT, "AN_EVIDENTIAT": 2024},
    "zonal": {"PERIOADA": ["2025-01-01", None], "FISIER": ".pixi/test_judete_v2.gpkg",
              "ZONARI": [{"prefix": "judete", "eticheta": "judet", "coloana": "NAME", "valori": []}]},
}

LIMITA_RAPIDA_GB, LIMITA_RAPIDA_S = 1.0, 60.0          # „Analize rapide”: descărcare și calcul, cu valorile implicite
_B = {"baza_de": 2014, "baza_pana": 2023}                  # cubul de test începe în 2014: baza normală 1991–2020 nu există
PE_RETETA = {
    "23_": {"INDICATORI": [dict(cod="pct_zile", indice="tx90p", **_B), dict(cod="pct_zile", indice="tn10p", **_B),
                           dict(cod="wsdi", durata=3, **_B), dict(cod="csdi", durata=3, **_B),
                           dict(cod="rnnptot", percentila="95", **_B)]},
    "r1_": {"PERIOADA": ["-30", None]},                   # perioadă relativă la frontiera datelor
    "r4_": {"PERIOADA": ["-30", None]},
    "s4_": {"ZONA": DR},                                    # hărțile pe pixel: zona mică de test
    "s5_": {"ZONA": POL},
    "24_": {"INDICATORI": [dict(cod="spi", **_B), dict(cod="spei", **_B), {"cod": "bilant"}, {"cod": "pet"}],
            "ANI": [2024, 2025], "SEZON": "JJA"},
}


def gpkg_test():
    """Patru „județe” pătrate, în Stereo70 (testează și reproiectarea); două în zona cu date a cubului.
    Coloanele imită ro_judete_poligon.gpkg real: „name” cu litere mici (testele cer „NAME”: potrivire fără majuscule)."""
    f = RAD / ".pixi" / "test_judete_v2.gpkg"
    if f.exists():
        return
    from osgeo import ogr, osr
    sr = osr.SpatialReference(); sr.ImportFromEPSG(3844)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(f))
    lyr = ds.CreateLayer("judete", sr, ogr.wkbPolygon)
    for c in ("countyCode", "name", "region"):
        lyr.CreateField(ogr.FieldDefn(c, ogr.OFTString))
    for nume, reg, (x0, y0) in [("Ilfov", "Sud", (580000, 320000)), ("Giurgiu", "Sud", (540000, 280000)),
                                ("Iași", "Nord-Est", (690000, 640000)), ("Bihor", "Nord-Vest", (260000, 600000))]:
        ft = ogr.Feature(lyr.GetLayerDefn()); ft.SetField("name", nume); ft.SetField("region", reg)
        ft.SetField("countyCode", nume[:2].upper())
        ft.SetGeometry(ogr.CreateGeometryFromWkt(
            f"POLYGON(({x0} {y0},{x0 + 40000} {y0},{x0 + 40000} {y0 + 40000},{x0} {y0 + 40000},{x0} {y0}))"))
        lyr.CreateFeature(ft)
    ds = None


def implicite(retete, env):
    """Fiecare rețetă cu valorile ei implicite (nemodificate), în modul „Verifică”, într-o copie a programului
    al cărei date/ conține ro_judete_poligon.gpkg și ro_frontiera_poligon.gpkg (aici: GPKG-ul de test)."""
    import shutil
    tmp = OUT / "_radacina_implicite"
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "date").mkdir(parents=True)
    for nume in ("ro_judete_poligon.gpkg", "ro_frontiera_poligon.gpkg"):
        shutil.copy(RAD / ".pixi" / "test_judete_v2.gpkg", tmp / "date" / nume)
    shutil.copytree(RAD / "retete", tmp / "retete")
    print("\n--- valorile implicite ale rețetelor (Verifică, fără modificări)")
    ok = 0
    for r in retete:
        jf = tmp / f"{r['id'].replace('/', '_')}.json"
        jf.write_text(json.dumps({"reteta": r["id"], "parametri": {"OUT": str(tmp / "rez")}, "_radacina": str(tmp)},
                                 ensure_ascii=False), encoding="utf-8")
        p = subprocess.run([sys.executable, str(RAD / "clima" / "ruleaza.py"), str(jf), "--verifica"], capture_output=True,
                           text=True, env=env, encoding="utf-8", errors="replace")
        bun = p.returncode == 0
        nota = ""
        if bun and r.get("rapida"):                      # o rețetă „rapidă” trebuie să rămână rapidă (v5.1)
            c = next((json.loads(l[9:]) for l in p.stdout.splitlines() if l.startswith("[[cost]] ")), {})
            bun = c.get("gb") is not None and c["gb"] <= LIMITA_RAPIDA_GB and c.get("calcul_s", 1e9) <= LIMITA_RAPIDA_S
            nota = f"rapidă: {c.get('gb')} GB, {c.get('calcul_s')} s de calcul" + ("" if bun else " — PESTE LIMITĂ")
        ok += bun
        print(f"{'OK  ' if bun else 'EȘEC'} {r['id']:32s} implicite  {nota}")
        if not bun:
            print("     " + "\n     ".join((p.stdout + p.stderr).strip().splitlines()[-6:]))
    return ok, len(retete)


def main(filtre):
    verifica = "--verifica" in filtre
    filtre = [f for f in filtre if not f.startswith("--")]
    if not (CUB / ".zmetadata").exists():
        print("Construiesc cubul sintetic de test (o singură dată)…")
        subprocess.run([sys.executable, str(RAD / "instrumente" / "cub_test.py"), str(CUB)], check=True)
    gpkg_test()
    import motoare as mo
    retete, erori = mo.citeste_retete(RAD)
    for e in erori:
        print("[eroare la citire]", e)
    env = dict(os.environ, ZARR_ANM_URL=str(CUB), PYTHONIOENCODING="utf-8", MPLBACKEND="Agg",
               CLIMA_CACHE_ANALIZE=str(RAD / ".pixi" / "test_retete" / "_cache"))
    if not filtre:                                     # întâi testele cu răspuns calculat de mână (valoarea, nu doar rularea)
        print("--- teste cu răspuns cunoscut")
        r = subprocess.run([sys.executable, str(RAD / "instrumente" / "teste_cunoscute.py")], env=env,
                           capture_output=True, text=True, encoding="utf-8")
        print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-500:])
        if r.returncode:
            print(r.stdout); sys.exit(1)
    # catalogul interfeței (ruleaza.py --catalog) trebuie să fie JSON valid: dacă nu, interfața nu arată nicio analiză
    c = subprocess.run([sys.executable, str(RAD / "clima" / "ruleaza.py"), "--catalog"], env=env,
                       capture_output=True, text=True, encoding="utf-8")
    try:
        cat = json.loads(c.stdout)
        assert not cat.get("erori") and len(cat.get("retete", [])) == len(retete), cat.get("erori")
        print(f"--- catalogul interfeței: OK ({len(cat['retete'])} rețete, {len(cat['motoare'])} motoare)")
    except (ValueError, AssertionError) as e:
        print("EȘEC catalogul interfeței (ruleaza.py --catalog):", (c.stderr or str(e))[-600:]); sys.exit(1)
    ok = n = 0
    t_total = time.time()
    for r in retete:
        if filtre and not any(r["id"].split("/")[-1].startswith(f) for f in filtre):
            continue
        campuri = {c["nume"] for c in mo.MOTOARE[r["motor"]]["campuri"]}
        par = {k: v for k, v in COMUN.items() if k in campuri}
        par.update({k: v for k, v in PE_MOTOR.get(r["motor"], {}).items() if k in campuri})
        for pref, d in PE_RETETA.items():
            if r["id"].split("/")[-1].startswith(pref):
                par.update(d)
        out = OUT / r["id"].replace("/", "_")
        out.mkdir(parents=True, exist_ok=True)
        jf = out / "job.json"
        jf.write_text(json.dumps({"reteta": r["id"], "parametri": dict(par, OUT=str(out), _setari={"CONTUR_HARTI": None}),
                                  "_radacina": str(RAD)}, ensure_ascii=False), encoding="utf-8")
        t = time.time(); n += 1
        p = subprocess.run([sys.executable, str(RAD / "clima" / "ruleaza.py"), str(jf)] + (["--verifica"] if verifica else []),
                           capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        if verifica:
            cost = [l for l in p.stdout.splitlines() if l.startswith("[[cost]] ")]
            bun = p.returncode == 0 and cost and all(json.loads(cost[0][9:]).get(k) is not None
                                                     for k in ("gb", "ram_mb", "calcul_s"))   # estimare completă
            ok += bool(bun)
            print(f"{'OK  ' if bun else 'EȘEC'} {r['id']:32s} {r['motor']:15s} {cost[0][9:] if cost else ''}")
            if not bun:
                print("     " + "\n     ".join((p.stdout + p.stderr).strip().splitlines()[-8:]))
            continue
        e = subprocess.run([sys.executable, str(RAD / "clima" / "ruleaza.py"), str(jf), "--exporta"], capture_output=True,
                           text=True, env=env, encoding="utf-8", errors="replace")
        fis = [x for x in out.rglob("*") if x.is_file() and x.name != "job.json" and "_scripturi" not in x.parts
               and not x.parent.name.startswith("cache")]
        bun = p.returncode == 0 and fis and e.returncode == 0
        ok += bool(bun)
        print(f"{'OK  ' if bun else 'EȘEC'} {r['id']:32s} {r['motor']:15s} {time.time() - t:5.1f} s {len(fis):3d} fișiere")
        if not bun:
            print("     " + "\n     ".join((p.stdout + p.stderr).strip().splitlines()[-12:]))
            if e.returncode:
                print("     export: " + (e.stdout + e.stderr).strip().splitlines()[-1])
    if not filtre:
        ok_i, n_i = implicite(retete, env)
        ok += ok_i; n += n_i
    print(f"\n{ok}/{n} verificări OK în {time.time() - t_total:.0f} s  (rezultatele: {OUT})")
    sys.exit(0 if ok == n else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
