// indicatori.js — tabul „Indicatori”: fișele teoretice (din clima/teorie_indicatori.py), codul Python real al fiecărei
// funcții și un calculator didactic pe 14 zile, care reproduce în JavaScript exact formula din cod.
"use strict";
const Indicatori = (() => {

// ------------------------------------------------------------------ seria didactică (editabilă)
const SERIE_IMPLICITA = {
  zile: ["24 iul","25 iul","26 iul","27 iul","28 iul","29 iul","30 iul","31 iul","1 aug","2 aug","3 aug","4 aug","5 aug","6 aug"],
  max_temp: [31.2,33.5,35.8,36.4,34.1,29.0,26.3,27.8,30.5,32.0,28.4,24.9,25.6,29.7],
  min_temp: [18.4,19.9,21.3,22.0,20.6,17.2,15.1,15.8,17.9,19.0,16.5,14.2,13.8,16.9],
  precipitation: [0,0,0,0,4.2,18.6,7.3,0,0,0.4,12.1,25.8,3.0,0],
};
let SERIE = JSON.parse(JSON.stringify(SERIE_IMPLICITA)), ACTIV_IND = null, CAUTA = "";
const NUME_VAR = {max_temp:"Tmax (°C)", min_temp:"Tmin (°C)", precipitation:"P (mm)"};
const r1 = (x, d=1) => x == null || !isFinite(x) ? "–" : Number(x).toFixed(d).replace(".", ",").replace("-", "−");

// Fiecare calcul întoarce {valoare, unitate, marcate:[indici de zile], detaliu:[text pe zi], explicatie}.
// O celulă goală = zi lipsă (null în JavaScript, NaN în Python); fiecare formulă o tratează EXACT ca funcția Python:
// media o ignoră (np.nanmean), suma o ia drept 0 (np.nansum), numărarea n-o numără (NaN ≥ prag e fals), CDD rupe șirul.
const ok = x => x != null && isFinite(x);
const val = v => v.filter(ok);
const med = v => { const a = val(v); return a.length ? a.reduce((x,y)=>x+y,0)/a.length : NaN; };
const sum = v => val(v).reduce((x,y)=>x+y,0);
const nl = v => { const k = v.filter(x => !ok(x)).length; return k ? ` · ${k} ${k===1?"zi lipsă":"zile lipsă"}` : ""; };
const T2 = (s, f) => s.max_temp.map((x,i) => ok(x) && ok(s.min_temp[i]) ? f(x, s.min_temp[i]) : null);   // NaN dacă oricare lipsește
const CALC = {
  medie: (s, p) => { const v = s[p.var], a = val(v);
                     return {valoare: med(v), unitate: p.var==="precipitation"?"mm/zi":"°C",
                             explicatie: `suma celor ${a.length} valori existente / ${a.length} (zilele lipsă sunt ignorate, ca np.nanmean)`}; },
  tmedie: s => { const t = T2(s, (a,b)=>(a+b)/2);
                 return {valoare: med(t), unitate:"°C", detaliu: t.map(x=>r1(x)), explicatie:"media valorilor (Tmax + Tmin)/2 din rândul de jos; o zi cu Tmax sau Tmin lipsă nu intră în medie"}; },
  suma: (s, p) => { const v = s[p.var];
                    return {valoare: val(v).length ? sum(v) : NaN, unitate: p.var==="precipitation"?"mm":"",
                            explicatie:`${v.map(x=>ok(x)?r1(x):"0 (lipsă)").join(" + ")} · zilele lipsă contează 0 (np.nansum)`}; },
  zile_peste: (s, p) => { const m = []; s[p.var].forEach((x,i)=>{ if (ok(x) && (p.strict ? x > p.prag : x >= p.prag)) m.push(i); });
                          return {valoare: m.length, unitate:"zile", marcate:m, var:p.var, explicatie:`zilele marcate au ${NUME_VAR[p.var].split(" ")[0]} ${p.strict?">":"≥"} ${r1(p.prag)}${nl(s[p.var])}${nl(s[p.var]) ? " (nu se numără)" : ""}`}; },
  zile_sub: (s, p) => { const m = []; s[p.var].forEach((x,i)=>{ if (ok(x) && (p.strict ? x < p.prag : x <= p.prag)) m.push(i); });
                        return {valoare: m.length, unitate:"zile", marcate:m, var:p.var, explicatie:`zilele marcate au ${NUME_VAR[p.var].split(" ")[0]} ${p.strict?"<":"≤"} ${r1(p.prag)}${nl(s[p.var])}${nl(s[p.var]) ? " (nu se numără)" : ""}`}; },
  amplitudine_medie: s => { const a = T2(s, (x,y)=>x-y);
                            return {valoare: med(a), unitate:"°C", detaliu:a.map(x=>r1(x)), explicatie:"media diferențelor Tmax − Tmin din rândul de jos (zilele incomplete sunt ignorate)"}; },
  amplitudine_absoluta: s => { const X = val(s.max_temp), N = val(s.min_temp);
                               if (!X.length || !N.length) return {valoare: NaN, unitate:"°C", explicatie:"nicio valoare existentă"};
                               const mx = Math.max(...X), mn = Math.min(...N);
                               return {valoare: mx - mn, unitate:"°C", marcate:[s.max_temp.indexOf(mx), s.min_temp.indexOf(mn)],
                                       explicatie:`max(Tmax) = ${r1(mx)} − min(Tmin) = ${r1(mn)} (np.nanmax / np.nanmin ignoră zilele lipsă)`}; },
  gdd: (s, p) => { const g = T2(s, (a,b)=>Math.max((a+b)/2 - p.baza, 0));
                   return {valoare: sum(g), unitate:"°C·zile", detaliu:g.map(x=>r1(x)), explicatie:`suma contribuțiilor max(Tmed − ${r1(p.baza)}, 0) din rândul de jos; o zi lipsă contribuie cu 0`}; },
  cdd: (s, p) => { let cur = 0, best = 0, fin = -1;
                   s.precipitation.forEach((x,i)=>{ cur = ok(x) && x < p.prag ? cur + 1 : 0; if (cur > best){ best = cur; fin = i; } });
                   const m = []; for (let i = fin - best + 1; i <= fin; i++) m.push(i);
                   return {valoare: best, unitate:"zile", marcate:m, var:"precipitation", explicatie:`cel mai lung șir de zile cu P < ${r1(p.prag)} mm (marcat)${nl(s.precipitation)}${nl(s.precipitation) ? ": o zi lipsă rupe șirul, ca o zi ploioasă" : ""}`}; },
  cwd: (s, p) => { let cur = 0, best = 0, fin = -1;
                   s.precipitation.forEach((x,i)=>{ cur = ok(x) && x >= p.prag ? cur + 1 : 0; if (cur > best){ best = cur; fin = i; } });
                   const m = []; for (let i = fin - best + 1; i <= fin; i++) m.push(i);
                   return {valoare: best, unitate:"zile", marcate:m, var:"precipitation", explicatie:`cel mai lung șir de zile cu P ≥ ${r1(p.prag)} mm (marcat)${nl(s.precipitation)}${nl(s.precipitation) ? ": o zi lipsă rupe șirul" : ""}`}; },
  sdii: (s, p) => { const m = []; let sum_ = 0; s.precipitation.forEach((x,i)=>{ if (ok(x) && x >= p.prag){ m.push(i); sum_ += x; } });
                    return m.length ? {valoare: sum_/m.length, unitate:"mm/zi", marcate:m, var:"precipitation", explicatie:`${r1(sum_)} mm în ${m.length} zile ploioase (marcate) → ${r1(sum_)} / ${m.length}`}
                                    : {valoare: NaN, unitate:"mm/zi", explicatie:`nicio zi cu P ≥ ${r1(p.prag)} mm: SDII este nedefinit (NoData), nu 0`}; },
  prcptot: (s, p) => { const m = []; let sum_ = 0; s.precipitation.forEach((x,i)=>{ if (ok(x) && x >= p.prag){ m.push(i); sum_ += x; } });
                       const tot = sum(s.precipitation);
                       return {valoare: sum_, unitate:"mm", marcate:m, var:"precipitation", explicatie:`suma zilelor marcate (P ≥ ${r1(p.prag)} mm); suma tuturor zilelor ar fi ${r1(tot)} mm, diferența ${r1(tot - sum_)} mm sunt urme`}; },
  rxnday: (s, p) => { const P = s.precipitation.map(x => ok(x) ? x : 0), n = p.n; let best = -Infinity, z0 = 0;
                      if (!Number.isInteger(n) || n < 1 || n > 30) return {valoare:NaN, unitate:"mm", explicatie:"Alegeți un număr întreg între 1 și 30."};
                      if (n > P.length) return {valoare:NaN, unitate:"mm", explicatie:"Seria este mai scurtă decât fereastra."};
                      for (let i = 0; i + n <= P.length; i++){ const v = P.slice(i, i+n).reduce((a,b)=>a+b,0); if (v > best){ best = v; z0 = i; } }
                      const m = []; for (let i = z0; i < z0 + n && i < P.length; i++) m.push(i);
                      return {valoare: best, unitate:"mm", marcate:m, var:"precipitation", explicatie:`fereastra de ${n} ${n===1?"zi":"zile"} cu suma maximă (marcată)${nl(s.precipitation)}${nl(s.precipitation) ? " (zilele lipsă = 0 mm)" : ""}`}; },
  de_martonne: s => { const idx = s.precipitation.map((x,i)=>i).filter(i => ok(s.precipitation[i]) && ok(s.max_temp[i]) && ok(s.min_temp[i]));
                      const n = idx.length; if (!n) return {valoare: NaN, unitate:"", explicatie:"nicio zi cu toate cele trei valori"};
                      const Ps = idx.reduce((a,i)=>a + s.precipitation[i], 0), Pan = Ps*365.25/n;
                      const T = idx.reduce((a,i)=>a + (s.max_temp[i] + s.min_temp[i])/2, 0)/n;
                      if (T <= -10) return {valoare: NaN, unitate:"", explicatie:`T = ${r1(T)} °C ≤ −10 °C: numitorul T + 10 este ≤ 0, indicele nu are sens → NoData.`};
                      return {valoare: Pan/(T + 10), unitate:"", explicatie:`P_an = ${r1(Ps)} mm × 365,25 / ${n} zile comune = ${r1(Pan,0)} mm; T = ${r1(T)} °C; I = ${r1(Pan,0)} / (${r1(T)} + 10). Atenție: pe 14 zile de vară, „anualizarea” e doar ilustrativă.`}; },
  // ---- indicatori cu perioadă de bază: pragurile zilei sunt ILUSTRATIVE (în program se calculează pe pixel, din bază)
  pct_zile: (s, p) => { const [v, sens] = PCT_DEF[p.indice], thr = PRAG_ILUSTR[p.indice], m = []; let n = 0;
                        s[v].forEach((x, i) => { if (!ok(x)) return; n++; if (sens === "peste" ? x > thr[i] : x < thr[i]) m.push(i); });
                        return n ? {valoare: 100*m.length/n, unitate:"% din zile", marcate:m, var:v, detaliu:thr.map(x=>r1(x)),
                                    explicatie:`${m.length} din ${n} zile cu date ${sens==="peste"?"depășesc":"coboară sub"} pragul zilei lor (rândul „pe zi”: p${sens==="peste"?90:10} al zilei calendaristice, valori ilustrative)${nl(s[v])}`}
                                 : {valoare:NaN, unitate:"% din zile", explicatie:"nicio zi cu date"}; },
  wsdi: (s, p) => siruriPct(s, p, "max_temp", "peste", PRAG_ILUSTR.tx90p),
  csdi: (s, p) => siruriPct(s, p, "min_temp", "sub", PRAG_ILUSTR.tn10p),
  rnnp: (s, p) => { const thr = PRAG_UMED[p.percentila], m = []; let sm = 0;
                    s.precipitation.forEach((x,i)=>{ if (ok(x) && x > thr){ m.push(i); sm += x; } });
                    return {valoare: sm, unitate:"mm", marcate:m, var:"precipitation", explicatie:`suma zilelor cu P > ${r1(thr)} mm (pragul p${p.percentila} al zilelor ploioase din bază; valoare ilustrativă)`}; },
  rnnptot: (s, p) => { const thr = PRAG_UMED[p.percentila], m = []; let ex = 0, tot = 0;
                       s.precipitation.forEach((x,i)=>{ if (!ok(x)) return; if (x >= 1) tot += x; if (x > thr){ m.push(i); ex += x; } });
                       return tot > 0 ? {valoare: 100*ex/tot, unitate:"% din PRCPTOT", marcate:m, var:"precipitation", explicatie:`R${p.percentila}p = ${r1(ex)} mm (zilele marcate, P > ${r1(thr)} mm, prag ilustrativ) / PRCPTOT = ${r1(tot)} mm (zilele ≥ 1 mm)`}
                                      : {valoare:NaN, unitate:"%", explicatie:"nicio zi ≥ 1 mm: raportul e nedefinit (0/0) → NoData"}; },
  pet: s => { const e = petZile(s); return {valoare: sum(e), unitate:"mm", detaliu:e.map(x=>r1(x)), explicatie:`suma PET zilnice din rândul de jos; latitudinea 44,4° N, zilele 24 iulie–6 august (Ra ≈ ${r1(raZi(44.4, 206),1)} MJ/m² pe 24 iulie)`}; },
  bilant: s => { const e = petZile(s), D = s.precipitation.map((x,i) => ok(x) && ok(e[i]) ? x - e[i] : null);
                 return {valoare: sum(D), unitate:"mm", detaliu:D.map(x=>r1(x)), explicatie:`Σ (P − PET), rândul de jos; P = ${r1(sum(s.precipitation))} mm, PET = ${r1(sum(e))} mm (Hargreaves, 44,4° N)`}; },
};
const PCT_DEF = {tx90p:["max_temp","peste"], tx10p:["max_temp","sub"], tn90p:["min_temp","peste"], tn10p:["min_temp","sub"]};
const PRAG_ILUSTR = {           // praguri ilustrative pentru 24 iulie – 6 august (variază lent de la o zi la alta)
  tx90p:[35.1,35.1,35.2,35.2,35.2,35.3,35.3,35.3,35.3,35.3,35.2,35.2,35.2,35.1],
  tx10p:[26.4,26.4,26.5,26.5,26.5,26.6,26.6,26.6,26.6,26.6,26.5,26.5,26.5,26.4],
  tn90p:[21.4,21.4,21.5,21.5,21.5,21.6,21.6,21.6,21.6,21.6,21.5,21.5,21.5,21.4],
  tn10p:[14.6,14.6,14.7,14.7,14.7,14.8,14.8,14.8,14.8,14.8,14.7,14.7,14.7,14.6]};
const PRAG_UMED = {"95": 18.0, "99": 32.0};
function siruriPct(s, p, v, sens, thr){
  const d = Math.round(p.durata), e = s[v].map((x,i) => ok(x) && (sens==="peste" ? x > thr[i] : x < thr[i]));
  const m = []; let run = 0;
  e.forEach((x, i) => { run = x ? run + 1 : 0; if (run === d) for (let k = i - d + 1; k <= i; k++) m.push(k); else if (run > d) m.push(i); });
  const zile = e.filter(Boolean).length;
  return {valoare: m.length, unitate:"zile", marcate:m, var:v, detaliu:thr.map(x=>r1(x)),
          explicatie:`${zile} zile ${sens==="peste"?"peste":"sub"} pragul zilei (rândul „pe zi”, ilustrativ); doar cele din șiruri de cel puțin ${d} zile consecutive (marcate) se numără. Micșorați durata ca să vedeți efectul.`};
}
function raZi(lat, J){
  const phi = lat * Math.PI / 180, dr = 1 + 0.033*Math.cos(2*Math.PI*J/365), dl = 0.409*Math.sin(2*Math.PI*J/365 - 1.39);
  const ws = Math.acos(Math.max(-1, Math.min(1, -Math.tan(phi)*Math.tan(dl))));
  return 24*60/Math.PI*0.0820*dr*(ws*Math.sin(phi)*Math.sin(dl) + Math.cos(phi)*Math.cos(dl)*Math.sin(ws));
}
function petZile(s){          // aceleași formule ca zarr_clima.pet_hargreaves; 24 iulie 2024 = ziua 206
  return s.max_temp.map((tx, i) => { const tn = s.min_temp[i]; if (!ok(tx) || !ok(tn)) return null;
    return Math.max(0.0023*0.408*raZi(44.4, 206 + i)*((tx+tn)/2 + 17.8)*Math.sqrt(Math.max(tx - tn, 0)), 0); });
}
// Pasul comun de validitate (zarr_clima.harti_anuale): o zi e validă dacă TOATE variabilele indicatorului există;
// sub PRAG_VALID (90 %) zile valide, pixelul devine NoData, oricare ar fi rezultatul formulei.
const PRAG_VALID = 0.9;
function validitate(s, vars){
  const n = s.zile.length, v = s.zile.filter((_, i) => vars.every(x => ok(s[x][i]))).length;
  return {n, v, ok: v / n >= PRAG_VALID};
}

// ------------------------------------------------------------------ DOM
function construieste(){
  const v = $("#v-indicatori"); v.innerHTML = "";
  v.append(el("aside",{class:"panou doc-meniu",id:"ind-meniu"}), el("section",{class:"panou doc-pagina",id:"ind-pagina"}));
  meniu(); arata(ACTIV_IND || "_pasi");
}

function meniu(){
  const m = $("#ind-meniu"); const focus = document.activeElement?.id === "ind-cauta"; m.innerHTML = "";
  const c = el("input",{type:"text",id:"ind-cauta",class:"cauta",placeholder:"Caută (ex. îngheț, ETCCDI, prag)…",value:CAUTA,
                        oninput:e=>{ CAUTA = e.target.value; meniu(); }});
  m.append(c, el("button",{class:"an"+(ACTIV_IND==="_pasi"?" activ":""),onclick:()=>arata("_pasi")}, el("span",{class:"nr",text:"★"}), "Cum se calculează orice indicator"));
  const q = fara_diacritice(CAUTA).split(/\s+/).filter(Boolean), grupuri = {};
  for (const [cod, d] of Object.entries(CAT.indicatori)){
    const text = fara_diacritice([cod, d.titlu, d.descriere, d.grup, JSON.stringify(d.teorie||{})].join(" "));
    if (q.every(t => text.includes(t))) (grupuri[d.grup] ??= []).push([cod, d]);
  }
  for (const [g, l] of Object.entries(grupuri)){
    m.append(el("h3",{text:g}));
    l.forEach(([cod, d]) => m.append(el("button",{class:"an"+(ACTIV_IND===cod?" activ":""),onclick:()=>arata(cod)}, d.titlu)));
  }
  const met = Object.entries(CAT.metode || {}).filter(([cod, d]) =>
    q.every(t => fara_diacritice([cod, d.titlu, "metode statistice", JSON.stringify(d.teorie||{})].join(" ")).includes(t)));
  if (met.length){
    m.append(el("h3",{text:"Metode statistice"}));
    met.forEach(([cod, d]) => m.append(el("button",{class:"an"+(ACTIV_IND==="m:"+cod?" activ":""),onclick:()=>arata("m:"+cod)}, d.titlu)));
  }
  if (focus){ const x = $("#ind-cauta"); x.focus(); x.setSelectionRange(x.value.length, x.value.length); }
}

function html(t){ const s = el("span"); s.innerHTML = t; return s; }       // conținut local, scris de noi

function arata(cod){
  ACTIV_IND = cod; meniu();
  const p = $("#ind-pagina"); p.innerHTML = ""; p.scrollTop = 0;
  if (cod === "_pasi"){
    p.append(el("h2",{text:"Cum se calculează orice indicator"}),
      el("p",{class:"descriere",text:"Fiecare analiză parcurge aceiași pași. Funcția indicatorului (pasul 7) e singura parte specifică; restul e comun și asigură că rezultatul e corect: fără zilele „viitoare” umplute cu 0, fără pixeli cu prea multe goluri, fără ani incompleți."}),
      el("ol",{class:"pasi-mari"}, CAT.pasi_comuni.map(([t, d]) => el("li",{}, el("b",{text:t}), el("div",{}, html(d))))),
      el("p",{class:"ajutor",text:"Pașii sunt implementați în clima/zarr_clima.py (harti_anuale, citeste, perioada, grila_zonei) și clima/motoare.py."}));
    return;
  }
  if (cod.startsWith("m:")){ arataMetoda(p, cod.slice(2)); return; }
  const d = CAT.indicatori[cod], T = d.teorie || {};
  p.append(el("div",{class:"ind-cap"}, el("span",{class:"pastila",text:d.grup}), el("code",{text:cod})),
           el("h2",{text:d.titlu}), el("p",{class:"descriere",text:T.rezumat || d.descriere}));
  if (T.formula) p.append(el("div",{class:"formula"}, html(T.formula)));
  if (T.simboluri) p.append(el("table",{class:"simboluri"}, T.simboluri.map(([s, e]) => el("tr",{}, el("td",{},html(s)), el("td",{},html(e))))));
  const sect = (titlu, ...c) => el("section",{class:"ind-sect"}, el("h3",{text:titlu}), ...c);
  if (T.definitie) p.append(sect("Ce măsoară", el("p",{},html(T.definitie))));
  if (T.pasi) p.append(sect("Ce face codul, pas cu pas", el("ol",{}, T.pasi.map(x => el("li",{},html(x)))),
    el("p",{class:"ajutor"}, "Înainte și după acești pași rulează pașii comuni (frontiera, validitatea, combinarea anilor): ",
       el("a",{class:"leg",text:"vezi pașii comuni",onclick:()=>arata("_pasi")}))));
  if (T.calculator && CALC[T.calculator]) p.append(sect("Încercați: calculul pe 14 zile", calculator(cod, d)));
  else if (T.calculator === "spi" || T.calculator === "spei") p.append(sect("Încercați: 30 de ani de bază și anul analizat", calcStandardizat(T.calculator)));
  else if (T.pasi && T.calculator !== "spi" && T.calculator !== "spei") p.append(sect("Calculul pe un exemplu", el("p",{class:"ajutor",text:"Acest indicator are nevoie de un an întreg de date (îngheț primăvara și toamna), deci nu are calculator pe 14 zile. Rulați rețeta lui pe o zonă mică și deschideți rezultatul pe hartă."})));
  if (T.interpretare) p.append(sect("Cum se interpretează", el("p",{},html(T.interpretare))));
  if (T.standard) p.append(sect("Standard și referințe", el("p",{},html(T.standard))));
  if (T.limitari) p.append(sect("Limitări (de știut înainte de a trage concluzii)", el("ul",{}, T.limitari.map(x => el("li",{},html(x))))));
  if (T.intrebare) p.append(sect("Întrebare pentru discuție", el("p",{class:"intrebare"},html(T.intrebare))));
  if (d.parametri?.length) p.append(sect("Parametrii", el("table",{class:"simboluri"}, d.parametri.map(x => el("tr",{},
    el("td",{},el("code",{text:x.nume})), el("td",{text:`${x.eticheta} · implicit: ${x.optiuni ? (x.optiuni.find(o=>o[0]===x.implicit)||[0,x.implicit])[1] : x.implicit}`}))))));
  if (d.retete?.length) p.append(sect("Folosit în analizele", el("div",{class:"rand"}, d.retete.map(r => el("a",{class:"leg",text:r.titlu,
    onclick:()=>{ arataVedere("analize"); alege(r.id); }})))));
  if (d.cod_sursa) p.append(el("details",{class:"cod-sursa"}, el("summary",{text:"Codul Python exact (clima/zarr_clima.py)"}), el("pre",{text:d.cod_sursa})));
}

// ------------------------------------------------------------------ metodele statistice
function arataMetoda(p, cod){
  const d = (CAT.metode || {})[cod]; if (!d){ p.append(el("p",{text:"Fișa nu există."})); return; }
  const T = d.teorie || {}, sect = (titlu, ...c) => el("section",{class:"ind-sect"}, el("h3",{text:titlu}), ...c);
  p.append(el("div",{class:"ind-cap"}, el("span",{class:"pastila",text:"Metode statistice"})),
           el("h2",{text:d.titlu}), el("p",{class:"descriere",text:T.rezumat || ""}));
  if (T.formula) p.append(el("div",{class:"formula"}, html(T.formula)));
  if (T.simboluri) p.append(el("table",{class:"simboluri"}, T.simboluri.map(([a, b]) => el("tr",{}, el("td",{},html(a)), el("td",{},html(b))))));
  if (T.definitie) p.append(sect("Ce face metoda", el("p",{},html(T.definitie))));
  if (T.pasi) p.append(sect("Ce face codul, pas cu pas", el("ol",{}, T.pasi.map(x => el("li",{},html(x))))));
  if (T.calculator === "trend") p.append(sect("Încercați: tendința pe o serie de ani", calcTendinta(cod)));
  if (T.calculator === "pixel_zona") p.append(sect("Încercați: patru pixeli, o săptămână", calcPixelZona()));
  if (T.interpretare) p.append(sect("Cum se interpretează", el("p",{},html(T.interpretare))));
  if (T.standard) p.append(sect("Standard și referințe", el("p",{},html(T.standard))));
  if (T.limitari) p.append(sect("Limitări (de știut înainte de a trage concluzii)", el("ul",{}, T.limitari.map(x => el("li",{},html(x))))));
  if (T.intrebare) p.append(sect("Întrebare pentru discuție", el("p",{class:"intrebare"},html(T.intrebare))));
  if (d.cod_sursa) p.append(el("details",{class:"cod-sursa"}, el("summary",{text:"Codul Python exact (clima/zarr_clima.py)"}), el("pre",{text:d.cod_sursa})));
}

// statistică scrisă de mână, identică cu Python: p_student (beta incompletă, Lentz) și erfc pentru Mann–Kendall
function lgamma(x){                                    // Lanczos (g = 7, n = 9), eroare < 1e-13
  const c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
             12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  if (x < 0.5) return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - lgamma(1 - x);
  x -= 1; let a = c[0]; const t = x + 7.5;
  for (let i = 1; i < 9; i++) a += c[i] / (x + i);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}
function betaInc(a, b, x){
  if (!(x > 0)) return 0; if (x >= 1) return 1;
  if (x > (a + 1) / (a + b + 2)) return 1 - betaInc(b, a, 1 - x);
  const MIC = 1e-300, fata = Math.exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * Math.log(x) + b * Math.log1p(-x));
  let c = 1, d = 1 - (a + b) * x / (a + 1); if (Math.abs(d) < MIC) d = MIC; d = 1 / d; let h = d;
  for (let k = 1; k <= 300; k++){
    for (const num of [k * (b - k) * x / ((a + 2*k - 1) * (a + 2*k)), -(a + k) * (a + b + k) * x / ((a + 2*k) * (a + 2*k + 1))]){
      d = 1 + num * d; if (Math.abs(d) < MIC) d = MIC; c = 1 + num / c; if (Math.abs(c) < MIC) c = MIC; d = 1 / d; h *= d * c;
    }
    if (Math.abs(d * c - 1) < 1e-14) break;
  }
  return fata * h / a;
}
const pStudent = (t, df) => isFinite(t) ? betaInc(df / 2, 0.5, df / (df + t * t)) : NaN;
function erfc(x){                                      // Numerical Recipes erfcc, eroare relativă < 1,2e-7
  const z = Math.abs(x), t = 1 / (1 + 0.5 * z);
  const r = t * Math.exp(-z*z - 1.26551223 + t*(1.00002368 + t*(0.37409196 + t*(0.09678418 + t*(-0.18628806 + t*(0.27886807 +
            t*(-1.13520398 + t*(1.48851587 + t*(-0.82215223 + t*0.17087277)))))))));
  return x >= 0 ? r : 2 - r;
}
function ols(x, y){
  const n = x.length, mx = x.reduce((a,b)=>a+b,0)/n, my = y.reduce((a,b)=>a+b,0)/n;
  let sxx = 0, sxy = 0; x.forEach((xi, i) => { sxx += (xi-mx)**2; sxy += (xi-mx)*(y[i]-my); });
  const b = sxy / sxx, a = my - b * mx; let sr = 0; x.forEach((xi, i) => sr += (y[i] - a - b*xi)**2);
  const se = Math.sqrt(sr / (n - 2) / sxx), t = b / se;
  return {b, a, t, p: se > 0 ? pStudent(t, n - 2) : (b === 0 ? 1 : 0), pNorm: se > 0 ? erfc(Math.abs(t) / Math.SQRT2) : NaN, n};
}
function senMK(x, y){
  const n = x.length, pante = []; let S = 0;
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++){ pante.push((y[j]-y[i])/(x[j]-x[i])); S += Math.sign(y[j]-y[i]); }
  pante.sort((u,v)=>u-v); const m = pante.length, b = m % 2 ? pante[(m-1)/2] : (pante[m/2-1] + pante[m/2]) / 2;
  const grupuri = {}; y.forEach(v => grupuri[v] = (grupuri[v]||0) + 1);
  const cor = Object.values(grupuri).filter(t => t > 1).reduce((s, t) => s + t*(t-1)*(2*t+5), 0);
  const v = (n*(n-1)*(2*n+5) - cor) / 18, z = v > 0 ? (S - Math.sign(S)) / Math.sqrt(v) : 0;
  const yM = [...y].sort((u,w)=>u-w), xM = [...x].sort((u,w)=>u-w), med = a => a.length % 2 ? a[(a.length-1)/2] : (a[a.length/2-1]+a[a.length/2])/2;
  return {b, S, v, z, p: erfc(Math.abs(z) / Math.SQRT2), a: med(yM) - b * med(xM)};
}

const ANI_TREND = [2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025];
const SERIE_TREND_IMPLICITA = [26.1,26.8,27.4,26.6,27.2,27.9,27.3,28.6,28.1,27.4,29.6,28.2];
let SERIE_TREND = [...SERIE_TREND_IMPLICITA];

function calcTendinta(cod){
  const cutie = el("div",{class:"calc"}), tabel = el("div",{class:"calc-tabel"}), grafic = el("div",{class:"calc-grafic"}), rez = el("div",{class:"calc-rez"});
  cutie.append(el("p",{class:"ajutor",text:"Valorile anuale ale unei zone (implicit: Tmax medie de vară, °C). Schimbați orice valoare; lăsați goală o celulă pentru un an lipsă. Calculul folosește exact formulele din Python."}),
    tabel, grafic, rez,
    el("div",{class:"rand"},
      el("a",{class:"leg",text:"seria inițială",onclick:()=>{ SERIE_TREND = [...SERIE_TREND_IMPLICITA]; calc(); }}),
      el("a",{class:"leg",text:"un an extrem la final",onclick:()=>{ SERIE_TREND = ANI_TREND.map((_,i)=> i===11 ? 33 : 27 + (i%3-1)*0.3); calc(); }}),
      el("a",{class:"leg",text:"numărare cu multe zerouri",onclick:()=>{ SERIE_TREND = [0,0,0,1,0,0,0,0,2,0,3,1]; calc(); }}),
      el("a",{class:"leg",text:"fără tendință",onclick:()=>{ SERIE_TREND = [27.1,26.4,27.8,26.9,27.5,26.7,27.3,27.0,26.6,27.6,26.8,27.2]; calc(); }})));
  function calc(){
    tabel.innerHTML = "";
    const t = el("table");
    t.append(el("tr",{}, el("th",{text:"an"}), ANI_TREND.map(a => el("th",{text:String(a)}))));
    t.append(el("tr",{}, el("th",{text:"valoare"}), SERIE_TREND.map((v, i) => {
      const inp = el("input",{type:"text",value:ok(v)?r1(v,1):""}); if (!ok(v)){ inp.placeholder="lipsă"; inp.classList.add("lipsa"); }
      inp.onchange = () => { const s = inp.value.trim(); SERIE_TREND[i] = s === "" ? null : num(s); if (SERIE_TREND[i] != null && !isFinite(SERIE_TREND[i])) SERIE_TREND[i] = null; calc(); };
      return el("td",{}, inp); })));
    tabel.append(t);
    const x = [], y = []; ANI_TREND.forEach((a, i) => { if (ok(SERIE_TREND[i])){ x.push(a); y.push(SERIE_TREND[i]); } });
    rez.innerHTML = ""; grafic.innerHTML = "";
    if (x.length < 10){ rez.append(el("div",{class:"calc-avert rau",text:`Doar ${x.length} ani cu valori: programul cere cel puțin 10 ani pentru o tendință (pixelul ar fi NoData).`})); return; }
    const o = ols(x, y), s = senMK(x, y);
    // leave-one-out (fișa „Sensibilitatea la un singur an”)
    const loo = x.map((a, k) => { const xx = x.filter((_,i)=>i!==k), yy = y.filter((_,i)=>i!==k); return {an:a, ols:ols(xx,yy), sen:senMK(xx,yy)}; });
    const prag = 0.05, semn = p => p < prag ? "semnificativă (p < 0,05)" : "nesemnificativă (p ≥ 0,05)";
    const fmtp = p => p < 0.001 ? "< 0,001" : r1(p, 3);
    rez.append(
      el("div",{class:"calc-valoare"}, "OLS: ", el("b",{text:`${o.b*10>=0?"+":""}${r1(o.b*10,2)} / deceniu`}), ` · t = ${r1(o.t,2)}, ${o.n-2} g.l., p = ${fmtp(o.p)} — ${semn(o.p)}`),
      el("div",{class:"calc-valoare"}, "Theil–Sen: ", el("b",{text:`${s.b*10>=0?"+":""}${r1(s.b*10,2)} / deceniu`}), ` · Mann–Kendall S = ${s.S}, Z = ${r1(s.z,2)}, p = ${fmtp(s.p)} — ${semn(s.p)}`),
      el("p",{class:"ajutor",text:`Cu aproximarea normală (folosită până în v5.0), p-valoarea OLS ar fi fost ${fmtp(o.pNorm)}. Pe serii scurte diferența poate muta concluzia peste prag.`}));
    const imp = loo.reduce((m, r) => Math.abs(r.ols.b - o.b) > Math.abs(m.ols.b - o.b) ? r : m, loo[0]);
    const schimbaSemn = loo.some(r => Math.sign(r.ols.b) !== Math.sign(o.b)), schimbaP = loo.some(r => (r.ols.p < prag) !== (o.p < prag));
    const schimbaMarime = Math.abs(imp.ols.b - o.b) > 0.5 * Math.abs(o.b);        // fără un an, panta se schimbă cu peste jumătate
    rez.append(el("div",{class:"calc-avert"+(schimbaSemn||schimbaP||schimbaMarime?" rau":"")},
      `Fără câte un an, panta OLS variază între ${r1(Math.min(...loo.map(r=>r.ols.b))*10,2)} și ${r1(Math.max(...loo.map(r=>r.ols.b))*10,2)} / deceniu; `+
      `anul cel mai influent: ${imp.an} (fără el: ${r1(imp.ols.b*10,2)}, p = ${fmtp(imp.ols.p)}). `+
      (schimbaSemn ? "Semnul tendinței se schimbă fără un singur an!" : schimbaP ? "Semnificația se schimbă fără un singur an: concluzie la limită."
        : schimbaMarime ? `Semnul și semnificația rămân, dar mărimea pantei atârnă de anul ${imp.an}: fără el se schimbă cu peste jumătate.`
        : "Concluzia nu depinde de un singur an.")));
    grafic.append(svgTendinta(x, y, o, s, imp.an));
  }
  calc(); return cutie;
}

function svgTendinta(x, y, o, s, anImp){
  const L = 620, H = 210, m = {s:46, d:12, sus:12, jos:28}, ns = "http://www.w3.org/2000/svg";
  const x0 = Math.min(...ANI_TREND), x1 = Math.max(...ANI_TREND), lo = Math.min(...y), hi = Math.max(...y), pad = (hi - lo || 1) * 0.15;
  const X = a => m.s + (a - x0) / (x1 - x0) * (L - m.s - m.d), Y = v => H - m.jos - (v - lo + pad) / (hi - lo + 2*pad) * (H - m.sus - m.jos);
  const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", `0 0 ${L} ${H}`); svg.setAttribute("class", "calc-svg");
  svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Valorile anuale, dreapta OLS și dreapta Theil–Sen");
  const e = (tag, at, text) => { const n = document.createElementNS(ns, tag); for (const k in at) n.setAttribute(k, at[k]); if (text != null) n.textContent = text; svg.append(n); return n; };
  for (let k = 0; k <= 3; k++){ const v = lo - pad + k * (hi - lo + 2*pad) / 3;
    e("line",{x1:m.s,x2:L-m.d,y1:Y(v),y2:Y(v),stroke:"#e8edf0"}); e("text",{x:m.s-6,y:Y(v)+4,"text-anchor":"end","font-size":11,fill:"#5e6e7c"}, r1(v,1)); }
  ANI_TREND.forEach((a, i) => { if (i % 2 === 0) e("text",{x:X(a),y:H-8,"text-anchor":"middle","font-size":11,fill:"#5e6e7c"}, String(a)); });
  e("line",{x1:X(x0),x2:X(x1),y1:Y(o.a+o.b*x0),y2:Y(o.a+o.b*x1),stroke:"#0f6b8c","stroke-width":2});
  e("line",{x1:X(x0),x2:X(x1),y1:Y(s.a+s.b*x0),y2:Y(s.a+s.b*x1),stroke:"#c2611f","stroke-width":2,"stroke-dasharray":"6 4"});
  x.forEach((a, i) => { const c = e("circle",{cx:X(a),cy:Y(y[i]),r:a===anImp?6:4.5,fill:a===anImp?"#c2611f":"#172634",stroke:"#fff","stroke-width":2});
    const t = document.createElementNS(ns, "title"); t.textContent = `${a}: ${r1(y[i],1)}${a===anImp?" (anul cel mai influent)":""}`; c.append(t); });
  const leg = el("div",{class:"calc-legenda"},
    el("span",{}, el("i",{style:"background:#0f6b8c"}), "OLS (regresie liniară)"),
    el("span",{}, el("i",{style:"background:repeating-linear-gradient(90deg,#c2611f 0 6px,transparent 6px 10px)"}), "Theil–Sen"),
    el("span",{}, el("i",{class:"punct-leg",style:"background:#c2611f"}), "anul cel mai influent"));
  return el("div",{}, svg, leg);
}

// patru pixeli (2 câmpie, 2 munte), 7 zile de Tmax: indicatorul „zile cu Tmax ≥ prag” pe cele două căi
const PIXELI_IMPLICIT = [[31.5,32.8,30.2,33.4,29.1,31.0,32.2],[30.8,31.9,29.6,32.7,28.4,30.3,31.5],
                         [22.4,23.6,21.0,24.2,19.8,22.1,23.0],[24.0,25.1,22.7,25.8,21.3,23.6,24.5]];
let PIXELI = PIXELI_IMPLICIT.map(r => [...r]), PRAG_PZ = 30;
function calcPixelZona(){
  const cutie = el("div",{class:"calc"}), tabel = el("div",{class:"calc-tabel"}), rez = el("div",{class:"calc-rez"});
  const prag = el("input",{type:"number",step:"0.5",value:PRAG_PZ,style:"width:80px"}); prag.oninput = () => { const v = num(prag.value); if (v != null){ PRAG_PZ = v; calc(); } };
  cutie.append(el("p",{class:"ajutor",text:"O zonă cu doi pixeli de câmpie și doi de munte, o săptămână de Tmax (°C). Indicatorul: zile cu Tmax ≥ prag."}),
    el("div",{class:"rand calc-param"}, el("label",{class:"param"}, "Pragul (°C)", prag)), tabel, rez,
    el("a",{class:"leg",text:"valorile inițiale",onclick:()=>{ PIXELI = PIXELI_IMPLICIT.map(r => [...r]); PRAG_PZ = 30; prag.value = 30; calc(); }}));
  const NUME = ["câmpie 1","câmpie 2","munte 1","munte 2"];
  function calc(){
    tabel.innerHTML = ""; rez.innerHTML = "";
    const t = el("table"), zileMedii = PIXELI[0].map((_, z) => PIXELI.reduce((s, r) => s + r[z], 0) / PIXELI.length);
    t.append(el("tr",{}, el("th",{text:""}), PIXELI[0].map((_, z) => el("th",{text:`ziua ${z+1}`})), el("th",{text:"zile ≥ prag"})));
    PIXELI.forEach((r, k) => t.append(el("tr",{}, el("th",{text:NUME[k]}), r.map((v, z) => {
      const inp = el("input",{type:"text",value:r1(v,1),class:v >= PRAG_PZ ? "marcat" : ""});
      inp.onchange = () => { const n = num(inp.value); if (n != null && isFinite(n)) PIXELI[k][z] = n; calc(); };
      return el("td",{}, inp); }), el("td",{class:"calc-nr",text:String(r.filter(v => v >= PRAG_PZ).length)}))));
    t.append(el("tr",{class:"detaliu"}, el("th",{text:"media zonei"}), zileMedii.map(v => el("td",{class:v >= PRAG_PZ ? "marcat-text" : "",text:r1(v,1)})),
      el("td",{class:"calc-nr",text:String(zileMedii.filter(v => v >= PRAG_PZ).length)})));
    tabel.append(t);
    const B = PIXELI.reduce((s, r) => s + r.filter(v => v >= PRAG_PZ).length, 0) / PIXELI.length, A = zileMedii.filter(v => v >= PRAG_PZ).length;
    rez.append(el("div",{class:"calc-valoare"}, "Întâi pixelul, apoi zona (programul): ", el("b",{text:`${r1(B,2)} zile`})),
               el("div",{class:"calc-valoare"}, "Întâi zona, apoi indicatorul: ", el("b",{text:`${A} zile`})),
               el("div",{class:"calc-avert"+(Math.abs(A - B) >= 1 ? " rau" : "")}, Math.abs(A - B) < 1e-9
                 ? "Aici cele două căi coincid. Încercați alt prag (de exemplu 22 °C): pentru indicatorii cu prag, egalitatea e o coincidență, nu o regulă."
                 : `Diferență de ${r1(Math.abs(A - B),2)} zile. Media zilnică a zonei nu corespunde niciunui loc real; media pixelilor spune câte zile cu prag a avut, în medie, un loc din zonă.`));
  }
  calc(); return cutie;
}

// ------------------------------------------------------------------ SPI / SPEI: ajustarea distribuției pe anii de bază
function gammaInc(a, x){                               // P(a, x), aceleași ramuri ca zarr_clima.gamma_inc
  if (!(x > 0)) return 0;
  const fata = Math.exp(-x + a*Math.log(x) - lgamma(a));
  if (x < a + 1){ let ap = a, dl = 1/a, s = dl; for (let k = 0; k < 400; k++){ ap += 1; dl *= x/ap; s += dl; if (Math.abs(dl) < Math.abs(s)*1e-15) break; } return Math.min(1, s*fata); }
  const MIC = 1e-300; let b = x + 1 - a, c = 1/MIC, d = 1/b, h = d;
  for (let i = 1; i <= 400; i++){ const an = -i*(i - a); b += 2; d = an*d + b; if (Math.abs(d) < MIC) d = MIC; c = b + an/c; if (Math.abs(c) < MIC) c = MIC; d = 1/d; const de = d*c; h *= de; if (Math.abs(de - 1) < 1e-15) break; }
  return Math.max(0, 1 - fata*h);
}
function normInv(p){                                   // Acklam, ca zarr_clima.normala_inversa
  const a=[-3.969683028665376e+01,2.209460984245205e+02,-2.759285104469687e+02,1.383577518672690e+02,-3.066479806614716e+01,2.506628277459239e+00],
        b=[-5.447609879822406e+01,1.615858368580409e+02,-1.556989798598866e+02,6.680131188771972e+01,-1.328068155288572e+01],
        c=[-7.784894002430293e-03,-3.223964580411365e-01,-2.400758277161838e+00,-2.549732539343734e+00,4.374664141464968e+00,2.938163982698783e+00],
        d=[7.784695709041462e-03,3.224671290700398e-01,2.445134137142996e+00,3.754408661907416e+00], pl = 0.02425;
  if (p < pl){ const q = Math.sqrt(-2*Math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  if (p > 1 - pl){ const q = Math.sqrt(-2*Math.log(1-p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  const q = p - 0.5, r = q*q; return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
}
const LIM_P = 1e-6, clipP = p => Math.min(1 - LIM_P, Math.max(LIM_P, p));
function fitGamma(v){
  const poz = v.filter(x => x > 0), n = v.length, m = poz.length; if (m < 10) return null;
  const xm = poz.reduce((s,x)=>s+x,0)/m, lnm = poz.reduce((s,x)=>s+Math.log(x),0)/m, A = Math.log(xm) - lnm; if (!(A > 0)) return null;
  const alfa = (1 + Math.sqrt(1 + 4*A/3))/(4*A); return {alfa, beta: xm/alfa, q: (n - m)/n};
}
const cdfGamma = (x, f) => f.q + (1 - f.q)*gammaInc(f.alfa, x/f.beta);
function fitGLO(v){                                    // L-momente nedeplasate + logistica generalizată (ca pachetul SPEI)
  const s = [...v].sort((u,w)=>u-w), n = s.length; if (n < 10) return null;
  let b0 = 0, b1 = 0, b2 = 0; s.forEach((x, k) => { const i = k + 1; b0 += x; b1 += (i-1)/(n-1)*x; b2 += (i-1)*(i-2)/((n-1)*(n-2))*x; });
  b0 /= n; b1 /= n; b2 /= n;
  const l1 = b0, l2 = 2*b1 - b0, l3 = 6*b2 - 6*b1 + b0, k = -l3/l2;
  if (!(Math.abs(k) < 1) || !(l2 > 0)) return null;
  const mic = Math.abs(k) < 1e-6, alfa = mic ? l2 : l2*Math.sin(k*Math.PI)/(k*Math.PI), xi = l1 - alfa*(mic ? 0 : 1/k - Math.PI/Math.sin(k*Math.PI));
  return {xi, alfa, k};
}
function cdfGLO(x, f){
  const arg = 1 - f.k*(x - f.xi)/f.alfa; if (!(arg > 0)) return f.k < 0 ? 0 : 1;
  const y = Math.abs(f.k) < 1e-6 ? (x - f.xi)/f.alfa : -Math.log(arg)/f.k; return 1/(1 + Math.exp(-y));
}
function clasaSPI(z){
  return z >= 2 ? "extrem de umed" : z >= 1.5 ? "foarte umed" : z >= 1 ? "moderat umed" : z > -1 ? "aproape normal"
       : z > -1.5 ? "secetă moderată" : z > -2 ? "secetă severă" : "secetă extremă";
}
const BAZA_SPI = [182,145,210,98,163,231,120,175,140,265,88,190,155,205,132,172,118,248,160,138,195,112,225,150,178,128,201,142,168,185];
const BAZA_SPEI = [-290,-245,-210,-330,-265,-180,-300,-240,-275,-150,-345,-225,-260,-205,-285,-235,-310,-170,-250,-280,-215,-320,-190,-255,-230,-295,-200,-270,-245,-220];
const STARE_STD = {spi:{baza:[...BAZA_SPI], x:72}, spei:{baza:[...BAZA_SPEI], x:-380}};
function calcStandardizat(tip){
  const st = STARE_STD[tip], spei = tip === "spei";
  const cutie = el("div",{class:"calc"}), tabel = el("div",{class:"calc-tabel"}), rez = el("div",{class:"calc-rez"});
  const xin = el("input",{type:"text",value:r1(st.x,1),style:"width:90px"});
  xin.onchange = () => { const v = num(xin.value); if (v != null && isFinite(v)) st.x = v; calc(); };
  cutie.append(el("p",{class:"ajutor",text: spei
      ? "Bilanțul P − PET al verii (iunie–august, mm) în cei 30 de ani de bază (valori ilustrative pentru câmpie) și în anul analizat. Modificați orice valoare."
      : "Precipitațiile verii (iunie–august, mm) în cei 30 de ani de bază (valori ilustrative pentru câmpie) și în anul analizat. Modificați orice valoare."}),
    tabel, el("div",{class:"rand calc-param"}, el("label",{class:"param"}, spei ? "Anul analizat: P − PET (mm)" : "Anul analizat: P (mm)", xin)), rez,
    el("a",{class:"leg",text:"valorile inițiale",onclick:()=>{ st.baza = [...(spei ? BAZA_SPEI : BAZA_SPI)]; st.x = spei ? -380 : 72; xin.value = r1(st.x,1); calc(); }}));
  function calc(){
    tabel.innerHTML = ""; rez.innerHTML = "";
    const t = el("table");
    for (let r = 0; r < 3; r++){
      t.append(el("tr",{}, el("th",{text:`${1991 + 10*r}–${2000 + 10*r}`}), st.baza.slice(10*r, 10*r + 10).map((v, j) => {
        const i = 10*r + j, inp = el("input",{type:"text",value:r1(v,0),title:String(1991 + i)});
        inp.onchange = () => { const n = num(inp.value); if (n != null && isFinite(n)) st.baza[i] = n; calc(); };
        return el("td",{}, inp); })));
    }
    tabel.append(t);
    const f = spei ? fitGLO(st.baza) : fitGamma(st.baza);
    if (!f){ rez.append(el("div",{class:"calc-avert rau",text: spei ? "Distribuția nu se poate ajusta (|κ| ≥ 1): pixelul ar fi NoData." : "Sub 10 ani cu total pozitiv: pixelul ar fi NoData."})); return; }
    const H = spei ? cdfGLO(st.x, f) : cdfGamma(st.x, f), z = normInv(clipP(H));
    const mai_mici = st.baza.filter(v => v < st.x).length;
    rez.append(
      el("div",{class:"calc-valoare"}, `${spei ? "SPEI" : "SPI"} = `, el("b",{text:`${z>=0?"+":""}${r1(z,2)}`}), ` — ${clasaSPI(z)}`),
      el("p",{class:"ajutor",text: (spei
          ? `Parametri (L-momente nedeplasate): ξ = ${r1(f.xi,1)}, α = ${r1(f.alfa,1)}, κ = ${r1(f.k,3)}. `
          : `Parametri: α = ${r1(f.alfa,2)}, β = ${r1(f.beta,1)} mm, q = ${r1(f.q,2)} (ani cu 0 mm). `) +
          `Probabilitatea cumulată ${spei ? "F" : "H"}(x) = ${H < 0.001 ? "< 0,001" : r1(H,3)} → Φ⁻¹ = ${r1(z,2)}. `+
          `În baza de 30 de ani, ${mai_mici} ${mai_mici===1?"an a avut":"ani au avut"} o valoare mai mică.`}),
      el("div",{class:"calc-avert"+(z <= -1.5 ? " rau" : "")}, z <= -1
          ? `Aproximativ o perioadă la ${r1(1/Math.max(H, 1e-6),0)} ani este cel puțin atât de ${spei ? "deficitară" : "secetoasă"} în clima de bază.`
          : "Valoare în intervalul obișnuit al climei de bază."));
  }
  calc(); return cutie;
}

// ------------------------------------------------------------------ calculatorul didactic
function calculator(cod, d){
  const T = d.teorie, cutie = el("div",{class:"calc"});
  const param = {};
  (d.parametri || []).forEach(x => param[x.nume] = x.implicit);
  const intrari = el("div",{class:"rand calc-param"});
  (d.parametri || []).filter(x => !x.nume.startsWith("baza_")).forEach(x => {     // perioada de bază: pragurile de aici sunt ilustrative
    let w;
    if (x.tip === "alegere"){ w = el("select",{}, x.optiuni.map(o => el("option",{value:o[0],text:o[1]}))); w.value = param[x.nume]; w.onchange = () => { param[x.nume] = w.value; calc(); }; }
    else if (x.tip === "bifa"){ w = el("input",{type:"checkbox"}); w.checked = !!param[x.nume]; w.onchange = () => { param[x.nume] = w.checked; calc(); }; }
    else { w = el("input",{type:"number",step:x.pas||"any",value:param[x.nume],style:"width:80px"}); w.oninput = () => { const v = num(w.value); if (v != null){ param[x.nume] = v; calc(); } }; }
    intrari.append(el("label",{class:"param"}, x.tip === "bifa" ? w : null, x.eticheta, x.tip === "bifa" ? null : w));
  });
  const tabel = el("div",{class:"calc-tabel"}), rez = el("div",{class:"calc-rez"});
  function calc(){
    const vars = param.var ? [param.var] : d.variabile;
    const va = validitate(SERIE, vars);
    const faraDate = vars.some(v => !SERIE[v].some(ok)) ||
      (T.calculator !== "amplitudine_absoluta" && va.v === 0);
    const r = faraDate
      ? {valoare:NaN, unitate:"", explicatie:"Nu există observații pentru calcul."}
      : CALC[T.calculator](SERIE, param);
    const marcate = new Set(r.marcate || []);
    tabel.innerHTML = "";
    const t = el("table");
    t.append(el("tr",{}, el("th",{text:""}), SERIE.zile.map((z, i) => el("th",{class:marcate.has(i)?"marcat":"",text:z}))));
    for (const v of ["max_temp","min_temp","precipitation"]){
      t.append(el("tr",{class: r.var && r.var !== v ? "estompat" : ""}, el("th",{text:NUME_VAR[v]}), SERIE[v].map((x, i) => {
        const inp = el("input",{type:"text",value:r1(x),class:(marcate.has(i) && (!r.var || r.var===v)) ? "marcat" : ""});
        if (!ok(x)){ inp.value = ""; inp.placeholder = "lipsă"; inp.classList.add("lipsa"); }
        inp.onchange = () => {                                   // gol, „-” sau „nan” = zi lipsă
          const t = inp.value.trim();
          if (t === "" || t === "-" || t === "–" || t.toLowerCase() === "nan"){ SERIE[v][i] = null; calc(); return; }
          const n = num(t); if (n != null && isFinite(n)){ SERIE[v][i] = n; calc(); } else inp.value = ok(SERIE[v][i]) ? r1(SERIE[v][i]) : "";
        };
        return el("td",{}, inp);
      })));
    }
    if (r.detaliu) t.append(el("tr",{class:"detaliu"}, el("th",{text:"pe zi"}), r.detaliu.map(x => el("td",{text:x}))));
    tabel.append(t);
    rez.innerHTML = "";
    rez.append(el("div",{class:"calc-valoare"}, "Rezultat: ", el("b",{text:`${r1(r.valoare, Number.isInteger(r.valoare) ? 0 : 2)} ${r.unitate}`})),
               el("div",{class:"ajutor",text:r.explicatie}));
    if (va.v < va.n) rez.append(el("div",{class:"calc-avert" + (va.ok ? "" : " rau"),
      text: va.ok ? `Zile valide: ${va.v} din ${va.n} (${Math.round(100*va.v/va.n)} %), peste pragul de ${PRAG_VALID*100} %: în program, pixelul păstrează rezultatul.`
                  : `Zile valide: ${va.v} din ${va.n} (${Math.round(100*va.v/va.n)} %), sub pragul de ${PRAG_VALID*100} % (PRAG_VALID): în program, acest pixel ar deveni NoData, oricare ar fi rezultatul de mai sus.`}));
  }
  calc();
  cutie.append(el("p",{class:"ajutor",text:"Valorile se pot modifica (clic pe o celulă). Ștergeți o celulă (sau scrieți „nan”) ca să simulați o zi lipsă și urmăriți cum o tratează formula. Programul face exact același calcul pentru fiecare pixel și fiecare an, apoi combină anii."}),
    intrari, tabel, rez,
    el("a",{class:"leg mic",text:"↺ valorile inițiale",onclick:()=>{ SERIE = JSON.parse(JSON.stringify(SERIE_IMPLICITA)); arata(ACTIV_IND); }}));
  return cutie;
}

return {construieste, arata};
})();
