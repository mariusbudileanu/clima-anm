# -*- coding: utf-8 -*-
"""
mediu_numpy.py — detectează o copie de numpy instalată cu `pip install --user` care umbrește numpy-ul din OSGeo4W / QGIS
======================================================================================================================
De ce contează: GDAL, matplotlib, pandas, bottleneck, numexpr din OSGeo4W sunt compilate pentru NumPy 1.x.
Dacă `pip install --user …` a adus un numpy 2.x în AppData\\Roaming\\Python, acesta se încarcă primul și fiecare modul
compilat pentru 1.x tipărește la import: „A module that was compiled using NumPy 1.x cannot be run in NumPy 2.x…”.

Modulul NU importă numpy (citește doar fișierele de versiune), deci funcționează chiar dacă mediul e stricat.
"""
import os
import re
import site
import sys
from pathlib import Path

_RE_VERSIUNE = re.compile(r"""^version\s*(?::\s*\w+)?\s*=\s*['"]([^'"]+)['"]""", re.M)

COMANDA_REPARARE = "python -m pip uninstall -y numpy"


def _nc(cale):
    return os.path.normcase(os.path.abspath(cale)) if cale else ""


def copii_numpy():
    """[(folder, versiune)] pentru fiecare folder din sys.path care conține numpy; prima = cea folosită la import."""
    ies, vazute = [], set()
    for d in sys.path:
        try:
            if not d:
                continue
            cheie = _nc(d)
            p = Path(d) / "numpy"
            if cheie in vazute or not (p / "__init__.py").exists():
                continue
            vazute.add(cheie)
            v = "?"
            f = p / "version.py"
            if f.exists():
                m = _RE_VERSIUNE.search(f.read_text(encoding="utf-8", errors="ignore"))
                if m:
                    v = m.group(1)
            ies.append((os.path.abspath(d), v))
        except Exception:  # noqa: BLE001
            continue
    return ies


def _major(v):
    try:
        return int(str(v).split(".")[0])
    except Exception:  # noqa: BLE001
        return None


def diagnostic():
    """→ dict(stare = 'ok' | 'atentie' | 'eroare', activa, altele, user_site, scurt, mesaj)."""
    copii = copii_numpy()
    try:
        user_site = site.getusersitepackages()
    except Exception:  # noqa: BLE001
        user_site = ""
    activa = copii[0] if copii else None
    if "numpy" in sys.modules and getattr(sys.modules["numpy"], "__file__", None):          # deja importat: copia reală
        dir_activ = _nc(str(Path(sys.modules["numpy"].__file__).parent.parent))
        activa = next((c for c in copii if _nc(c[0]) == dir_activ), activa)
    altele = [c for c in copii if activa and _nc(c[0]) != _nc(activa[0])]
    r = dict(stare="ok", activa=activa, altele=altele, user_site=user_site, scurt="", mesaj="")
    if not activa or not altele or _nc(activa[0]) != _nc(user_site):
        return r
    sistem = altele[0]
    major_diferit = _major(activa[1]) != _major(sistem[1])
    r["stare"] = "eroare" if major_diferit else "atentie"
    r["scurt"] = (f"numpy {activa[1]} din folderul utilizatorului umbrește numpy {sistem[1]} din OSGeo4W/QGIS"
                  + (" — de aici mesajul „A module that was compiled using NumPy 1.x…”" if major_diferit else ""))
    r["mesaj"] = (
        f"numpy {activa[1]} instalat cu --user:  {activa[0]}\n"
        f"      umbrește numpy {sistem[1]} din OSGeo4W / QGIS:  {sistem[0]}\n"
        + ("      Modulele compilate pentru NumPy 1.x (GDAL, matplotlib, pandas, bottleneck, numexpr) nu pot rula cu NumPy 2.x:\n"
           "      de aici mesajul „A module that was compiled using NumPy 1.x cannot be run in NumPy 2.x”.\n" if major_diferit else "")
        + "      Remediu, în OSGeo4W Shell (comanda se rulează O SINGURĂ DATĂ — a doua oară ar scoate numpy-ul din OSGeo4W):\n"
          f"          {COMANDA_REPARARE}\n"
          "          python -m pip check\n"
          "          python 00_verificare_mediu.py")
    return r


if __name__ == "__main__":
    d = diagnostic()
    print("copii numpy găsite:", copii_numpy())
    print(d["stare"], "-", d["scurt"] or "nimic de reparat")
    if d["mesaj"]:
        print(d["mesaj"])
