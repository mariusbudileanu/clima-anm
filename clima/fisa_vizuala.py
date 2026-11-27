# -*- coding: utf-8 -*-
"""
fisa_vizuala.py — „posterul” unei rulări: rezultate/<data_ora>_<analiza>/index.html
====================================================================================
O pagină HTML statică, fără dependențe, care se deschide din folderul rulării (dublu-clic) sau din program:
harta principală, faptele-cheie, comparația cu cortină între două hărți, galeria graficelor, fișierele,
parametrii, refacerea și citarea. Imaginile sunt legate relativ, deci folderul se poate copia sau trimite întreg.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

LUNI = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie",
        "noiembrie", "decembrie"]
TIPURI = {".tif": "GeoTIFF (QGIS)", ".csv": "tabel CSV (Excel)", ".gpkg": "GeoPackage (QGIS)", ".nc": "NetCDF",
          ".gif": "animație GIF", ".json": "JSON", ".py": "script Python", ".txt": "text",
          ".qml": "stil QGIS (culorile hărții)", ".md": "text Markdown (Date și metode)"}
# dungile antetului: aceleași culori ca banda din interfață (de la rece la cald)
DUNGI = ["#08306b", "#08519c", "#2171b5", "#4292c6", "#6baed6", "#9ecae1", "#c6dbef", "#deebf7", "#fee0d2", "#fcbba1",
         "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#a50f15", "#67000d"]


def _e(s):
    return html.escape(str(s), quote=True)


def _data_ro(iso):
    s = str(iso)
    try:
        return f"{int(s[8:10])} {LUNI[int(s[5:7]) - 1]} {s[:4]}" + (f", ora {s[11:16]}" if len(s) > 11 else "")
    except (ValueError, IndexError):
        return s


def _mb(n):
    return f"{n / 1e6:.1f} MB".replace(".", ",") if n >= 1e5 else f"{max(1, round(n / 1e3))} kB"


def _uman(nume, prefix):
    """„s4_anul_celei_mai_calde_veri_an_record_harta.png” → „an record”."""
    b = nume.rsplit(".", 1)[0]
    if prefix and b.startswith(prefix):
        b = b[len(prefix):]
    b = b.strip("_").replace("_harta", "").replace("_", " ").strip()
    return b or nume


def _prefix_comun(nume):
    if len(nume) < 2:
        return ""
    p = nume[0]
    for n in nume:
        while p and not n.startswith(p):
            p = p[:-1]
    return p[:p.rfind("_") + 1] if "_" in p else ""


def _fapte(rez, fisa):
    """Faptele-cheie: din rezumatul superlativelor, dacă există, altfel din fișa de reproducere."""
    f = []
    if rez and rez.get("zone"):
        z = rez["zone"][0]
        um = rez.get("unitate_masura", "")
        f.append(("Recordul", f"{z['record']:.1f} {um}".replace(".", ","), z["eticheta"]))
        if z.get("al_doilea") is not None:
            f.append(("Al doilea", f"{z['al_doilea']:.1f} {um}".replace(".", ","), z.get("eticheta_al_doilea", "")))
        if z.get("loc_an"):
            f.append((f"Anul {z['an_evidentiat']}", f"locul {z['loc_an']}", f"din {z['din']}"))
        if z.get("media") is not None:
            f.append(("Media", f"{z['media']:.1f} {um}".replace(".", ","), "a tuturor anilor"))
    elif rez and rez.get("mod") == "harta":
        if rez.get("ani_record"):
            a = rez["ani_record"][0]
            f.append(("Anul cu cele mai multe recorduri", str(a["an"]),
                      f"{100 * a['pixeli'] / max(rez.get('pixeli', 1), 1):.1f} % din pixeli".replace(".", ",")))
        if rez.get("procent_record_an") is not None:
            f.append((f"Anul {rez['an_evidentiat']}", f"{rez['procent_record_an']:.1f} %".replace(".", ","), "din pixeli au recordul atunci"))
    p = fisa.get("parametri", {})
    if p.get("ANI"):
        f.append(("Anii", f"{p['ANI'][0]}–{p['ANI'][1]}", ""))
    if p.get("PERIOADA"):
        f.append(("Perioada", f"{_data_ro(p['PERIOADA'][0])}", f"→ {_data_ro(p['PERIOADA'][1]) if p['PERIOADA'][1] else 'ultima zi cu date'}"))
    fr = fisa.get("frontiera_datelor") or {}
    if fr:
        f.append(("Date până la", _data_ro(min(fr.values())), "ultima zi din cub"))
    return f[:6]


def _zona(p):
    z = p.get("ZONA")
    if not isinstance(z, dict):
        return ""
    if z.get("tip") == "tara":
        return "România"
    if z.get("tip") == "poligoane":
        return ", ".join(map(str, z.get("valori") or [])) or f"zonele din {Path(str(z.get('fisier', ''))).name}"
    return z.get("nume") or z.get("tip", "")


def _metode(fisa):
    """Secțiunea „Date și metode”: paragraful RO / EN gata de copiat în lucrare, plus bibliografia (metode_text.py)."""
    m = fisa.get("metode")
    if not m:
        return ('<p class="cita">Date: Administrația Națională de Meteorologie (ANM / MeteoRomania), grilele zilnice '
                '<code>anm-daily-grids</code>, procesare UVT – EOCube.Ro, licența CC-BY-4.0. Analiza: programul Clima ANM.</p>')
    bloc = lambda i, et, t: (f'<div class="met"><div class="met-cap"><b>{et}</b>'
                             f'<button type="button" onclick="copiaza(\'m{i}\', this)">copiază</button></div>'
                             f'<p id="m{i}">{_e(t)}</p></div>')
    ref = "".join(f"<li>{_e(r)}</li>" for r in m.get("referinte", []))
    return (f"""<h2>Date și metode</h2>
<p class="ajutor">Paragraf descriptiv, gata de inclus în capitolul de date și metode al unei lucrări (completați
interpretarea). Același text, cu bibliografia, e în <a href="metode.md">metode.md</a>. Fiecare GeoTIFF are lângă el un
stil QGIS (<code>.qml</code>) cu culorile hărții: QGIS îl încarcă automat.</p>
{bloc(1, "Română", m.get("ro", ""))}{bloc(2, "English", m.get("en", ""))}
<div class="met"><div class="met-cap"><b>Bibliografie / References</b>
<button type="button" onclick="copiaza('m3', this)">copiază</button></div><ol id="m3" class="ref">{ref}</ol></div>
<script>
function copiaza(id, b){{
  const t = document.getElementById(id).innerText;
  const gata = () => {{ const v = b.textContent; b.textContent = "copiat ✓"; setTimeout(() => b.textContent = v, 1500); }};
  if (navigator.clipboard) navigator.clipboard.writeText(t).then(gata, () => alert(t)); else alert(t);
}}
</script>""")


def scrie_fisa(out: Path, fisa: dict) -> Path | None:
    """Scrie out/index.html. `fisa` = conținutul reproducere.json (finalizat)."""
    out = Path(out)
    if not out.is_dir():
        return None
    toate = sorted(f for f in out.rglob("*") if f.is_file() and f.name not in ("index.html",))
    png = [f for f in toate if f.suffix.lower() == ".png"]
    pref = _prefix_comun([f.name for f in toate if f.suffix.lower() in (".png", ".tif", ".csv")])
    harti = [f for f in png if f.name.endswith("_harta.png")]
    ordine = lambda f: (0 if "an_record" in f.name else 1 if f in harti else 2 if "clasament" in f.name else 3, f.name)  # noqa: E731
    png.sort(key=ordine)
    erou = png[0] if png else None
    rez = None
    for f in toate:
        if f.name.endswith("_rezumat.json"):
            try:
                rez = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    titlu = fisa.get("titlu") or "Rulare Clima ANM"
    p = fisa.get("parametri", {})
    zona = _zona(p)
    rel = lambda f: f.relative_to(out).as_posix()          # noqa: E731
    fapte = _fapte(rez, fisa)
    eroare = fisa.get("stare") == "eroare"

    dungi = "".join(f'<i style="background:{c}"></i>' for c in DUNGI)
    h = [f"""<!DOCTYPE html>
<html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(titlu)} · Clima ANM</title>
<style>
:root{{--ink:#1d2733;--slab:#5e6e7c;--linie:#dde3e8;--fond:#f3f5f7;--petrol:#0f6b8c;--petrol-i:#0b4f68;--hartie:#fff}}
*{{box-sizing:border-box}}
body{{margin:0;font:15px/1.55 "Segoe UI",Bahnschrift,system-ui,sans-serif;color:var(--ink);background:var(--fond)}}
header{{background:#1d2733;color:#eef2f5;padding:26px 40px 22px}}
header .prog{{font-size:13px;letter-spacing:.02em;color:#9fb0bf}}
header h1{{font:600 clamp(24px,3.4vw,38px)/1.15 Bahnschrift,"Segoe UI",system-ui,sans-serif;margin:6px 0 8px;max-width:30ch}}
header .zona{{font-size:16px;color:#cfd9e2}}
.dungi{{display:flex;height:10px}} .dungi i{{flex:1}}
main{{max-width:1180px;margin:0 auto;padding:28px 40px 60px}}
.erou{{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:28px;align-items:start}}
figure{{margin:0;background:var(--hartie);border:1px solid var(--linie);border-radius:10px;padding:10px}}
figure img{{width:100%;display:block;border-radius:6px}}
figcaption{{font-size:13px;color:var(--slab);padding:8px 4px 2px}}
.fapte{{display:flex;flex-direction:column;gap:2px}}
.fapt{{padding:12px 0;border-bottom:1px solid var(--linie)}}
.fapt b{{display:block;font:600 26px/1.15 Bahnschrift,"Segoe UI",sans-serif;color:var(--petrol-i)}}
.fapt span{{font-size:13px;color:var(--slab)}} .fapt em{{font-style:normal;font-size:13.5px}}
h2{{font:600 20px/1.2 Bahnschrift,"Segoe UI",sans-serif;margin:46px 0 14px}}
.cortina{{position:relative;max-width:900px;user-select:none;background:var(--hartie);border:1px solid var(--linie);border-radius:10px;overflow:hidden}}
.cortina img{{display:block;width:100%}}
.cortina .sus{{position:absolute;inset:0;clip-path:inset(0 50% 0 0)}}
.cortina .linie{{position:absolute;top:0;bottom:0;left:50%;width:2px;background:var(--petrol);pointer-events:none}}
.cortina .linie::after{{content:"⇆";position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--petrol);color:#fff;
  border-radius:50%;width:32px;height:32px;display:grid;place-items:center;font-size:15px}}
.cortina input{{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:ew-resize;margin:0}}
.alege{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;font-size:14px}}
select{{font:inherit;padding:5px 8px;border:1px solid var(--linie);border-radius:6px;background:#fff;max-width:420px}}
.galerie{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px}}
.galerie a{{color:inherit;text-decoration:none}}
table{{border-collapse:collapse;width:100%;background:var(--hartie);border:1px solid var(--linie);border-radius:10px;font-size:14px}}
td,th{{padding:7px 12px;border-bottom:1px solid var(--linie);text-align:left;vertical-align:top}}
th{{color:var(--slab);font-weight:600;width:30%}}
td a{{color:var(--petrol-i)}} code,pre{{font-family:Consolas,"Cascadia Mono",monospace;font-size:13px}}
pre{{background:#1d2733;color:#e4ebf0;padding:14px 16px;border-radius:8px;overflow:auto}}
.met{{background:var(--hartie);border-left:4px solid var(--petrol);border-radius:0 8px 8px 0;padding:10px 16px 12px;margin:0 0 12px}}
.met-cap{{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;font-size:13px}}
.met-cap button{{font:inherit;font-size:12px;border:1px solid #c9d3dc;background:#fff;border-radius:6px;padding:2px 10px;cursor:pointer}}
.met p{{margin:0;font-size:14.5px;line-height:1.55}}
.ref{{margin:0;padding-left:20px;font-size:13px;line-height:1.5}}
.ref li{{margin:3px 0}}
.ajutor{{color:#5b6875;font-size:13px}}
.buton-refa{{display:inline-block;background:var(--petrol);color:#fff;text-decoration:none;border-radius:6px;padding:5px 12px;font-weight:600}}
.cita{{background:var(--hartie);border-left:4px solid var(--petrol);padding:12px 16px;border-radius:0 8px 8px 0;font-size:14px}}
.eroare{{background:#fbe9e7;border:1px solid #f0b8ae;color:#8a2a1c;padding:12px 16px;border-radius:8px}}
footer{{color:var(--slab);font-size:12.5px;text-align:center;padding:24px}}
@media (max-width:860px){{.erou{{grid-template-columns:1fr}} header,main{{padding-left:18px;padding-right:18px}}}}
@media print{{body{{background:#fff}} .cortina,.alege,#comparatie{{display:none}} h2{{break-after:avoid}} figure{{break-inside:avoid}}}}
</style></head><body>
<header><div class="prog">Clima ANM · fișa rulării din {_e(_data_ro(fisa.get('pornit', '')))}</div>
<h1>{_e(titlu.split(' · ')[0])}</h1><div class="zona">{_e(zona)}{' · din rețeta „' + _e(fisa.get('reteta_titlu', '')) + '”' if fisa.get('reteta_titlu') and fisa.get('reteta_titlu') != titlu.split(' · ')[0] else ''}</div></header>
<div class="dungi" aria-hidden="true">{dungi}</div>
<main>"""]
    if eroare:
        h.append(f'<p class="eroare"><b>Rularea s-a oprit cu o eroare:</b> {_e(fisa.get("eroare", ""))}</p>')
    if fisa.get("avertisment_date"):
        h.append('<p class="eroare" style="background:#fff4e0;border-color:#f59f00;color:#7a4a00"><b>Date cu goluri.</b> '
                 + _e(fisa["avertisment_date"].replace("[atenție] ", "")) + '</p>')
    if erou or fapte:
        h.append('<section class="erou">')
        if erou:
            h.append(f'<figure><img src="{_e(rel(erou))}" alt="{_e(_uman(erou.name, pref))}"><figcaption>{_e(_uman(erou.name, pref))}</figcaption></figure>')
        h.append('<div class="fapte">' + "".join(
            f'<div class="fapt"><span>{_e(a)}</span><b>{_e(b)}</b><em>{_e(c)}</em></div>' for a, b, c in fapte) + "</div>")
        h.append("</section>")
    if len(harti) >= 2:
        opt = "".join(f'<option value="{_e(rel(f))}">{_e(_uman(f.name, pref))}</option>' for f in harti)
        h.append(f"""<section id="comparatie"><h2>Comparați două hărți</h2>
<div class="alege"><label>stânga <select id="ca">{opt}</select></label><label>dreapta <select id="cb">{opt}</select></label></div>
<div class="cortina" id="cort"><img id="ib" src="{_e(rel(harti[1]))}" alt=""><img class="sus" id="ia" src="{_e(rel(harti[0]))}" alt="">
<div class="linie" id="cl"></div><input type="range" min="0" max="100" value="50" id="cr" aria-label="poziția cortinei"></div>
<script>
(function(){{const a=document.getElementById("ia"),b=document.getElementById("ib"),r=document.getElementById("cr"),l=document.getElementById("cl"),
sa=document.getElementById("ca"),sb=document.getElementById("cb");sb.selectedIndex=1;
const m=()=>{{a.style.clipPath="inset(0 "+(100-r.value)+"% 0 0)";l.style.left=r.value+"%";}};
r.oninput=m;sa.onchange=()=>a.src=sa.value;sb.onchange=()=>b.src=sb.value;m();}})();
</script></section>""")
    rest = [f for f in png if f is not erou]
    if rest:
        h.append("<h2>Graficele și hărțile</h2><div class=\"galerie\">" + "".join(
            f'<a href="{_e(rel(f))}" target="_blank"><figure><img loading="lazy" src="{_e(rel(f))}" alt=""><figcaption>{_e(_uman(f.name, pref))}</figcaption></figure></a>'
            for f in rest) + "</div>")
    alte = [f for f in toate if f.suffix.lower() != ".png" and f.name != "reproducere.json"]
    if alte:
        h.append("<h2>Fișierele rulării</h2><table>" + "".join(
            f'<tr><th>{_e(TIPURI.get(f.suffix.lower(), f.suffix))}</th><td><a href="{_e(rel(f))}">{_e(rel(f))}</a> · {_mb(f.stat().st_size)}</td></tr>'
            for f in alte) + "</table>")
    rand_p = "".join(f"<tr><th>{_e(k)}</th><td>{_e(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)}</td></tr>"
                     for k, v in p.items() if not str(k).startswith("_") and v not in (None, "", [], {}))
    h.append(f"""<h2>Parametrii</h2><table>{rand_p}<tr><th>rețeta</th><td>{_e(fisa.get('reteta', ''))}</td></tr>
<tr><th>sursa datelor</th><td>{_e(fisa.get('sursa_datelor', ''))}</td></tr>
<tr><th>durata</th><td>{_e(str(fisa.get('durata_s', '–')).replace('.', ','))} s</td></tr></table>
<h2>Refacerea și citarea</h2>
<p id="refa-app" style="display:none"><a class="buton-refa" href="/?refa={_e(out.name)}">↻ Refă sau modifică analiza în Clima ANM</a>
(parametrii acestei rulări se încarcă în formular)</p>
<script>if (location.protocol.startsWith("http")) document.getElementById("refa-app").style.display = "";</script>
<p>Analiza se reface, într-un folder nou, din fișa de reproducere (<a href="reproducere.json">reproducere.json</a>).
În Clima ANM: pagina Start → „deschide o fișă de reproducere…”. Din linia de comandă:</p>
<pre>{_e(fisa.get('refacere', 'instrumente/pixi run python clima/ruleaza.py reproducere.json'))}</pre>
{_metode(fisa)}
</main><footer>Clima ANM · {_e(_data_ro(fisa.get('pornit', '')))} · <a href="jurnal.txt">jurnalul rulării</a></footer>
</body></html>""")
    f = out / "index.html"
    f.write_text("\n".join(h), encoding="utf-8")
    return f
