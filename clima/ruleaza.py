# -*- coding: utf-8 -*-
"""
ruleaza.py — rulează o rețetă (motor + indicatori + parametri)
==============================================================
  python ruleaza.py job.json                 rulează analiza descrisă în job.json (scris de interfață)
  python ruleaza.py job.json --verifica      doar verifică parametrii (zone, indicatori, perioade); nu descarcă date
  python ruleaza.py job.json --exporta       scrie scriptul Python echivalent în rezultate/_scripturi/
  python ruleaza.py --catalog                catalogul (indicatori, motoare, rețete) în JSON, pentru interfață
  python ruleaza.py --indicatori             lista indicatorilor și a parametrilor lor, în text

job.json:  {"reteta": "02_zile_tropicale", "parametri": {...}, "_radacina": "C:\\...\\ClimaANM"}
"""
from __future__ import annotations

import json

import numpy as np
import time
import os
import sys
from pathlib import Path

AICI = Path(__file__).resolve().parent
sys.path.insert(0, str(AICI))

import zarr_clima as zc   # noqa: E402
import indicatori as ri   # noqa: E402
import motoare as mo      # noqa: E402

RADACINA = AICI.parent


class EroareParametri(Exception):
    """Greșeală în parametri (nu în calcul): se afișează scurt, fără traceback."""


def _gaseste_reteta(rid, radacina):
    retete, erori = mo.citeste_retete(radacina)
    for r in retete:
        if r["id"] == rid:
            return r
    raise SystemExit(f"Rețeta „{rid}” nu există." + (f" Erori la citirea rețetelor: {'; '.join(erori)}" if erori else ""))


def _afiseaza(v):
    """Valoarea unui parametru, pentru jurnal: fără repr, căi cu separatorul sistemului."""
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, zc.Zona):
        return v.descriere()
    if isinstance(v, dict) and v and all(isinstance(x, bool) for x in v.values()):
        alese = [k for k, x in v.items() if x]
        return ", ".join(alese) if alese else "(niciuna)"
    if isinstance(v, (list, tuple)):
        if v and all(isinstance(x, dict) and "cod" in x for x in v):
            return " · ".join(ri.din_dict(x).titlu for x in v)
        if len(v) == 2 and all(isinstance(x, int) for x in v):
            return f"{v[0]}–{v[1]}"
        return ", ".join(_afiseaza(x) for x in v) if v else "(nimic)"
    if v is None:
        return "—"
    return str(v)


# Reperele de an din rețetele rapide („Vara trecută” rămâne vara trecută și la anul): (luna, ziua) la care se
# încheie perioada în anul ei. Iarna anului A = decembrie A−1 … februarie A, deci se încheie la sfârșitul lui februarie.
REPERE_AN = {"ultimul_an": (12, 31), "ultima_vara": (8, 31), "ultima_iarna": (2, 28)}


def an_reper(reper, frontiera):
    """Ultimul an în care perioada reperului e încheiată până la frontiera datelor."""
    luna, zi = REPERE_AN[reper]
    an = int(str(frontiera)[:4])
    return an if str(frontiera)[5:] >= f"{luna:02d}-{zi:02d}" else an - 1


def _date_relative(p, m):
    """Perioadele cu începutul „-N” = ultimele N zile până la frontiera datelor, iar anii „ultimul_an”, „ultima_vara”,
    „ultima_iarna” = ultima perioadă încheiată (rețetele rapide nu îmbătrânesc).
    Se rezolvă aici, deci fișa de reproducere păstrează datele exacte."""
    import re
    rel = [c["nume"] for c in m["campuri"] if c.get("tip") == "perioada" and isinstance(p.get(c["nume"]), (list, tuple))
           and p[c["nume"]] and isinstance(p[c["nume"]][0], str) and re.fullmatch(r"-\d+", p[c["nume"]][0].strip())]
    ani = [c["nume"] for c in m["campuri"] if c.get("tip") == "interval_ani" and isinstance(p.get(c["nume"]), (list, tuple))
           and any(isinstance(v, str) and v.strip() in REPERE_AN for v in p[c["nume"]])]
    if not rel and not ani:
        return
    _, fr = zc.deschide()
    frontiera = min(fr.values())
    for k in ani:
        p[k] = [an_reper(v.strip(), frontiera) if isinstance(v, str) and v.strip() in REPERE_AN else int(v) for v in p[k]]
    for k in rel:
        n = int(p[k][0].strip()[1:])
        p[k] = [str(frontiera - np.timedelta64(max(n, 1) - 1, "D")), p[k][1] or str(frontiera)]   # capete fixe: reproductibil


def slug(t):
    """Text → nume de fișier/folder: fără diacritice, litere mici, „_” între cuvinte."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _slug_titlu(t, n=56):
    """Partea principală a titlului (fără zonă și fără „(după Tmax)”), tăiată la un cuvânt întreg."""
    import re
    t = re.sub(r"\s*\(după [^)]*\)", "", t.split(" · ")[0])
    s = slug(t)
    if len(s) > n:
        s = s[:n].rsplit("_", 1)[0]
    return s


def titlu_rulare(r, m, p):
    """Ce calculează efectiv rularea. Titlul rețetei, cât timp parametrii nu schimbă subiectul; altfel un titlu
    construit din parametri (superlative: întotdeauna; hărți etc.: când indicatorii diferă de ai rețetei)."""
    try:
        if m.get("titlu_rulare"):
            return m["titlu_rulare"](p)
        impl = next((x.get("implicit") for x in r["campuri"] if x["nume"] == "INDICATORI"), r["fixe"].get("INDICATORI"))
        if p.get("INDICATORI") and impl is not None and p["INDICATORI"] != impl:
            import indicatori as ri
            t = [ri.din_dict(d).titlu for d in p["INDICATORI"]]
            return t[0] + (f" (+{len(t) - 1})" if len(t) > 1 else "")
    except Exception:  # noqa: BLE001  (titlul nu trebuie să oprească rularea; validarea vine după)
        pass
    return r["titlu"]


def pregateste(job: dict):
    """→ (rețeta, parametrii JSON compleți, parametrii convertiți pentru motor, setările zc)."""
    radacina = Path(job.get("_radacina", RADACINA))
    r = _gaseste_reteta(job["reteta"], radacina)
    m = mo.MOTOARE[r["motor"]]
    brut = dict(job.get("parametri", {}))
    if r["motor"] in ("dungi", "serii") and "VARIABILA" in brut:     # job / script scris înainte de v4
        v = brut.pop("VARIABILA")
        brut.setdefault("INDICATORI", [mo._ind_din_variabila(v)])
    setari = dict(brut.pop("_setari", {}))
    permise = {c["nume"] for c in m["campuri"] if c.get("setare")}
    # CONTUR_HARTI=None este folosit și de scripturile de verificare fără hartă.
    necunoscute = set(setari) - (permise | {"CONTUR_HARTI"})
    if necunoscute:
        raise ValueError(f"Setări necunoscute: {sorted(necunoscute)}")
    brut.pop("_zone", None)
    p = {}
    for c in m["campuri"]:                               # implicitele motorului, apoi ale rețetei, apoi ale formularului
        k = c["nume"]
        if c.get("setare"):
            setari.setdefault(k, r["fixe"].get(k, next((x.get("implicit") for x in r["campuri"] if x["nume"] == k), c.get("implicit"))))
            continue
        if k in brut:
            p[k] = brut.pop(k)
        elif k in r["fixe"]:
            p[k] = r["fixe"][k]
        else:
            p[k] = next((x.get("implicit") for x in r["campuri"] if x["nume"] == k), c.get("implicit"))
    p.update(brut)                                        # OUT, NUME
    _date_relative(p, m)
    p["_titlu_rulare"] = titlu_rulare(r, m, p)
    folder_auto = not p.get("OUT")
    if folder_auto:                                       # fiecare rulare în folderul ei: rezultate/<data_ora>_<analiza>
        from datetime import datetime
        rid = r["id"].split("/")[-1]
        baza_rez = Path(os.environ.get("CLIMA_REZULTATE", radacina / "rezultate"))
        # numele folderului spune ce s-a calculat: prefixul rețetei + titlul rulării (dacă parametrii schimbă subiectul)
        sl = _slug_titlu(p["_titlu_rulare"])
        baza_f = baza_rez / f"{datetime.now().strftime('%Y-%m-%d_%H%M')}_{rid.split('_')[0]}_{sl}"
        f, k = baza_f, 2
        while f.exists():
            f = baza_f.with_name(f"{baza_f.name}_{k}"); k += 1
        p["OUT"] = str(f)
    rid = r["id"].split("/")[-1]
    if p["_titlu_rulare"] != r["titlu"]:                  # parametrii schimbă subiectul: fișierele poartă titlul rulării
        rid = f"{rid.split('_')[0]}_{_slug_titlu(p['_titlu_rulare'])}"
    if not p.get("NUME") and folder_auto:                 # în folderul propriu, numele nu mai au nevoie de amprentă
        p["NUME"] = m["nume"](p, rid) if m.get("nume") else rid
    if not p.get("NUME"):
        import hashlib
        baza = m["nume"](p, rid) if m.get("nume") else rid
        param = {k: v for k, v in p.items() if k not in {"OUT", "NUME"}}
        spec = json.dumps([r["id"], param, setari], ensure_ascii=False, sort_keys=True)
        # amprenta parametrilor: două rulări cu zone / filtre / setări diferite nu se mai suprascriu (auditul v4, E.7)
        p["NUME"] = f"{baza}_{hashlib.sha256(spec.encode()).hexdigest()[:6]}"
    import re
    if not re.fullmatch(r"[\w. -]{1,180}", str(p["NUME"])) or str(p["NUME"]).endswith((".", " ")):
        raise ValueError("Prefix de fișier invalid.")
    if Path(str(p["NUME"])).is_reserved():
        raise ValueError("Prefix de fișier rezervat pe Windows.")
    if setari.get("CONTUR_HARTI"):
        setari["CONTUR_HARTI"] = str(zc._cale(setari["CONTUR_HARTI"], radacina))
    else:
        setari["CONTUR_HARTI"] = None
    for c in m["campuri"]:                                # căile fișierelor vectoriale: absolute
        if c["tip"] == "zona" and isinstance(p.get(c["nume"]), dict) and p[c["nume"]].get("fisier"):
            p[c["nume"]] = dict(p[c["nume"]], fisier=str(zc._cale(p[c["nume"]]["fisier"], radacina)))
        elif c["tip"] == "vector" and p.get(c["nume"]):
            p[c["nume"]] = str(zc._cale(p[c["nume"]], radacina))
    conv = {}
    for c in m["campuri"]:
        k = c["nume"]
        if k not in p:
            continue
        if c["tip"] == "zona":
            conv[k] = zc.zona_din_dict(p[k], radacina)
        elif c["tip"] == "indicatori":
            conv[k] = [dict(x) for x in (p[k] or [])]
        elif c["tip"] == "zonari":
            conv[k] = [dict(x) for x in (p[k] or [])]
        elif c["tip"] == "vector":
            conv[k] = Path(p[k]) if p[k] else None
        else:
            conv[k] = zc._din_json(p[k])
    conv["OUT"] = zc._cale(p["OUT"], radacina)
    conv["NUME"] = p["NUME"]
    return r, m, p, conv, setari


def ruleaza(cale_job: Path, verifica=False, exporta=False):
    job = json.loads(Path(cale_job).read_text(encoding="utf-8"))
    try:
        r, m, p, conv, setari = pregateste(job)
    except (ValueError, KeyError, FileNotFoundError) as e:
        raise EroareParametri(e.args[0] if e.args else e) from None
    if exporta:
        cod = m["exporta"](dict(job, titlu=r["titlu"], motor=r["motor"], _radacina=str(Path(job.get("_radacina", RADACINA)).resolve())), p, setari)
        auto = not job.get("parametri", {}).get("OUT")       # exportul nu creează un folder de rulare
        baza_rez = Path(os.environ.get("CLIMA_REZULTATE", Path(job.get("_radacina", RADACINA)) / "rezultate"))
        dest = (baza_rez / "_scripturi" if auto else Path(conv["OUT"]) / "_scripturi") / f"{p['NUME']}.py"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(cod, encoding="utf-8")
        print(cod, end="")
        print(f"# --- salvat în {dest}", file=sys.stderr)
        return
    for k, v in setari.items():
        setattr(zc, k, zc._din_json(v))
    zc.log(f"Rețeta: {r['titlu']}  ·  motorul: {m['titlu']}")
    ascunse = {c["nume"] for c in m["campuri"] if c.get("doar_daca")                # câmpuri care nu se aplică (ex. LUNA
               and str(p.get(c["doar_daca"]["camp"])) not in map(str, c["doar_daca"]["valori"])}   # când unitatea e „zi”)
    for k, v in conv.items():
        if k not in ascunse:
            zc.log(f"   {k} = {_afiseaza(v)}")
    for k, v in setari.items():
        zc.log(f"   {k} = {_afiseaza(getattr(zc, k))}")
    try:                                                  # validare (și la rulare): greșelile apar înainte de descărcare
        if conv.get("INDICATORI") is not None:
            mo._indicatori(conv)
        for c in m["campuri"]:
            k, v = c["nume"], conv.get(c["nume"])
            if c["tip"] == "interval_ani" and (v is None or v[0] is None or v[1] is None or v[0] > v[1]):
                raise ValueError(f"{c.get('eticheta', k)}: interval de ani invalid {v!r}")
            if c["tip"] == "perioada" and v is not None:
                if not v[0]:
                    raise ValueError(f"{c.get('eticheta', k)}: lipsește data de început")
                if v[1] and str(v[1]) < str(v[0]):
                    raise ValueError(f"{c.get('eticheta', k)}: sfârșitul ({v[1]}) e înaintea începutului ({v[0]})")
            if c["tip"] == "vector" and v is not None and not Path(v).exists():
                raise FileNotFoundError(f"{c.get('eticheta', k)}: fișierul nu există: {v}")
        if verifica and r["motor"] == "zonal":            # fiecare zonare: coloana și valorile există?
            for zn in mo._zonari(conv):
                zt = zc.Zona.poligoane(str(conv["FISIER"]), coloana=zn["coloana"], strat=conv.get("STRAT"),
                                       valori=zn.get("valori"))
                zc._citeste_poligoane(zt)
                zc.log(f"   zonarea „{zn['prefix']}”: coloana „{zt.coloana}”, {len(zt.poligoane)} zone")
        if verifica:
            for k, v in conv.items():
                if isinstance(v, zc.Zona) and v.gpkg:
                    zc._citeste_poligoane(v)
                    zc.log(f"   {k}: {v.descriere()} · {len(v.poligoane)} poligoane citite")
    except (ValueError, KeyError, FileNotFoundError) as e:
        raise EroareParametri(e.args[0] if e.args else e) from None
    if verifica:
        zc.log("Parametrii sunt corecți. Estimez volumul de date (doar metadatele cubului)…")
        try:
            import estimare as es
            e = es.estimeaza(r["motor"], conv)
            for desc, var, n, mb in e["randuri"]:
                zc.log(f"   {desc} · {var}: {n} chunk-uri ≈ {zc.ro(mb / 1000, 2)} GB")
            for a in e.get("avertismente", []):
                zc.log(f"   [atenție] {a}")
            zc.log(f"   TOTAL ≈ {zc.ro(e['gb'], 2)} GB · {e['chunkuri']} chunk-uri · {es.text_durata(e['secunde'])} "
                   f"la ~{e['mbs']:g} MB/s (prima rulare; din cache, mult mai puțin)")
            zc.log(f"   CALCUL: memorie ≈ {zc.ro(e['ram_mb'] / 1000, 1)} GB · {es.text_durata(e['calcul_s'])} de procesare "
                   f"(pe un calculator cu 2 nuclee; fără descărcare)")
            disp = e.get("ram_disponibil_mb")
            if disp and e["ram_mb"] > 0.8 * disp:
                zc.log(f"   [atenție] analiza cere ≈ {zc.ro(e['ram_mb'] / 1000, 1)} GB de memorie, iar acum sunt libere "
                       f"≈ {zc.ro(disp / 1000, 1)} GB: închideți alte programe sau alegeți o zonă mai mică.")
            print("[[cost]] " + json.dumps({"gb": round(e["gb"], 3), "chunkuri": e["chunkuri"],
                                            "durata": es.text_durata(e["secunde"]), "frontiera": e["frontiera"],
                                            "ram_mb": e["ram_mb"], "calcul_s": e["calcul_s"],
                                            "calcul": es.text_durata(e["calcul_s"]), "ram_disponibil_mb": disp}), flush=True)
        except Exception as ex:  # noqa: BLE001
            zc.log(f"   [atenție] nu pot estima volumul ({type(ex).__name__}: {ex}); EOCube e accesibil?")
        zc.log("Verificare încheiată (nu s-au descărcat date).")
        return
    out = Path(conv["OUT"]); out.mkdir(parents=True, exist_ok=True)
    print(f"[[folder]] {out}", flush=True)                 # serverul scrie aici și jurnalul rulării
    print(f"[[titlu]] {p.get('_titlu_rulare') or r['titlu']}", flush=True)
    t0 = time.time()
    fisa = _fisa_reproducere(job, r, m, p, setari)
    _scrie_fisa(out, fisa)
    try:
        m["ruleaza"](conv)
        fisa.update(stare="gata", durata_s=round(time.time() - t0, 1))
        av = zc.raport_corectii()                          # golurile din cub, tratate ca date lipsă
        if av:
            zc.log("   " + av)
            fisa["avertisment_date"] = av
    except (ValueError, FileNotFoundError) as e:
        fisa.update(stare="eroare", eroare=str(e.args[0] if e.args else e), durata_s=round(time.time() - t0, 1))
        _scrie_fisa(out, fisa)
        _fisa_vizuala(out, fisa)
        # nucleul ridică ValueError pentru situații explicabile (ani incompleți, coloane lipsă, perioade goale);
        # traceback-ul complet rămâne disponibil cu variabila de mediu CLIMA_DEPANARE=1
        if os.environ.get("CLIMA_DEPANARE"):
            raise
        raise EroareParametri(e.args[0] if e.args else e) from None
    fisa["frontiera_datelor"] = {k: str(v) for k, v in (getattr(zc, "FRONTIERE_ULTIME", None) or {}).items()}
    try:                                             # paragraful „Date și metode” (RO + EN) și bibliografia
        import metode_text
        m = metode_text.compune(fisa, fisa.get("versiune_program", ""))
        if m:
            fisa["metode"] = m
            metode_text.scrie_md(out, m)
    except Exception as e:  # noqa: BLE001  (un plus: rularea e bună și fără el)
        zc.log(f"   [atenție] paragraful de metode nu s-a putut scrie: {type(e).__name__}: {e}")
    fisa["fisiere"] = sorted(str(f.relative_to(out)).replace("\\", "/") for f in out.rglob("*")
                             if f.is_file() and f.name not in ("reproducere.json", "jurnal.txt", "index.html"))
    _scrie_fisa(out, fisa)
    _fisa_vizuala(out, fisa)


def versiune_program():
    """Versiunea din pixi.toml (sursa unică a numărului de versiune)."""
    import re
    try:
        t = (Path(__file__).resolve().parent.parent / "pixi.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', t, re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def _fisa_vizuala(out, fisa):
    """index.html: „posterul” rulării (clima/fisa_vizuala.py). O eroare aici nu strică rularea."""
    try:
        import fisa_vizuala
        f = fisa_vizuala.scrie_fisa(out, fisa)
        if f:
            zc.log(f"   Fișa vizuală: {f}")
    except Exception as e:  # noqa: BLE001
        zc.log(f"   [atenție] fișa vizuală nu s-a putut scrie: {type(e).__name__}: {e}")


def _fisa_reproducere(job, r, m, p, setari):
    """Tot ce trebuie ca rezultatul să poată fi refăcut și citat: rețeta, parametrii efectivi, sursa datelor,
    versiunile bibliotecilor și amprenta mediului (pixi.lock). Frontiera datelor se adaugă la final."""
    import hashlib
    import platform
    from datetime import datetime
    vers = {"python": platform.python_version()}
    for mod in ("numpy", "xarray", "zarr", "osgeo.gdal"):
        try:
            vers[mod.split(".")[-1]] = __import__(mod, fromlist=["x"]).__version__
        except Exception:  # noqa: BLE001
            pass
    rad = Path(job.get("_radacina", RADACINA))
    lock = rad / "pixi.lock"
    param = {k: v for k, v in p.items() if not str(k).startswith("_") and k not in ("OUT", "NUME")}
    param["_setari"] = setari
    # fișa este și un job valid: „reteta” + „parametri” → ruleaza.py o poate rula din nou (într-un folder nou)
    return {"reteta": r["id"], "parametri": param,          # fără _radacina: merge și pe alt calculator
            "program": "Clima ANM", "versiune_program": versiune_program(), "titlu": p.get("_titlu_rulare") or r["titlu"], "reteta_titlu": r["titlu"], "motor": r["motor"],
            "pornit": datetime.now().isoformat(timespec="seconds"), "sursa_datelor": zc.URL,
            "versiuni": vers, "pixi_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()[:16] if lock.exists() else None,
            "refacere": "instrumente\\pixi.exe run python clima\\ruleaza.py <acest folder>\\reproducere.json"}


def _scrie_fisa(out, fisa):
    (Path(out) / "reproducere.json").write_text(json.dumps(fisa, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def zarr_info():
    import math
    import time as _t
    t0 = _t.perf_counter()
    cub, fr = zc.deschide()
    t_desc = _t.perf_counter() - t0
    var = {}
    for v in ("max_temp", "min_temp", "precipitation"):
        da = cub[v]
        enc = da.encoding
        ch = list(enc.get("chunks") or enc.get("preferred_chunks", {}).values() or [])
        comp = enc.get("compressor") or (enc.get("compressors") or [None])[0]
        nchunk = [math.ceil(n / c) for n, c in zip(da.shape, ch)] if ch else []
        var[v] = {"shape": list(da.shape), "dims": list(da.dims), "chunks": ch, "dtype": str(enc.get("dtype", da.dtype)),
                  "compresor": str(comp), "fill_value": str(enc.get("_FillValue", "?")),
                  "units": da.attrs.get("units", ""), "grid_mapping": da.attrs.get("grid_mapping", ""),
                  "grila_chunk": nchunk, "n_chunk": int(math.prod(nchunk)) if nchunk else None,
                  "mb_chunk_necomprimat": round(math.prod(ch) * 4 / 1e6, 2) if ch else None,
                  "gb_necomprimat": round(math.prod(da.shape) * 4 / 1e9, 2), "frontiera": str(fr[v])}
    t = cub.time.values
    x, y = cub.x.values, cub.y.values
    return {"ok": True, "sursa": zc.URL, "secunde_deschidere": round(t_desc, 2),
            "test": "TEST" in str(cub.attrs.get("institution", "")), "atribute": {k: str(v) for k, v in cub.attrs.items()},
            "timp": {"inceput": str(t[0])[:10], "sfarsit_alocat": str(t[-1])[:10], "n_zile": int(t.size),
                     "units": cub.time.encoding.get("units", ""), "calendar": cub.time.encoding.get("calendar", "")},
            "x": {"n": int(x.size), "min": float(x.min()), "max": float(x.max()), "pas": float(abs(x[1] - x[0]))},
            "y": {"n": int(y.size), "prim": float(y[0]), "ultim": float(y[-1]), "pas": float(abs(y[1] - y[0])),
                  "descrescator": bool(y[0] > y[-1])},
            "variabile": var, "variabile_toate": sorted(cub.variables)}


def catalog():
    retete, erori = mo.citeste_retete(RADACINA)
    motoare = {c: {k: v for k, v in m.items() if not callable(v)} for c, m in mo.MOTOARE.items()}   # fără funcții: JSON
    ind = ri.catalog()
    for r in retete:                                      # ce analize folosesc fiecare indicator
        for c in r["campuri"]:
            if c["tip"] == "indicatori":
                for d in c.get("implicit") or []:
                    lst = ind.get(d.get("cod"), {}).setdefault("retete", []) if d.get("cod") in ind else None
                    if lst is not None and all(x["id"] != r["id"] for x in lst):
                        lst.append({"id": r["id"], "titlu": r["titlu"]})
    lipsa = [c for c, d in ind.items() if not d.get("teorie")]
    if lipsa:
        erori.append("indicatori fără fișă teoretică (teorie_indicatori.py): " + ", ".join(lipsa))
    return {"indicatori": ind, "pasi_comuni": ri.pasi_comuni(), "metode": ri.metode(), "motoare": motoare, "retete": retete, "erori": erori}


def main(argv):
    if "--catalog" in argv:
        sys.stdout.write(json.dumps(catalog(), ensure_ascii=False))
        return
    if "--frontiere" in argv:                             # pentru antetul interfeței
        try:
            cub, fr = zc.deschide()
            rez = {"ok": True, "frontiere": {k: str(v) for k, v in fr.items()}, "inceput": str(cub.time.values[0])[:10],
                   "sursa": zc.URL, "test": "institution" in cub.attrs and "TEST" in str(cub.attrs.get("institution"))}
        except Exception as ex:  # noqa: BLE001
            rez = {"ok": False, "eroare": f"{type(ex).__name__}: {ex}"[:300], "sursa": zc.URL}
        sys.stdout.write("\n[[frontiere]] " + json.dumps(rez, ensure_ascii=False))
        return
    if "--zarr-info" in argv:                             # tabul „Zarr info”: metadatele store-ului, citite acum
        try:
            rez = zarr_info()
        except Exception as ex:  # noqa: BLE001
            rez = {"ok": False, "eroare": f"{type(ex).__name__}: {ex}"[:300], "sursa": zc.URL}
        sys.stdout.write("\n[[zarr]] " + json.dumps(rez, ensure_ascii=False, default=str))
        return
    if "--indicatori" in argv:
        for c, d in ri.REGISTRU.items():
            par = ", ".join(f"{x['nume']}={x.get('implicit')!r}" for x in d.parametri) or "—"
            print(f"{c:22s} [{d.grup}]  {par}\n{'':24s}{d.descriere}")
        return
    fis = [a for a in argv if not a.startswith("--")]
    if not fis:
        print(__doc__)
        return
    try:
        ruleaza(Path(fis[0]), verifica="--verifica" in argv, exporta="--exporta" in argv)
    except EroareParametri as e:
        print(f"\n[eroare] {e}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
