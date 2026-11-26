"""Măsoară memoria de vârf (RSS) și timpul de calcul ale fiecărei rețete, pe cubul de test (grila completă a României),
pe toată țara și pe o zonă mică. Rezultatele (CSV) servesc la calibrarea estimării din „Verifică” (clima/estimare.py).

    instrumente/pixi run python instrumente/masoara_resurse.py [prefix_retete…]

Doar Linux / macOS (folosește os.wait4). Cache-ul analizelor e golit la fiecare rulare: se măsoară prima rulare."""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAD / "instrumente"))
import testeaza_retete as tr                                   # noqa: E402  (aceiași parametri ca suita de teste)

sys.path.insert(0, str(RAD / "clima"))
import motoare as mo                                           # noqa: E402
import ruleaza as rl                                           # noqa: E402,F401

TARA = {"tip": "tara"}


def ruleaza_masurat(cmd, env):
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace")
    anon = [0]

    def esantion():                         # memoria anonimă (fără fișierele mapate), din /proc — doar Linux
        f = Path(f"/proc/{p.pid}/status")
        while p.poll() is None:
            try:
                for l in f.read_text().splitlines():
                    if l.startswith("RssAnon"):
                        anon[0] = max(anon[0], int(l.split()[1]) // 1024)
            except OSError:
                pass
            time.sleep(0.05)
    import threading
    th = threading.Thread(target=esantion, daemon=True); th.start()
    iesire = p.stdout.read()
    _, stare, ru = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(stare)
    rss_mb = ru.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    return p.returncode, iesire, time.perf_counter() - t0, rss_mb, anon[0]


def main():
    filtre = sys.argv[1:]
    tr.gpkg_test()
    out_csv = RAD / ".pixi" / "resurse.csv"
    randuri = []
    for r in mo.citeste_retete(RAD)[0]:
        rid = r["id"].split("/")[-1]
        if filtre and not any(rid.startswith(f) for f in filtre):
            continue
        campuri = {c["nume"] for c in mo.MOTOARE[r["motor"]]["campuri"]}
        baza = {k: v for k, v in tr.COMUN.items() if k in campuri}
        baza.update({k: v for k, v in tr.PE_MOTOR.get(r["motor"], {}).items() if k in campuri})
        for pref, d in tr.PE_RETETA.items():
            if rid.startswith(pref):
                baza.update(d)
        variante = [("mica", baza)]
        if "ZONA" in campuri and baza.get("ZONA", {}).get("tip") not in ("punct", "poligoane"):
            variante.append(("tara", dict(baza, ZONA=TARA)))
        for eticheta, par in variante:
            tmp = Path(tempfile.mkdtemp(prefix="masura_"))
            env = dict(os.environ, ZARR_ANM_URL=str(tr.CUB), PYTHONIOENCODING="utf-8", MPLBACKEND="Agg",
                       CLIMA_CACHE_ANALIZE=str(tmp / "_cache"), CLIMA_CACHE_DATE=str(tmp / "_date"))
            jf = tmp / "job.json"
            jf.write_text(json.dumps({"reteta": r["id"], "_radacina": str(RAD),
                                      "parametri": dict(par, OUT=str(tmp / "out"), _setari={"CONTUR_HARTI": None})}),
                          encoding="utf-8")
            v = subprocess.run([sys.executable, str(RAD / "clima" / "ruleaza.py"), str(jf), "--verifica"], env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            cost = next((json.loads(l[9:]) for l in v.stdout.splitlines() if l.startswith("[[cost]] ")), {})
            cod, iesire, sec, rss, anon = ruleaza_masurat([sys.executable, str(RAD / "clima" / "ruleaza.py"), str(jf)], env)
            rand = {"reteta": rid, "motor": r["motor"], "zona": eticheta, "ok": cod == 0, "secunde": round(sec, 1),
                    "rss_mb": round(rss), "anon_mb": anon, "gb_estimat": cost.get("gb"), "chunkuri": cost.get("chunkuri"),
                    "ram_estimat_mb": cost.get("ram_mb"), "calcul_estimat_s": cost.get("calcul_s")}
            randuri.append(rand)
            print(f"{'OK  ' if cod == 0 else 'EȘEC'} {rid:30s} {eticheta:5s} {sec:6.1f} s  RSS {rss:6.0f} MB  anonim {anon:5d} MB  "
                  f"citit ≈ {cost.get('gb')} GB  (estimat: {cost.get('ram_mb')} MB, {cost.get('calcul_s')} s)", flush=True)
            if cod:
                print("     " + "\n     ".join(iesire.strip().splitlines()[-6:]))
            shutil.rmtree(tmp, ignore_errors=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(randuri[0])); w.writeheader(); w.writerows(randuri)
    print(f"\n{len(randuri)} măsurători → {out_csv}")


if __name__ == "__main__":
    main()
