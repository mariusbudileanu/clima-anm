// alegator.js — alegerea unui punct sau a unui dreptunghi pe hartă, în formularele analizelor.
// Fără hărți de fundal (funcționează offline): grila cubului, o rețea de coordonate și conturul din date/.
"use strict";
const Alegator = (() => {
const EXT = {lon0: 20.13, lon1: 29.85, lat0: 43.53, lat1: 48.36};      // grila cubului anm-daily-grids
let CONTUR = null;

async function contur(){
  if (CONTUR !== null) return CONTUR;
  const v = (CAT.vectori || []), cale = v.find(x => /judet/i.test(x)) || v.find(x => /frontier|granit/i.test(x)) || v[0];
  CONTUR = {inele: [], entitati: []};
  if (!cale) return CONTUR;
  const g = await api("/api/contur?cale=" + encodeURIComponent(cale));
  if (g.eroare) return CONTUR;
  for (const f of g.features){
    const gm = f.geometry, poli = gm.type === "Polygon" ? [gm.coordinates] : gm.type === "MultiPolygon" ? gm.coordinates : [];
    const ale = []; poli.forEach(p => p.forEach(r => { CONTUR.inele.push(r); ale.push(r); }));
    CONTUR.entitati.push({nume: f.properties.nume, inele: ale});
  }
  return CONTUR;
}
function inPoligon(lon, lat){
  for (const f of CONTUR?.entitati || []){
    let in_ = false;
    for (const inel of f.inele) for (let i = 0, j = inel.length - 1; i < inel.length; j = i++){
      const [xi, yi] = inel[i], [xj, yj] = inel[j];
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi)*(lat - yi)/(yj - yi) + xi) in_ = !in_;
    }
    if (in_) return f.nume;
  }
  return null;
}

// tip: "punct" | "dreptunghi"; initial: {lon, lat} sau {lon_min, lat_min, lon_max, lat_max}
function alege(tip, initial){
  return new Promise(async rezolva => {
    const W = 820, H = 470, k = Math.cos(45.95*Math.PI/180), m = 18;
    const s = Math.min((W - 2*m)/((EXT.lon1 - EXT.lon0)*k), (H - 2*m)/(EXT.lat1 - EXT.lat0));
    const ox = (W - (EXT.lon1 - EXT.lon0)*k*s)/2, oy = (H - (EXT.lat1 - EXT.lat0)*s)/2;
    const ecran = (lon, lat) => [ox + (lon - EXT.lon0)*k*s, oy + (EXT.lat1 - lat)*s];
    const geo = (x, y) => [EXT.lon0 + (x - ox)/(k*s), EXT.lat1 - (y - oy)/s];
    const rot = x => Math.round(x*10000)/10000;
    const c = el("canvas",{width:W,height:H,style:"width:100%;max-width:820px;border:1px solid #d6dee4;border-radius:8px;cursor:crosshair;display:block"});
    const stare = el("div",{class:"ajutor",style:"min-height:20px;margin-top:6px",text:"se încarcă conturul…"});
    let sel = initial && (tip === "punct" ? (initial.lon != null && initial.lat != null) : initial.lon_min != null) ? {...initial} : null, trage = null;
    await contur();
    function deseneaza(){
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#f4f7f8"; ctx.fillRect(0, 0, W, H);
      const [gx0, gy0] = ecran(EXT.lon0, EXT.lat1), [gx1, gy1] = ecran(EXT.lon1, EXT.lat0);
      ctx.fillStyle = "#fff"; ctx.fillRect(gx0, gy0, gx1 - gx0, gy1 - gy0);
      ctx.strokeStyle = "#e3e7ee"; ctx.lineWidth = 1; ctx.fillStyle = "#98a2b3"; ctx.font = "11px system-ui";
      for (let lo = 21; lo <= 29; lo++){ const [x] = ecran(lo, 0); ctx.beginPath(); ctx.moveTo(x, gy0); ctx.lineTo(x, gy1); ctx.stroke(); ctx.fillText(lo + "°E", x + 2, gy1 - 3); }
      for (let la = 44; la <= 48; la++){ const [, y] = ecran(0, la); ctx.beginPath(); ctx.moveTo(gx0, y); ctx.lineTo(gx1, y); ctx.stroke(); ctx.fillText(la + "°N", gx0 + 3, y - 3); }
      ctx.strokeStyle = "#475467"; ctx.lineWidth = 0.9; ctx.beginPath();
      for (const r of CONTUR.inele) r.forEach(([lo, la], j) => { const [x, y] = ecran(lo, la); j ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
      if (sel){
        ctx.strokeStyle = "#0f6b8c"; ctx.fillStyle = "rgba(15,107,140,.18)"; ctx.lineWidth = 2;
        if (tip === "punct"){ const [x, y] = ecran(sel.lon, sel.lat); ctx.beginPath(); ctx.arc(x, y, 6, 0, 2*Math.PI); ctx.fill(); ctx.stroke();
                              ctx.beginPath(); ctx.moveTo(x - 12, y); ctx.lineTo(x + 12, y); ctx.moveTo(x, y - 12); ctx.lineTo(x, y + 12); ctx.stroke(); }
        else { const [x0, y0] = ecran(sel.lon_min, sel.lat_max), [x1, y1] = ecran(sel.lon_max, sel.lat_min); ctx.fillRect(x0, y0, x1 - x0, y1 - y0); ctx.strokeRect(x0, y0, x1 - x0, y1 - y0); }
      }
    }
    const descrie = () => !sel ? (tip === "punct" ? "Dați clic pe hartă pentru a alege punctul." : "Țineți apăsat și trageți pentru a desena dreptunghiul.")
      : tip === "punct" ? `punctul: lon ${sel.lon}, lat ${sel.lat}` + (inPoligon(sel.lon, sel.lat) ? ` · ${inPoligon(sel.lon, sel.lat)}` : "")
      : `dreptunghiul: lon ${sel.lon_min} – ${sel.lon_max}, lat ${sel.lat_min} – ${sel.lat_max} (~${Math.round((sel.lon_max - sel.lon_min)*111*k)} × ${Math.round((sel.lat_max - sel.lat_min)*111)} km)`;
    const poz = e => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left)*W/r.width, (e.clientY - r.top)*H/r.height]; };
    const inGrila = (lon, lat) => lon >= EXT.lon0 && lon <= EXT.lon1 && lat >= EXT.lat0 && lat <= EXT.lat1;
    c.addEventListener("mousedown", e => {
      const [lon, lat] = geo(...poz(e)); if (!inGrila(lon, lat)) return;
      if (tip === "punct"){ sel = {lon: rot(lon), lat: rot(lat)}; deseneaza(); stare.textContent = descrie(); }
      else trage = [lon, lat];
    });
    c.addEventListener("mousemove", e => {
      const [lon, lat] = geo(...poz(e));
      if (trage){
        const cl = (v, a, b) => Math.min(b, Math.max(a, v)), lo = cl(lon, EXT.lon0, EXT.lon1), la = cl(lat, EXT.lat0, EXT.lat1);
        sel = {lon_min: rot(Math.min(trage[0], lo)), lon_max: rot(Math.max(trage[0], lo)), lat_min: rot(Math.min(trage[1], la)), lat_max: rot(Math.max(trage[1], la))};
        deseneaza(); stare.textContent = descrie(); return;
      }
      const z = inGrila(lon, lat) ? inPoligon(lon, lat) : null;
      stare.textContent = (inGrila(lon, lat) ? `lon ${lon.toFixed(3)} · lat ${lat.toFixed(3)}${z ? " · " + z : ""}  —  ` : "") + descrie();
    });
    // pe window (ca tragerea să se termine și în afara hărții); se scoate la închidere, oricum s-ar închide fereastra
    const sus = () => { if (!c.isConnected){ window.removeEventListener("mouseup", sus); return; } if (trage){ trage = null; if (sel && (sel.lon_max - sel.lon_min < 0.02 || sel.lat_max - sel.lat_min < 0.02)) sel = null; deseneaza(); stare.textContent = descrie(); } };
    window.addEventListener("mouseup", sus);
    deseneaza(); stare.textContent = descrie();
    const curata = () => { window.removeEventListener("mouseup", sus); $("#fundal").removeEventListener("click", laFundal); };
    const gata = v => { curata(); inchide(); rezolva(v); };
    fereastra(tip === "punct" ? "Alegeți punctul pe hartă" : "Desenați dreptunghiul pe hartă",
      [c, stare, el("p",{class:"ajutor",text:"Grila cubului: 20,13–29,85 °E, 43,53–48,36 °N (dreptunghiul alb). Contur: primul fișier vectorial din date/ (județele, dacă există)."})],
      [el("button",{class:"b prim",text:"Folosește",onclick:()=>{ if (!sel){ mesaj(tip === "punct" ? "Alegeți un punct." : "Desenați un dreptunghi."); return; } gata(sel); }})]);
    function laFundal(e){ if (e.target.id === "fundal"){ curata(); rezolva(null); } }
    $("#fundal").addEventListener("click", laFundal);
  });
}
return {alege};
})();
