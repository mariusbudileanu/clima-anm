// harta.js — vizualizatorul de rastere al interfeței Clima ANM (fără biblioteci externe)
// Serverul trimite benzile ca float32 brut (EPSG:4326); aici se colorează, se desenează pe canvas cu corecția
// cos(φ) a longitudinii, se suprapune conturul vectorial și se compară două hărți cu un glisor (swipe).
"use strict";
const Harta = (() => {

// ------------------------------------------------------------------ palete (ColorBrewer, matplotlib)
const PAL = {
  viridis: ["440154","482878","3e4989","31688e","26828e","1f9e89","35b779","6ece58","b5de2b","fde725"],
  magma:   ["000004","180f3d","440f76","721f81","9e2f7f","cd4071","f1605d","fd9668","feca8d","fcfdbf"],
  YlOrRd:  ["ffffcc","ffeda0","fed976","feb24c","fd8d3c","fc4e2a","e31a1c","bd0026","800026"],
  YlOrBr:  ["ffffe5","fff7bc","fee391","fec44f","fe9929","ec7014","cc4c02","993404","662506"],
  YlGn:    ["ffffe5","f7fcb9","d9f0a3","addd8e","78c679","41ab5d","238443","006837","004529"],
  YlGnBu:  ["ffffd9","edf8b1","c7e9b4","7fcdbb","41b6c4","1d91c0","225ea8","253494","081d58"],
  GnBu:    ["f7fcf0","e0f3db","ccebc5","a8ddb5","7bccc4","4eb3d3","2b8cbe","0868ac","084081"],
  Blues:   ["f7fbff","deebf7","c6dbef","9ecae1","6baed6","4292c6","2171b5","08519c","08306b"],
  PuBu:    ["fff7fb","ece7f2","d0d1e6","a6bddb","74a9cf","3690c0","0570b0","045a8d","023858"],
  PuBuGn:  ["fff7fb","ece2f0","d0d1e6","a6bddb","67a9cf","3690c0","02818a","016c59","014636"],
  RdYlBu:  ["a50026","d73027","f46d43","fdae61","fee090","ffffbf","e0f3f8","abd9e9","74add1","4575b4","313695"],
  RdBu:    ["67001f","b2182b","d6604d","f4a582","fddbc7","f7f7f7","d1e5f0","92c5de","4393c3","2166ac","053061"],
  BrBG:    ["543005","8c510a","bf812d","dfc27d","f6e8c3","f5f5f5","c7eae5","80cdc1","35978f","01665e","003c30"],
};
const NUME_PAL = ["RdYlBu_r","YlOrRd","YlOrBr","viridis","magma_r","magma","Blues","YlGnBu","GnBu","PuBu","PuBuGn","YlGn","viridis_r","RdBu_r","BrBG"];
function stopuri(nume){
  const inv = nume.endsWith("_r"), b = PAL[inv ? nume.slice(0,-2) : nume] || PAL.viridis;
  const s = b.map(h => [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)]);
  return inv ? s.reverse() : s;
}
function lut(nume){                                  // 256 de culori interpolate
  const s = stopuri(nume), L = new Uint8Array(256*3);
  for (let i = 0; i < 256; i++){
    const t = i/255*(s.length-1), k = Math.min(Math.floor(t), s.length-2), f = t-k;
    for (let c = 0; c < 3; c++) L[i*3+c] = Math.round(s[k][c]*(1-f) + s[k+1][c]*f);
  }
  return L;
}
function ghiceste(b, cale){                          // paleta, când COG-ul nu o declară (rastere mai vechi / externe)
  const t = (b.descriere + " " + b.unitate + " " + cale).toLowerCase();
  const p = /precip|ploi|suma_p|_p[_.]|rx\d|cdd|uscat/.test(t);
  if (/p-valoare|p_valoare/.test(t)) return {cmap:"viridis_r"};
  if (/anomal|diferen|tendin|trend|abatere/.test(t)) return {cmap: p ? "BrBG" : "RdBu_r", divergent:true, centru: /%|procent/.test(t) ? 100 : 0};
  if (/% din normal|procent/.test(t)) return {cmap:"BrBG", divergent:true, centru:100};
  if (/rang/.test(t)) return {cmap:"viridis"};
  if (p) return {cmap:"YlGnBu"};
  if (/zile/.test(t)) return {cmap:"YlOrRd"};
  if (/°c|temp|tmax|tmin|tmed/.test(t)) return {cmap:"RdYlBu_r"};
  return {cmap:"viridis"};
}

// ------------------------------------------------------------------ starea
const S = {A:null, B:null, s:1, cx:0, cy:0, k:Math.cos(45.9*Math.PI/180), contur:null, conturCale:null,
           swipe:0.5, trage:null, rastere:[], cauta:"", initializat:false, w:0, h:0,
           relief:{pornit:false, forta:0.55, img:null, info:null, lipsa:false},
           anim:{ruleaza:false, viteza:700, timer:null, export:false}};
const DEM = "_date/dem_grila_zarr.tif";
const pauza = ms => new Promise(r => setTimeout(r, ms));
const ro = (x, d=1) => x == null || !isFinite(x) ? "–" : Number(x).toFixed(d).replace(".", ",").replace("-", "−");
const zec = v => { const a = Math.abs(v); return a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : 3; };

// ------------------------------------------------------------------ DOM
function construieste(){
  const v = $("#v-harta"); v.innerHTML = "";
  const lista = el("div",{class:"h-lista",id:"h-lista"});
  const cauta = el("input",{type:"text",class:"cauta",placeholder:"Caută un raster…",oninput:e=>{S.cauta=e.target.value; listeaza();}});
  v.append(
    el("aside",{class:"panou h-explorator"}, el("div",{class:"h-cap"}, el("b",{text:"Rasterele din rezultate"}),
        el("a",{class:"leg",text:"↻",title:"reîncarcă lista",onclick:incarcaLista})), cauta,
        el("div",{class:"ajutor",style:"margin:4px 2px 8px",text:"clic = harta principală (A) · „B” = a doua hartă, pentru comparație"}), lista),
    el("section",{class:"panou h-scena"},
      el("div",{class:"h-titlu",id:"h-titlu",text:"Alegeți un raster din listă"}),
      el("div",{class:"h-canvas",id:"h-cutie"}, el("canvas",{id:"h-canvas"}),
        el("div",{class:"h-unelte"}, el("button",{text:"+",title:"apropie",onclick:()=>zoom(1.5)}), el("button",{text:"−",title:"depărtează",onclick:()=>zoom(1/1.5)}),
          el("button",{text:"⤢",title:"toată harta (dublu-clic)",onclick:()=>{ incadreaza(); deseneaza(); }}),
          el("span",{class:"h-sep"}),
          el("button",{id:"h-bcomp",class:"text",text:"A|B",title:"Compară două hărți cu o cortină (tasta C)",onclick:comuta_comparatia}),
          el("button",{id:"h-brelief",text:"⛰",title:"Relieful (umbrire din DEM) sub hartă (tasta R)",onclick:comuta_relieful}),
          el("button",{id:"h-bprez",text:"⛶",title:"Modul prezentare: ecran complet (tasta P)",onclick:prezentare})),
        el("div",{class:"h-player",id:"h-player",style:"display:none"},
          el("button",{class:"h-play",id:"h-play",text:"▶",title:"pornește / oprește (spațiu)",onclick:()=>S.anim.ruleaza ? opreste() : porneste()}),
          el("div",{class:"h-an",id:"h-an",text:""}),
          el("input",{type:"range",id:"h-cursor",min:1,max:2,value:1,oninput:e=>cadru(+e.target.value)}),
          el("select",{id:"h-viteza",title:"viteza",onchange:e=>S.anim.viteza=+e.target.value},
            [[1400,"lent"],[700,"normal"],[350,"rapid"]].map(([v,t])=>el("option",{value:v,text:t}))),
          el("button",{class:"h-video",id:"h-video",text:"⬇ video",title:"exportă animația ca video (WebM/MP4), cu titlu și legendă",onclick:exportVideo})),
        el("div",{class:"h-legflot",id:"h-legflot"}),
        el("div",{class:"h-ajprez",text:"← → anii / benzile · spațiu: pornește · ↑ ↓ alt raster din rulare · C: comparație · R: relief · Esc: ieșire"})),
      el("div",{class:"h-stare",id:"h-stare",text:"mutați cursorul peste hartă"})),
    el("aside",{class:"panou h-control",id:"h-control"}));
  const c = $("#h-canvas");
  c.addEventListener("wheel", e => { e.preventDefault(); zoom(e.deltaY < 0 ? 1.25 : 0.8, e.offsetX, e.offsetY); }, {passive:false});
  c.addEventListener("mousedown", e => { S.trage = S.B && Math.abs(e.offsetX - S.swipe*S.w) < 9 ? {swipe:true} : {x:e.clientX, y:e.clientY, cx:S.cx, cy:S.cy}; });
  window.addEventListener("mouseup", () => S.trage = null);
  window.addEventListener("mousemove", e => {
    if (!S.trage) return;
    if (S.trage.swipe){ const r = c.getBoundingClientRect(); S.swipe = Math.min(0.98, Math.max(0.02, (e.clientX - r.left)/S.w)); }
    else { S.cx = S.trage.cx - (e.clientX - S.trage.x)/S.s; S.cy = S.trage.cy + (e.clientY - S.trage.y)/S.s; }
    deseneaza();
  });
  c.addEventListener("mousemove", e => { arataValoare(e.offsetX, e.offsetY); c.style.cursor = S.B && Math.abs(e.offsetX - S.swipe*S.w) < 9 ? "ew-resize" : (S.trage ? "grabbing" : "crosshair"); });
  c.addEventListener("dblclick", () => { incadreaza(); deseneaza(); });
  new ResizeObserver(() => { redimensioneaza(); deseneaza(); }).observe($("#h-cutie"));
  $("#h-viteza").value = S.anim.viteza;
  document.addEventListener("keydown", taste);
  document.addEventListener("fullscreenchange", () => { $("#h-bprez")?.classList.toggle("activ", !!document.fullscreenElement); });
  S.initializat = true;
}

async function incarcaLista(){
  const r = await api("/api/rastere");
  S.rastere = r.rastere || []; S.cos = r.cos || 0;
  if (!r.gdal) $("#h-lista").innerHTML = '<div class="gol">GDAL nu este disponibil în acest mediu: harta nu poate citi rasterele.</div>';
  else listeaza();
}

// Lista, grupată pe rulări (rezultate/<data_ora>_<analiza>/): cea mai recentă deschisă, restul pliate; căutarea
// deschide grupurile în care găsește ceva. Fiecare rulare: fișa vizuală, folderul, mutarea la coș.
S.deschise = new Set(); S.toate = false;
const DATA_RULARE = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})_/;
function grupuri(lista){
  const g = new Map();
  for (const r of lista){
    const k = r.cale.startsWith("_date/") ? "_relief" : (r.rulare || "_vechi");
    if (!g.has(k)) g.set(k, {cheie:k, rastere:[], titlu: r.rulare_titlu, fisa: r.fisa, mtime: 0});
    const x = g.get(k); x.rastere.push(r); x.mtime = Math.max(x.mtime, r.mtime || 0);
  }
  const rang = k => k === "_relief" ? 2 : k === "_vechi" ? 1 : 0;      // rulările, apoi rezultatele vechi, apoi relieful
  return [...g.values()].sort((a, b) => rang(a.cheie) - rang(b.cheie) || b.mtime - a.mtime);
}
function prefixComun(nume){
  if (nume.length < 2) return "";
  let p = nume[0];
  for (const n of nume) while (p && !n.startsWith(p)) p = p.slice(0, -1);
  return p.includes("_") ? p.slice(0, p.lastIndexOf("_") + 1) : "";
}
function textGrup(g){
  if (g.cheie === "_relief") return ["Relieful (DEM pe grila Zarr)", ""];
  if (g.cheie === "_vechi") return ["Rezultate mai vechi (fără folder de rulare)", ""];
  const m = g.cheie.match(DATA_RULARE);
  const cand = m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : "";
  return [g.titlu || g.cheie.replace(DATA_RULARE, "").replace(/_/g, " "), cand];
}
function listeaza(){
  const d = $("#h-lista"); d.innerHTML = "";
  const q = fara_diacritice(S.cauta).split(/\s+/).filter(Boolean);
  const potriveste = r => q.every(t => fara_diacritice(r.cale + " " + (r.rulare_titlu||"")).includes(t));
  const vizibile = S.rastere.filter(potriveste);
  if (!vizibile.length){ d.append(el("div",{class:"gol",text: S.rastere.length ? "Niciun raster nu se potrivește." : "Încă nu există GeoTIFF-uri în rezultate. Rulați o analiză cu ieșirea „GeoTIFF (COG)”."})); return; }
  const gr = grupuri(vizibile), MAX = 8;
  const rulari = gr.filter(g => !g.cheie.startsWith("_"));
  if (!S.deschise.size && rulari.length) S.deschise.add(rulari[0].cheie);           // cea mai recentă, deschisă
  for (const L of [S.A, S.B]) if (L) S.deschise.add(L.cale.startsWith("_date/") ? "_relief" : (L.cale.split("/").length > 1 ? L.cale.split("/")[0] : "_vechi"));
  let n = 0;
  for (const g of gr){
    const rulare = !g.cheie.startsWith("_");
    if (rulare && ++n > MAX && !S.toate && !q.length) continue;
    const deschis = q.length || S.deschise.has(g.cheie);
    const [titlu, cand] = textGrup(g);
    let pref = prefixComun(g.rastere.map(r => r.cale.split("/").pop()));
    if (pref && g.rastere.some(r => /^[\d.]/.test(r.cale.split("/").pop().slice(pref.length))))    // „30”, „35” spun prea puțin:
      pref = pref.slice(0, pref.slice(0, -1).lastIndexOf("_") + 1);                                  // păstrez și cuvântul de dinainte
    const cap = el("div",{class:"h-grup-cap"+(deschis?" deschis":""), onclick:()=>{ S.deschise.has(g.cheie) ? S.deschise.delete(g.cheie) : S.deschise.add(g.cheie); listeaza(); }},
      el("span",{class:"h-sageata",text:deschis?"▾":"▸"}),
      el("span",{class:"h-grup-titlu"}, titlu, el("span",{class:"h-meta",text:`${cand}${cand?" · ":""}${g.rastere.length} ${g.rastere.length===1?"raster":"rastere"}`})),
      rulare ? el("span",{class:"h-actiuni",onclick:e=>e.stopPropagation()},
        g.fisa ? el("a",{class:"h-act",text:"fișa",title:"fișa vizuală a rulării",href:"/rezultate/"+encodeURIComponent(g.cheie)+"/index.html",target:"_blank"}) : null,
        el("a",{class:"h-act",text:"📂",title:"deschide folderul rulării",onclick:()=>api("/api/deschide_folder",{folder:g.cheie})}),
        el("a",{class:"h-act",text:"🗑",title:"mută rularea la coș (rezultate/_cos)",onclick:()=>laCos(g)})) : null);
    const bloc = el("div",{class:"h-grup"+(g.cheie===rulari[0]?.cheie?" recent":"")}, cap);
    if (deschis) for (const r of g.rastere){
      const nume = r.cale.split("/").pop().replace(/\.tiff?$/,"");
      const serie = /_pe_ani$/.test(nume);
      const scurt = (pref && nume.length > pref.length ? nume.slice(pref.length) : nume).replace(/_pe_ani$/, "").replace(/_/g, " ").replace(/\bge\b/g, "≥").replace(/\ble\b/g, "≤").replace(/\bgt\b/g, ">").replace(/\blt\b/g, "<");
      const activ = (S.A && S.A.cale === r.cale) ? " activ" : (S.B && S.B.cale === r.cale) ? " activB" : "";
      bloc.append(el("div",{class:"h-item"+activ,title:r.cale},
        el("div",{class:"h-nume",onclick:()=>deschide(r.cale,"A")}, scurt, serie ? " " : null, serie ? el("span",{class:"h-anim",text:"▶ pe ani"}) : null,
          el("span",{class:"h-meta",text:serie ? `animație · ${fmtMB(r.marime)}` : fmtMB(r.marime)})),
        el("button",{class:"h-b",text:"B",title:"compară: a doua hartă, cu cortină (trageți linia de pe hartă)",onclick:()=>deschide(r.cale,"B")})));
    }
    d.append(bloc);
  }
  const ascunse = rulari.length - MAX;
  const jos = el("div",{class:"h-jos"});
  if (ascunse > 0 && !q.length) jos.append(el("a",{class:"leg",text: S.toate ? "doar ultimele 8 rulări" : `arată toate rulările (încă ${ascunse})`, onclick:()=>{ S.toate = !S.toate; listeaza(); }}));
  if (S.cos) jos.append(el("a",{class:"leg",text:`golește coșul (${S.cos} ${S.cos===1?"rulare":"rulări"})`,onclick:golesteCosul}));
  if (jos.children.length) d.append(jos);
}
async function laCos(g){
  const [titlu] = textGrup(g);
  if (!confirm(`Mutați la coș rularea „${titlu}”?\n\nFolderul ajunge în rezultate/_cos; îl puteți recupera de acolo până goliți coșul.`)) return;
  if (S.A && S.A.cale.startsWith(g.cheie + "/")) { S.A = null; S.B = null; }
  if (S.B && S.B.cale.startsWith(g.cheie + "/")) S.B = null;
  const r = await api("/api/la_cos", {folder: g.cheie});
  if (r.eroare) { mesaj(r.eroare); return; }
  await incarcaLista(); controale(); deseneaza();
}
async function golesteCosul(){
  if (!confirm(`Ștergeți definitiv cele ${S.cos} rulări din coș (rezultate/_cos)? Operația nu se poate anula.`)) return;
  await api("/api/goleste_cosul", {}); await incarcaLista();
}

// ------------------------------------------------------------------ straturile
async function deschide(cale, cine="A"){
  arataVedere("harta");
  if (!S.rastere.length) await incarcaLista();
  const info = await api("/api/raster?cale=" + encodeURIComponent(cale));
  if (info.eroare){ mesaj(info.eroare); return; }
  if (cine === "A") opreste();
  const L = {cale, info, banda:1, cache:new Map(), ani: info.ani || null};
  S[cine] = L;
  await alegeBanda(L, 1, true);
  if (cine === "B" && S.A && S.A.cale === cale) Object.assign(L, {min:S.A.min, max:S.A.max, cmap:S.A.cmap}), coloreaza(L);
  if (cine === "A") S.B = null;                       // o hartă A nouă închide comparația; B se alege după
  if (cine === "A") incadreaza();
  if (!S.contur && S.conturCale === null) await alegeContur(conturImplicit());
  listeaza(); controale(); deseneaza();
}

async function dateBanda(L, nr){
  if (!L.cache) L.cache = new Map();
  if (!L.cache.has(nr)){
    const r = await fetch(`/api/raster_banda?cale=${encodeURIComponent(L.cale)}&banda=${nr}`, {headers:{"X-Jeton":JETON}});
    L.cache.set(nr, new Float32Array(await r.arrayBuffer()));
  }
  return L.cache.get(nr);
}
async function alegeBanda(L, nr, resetScala=true){
  L.banda = nr;
  const b = L.info.benzi[nr-1];
  L.date = await dateBanda(L, nr);
  if (resetScala || !L.cmap){
    const b1 = L.ani ? L.info.benzi[0] : b;              // seria pe ani: paleta și scara sunt ale întregii serii
    const g = b1.cmap ? {cmap:b1.cmap, divergent:b1.divergent, centru:b1.centru} : ghiceste(b1, L.cale);
    L.cmap = g.cmap; L.divergent = !!g.divergent; L.centru = g.centru ?? 0; L.clase = b1.clase;
    scalaAuto(L);
  }
  coloreaza(L);
}

function scalaAuto(L, tot=false){
  if (L.ani){                                            // o scară comună tuturor anilor: culorile se pot compara
    const B = L.info.benzi.filter(x => x.n_valide);
    if (!tot && L.info.scara){ [L.min, L.max] = L.info.scara; }
    else if (B.length){
      L.min = Math.min(...B.map(x => tot ? x.min : x.p02)); L.max = Math.max(...B.map(x => tot ? x.max : x.p98));
      if (L.divergent){ const m = Math.max(Math.abs(L.min - L.centru), Math.abs(L.max - L.centru)); L.min = L.centru - m; L.max = L.centru + m; }
    }
    if (L.min === L.max){ L.min -= 0.5; L.max += 0.5; }
    return;
  }
  const b = L.info.benzi[L.banda-1];
  if (L.divergent){
    const m = tot ? Math.max(Math.abs(b.max - L.centru), Math.abs(b.min - L.centru)) : (b.p98abs || 1);
    L.min = L.centru - m; L.max = L.centru + m;
  } else { L.min = tot ? b.min : b.p02; L.max = tot ? b.max : b.p98; }
  if (L.min === L.max){ L.min -= 0.5; L.max += 0.5; }
}

function coloreaza(L){
  const {latime:w, inaltime:h} = L.info, T = lut(L.cmap);
  const c = L.img || document.createElement("canvas"); c.width = w; c.height = h;
  const ctx = c.getContext("2d"), im = ctx.createImageData(w, h), px = im.data, d = L.date;
  const lo = L.min, sc = 255/(L.max - L.min), cl = L.clase, nc = cl ? cl.length + 1 : 0;
  for (let i = 0; i < d.length; i++){
    const v = d[i]; if (!(v === v)) { px[i*4+3] = 0; continue; }       // NaN → transparent
    let k;
    if (cl){ let j = 0; while (j < cl.length && v >= cl[j]) j++; k = Math.round((j + 0.5)/nc*255); }
    else k = Math.max(0, Math.min(255, Math.round((v - lo)*sc)));
    px[i*4] = T[k*3]; px[i*4+1] = T[k*3+1]; px[i*4+2] = T[k*3+2]; px[i*4+3] = 255;
  }
  ctx.putImageData(im, 0, 0); L.img = c;
}

// ------------------------------------------------------------------ geometria ecranului
function redimensioneaza(){
  const c = $("#h-canvas"), cut = $("#h-cutie"); if (!c) return;
  const r = window.devicePixelRatio || 1; S.w = cut.clientWidth; S.h = cut.clientHeight;
  c.width = S.w*r; c.height = S.h*r; c.style.width = S.w+"px"; c.style.height = S.h+"px";
  c.getContext("2d").setTransform(r,0,0,r,0,0);
  if (S.A && !S.s0) incadreaza();
}
function incadreaza(){
  const L = S.A; if (!L || !S.w) return;
  const i = L.info, lat0 = i.y0 - i.inaltime*i.dy/2;
  S.k = Math.cos(lat0*Math.PI/180);
  const lx = i.latime*i.dx*S.k, ly = i.inaltime*i.dy;
  S.s = Math.min(S.w/lx, S.h/ly)*0.94; S.s0 = S.s;
  S.cx = (i.x0 + i.latime*i.dx/2)*S.k; S.cy = lat0;
}
const ecran = (lon, lat) => [(lon*S.k - S.cx)*S.s + S.w/2, (S.cy - lat)*S.s + S.h/2];
const geo = (x, y) => [((x - S.w/2)/S.s + S.cx)/S.k, S.cy - (y - S.h/2)/S.s];
function zoom(f, x=S.w/2, y=S.h/2){
  const [lon, lat] = geo(x, y); S.s *= f;
  const [x2, y2] = ecran(lon, lat); S.cx += (x2 - x)/S.s; S.cy -= (y2 - y)/S.s; deseneaza();
}

// ------------------------------------------------------------------ desenul
function stratPeCanvas(ctx, L){
  const i = L.info, [x, y] = ecran(i.x0, i.y0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(L.img, x, y, i.latime*i.dx*S.k*S.s, i.inaltime*i.dy*S.s);
}
function deseneaza(ctx = $("#h-canvas")?.getContext("2d")){
  if (!ctx) return;
  ctx.fillStyle = "#f3f5f8"; ctx.fillRect(0, 0, S.w, S.h);
  if (!S.A) return;
  stratPeCanvas(ctx, S.A);
  if (S.B){
    ctx.save(); ctx.beginPath(); ctx.rect(S.swipe*S.w, 0, S.w, S.h); ctx.clip();
    ctx.fillStyle = "#f3f5f8"; ctx.fillRect(S.swipe*S.w, 0, S.w, S.h); stratPeCanvas(ctx, S.B); ctx.restore();
  }
  if (S.relief.pornit && S.relief.img){
    const i = S.relief.info, [x, y] = ecran(i.x0, i.y0);
    ctx.save(); ctx.globalCompositeOperation = "soft-light"; ctx.globalAlpha = Math.min(1, S.relief.forta*1.6);
    ctx.imageSmoothingEnabled = true; ctx.drawImage(S.relief.img, x, y, i.latime*i.dx*S.k*S.s, i.inaltime*i.dy*S.s);
    ctx.restore();
  }
  if (S.contur){
    ctx.strokeStyle = "rgba(30,36,48,.75)"; ctx.lineWidth = 0.8; ctx.beginPath();
    for (const inel of S.contur.inele){ inel.forEach(([lo, la], j) => { const [x, y] = ecran(lo, la); j ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); }
    ctx.stroke();
  }
  if (S.B){
    const x = S.swipe*S.w;
    ctx.fillStyle = "#0f6b8c"; ctx.fillRect(x - 1.5, 0, 3, S.h);
    ctx.beginPath(); ctx.arc(x, S.h/2, 11, 0, 2*Math.PI); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "bold 11px system-ui"; ctx.textAlign = "center"; ctx.fillText("⇆", x, S.h/2 + 4);
    ctx.font = "600 12px system-ui"; ctx.fillStyle = "rgba(29,36,48,.85)";
    if (!(S.A.ani && S.B.ani)){ const y = $("#h-player")?.style.display === "none" ? 20 : 66;
      ctx.textAlign = "left"; ctx.fillText("A", 10, y); ctx.textAlign = "right"; ctx.fillText("B", S.w - 10, y); }
  }
  const anul = L => L && L.ani ? L.info.benzi[L.banda-1].descriere : null;       // eticheta mare a anului
  const eA = anul(S.A), eB = S.B ? anul(S.B) : null;
  if (eA || eB){
    const m = Math.max(28, Math.min(64, S.w/12));
    ctx.save(); ctx.font = `700 ${m}px ${getComputedStyle(document.body).getPropertyValue("--titluri") || "system-ui"}`;
    ctx.lineJoin = "round"; ctx.lineWidth = 5; ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.fillStyle = "#172634";
    ctx.textBaseline = "bottom";
    if (eA){ ctx.textAlign = "left"; ctx.strokeText(eA, 18, S.h - 14); ctx.fillText(eA, 18, S.h - 14); }
    if (eB){ ctx.textAlign = "right"; ctx.strokeText(eB, S.w - 18, S.h - 14); ctx.fillText(eB, S.w - 18, S.h - 14); }
    ctx.restore();
  }
}

// ------------------------------------------------------------------ valoarea de sub cursor
function valoare(L, lon, lat){
  if (!L) return null;
  const i = L.info, c = Math.floor((lon - i.x0)/i.dx), r = Math.floor((i.y0 - lat)/i.dy);
  if (c < 0 || r < 0 || c >= i.latime || r >= i.inaltime) return null;
  return L.date[r*i.latime + c];
}
function inPoligon(lon, lat){
  if (!S.contur) return null;
  for (const f of S.contur.entitati){
    let in_ = false;
    for (const inel of f.inele) for (let i = 0, j = inel.length - 1; i < inel.length; j = i++){
      const [xi, yi] = inel[i], [xj, yj] = inel[j];
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi)*(lat - yi)/(yj - yi) + xi) in_ = !in_;
    }
    if (in_) return f.nume;
  }
  return null;
}
function arataValoare(x, y){
  if (!S.A) return;
  const [lon, lat] = geo(x, y), u = L => L.info.benzi[L.banda-1].unitate;
  const fmt = (L) => { const v = valoare(L, lon, lat); return v == null || !(v === v) ? "fără date" : `${ro(v, zec(v))} ${u(L)}`; };
  const z = inPoligon(lon, lat);
  $("#h-stare").textContent = `lon ${ro(lon,3)} · lat ${ro(lat,3)}${z ? " · " + z : ""}  —  ` +
    (S.B ? `A: ${fmt(S.A)}  ·  B: ${fmt(S.B)}` : fmt(S.A));
}

// ------------------------------------------------------------------ conturul
function conturImplicit(){
  const v = CAT.vectori || [];
  return v.find(x => /judet/i.test(x)) || v.find(x => /frontier|granit/i.test(x)) || v[0] || "";
}
async function alegeContur(cale){
  S.conturCale = cale || "";
  if (!cale){ S.contur = null; deseneaza(); return; }
  const g = await api("/api/contur?cale=" + encodeURIComponent(cale));
  if (g.eroare){ mesaj("Conturul nu poate fi citit: " + g.eroare); S.contur = null; return; }
  const inele = [], entitati = [];
  for (const f of g.features){
    const gm = f.geometry, poli = gm.type === "Polygon" ? [gm.coordinates] : gm.type === "MultiPolygon" ? gm.coordinates :
               gm.type === "LineString" ? [[gm.coordinates]] : gm.type === "MultiLineString" ? [gm.coordinates] : [];
    const ale = []; poli.forEach(p => p.forEach(r => { inele.push(r); ale.push(r); }));
    entitati.push({nume: f.properties.nume, inele: ale});
  }
  S.contur = {inele, entitati}; deseneaza();
}

// ------------------------------------------------------------------ panoul de control
function legenda(L){
  const c = el("canvas",{width:240,height:14,class:"h-leg"}), ctx = c.getContext("2d"), T = lut(L.cmap);
  if (L.clase){
    const n = L.clase.length + 1;
    for (let j = 0; j < n; j++){ const k = Math.round((j+0.5)/n*255); ctx.fillStyle = `rgb(${T[k*3]},${T[k*3+1]},${T[k*3+2]})`; ctx.fillRect(j*240/n, 0, 240/n + 1, 14); }
    return el("div",{}, c, el("div",{class:"h-ticks"}, ...["<"+L.clase[0], ...L.clase.slice(1).map(String), "≥"+L.clase[L.clase.length-1]].map(t=>el("span",{text:t}))));
  }
  for (let x = 0; x < 240; x++){ const k = Math.round(x/239*255); ctx.fillStyle = `rgb(${T[k*3]},${T[k*3+1]},${T[k*3+2]})`; ctx.fillRect(x, 0, 1, 14); }
  const u = L.info.benzi[L.banda-1].unitate, d = zec(Math.max(Math.abs(L.min), Math.abs(L.max)));
  return el("div",{}, c, el("div",{class:"h-ticks"}, el("span",{text:ro(L.min,d)}), el("span",{text:ro((L.min+L.max)/2,d)}), el("span",{text:`${ro(L.max,d)} ${u}`})));
}

function blocStrat(L, cine){
  const b = L.info.benzi[L.banda-1];
  const banda = el("select",{}, L.info.benzi.map(x => el("option",{value:x.nr,text:`${x.nr}. ${x.descriere}`})));
  banda.value = L.banda; banda.onchange = async () => { await alegeBanda(L, +banda.value, true); controale(); deseneaza(); };
  const pal = el("select",{}, [...new Set([L.cmap, ...NUME_PAL])].map(p => el("option",{value:p,text:p})));
  pal.value = L.cmap; pal.onchange = () => { L.cmap = pal.value; coloreaza(L); controale(); deseneaza(); };
  const mn = el("input",{type:"number",step:"any",value:+L.min.toPrecision(4)}), mx = el("input",{type:"number",step:"any",value:+L.max.toPrecision(4)});
  const aplica = () => { const a = num(mn.value), z = num(mx.value); if (a != null && z != null && z > a){ L.min = a; L.max = z; coloreaza(L); controale(); deseneaza(); } };
  mn.onchange = aplica; mx.onchange = aplica;
  const div = el("input",{type:"checkbox"}); div.checked = L.divergent;
  const centru = el("input",{type:"number",step:"any",value:L.centru,style:"width:70px"});
  div.onchange = centru.onchange = () => { L.divergent = div.checked; L.centru = num(centru.value) ?? 0; scalaAuto(L); coloreaza(L); controale(); deseneaza(); };
  const statistici = b.n_valide ? `${b.n_valide.toLocaleString("ro-RO")} pixeli valizi · min ${ro(b.min, zec(b.min))} · max ${ro(b.max, zec(b.max))}` : "banda nu are pixeli valizi";
  return el("div",{class:"h-bloc"},
    el("div",{class:"h-cap"}, el("b",{text: cine === "A" ? "Harta A" : "Harta B (dreapta glisorului)"}),
      cine === "B" ? el("a",{class:"leg",text:"scoate",onclick:()=>{ S.B = null; listeaza(); controale(); deseneaza(); }}) : null),
    el("div",{class:"h-fis",text:L.cale}),
    L.info.reproiectat || L.info.micsorat > 1 ? el("div",{class:"ajutor",text:(L.info.reproiectat ? "reproiectat în EPSG:4326 · " : "") + (L.info.micsorat > 1 ? `afișat micșorat ×${L.info.micsorat}` : "")}) : null,
    el("label",{class:"et",text:"Banda"}), banda,
    el("label",{class:"et",text:"Paleta"}), pal,
    el("label",{class:"et",text:"Scara culorilor"}), el("div",{class:"rand"}, mn, "–", mx),
    el("div",{class:"mic",style:"margin-top:4px"}, el("a",{class:"leg",text:"2–98 %",onclick:()=>{ scalaAuto(L); coloreaza(L); controale(); deseneaza(); }}),
      el("a",{class:"leg",text:"min–max",onclick:()=>{ scalaAuto(L, true); coloreaza(L); controale(); deseneaza(); }}),
      cine === "B" ? el("a",{class:"leg",text:"ca A",onclick:()=>{ Object.assign(L, {min:S.A.min, max:S.A.max, cmap:S.A.cmap, divergent:S.A.divergent, centru:S.A.centru}); coloreaza(L); controale(); deseneaza(); }}) : null),
    el("label",{class:"h-check"}, div, " divergentă, simetrică față de ", centru),
    L.clase ? el("div",{class:"ajutor",text:"clase: " + L.clase.join(" · ")}) : null,
    legenda(L), el("div",{class:"ajutor",text:statistici}));
}

function controale(){
  const d = $("#h-control"); if (!d) return; d.innerHTML = "";
  if (!S.A){ d.append(el("div",{class:"gol",text:"Alegeți un raster din lista din stânga."})); return; }
  actualizeazaTitlu();
  const lf = $("#h-legflot"); lf.innerHTML = ""; lf.append(legenda(S.A));
  if (S.B && (S.B.cmap !== S.A.cmap || S.B.min !== S.A.min || S.B.max !== S.A.max)) lf.append(el("div",{class:"h-legB",text:"B:"}), legenda(S.B));
  player();
  d.append(blocStrat(S.A, "A"));
  d.append(S.B ? blocStrat(S.B, "B") : blocAlegeB());
  $("#h-bcomp")?.classList.toggle("activ", !!S.B);
  const sc = el("select",{}, el("option",{value:"",text:"— fără contur —"}), (CAT.vectori||[]).map(v => el("option",{value:v,text:v})));
  sc.value = S.conturCale || ""; sc.onchange = () => alegeContur(sc.value);
  d.append(el("div",{class:"h-bloc"}, el("label",{class:"et",text:"Contur"}), sc,
    el("label",{class:"et",text:"Imagine"}), el("button",{class:"b",text:"Salvează harta ca PNG",onclick:salveazaPNG})));
}

// ------------------------------------------------------------------ export PNG (harta + titlu + legendă + atribuire)
function salveazaPNG(){
  const c = compune(document.createElement("canvas"), 1600), L = S.A;
  const sufix = L.ani ? "_" + L.info.benzi[L.banda-1].descriere.replace(/\W+/g, "_") : "";
  c.toBlob(b => { const a = el("a",{href:URL.createObjectURL(b),download:L.cale.split("/").pop().replace(/\.tiff?$/,"") + sufix + "_harta.png"}); a.click(); });
}
function compune(c, W){                                 // harta + titlu + legendă + atribuire, la lățimea W
  const Hm = Math.round(W*S.h/S.w/2)*2, H = Hm + 120 + (S.B ? 26 : 0); c.width = W; c.height = H;
  const ctx = c.getContext("2d"), f = W/S.w, salv = {w:S.w, h:S.h, s:S.s};
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);
  ctx.save(); ctx.translate(0, 50); ctx.beginPath(); ctx.rect(0, 0, W, Hm); ctx.clip();
  S.w = W; S.h = Hm; S.s = salv.s*f; deseneaza(ctx); ctx.restore();
  Object.assign(S, salv);
  ctx.fillStyle = "#1d2430"; ctx.font = "600 22px system-ui"; ctx.textAlign = "left";
  ctx.fillText($("#h-titlu").textContent, 20, 33);
  const y = 50 + Hm + 22, L = S.A;
  const legendaPNG = (Lx, x0, eticheta) => {                // bara de culori + capetele scării (A, și B dacă există)
    const T = lut(Lx.cmap), d = zec(Math.max(Math.abs(Lx.min), Math.abs(Lx.max))), u = Lx.info.benzi[Lx.banda-1].unitate;
    if (Lx.clase){                                        // clase discrete (ex. De Martonne): aceleași casete ca pe ecran
      const n = Lx.clase.length + 1, w = 360 / n;
      const et = ["<" + Lx.clase[0], ...Lx.clase.slice(1).map(String), "≥" + Lx.clase[Lx.clase.length-1]];
      for (let j = 0; j < n; j++){ const k = Math.round((j+0.5)/n*255); ctx.fillStyle = `rgb(${T[k*3]},${T[k*3+1]},${T[k*3+2]})`; ctx.fillRect(x0 + j*w, y, w + 0.5, 16); }
      ctx.fillStyle = "#1d2430"; ctx.font = "13px system-ui"; ctx.textAlign = "center";
      et.forEach((t, j) => ctx.fillText(t, x0 + (j + 0.5)*w, y + 34));
      if (eticheta){ ctx.textAlign = "right"; ctx.fillText(eticheta, x0 - 4, y + 13); }
      return;
    }
    for (let x = 0; x < 360; x++){ const k = Math.round(x/359*255); ctx.fillStyle = `rgb(${T[k*3]},${T[k*3+1]},${T[k*3+2]})`; ctx.fillRect(x0 + x, y, 1, 16); }
    ctx.fillStyle = "#1d2430"; ctx.font = "14px system-ui"; ctx.textAlign = "left";
    ctx.fillText((eticheta ? eticheta + "  " : "") + ro(Lx.min,d), x0, y + 36);
    ctx.textAlign = "right"; ctx.fillText(`${ro(Lx.max,d)} ${u}`, x0 + 360, y + 36);
  };
  const doua = S.B && (S.B.cmap !== L.cmap || S.B.min !== L.min || S.B.max !== L.max);    // aceeași scară: o legendă
  legendaPNG(L, 20, doua ? "A:" : "");
  if (doua) legendaPNG(S.B, 420, "B:");
  ctx.fillStyle = "#667085"; ctx.font = "13px system-ui"; ctx.textAlign = "right";
  if (doua) ctx.translate(0, 26);
  ctx.fillText("Date: ANM / MeteoRomania · procesare: UVT – EOCube.Ro · CC-BY-4.0" + (S.relief.pornit && S.relief.img ? " · relief: Copernicus GLO-30" : ""), W - 20, y + 36);
  return c;
}

// ------------------------------------------------------------------ titlul hărții
function actualizeazaTitlu(){
  const t = L => { const b = L.info.benzi[L.banda-1]; return L.ani && L.info.titlu ? `${L.info.titlu} · ${b.descriere}` : b.descriere; };
  $("#h-titlu").textContent = S.A ? t(S.A) + (S.B ? "   ⇆   " + t(S.B) : "") : "Alegeți un raster din listă";
}

// ------------------------------------------------------------------ animația pe ani (rasterele „…_pe_ani.tif”)
function player(){
  const P = $("#h-player"), L = S.A; if (!P) return;
  const n = L ? L.info.benzi.length : 0;
  P.style.display = L && L.ani && n > 1 ? "" : "none";            // doar seriile pe ani; benzile obișnuite: ← →
  if (!L || !L.ani || n < 2) return;
  P.classList.toggle("serie", !!L.ani);
  const c = $("#h-cursor"); c.max = n; c.value = L.banda;
  $("#h-an").textContent = L.ani ? L.info.benzi[L.banda-1].descriere : `banda ${L.banda}/${n}`;
  $("#h-play").textContent = S.anim.ruleaza ? "❚❚" : "▶";
  $("#h-video").style.display = L.ani ? "" : "none";
}
async function incarcaToate(L, eticheta){              // toate benzile în memorie, ca animația să curgă fără sacadări
  const n = L.info.benzi.length;
  for (let i = 1; i <= n; i++){
    if (!L.cache.has(i)){ $("#h-an").textContent = `${eticheta || "se încarcă"} ${i}/${n}`; await dateBanda(L, i); }
  }
}
async function cadru(nr){
  const L = S.A; if (!L) return;
  nr = ((nr - 1 + L.info.benzi.length) % L.info.benzi.length) + 1;
  await alegeBanda(L, nr, false);
  actualizeazaTitlu(); player(); deseneaza();
  const sel = document.querySelector("#h-control select"); if (sel) sel.value = nr;          // banda din panoul A
}
async function porneste(){
  const L = S.A; if (!L || L.info.benzi.length < 2 || S.anim.ruleaza) return;
  S.anim.ruleaza = true; player();
  await incarcaToate(L);
  if (L.banda === L.info.benzi.length) await cadru(1);
  const pas = async () => {
    if (!S.anim.ruleaza || S.A !== L) return;
    const t0 = performance.now();
    await cadru(L.banda + 1);
    if (L.banda === L.info.benzi.length){ S.anim.timer = setTimeout(() => { if (S.anim.ruleaza) pas(); }, S.anim.viteza*2.5); return; }
    S.anim.timer = setTimeout(pas, Math.max(30, S.anim.viteza - (performance.now() - t0)));
  };
  S.anim.timer = setTimeout(pas, S.anim.viteza);
}
function opreste(){ S.anim.ruleaza = false; clearTimeout(S.anim.timer); player(); }

async function exportVideo(){
  const L = S.A; if (!L || !L.ani || S.anim.export) return;
  if (!window.MediaRecorder){ mesaj("Browserul nu poate înregistra video (MediaRecorder lipsește)."); return; }
  opreste(); S.anim.export = true;
  const tip = ["video/mp4;codecs=avc1", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find(t => MediaRecorder.isTypeSupported(t));
  const banda0 = L.banda, buton = $("#h-video");
  try {
    await incarcaToate(L, "pregătesc");
    buton.disabled = true;
    const c = document.createElement("canvas"); await alegeBanda(L, 1, false); actualizeazaTitlu(); compune(c, 1280);
    const flux = c.captureStream(0), pista = flux.getVideoTracks()[0];
    const rec = new MediaRecorder(flux, {mimeType: tip, videoBitsPerSecond: 8e6}), bucati = [];
    rec.ondataavailable = e => { if (e.data.size) bucati.push(e.data); };
    const gata = new Promise(r => rec.onstop = r);
    rec.start();
    const n = L.info.benzi.length;
    for (let i = 1; i <= n; i++){
      buton.textContent = `● ${i}/${n}`;
      await alegeBanda(L, i, false); actualizeazaTitlu(); deseneaza(); compune(c, 1280);
      pista.requestFrame?.();
      await pauza(i === n ? S.anim.viteza*3 : S.anim.viteza);
    }
    pista.requestFrame?.(); await pauza(100);
    rec.stop(); await gata;
    const ext = tip.startsWith("video/mp4") ? "mp4" : "webm";
    const a = el("a",{href:URL.createObjectURL(new Blob(bucati, {type: tip.split(";")[0]})),
                      download: L.cale.split("/").pop().replace(/\.tiff?$/,"") + "." + ext});
    a.click();
    mesaj(`Video salvat (${ext.toUpperCase()}, ${n} cadre, ${(S.anim.viteza/1000).toLocaleString("ro-RO")} s pe an).`);
  } catch (e){ mesaj("Exportul video a eșuat: " + e); }
  finally {
    S.anim.export = false; buton.disabled = false; buton.textContent = "⬇ video";
    await cadru(banda0);
  }
}

// ------------------------------------------------------------------ comparația A | B
function blocAlegeB(){
  const opt = [];
  if (S.A.info.benzi.length > 1)
    opt.push(el("optgroup",{label: S.A.ani ? "aceeași serie, alt an" : "același raster, altă bandă"},
      S.A.info.benzi.filter(b => b.nr !== S.A.banda).map(b => el("option",{value:"#"+b.nr,text:b.descriere}))));
  const rul = S.A.cale.split("/").length > 1 ? S.A.cale.split("/")[0] : null;
  const dinRulare = S.rastere.filter(r => r.cale !== S.A.cale && rul && r.cale.startsWith(rul + "/"));
  const altele = S.rastere.filter(r => r.cale !== S.A.cale && !dinRulare.includes(r)).slice(0, 60);
  const numeR = r => r.cale.split("/").pop().replace(/\.tiff?$/,"").replace(/_/g," ");
  if (dinRulare.length) opt.push(el("optgroup",{label:"din aceeași rulare"}, dinRulare.map(r => el("option",{value:r.cale,text:numeR(r)}))));
  if (altele.length) opt.push(el("optgroup",{label:"alte rulări"}, altele.map(r => el("option",{value:r.cale,text:(r.rulare_titlu ? r.rulare_titlu + " · " : "") + numeR(r)}))));
  const sel = el("select",{id:"h-alegeB"}, el("option",{value:"",text:"— alegeți harta B —"}), opt);
  sel.onchange = () => comparaCu(sel.value);
  return el("div",{class:"h-bloc h-faraB"},
    el("div",{class:"h-cap"}, el("b",{text:"Compară cu o hartă B"})),
    el("div",{class:"ajutor",style:"margin-bottom:6px",text:"B apare în dreapta cortinei; trageți linia albastră peste hartă. Se poate alege și din listă, cu butonul „B”."}),
    sel);
}
async function comparaCu(v){
  if (!v || !S.A) return;
  if (v.startsWith("#")){                                // aceeași hartă, altă bandă (alt an)
    const nr = +v.slice(1), L = {cale:S.A.cale, info:S.A.info, banda:nr, cache:S.A.cache, ani:S.A.ani};
    S.B = L; await alegeBanda(L, nr, true);
    Object.assign(L, {min:S.A.min, max:S.A.max, cmap:S.A.cmap, divergent:S.A.divergent, centru:S.A.centru}); coloreaza(L);
    S.swipe = 0.5; listeaza(); controale(); deseneaza(); return;
  }
  S.swipe = 0.5; await deschide(v, "B");
}
function comuta_comparatia(){
  if (!S.A) return;
  if (S.B){ S.B = null; listeaza(); controale(); deseneaza(); }
  else if (S.A.info.benzi.length > 1){                  // seria pe ani: primul an | ultimul an
    const n = S.A.info.benzi.length;
    (async () => { if (S.A.banda === n) await cadru(1); await comparaCu("#" + n); })();
  } else {
    const s = $("#h-alegeB"); if (s){ s.focus(); s.classList.add("clipeste"); setTimeout(() => s.classList.remove("clipeste"), 1200); }
  }
}

// ------------------------------------------------------------------ relieful (umbrire calculată din DEM, în browser)
async function incarcaRelief(){
  if (S.relief.img || S.relief.lipsa) return !!S.relief.img;
  const info = await api("/api/raster?cale=" + encodeURIComponent(DEM));
  if (info.eroare){ S.relief.lipsa = true; mesaj("Relieful nu e disponibil: lipsește date/dem_grila_zarr.tif."); return false; }
  const r = await fetch(`/api/raster_banda?cale=${encodeURIComponent(DEM)}&banda=1`, {headers:{"X-Jeton":JETON}});
  const z = new Float32Array(await r.arrayBuffer()), w = info.latime, h = info.inaltime;
  const lat0 = info.y0 - h*info.dy/2, mx = info.dx*111320*Math.cos(lat0*Math.PI/180), my = info.dy*111320;
  const ex = 2.0, zen = (90 - 45)*Math.PI/180, az = (360 - 315 + 90)*Math.PI/180, plat = Math.cos(zen);
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  const ctx = c.getContext("2d"), im = ctx.createImageData(w, h), px = im.data;
  const Z = (rr, cc) => { const v = z[Math.min(h-1, Math.max(0, rr))*w + Math.min(w-1, Math.max(0, cc))]; return v === v ? v : NaN; };
  for (let rr = 0; rr < h; rr++) for (let cc = 0; cc < w; cc++){
    const i = rr*w + cc, z0 = z[i];
    if (!(z0 === z0)){ px[i*4+3] = 0; continue; }
    let a = Z(rr, cc+1), b = Z(rr, cc-1), d = Z(rr+1, cc), u = Z(rr-1, cc);
    if (!(a === a)) a = z0; if (!(b === b)) b = z0; if (!(d === d)) d = z0; if (!(u === u)) u = z0;
    const dzdx = (a - b)/(2*mx), dzdy = (d - u)/(2*my);
    const panta = Math.atan(ex*Math.hypot(dzdx, dzdy)), asp = Math.atan2(dzdy, -dzdx);
    const hs = Math.cos(zen)*Math.cos(panta) + Math.sin(zen)*Math.sin(panta)*Math.cos(az - asp);
    const g = Math.max(0, Math.min(255, 128 + (hs - plat)*330));        // 128 = neutru pentru „soft-light”
    px[i*4] = px[i*4+1] = px[i*4+2] = g; px[i*4+3] = 255;
  }
  ctx.putImageData(im, 0, 0);
  S.relief.img = c; S.relief.info = info;
  return true;
}
async function comuta_relieful(){
  if (!S.relief.pornit && !(await incarcaRelief())) return;
  S.relief.pornit = !S.relief.pornit;
  $("#h-brelief")?.classList.toggle("activ", S.relief.pornit);
  deseneaza();
}

// ------------------------------------------------------------------ modul prezentare și tastele
function prezentare(){
  const sc = document.querySelector("#v-harta .h-scena"); if (!sc) return;
  if (document.fullscreenElement) document.exitFullscreen();
  else sc.requestFullscreen?.().catch(e => mesaj("Ecranul complet nu e permis: " + e));
}
async function rasterVecin(d){
  if (!S.A) return;
  const rul = S.A.cale.split("/").length > 1 ? S.A.cale.split("/")[0] : null;
  const lista = S.rastere.filter(r => rul ? r.cale.startsWith(rul + "/") : !r.cale.includes("/"));
  const i = lista.findIndex(r => r.cale === S.A.cale);
  if (lista.length < 2 || i < 0) return;
  const t = lista[(i + d + lista.length) % lista.length];
  const vedere = {s:S.s, cx:S.cx, cy:S.cy}, rel = S.relief.pornit;
  await deschide(t.cale, "A");
  Object.assign(S, vedere); S.relief.pornit = rel; deseneaza();       // aceeași încadrare, ca într-o prezentare
}
function taste(e){
  if ($("#v-harta")?.style.display === "none" || !S.A) return;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== "range") return;
  const k = e.key;
  if (k === "ArrowRight" || k === "ArrowLeft"){ e.preventDefault(); opreste(); cadru(S.A.banda + (k === "ArrowRight" ? 1 : -1)); }
  else if (k === " "){ e.preventDefault(); S.anim.ruleaza ? opreste() : porneste(); }
  else if (k === "ArrowDown" || k === "ArrowUp"){ e.preventDefault(); rasterVecin(k === "ArrowDown" ? 1 : -1); }
  else if (k === "c" || k === "C") comuta_comparatia();
  else if (k === "r" || k === "R") comuta_relieful();
  else if (k === "p" || k === "P") prezentare();
}

// ------------------------------------------------------------------ vederile
function activeaza(){                                  // apelată de arataVedere("harta") din index.html
  if (!S.initializat){ construieste(); controale(); }
  incarcaLista(); requestAnimationFrame(() => { redimensioneaza(); deseneaza(); });
}

return {deschide, activeaza, prezentare, porneste, incarcaLista, stare: S};
})();
