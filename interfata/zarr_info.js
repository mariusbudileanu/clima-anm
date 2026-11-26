// zarr_info.js — tabul „Zarr info”: teoria formatului Zarr pe cazul cubului anm-daily-grids (EOCube.ro), metadatele
// store-ului citite live, calculatorul cheii unui chunk și simulatorul 3D (interfata/zarr/simulator_zarr_anm.html).
"use strict";
const ZarrInfo = (() => {

let INFO = null;
const r = (x, d=2) => x == null || !isFinite(x) ? "–" : Number(x).toFixed(d).replace(".", ",");
const mii = n => Number(n).toLocaleString("ro-RO");

const SECTIUNI = [
["ce", "Ce este Zarr", `
<p><b>Zarr</b> este un format pentru tablouri mari, cu oricâte dimensiuni (timp × latitudine × longitudine × …), gândit pentru
stocarea în cloud. A fost creat în genomică (Alistair Miles, ~2015–2016) și a fost adoptat rapid în climatologie și
observarea Pământului (Pangeo, ESA, NASA). <b>OGC</b> l-a aprobat ca <i>Community Standard</i> în iunie 2022 (Zarr v2);
<b>Zarr v3</b> este specificația curentă a comunității.</p>
<p>Ideea se rezumă la trei reguli:</p>
<ol>
<li><b>Divide</b>: tabloul se taie în blocuri de dimensiune fixă, numite <i>chunk-uri</i>. La cubul ANM: 90 de zile × 161 × 324 pixeli.</li>
<li><b>Comprimă</b>: fiecare chunk se comprimă separat (aici Blosc + LZ4 + byte-shuffle).</li>
<li><b>Adresează direct</b>: fiecare chunk e un obiect separat în object storage, iar numele lui este chiar poziția în grila de chunk-uri
(ex. <code>max_temp/266.2.1</code>). Toate metadatele stau într-un singur fișier JSON, <code>.zmetadata</code>.</li>
</ol>
<p>Consecința: nu există un index de căutat pe server. Cine știe data și coordonatele <b>calculează</b> numele obiectului
cu trei împărțiri întregi și îl cere direct (vezi calculatorul de mai jos). Prețul: pentru o singură valoare dintr-un chunk,
se descarcă și se decomprimă chunk-ul întreg.</p>`],

["cub", "Cubul de date", `
<p>În loc de „hărți plate în sertare separate” (un GeoTIFF pe zi), avem <b>un singur tablou 3D</b> pe variabilă, cu
dimensiunile <code>(time, y, x)</code>. Cubul poate fi tăiat în două feluri:</p>
<ul>
<li><b>orizontal</b>: harta unei zile (toți pixelii, o zi);</li>
<li><b>vertical</b>: seria de timp a unui loc (un pixel, toate zilele): ca un ac înfipt prin toți anii.</li>
</ul>
<p>Tot ce urmează se învârte în jurul acestor două tăieturi: un store Zarr <b>nu le poate face pe amândouă la fel de ieftin</b>.
Forma chunk-urilor decide care dintre ele e rapidă.</p>`],

["live", "Store-ul, citit acum", `<div id="zi-live"><p class="ajutor">Se citesc metadatele store-ului…</p></div>`],

["comparatie", "Zarr, GeoTIFF sau NetCDF?", `
<table class="doc-tabel">
<tr><th></th><th>Un GeoTIFF / COG pe zi</th><th>Un fișier NetCDF4 / HDF5</th><th>Zarr</th></tr>
<tr><td>Fișiere</td><td>3 × ~24.000 de fișiere</td><td>unul singur, mare</td><td>~10.000 de obiecte + 1 JSON cu metadatele</td></tr>
<tr><td>Harta unei zile</td><td>excelent (un fișier)</td><td>bine local; peste HTTP, multe cereri mici</td><td>9 obiecte, ~3 s</td></tr>
<tr><td>Seria unui punct</td><td>24.000 de fișiere deschise</td><td>depinde de chunk-urile interne</td><td>depinde de chunk-uri (aici: lentă)</td></tr>
<tr><td>Zile noi</td><td>un fișier nou</td><td>rescrierea fișierului / a unor blocuri</td><td>se rescriu doar chunk-urile curente</td></tr>
<tr><td>Metadate</td><td>în fiecare fișier</td><td>răspândite în fișier (arbore B)</td><td>toate într-un JSON (<code>.zmetadata</code>)</td></tr>
</table>
<p><b>NetCDF nu e un format „rău”</b>: a fost proiectat pentru discul local, unde o citire în plus costă microsecunde. Peste internet,
fiecare citire în plus costă zeci de milisecunde. Zarr nu e mai rapid pentru că ar comprima mai bine, ci pentru că
<b>reduce numărul de călătorii dus-întors prin rețea</b>. Cale de mijloc: <i>kerchunk / VirtualiZarr</i> construiesc un „index Zarr”
peste fișiere NetCDF existente, fără conversie.</p>`],

["chunkuri", "Geometria chunk-urilor", `
<p>Chunk-ul <code>[90, 161, 324]</code> împarte grila spațială exact: 483 / 3 = 161 rânduri și 972 / 3 = 324 coloane, deci
<b>9 sectoare</b> de ~179 × 250 km. Pe timp, 90 de zile pe bucată.</p>
<p><b>Atenție: 90 de zile nu înseamnă un trimestru.</b> Granițele chunk-urilor alunecă față de calendar (un trimestru are ~91,3 zile),
deci un sezon de vară (92 de zile) atinge <b>întotdeauna cel puțin 2 chunk-uri de timp</b>.</p>
<p>Un chunk are 90 × 161 × 324 = 4.694.760 de valori float32, adică <b>18,8 MB necomprimat</b>. Comprimat, între ~2,8 MB
(sector cu mult „în afara țării”, NaN) și ~9,4 MB (sectorul central, plin de date). <b>Compresia depinde de date, nu de format</b>:
se comprimă bine NaN-urile și zilele fără ploaie (0,0), nu temperaturile.</p>
<p class="ajutor">Valorile comprimate sunt măsurate pe store-ul real la 2026-10-16 (suportul de curs, anexa A).</p>`],

["cheie", "Calculatorul cheii unui chunk", `
<p>Cum găsește programul obiectul de descărcat, fără să caute nimic pe server: indicii în grilă, apoi împărțire întreagă la mărimea chunk-ului.</p>
<div class="rand" style="margin:8px 0">
  lon <input type="number" id="zi-lon" step="0.0001" value="26.1025" style="width:110px">
  lat <input type="number" id="zi-lat" step="0.0001" value="44.4268" style="width:110px">
  data <input type="date" id="zi-data" value="2026-10-15">
  variabila <select id="zi-var"><option value="max_temp">max_temp</option><option value="min_temp">min_temp</option><option value="precipitation">precipitation</option></select>
</div>
<div id="zi-cheie" class="calc-rez"></div>`],

["cost", "Hartă sau serie: costul unei citiri", `
<table class="doc-tabel">
<tr><th>Interogare (cubul real, max_temp)</th><th>Obiecte</th><th>Transfer</th><th>Timp măsurat</th><th>Amplificare</th></tr>
<tr><td>A. Harta națională, o zi</td><td>9</td><td>~49 MB</td><td>2,8 s</td><td>~90×</td></tr>
<tr><td>B. Un sector, o vară</td><td>2 × 1</td><td>~12 MB</td><td>0,9 s</td><td>~2×</td></tr>
<tr><td>C. Seria unui pixel, 1961 → azi</td><td>267</td><td>~1,6 GB</td><td>148 s</td><td><b>~52.000×</b></td></tr>
</table>
<p><i>Amplificare</i> = valori decomprimate / valori de care avem nevoie. Pentru seria unui singur pixel (~24.000 de numere) se decomprimă
peste un miliard de numere. Nu e o eroare: este consecința directă a formei <code>[90, 161, 324]</code>, <b>optimizată pentru hărți</b>.</p>
<p>Alte forme posibile ale aceluiași cub (volume necomprimate de citit):</p>
<table class="doc-tabel">
<tr><th>Chunk</th><th>Serie un pixel</th><th>Harta unei zile</th></tr>
<tr><td><b>[90, 161, 324]</b> (actual)</td><td>267 obiecte · 5,0 GB</td><td><b>9 obiecte · 169 MB</b></td></tr>
<tr><td>[3650, 32, 32] (compromis)</td><td>7 obiecte · 105 MB</td><td>496 obiecte · 7,4 GB</td></tr>
<tr><td>[32872, 16, 16] („serie de timp”)</td><td><b>1 obiect · 34 MB</b></td><td>1.891 obiecte · 63,7 GB</td></tr>
</table>
<p><b>Nu există o formă universală.</b> Practica Pangeo: două copii ale cubului (una pentru hărți, una pentru serii) sau
<i>rechunking</i> local pe zona de interes. Programul face a doua variantă automat: seriile citite o dată (analiza episodului,
dungile, seriile pe zone) rămân în <code>rezultate/cache_serii</code>, iar rulările următoare durează secunde.
Butonul „Verifică parametrii” calculează exact acest cost înainte de rulare.</p>`],

["capcane", "Capcanele acestui cub", `
<ol>
<li><b>Pre-alocarea până în 2050.</b> Axa timpului merge până la 2050-12-31, iar <b>toate</b> chunk-urile există fizic, cele din viitor
umplute cu <b>0,0, nu NaN</b>. De ce nu NaN? <code>fill_value: NaN</code> se aplică doar chunk-urilor <i>lipsă</i>, iar acestea au fost scrise
cu zerouri. Media Tmax la București pe 1961 → 2050, fără filtru, iese ~13,0 °C în loc de ~17,8 °C: <b>o eroare de aproape 5 grade,
fără niciun avertisment</b>.</li>
<li><b>Soluția: <code>last_*_time</code>.</b> Trei scalari marchează ultima zi validă, pe variabilă (pot fi diferite!). La combinații
(Tmax − Tmin) se folosește frontiera comună, minimul. La precipitații, 0,0 e o valoare validă: frontiera <b>nu</b> se poate deduce din date.
Programul aplică acest filtru peste tot.</li>
<li><b>Axa y e descrescătoare</b> (nordul primul). <code>y=slice(44, 46)</code> întoarce <b>0 pixeli, fără eroare</b>;
corect: <code>slice(46, 44)</code>. Verificați mereu <code>.sizes</code> după o tăietură.</li>
<li><b>Catalogul STAC poate rămâne în urmă</b> față de date (la 2026-10-16 era în urmă cu o lună). Frontiera se citește din store, nu din catalog.</li>
<li><b>Goluri interne.</b> Unele sectoare au NaN între 2026-04-20 și 2026-05-12/13; golul depinde de obiect (sector × variabilă).
Pragul de validitate al programului (90 %) exclude pixelii afectați în loc să producă medii false.</li>
<li><b>Rezoluția grilei ≠ rezoluția informației.</b> Pasul e 0,01° (~1 km), dar datele sunt interpolate din stații și cuantizate la 0,1 °C.
Pentru parcele sau cartiere, rezoluția e nominală, nu reală.</li>
</ol>`],

["relief", "Relieful pe aceeași grilă (DEM)", `
<p>Ca să comparăm clima cu relieful pixel cu pixel, altitudinea trebuie să stea <b>pe exact aceeași grilă</b> ca datele climatice.
Programul folosește <b>Copernicus DEM GLO-30</b> (pas 1″ ≈ 30 m), adus o singură dată pe grila cubului cu
<code>instrumente/pregateste_dem.py</code>. Rezultatul, <code>date/dem_grila_zarr.tif</code>, are 972 × 483 pixeli, ca și cubul.</p>
<p><b>Aceeași proiecție nu înseamnă aceeași grilă.</b> Ambele sunt în EPSG:4326, iar 0,01° = 36″, deci un pixel Zarr cuprinde
36 × 36 de pixeli DEM. Dar tile-urile Copernicus au <b>centrele</b> pixelilor pe secunde întregi (originea unui tile e la −0,5″
de gradul întreg), iar marginile pixelilor Zarr cad la multipli de 36″. Marginile Zarr trec deci <b>prin mijlocul</b> unor pixeli DEM:</p>
<table class="doc-tabel"><tr><th>pixelii DEM de-a lungul unui pixel Zarr</th><td>½ · 1 · 1 · … (35 întregi) … · 1 · ½</td></tr>
<tr><th>media corectă</th><td>ponderată cu <b>aria comună</b>: pixelii tăiați de margine contează pe jumătate (la colțuri, un sfert)</td></tr></table>
<p>Un „resample” fără ponderi ar lua 36 sau 37 de pixeli și ar deplasa media cu o jumătate de pixel DEM. Scriptul calculează ponderile
din geometria reală, deci funcționează oricare ar fi decalajul.</p>
<p><b>Ordinea operațiilor contează.</b> Panta se calculează pe DEM-ul de 30 m și <b>abia apoi</b> se mediază pe pixelul Zarr.
Invers, din altitudinea deja mediată la 1 km, relieful fin dispare înainte de derivare și panta iese mult subestimată.
Regula generală: <i>o mărime neliniară (panta, abaterea standard, un prag) se calculează la rezoluția fină și apoi se agregă</i>.</p>
<p><b>Ce înseamnă „altitudinea pixelului”.</b> Media pe ~1 km². Cel mai înalt pixel al țării e în <b>Bucegi</b> (platoul Omu, medie
2398 m), nu în Făgăraș: platoul e larg și înalt, pe când creasta Făgărașului e îngustă, iar pixelii ei cuprind și versanții.
Vârfurile ascuțite ies cu 8–27 m sub altitudinea reală în banda „maximă” (o celulă de 30 m nu nimerește chiar vârful).</p>
<p><b>DSM, nu DTM.</b> Copernicus DEM este un model al <i>suprafeței</i>: include pădurea și clădirile. Pentru altitudinea medie
eroarea e mică (10–25 m în păduri), dar panta și abaterea standard cresc artificial pe câmpie:</p>
<table class="doc-tabel"><tr><th>zona</th><th>panta medie</th><th>abaterea standard</th></tr>
<tr><td>Bărăgan, câmp agricol</td><td>0,6°</td><td>1,4 m</td></tr><tr><td>Câmpia Banatului</td><td>0,5°</td><td>0,5 m</td></tr>
<tr><td>Codrii Vlăsiei, pădure</td><td>2,7°</td><td>5,6 m</td></tr><tr><td>București, centru</td><td>3,9°</td><td>4,1 m</td></tr></table>
<p>Folosiți deci altitudinea pentru analize; panta, doar la deal și la munte.</p>
<p><b>O capcană întâlnită chiar la construirea acestui fișier.</b> Ca verificare, media a fost refăcută independent cu
<code>gdal.Warp(resampleAlg="average")</code>. Prima comparație a dat diferențe de până la 8 m. Cauza: COG-urile Copernicus au
<i>prezentări generale</i> (overviews) interne, iar GDAL le folosește <b>implicit</b> la micșorare, deci media venea dintr-o versiune
deja micșorată a DEM-ului. Cu <code>overviewLevel="NONE"</code> diferența a scăzut la 0,0001 m. Lecția: un COG nu e „un raster”,
ci o piramidă de rastere, iar instrumentele aleg singure nivelul dacă nu le spuneți.</p>
<p>În program: <b>filtrul de altitudine</b> din caseta „Zona analizei” (orice rețetă) și rețeta <b>19, „Indicatorul față de altitudine”</b>
(gradientul pe 100 m, media pe trepte, harta reziduului).</p>
<p class="ajutor">DEM: Copernicus DEM GLO-30, © DLR e.V. 2010–2014 și © Airbus Defence and Space GmbH 2014–2018, furnizat în cadrul
programului Copernicus; tile-urile, prin EOCube.ro (copernicus-dem-30).</p>`],

["simulator", "Simulatorul 3D", `
<p>Simulatorul arată cubul și chunk-urile lui, cât costă fiecare tip de citire (hartă, sezon, serie), cele trei forme de chunk (A/B/C)
și capcana zerourilor din viitor. Se folosește cu mouse-ul; are și un mod de prezentare.</p>
<div class="rand" style="margin-bottom:8px"><a class="leg" href="/zarr/simulator_zarr_anm.html" target="_blank">deschide pe tot ecranul ↗</a></div>
<iframe class="simulator" src="/zarr/simulator_zarr_anm.html" title="Simulatorul Zarr" loading="lazy"></iframe>`],

["cod", "Cum se deschide în Python", `
<pre class="cod">import fsspec, xarray as xr

URL = "https://storage.svc.uvt-01.eocube.ro/meteo/cube/open-v1"
cub = xr.open_zarr(fsspec.get_mapper(URL), consolidated=True, decode_coords="all")

# 1) frontiera comună (OBLIGATORIU: după ea, zilele conțin 0,0)
VARS = ["max_temp", "min_temp", "precipitation"]
ultima = min(cub[f"last_{v}_time"].values for v in VARS)

# 2) tăiați întâi în timp și spațiu (y descrescător!), abia apoi calculați
vara = cub["max_temp"].sel(time=slice("2025-06-01", "2025-08-31"),
                           y=slice(45.0, 44.0), x=slice(25.5, 27.0))
print(vara.sizes)                      # verificați că nu e gol
medie = vara.mean("time").compute()    # abia acum se descarcă datele</pre>
<p>Același lucru, pentru orice analiză din program: butonul <b>„Exportă Python”</b> scrie scriptul complet, gata de rulat.</p>`],

["surse", "Atribuire și lecturi", `
<ul>
<li>Date: <b>ANM / MeteoRomania</b>, procesare: <b>UVT – EOCube.Ro</b>, licență <b>CC-BY-4.0</b>.</li>
<li>Documentația platformei: docs.eocube.ro · catalogul STAC: browser.stac.eocube.ro (API: stac.eocube.ro).</li>
<li>Specificația Zarr: zarr.dev · standardul OGC Zarr v2 (2022) · GeoZarr (în lucru, OGC).</li>
</ul>`],
];

function construieste(){
  const v = $("#v-zarr"); v.innerHTML = "";
  const meniu = el("aside",{class:"panou doc-meniu"}, el("h3",{text:"Zarr: cuprins"}),
    SECTIUNI.map(([id, t]) => el("button",{class:"an",text:t,onclick:()=>document.getElementById("zs-"+id).scrollIntoView({behavior:"smooth"})})));
  const pagina = el("section",{class:"panou doc-pagina zarr-pagina"});
  pagina.append(el("h2",{text:"Formatul Zarr, pe cubul anm-daily-grids"}),
    el("p",{class:"descriere",text:"Datele tuturor analizelor din program vin dintr-un singur store Zarr: temperaturile maxime, minime și precipitațiile zilnice ale României, 1961 – ieri, pe o grilă de 0,01°."}));
  for (const [id, t, h] of SECTIUNI){
    const s = el("section",{class:"ind-sect",id:"zs-"+id}, el("h3",{text:t})); const c = el("div"); c.innerHTML = h; s.append(c); pagina.append(s);
  }
  v.append(meniu, pagina);
  ["zi-lon","zi-lat","zi-data","zi-var"].forEach(i => $("#"+i).addEventListener("input", cheie));
  cheie(); incarcaLive();
}

async function incarcaLive(forteaza){
  const d = $("#zi-live"); if (!d) return;
  INFO = await api("/api/zarr_info" + (forteaza ? "?reincearca=1" : ""));
  if (INFO.stare === "se verifică" || INFO.stare === "necunoscut"){ setTimeout(()=>incarcaLive(false), 2500); return; }
  d.innerHTML = "";
  if (!INFO.ok){
    d.append(el("p",{class:"ajutor",text:`Store-ul nu poate fi citit acum (${INFO.eroare || "fără răspuns"}). Restul paginii e valabil; reîncercați când sunteți online.`}),
             el("a",{class:"leg",text:"↻ reîncearcă",onclick:()=>{ d.innerHTML = '<p class="ajutor">Se citesc metadatele…</p>'; incarcaLive(true); }}));
    return;
  }
  const t = INFO.timp, mt = INFO.variabile.max_temp;
  if (INFO.test) d.append(el("p",{class:"avert",text:"Atenție: programul citește acum CUBUL SINTETIC DE TEST (valori inventate), nu store-ul EOCube."}));
  d.append(el("p",{}, "Metadatele de mai jos sunt citite ", el("b",{text:"chiar acum"}), ` din `, el("code",{text:INFO.sursa}),
    ` (prima deschidere: ${r(INFO.secunde_deschidere,1)} s, inclusiv încărcarea bibliotecilor; nu se descarcă date).`));
  const rand = (a, b) => el("tr",{}, el("td",{text:a}), el("td",{}, b));
  const tab = el("table",{class:"doc-tabel"},
    rand("Timp", `${t.n_zile.toLocaleString("ro-RO")} zile alocate: ${t.inceput} → ${t.sfarsit_alocat} · ${t.units} · ${t.calendar}`),
    rand("Grila", `${INFO.y.n} rânduri × ${INFO.x.n} coloane · pas ${r(INFO.y.pas,3)}° · x ${r(INFO.x.min,3)}…${r(INFO.x.max,3)} · y ${r(INFO.y.prim,3)} → ${r(INFO.y.ultim,3)} ` + (INFO.y.descrescator ? "(descrescător: nordul primul)" : "")),
    rand("Chunk", `[${mt.chunks.join(", ")}] → grilă de ${mt.grila_chunk.join(" × ")} = ${mii(mt.n_chunk)} chunk-uri pe variabilă · ${r(mt.mb_chunk_necomprimat,1)} MB necomprimat fiecare`),
    rand("Tip, compresie", `${mt.dtype} · ${mt.compresor} · fill_value ${mt.fill_value}`),
    rand("Volum necomprimat", `${r(mt.gb_necomprimat,1)} GB pe variabilă · ${r(mt.gb_necomprimat*3,1)} GB în total`));
  const fr = el("table",{class:"doc-tabel"}, el("tr",{}, el("th",{text:"Variabila"}), el("th",{text:"Unitatea"}), el("th",{text:"Frontiera (last_*_time)"}), el("th",{text:"Zile cu date"})));
  for (const [k, v] of Object.entries(INFO.variabile)){
    const n = Math.round((new Date(v.frontiera) - new Date(t.inceput))/864e5) + 1;
    fr.append(el("tr",{}, el("td",{},el("code",{text:k})), el("td",{text:v.units}), el("td",{text:v.frontiera}), el("td",{text:`${mii(n)} din ${mii(t.n_zile)} (${r(100*n/t.n_zile,0)} %)`})));
  }
  d.append(tab, el("p",{class:"ajutor",text:"Frontiera fiecărei variabile: după ea, zilele sunt pre-alocate și conțin 0,0."}), fr);
  cheie(); trimiteFrontiere();
}

// Simulatorul din iframe are o frontieră fixă (data generării lui); îi trimitem frontierele citite acum.
function trimiteFrontiere(){
  if (!INFO?.ok) return;
  const f = Object.fromEntries(Object.entries(INFO.variabile).map(([k, v]) => [k, v.frontiera]));
  document.querySelectorAll("iframe.simulator").forEach(fr => fr.contentWindow?.postMessage({tip:"frontiere", frontiere:f}, location.origin));
}
window.addEventListener("message", e => { if (e.origin === location.origin && e.data?.tip === "cere_frontiere") trimiteFrontiere(); });

function cheie(){
  const out = $("#zi-cheie"); if (!out) return;
  const lon = num($("#zi-lon").value), lat = num($("#zi-lat").value), data = $("#zi-data").value, v = $("#zi-var").value;
  const t0 = INFO?.ok ? INFO.timp.inceput : "1961-01-01", ch = INFO?.ok ? INFO.variabile[v].chunks : [90, 161, 324];
  const x0 = INFO?.ok ? INFO.x.min - INFO.x.pas/2 : 20.13, y0 = INFO?.ok ? INFO.y.prim + INFO.y.pas/2 : 48.36;
  const nx = INFO?.ok ? INFO.x.n : 972, ny = INFO?.ok ? INFO.y.n : 483, pas = 0.01;
  if (lon == null || lat == null || !data){ out.textContent = ""; return; }
  const it = Math.round((new Date(data) - new Date(t0))/864e5), iy = Math.floor((y0 - lat)/pas), ix = Math.floor((lon - x0)/pas);
  out.innerHTML = "";
  if (iy < 0 || iy >= ny || ix < 0 || ix >= nx || it < 0){ out.append(el("p",{class:"avert",text:"Punctul sau data sunt în afara cubului."})); return; }
  const ct = Math.floor(it/ch[0]), cy = Math.floor(iy/ch[1]), cx = Math.floor(ix/ch[2]);
  const z0 = new Date(new Date(t0).getTime() + ct*ch[0]*864e5), z1 = new Date(z0.getTime() + (ch[0]-1)*864e5);
  const f = d => d.toISOString().slice(0,10);
  out.append(el("ol",{class:"pasi-mici"},
    el("li",{}, `indicele zilei: ${data} − ${t0} = `, el("b",{text:mii(it)}), " zile"),
    el("li",{}, `rândul: ⌊(${r(y0,2)} − ${r(lat,4)}) / 0,01⌋ = `, el("b",{text:iy}), ` · coloana: ⌊(${r(lon,4)} − ${r(x0,2)}) / 0,01⌋ = `, el("b",{text:ix})),
    el("li",{}, `împărțire întreagă la chunk-ul [${ch.join(", ")}]: ⌊${it}/${ch[0]}⌋ = ${ct} · ⌊${iy}/${ch[1]}⌋ = ${cy} · ⌊${ix}/${ch[2]}⌋ = ${cx}`)),
    el("div",{class:"calc-valoare"}, "Cheia obiectului: ", el("code",{class:"cheie",text:`${v}/${ct}.${cy}.${cx}`})),
    el("div",{class:"ajutor",text:`Acest obiect conține zilele ${f(z0)} → ${f(z1)} pentru sectorul (${cy}, ${cx}) din cele 9. Pentru valoarea unui singur pixel se descarcă tot obiectul.`}));
}

return {construieste};
})();
