# Scripturi de analiză climatică pe cubul Zarr `anm-daily-grids`

Toate scripturile folosesc același nucleu (`zarr_clima.py`). Fiecare script conține **doar parametrii**,
marcați cu `# <-- MODIFICABIL`. Rezultatele se scriu în `rezultate/`.

## Pasul 0 — precondiții (o singură dată)

1. Copiați tot folderul (de ex. în `C:\Users\<utilizator>\Documente\ClimaANM\clima`).
2. Deschideți **OSGeo4W Shell** și instalați bibliotecile care nu vin cu QGIS. **Fixați numpy-ul din OSGeo4W**,
   altfel `pip` aduce un numpy 2.x în `AppData\Roaming\Python`, care îl umbrește pe cel din QGIS și produce mesajul
   „A module that was compiled using NumPy 1.x cannot be run in NumPy 2.x…” la fiecare rulare:
   ```
   python -c "import numpy; print('numpy==' + numpy.__version__)" > "%TEMP%\constr_numpy.txt"
   python -m pip install --user -c "%TEMP%\constr_numpy.txt" xarray zarr fsspec aiohttp requests dask netCDF4 pillow
   ```
   (`numpy`, `matplotlib` și GDAL sunt deja în OSGeo4W. `netCDF4` și `pillow` sunt necesare doar pentru scriptul 12.
   Dacă `pip` raportează un conflict de versiuni, spune ce pachet cere numpy 2.x: pentru acela se alege o versiune mai veche.)

   **Dacă ați instalat deja pachete fără această constrângere** și vedeți mesajul despre NumPy 1.x / 2.x:
   ```
   python mediu_numpy.py                      # arată ce copie de numpy umbrește pe care
   python -m pip uninstall -y numpy           # O SINGURĂ DATĂ: scoate copia din AppData (cea din OSGeo4W rămâne)
   python -m pip check                        # trebuie să nu raporteze conflicte
   python 00_verificare_mediu.py
   ```
   Nu rulați `pip uninstall numpy` a doua oară: ar încerca să scoată numpy-ul din OSGeo4W. Dacă `pip check` raportează
   că un pachet cere numpy 2.x, reinstalați-l cu constrângerea de mai sus (eventual într-o versiune mai veche).
3. Rulați verificarea:
   ```
   cd C:\Users\<utilizator>\Documente\ClimaANM\clima
   python 00_verificare_mediu.py
   ```
   La final trebuie să apară **„MEDIUL ESTE GATA”**. Dacă lipsește ceva, scriptul afișează comanda exactă de instalare.

## Rulare

| Unde | Comandă |
|---|---|
| OSGeo4W Shell | `python 02_zile_tropicale.py` |
| Consola Python din QGIS | `exec(open(r"C:\...\clima\02_zile_tropicale.py", encoding="utf-8").read())` |

În QGIS, straturile COG și GPKG se încarcă automat în proiect (grupul „Zarr ANM”).
În consola QGIS verificați variabila `FOLDER` din antetul scriptului (calea către `zarr_clima.py`).

## Scripturile

| # | Script | Ce produce | Cost tipic (toată țara) |
|---|---|---|---|
| 00 | `00_verificare_mediu.py` | verifică bibliotecile, GDAL, rețeaua, un mini-test | câteva secunde |
| 00b | `00b_inspecteaza_vector.py` | ce conține un fișier vectorial (straturi, coloane, valori) + liniile `ZONA = …` gata de lipit | o secundă |
| 01 | `01_anomalie_termica.py` | anomalia față de normala 1991–2020 | JJA × 31 ani ≈ 3 GB, ~5 min |
| 02 | `02_zile_tropicale.py` | zile cu Tmax ≥ 30 / 35 °C | 10 ani ≈ 2 GB, ~3 min |
| 03 | `03_nopti_tropicale.py` | nopți cu Tmin > 20 °C, două decenii comparate | ≈ 4 GB, ~6 min |
| 04 | `04_amplitudine_termica.py` | amplitudinea diurnă medie și cea extremă | 10 ani ≈ 4 GB |
| 05 | `05_trend_incalzire.py` | tendința per pixel (°C/deceniu), hașurat = nesemnificativ | 1961–2025 ≈ 13 GB, ~20–25 min |
| 06 | `06_grade_zile_gdd.py` | grade-zile de creștere (bază 10 / 5 °C) | 10 ani ≈ 4 GB |
| 07 | `07_inghet.py` | ultimul / primul îngheț, sezonul fără îngheț | 10 ani ≈ 2 GB |
| 08 | `08_ariditate_de_martonne.py` | indicele De Martonne, în clase | 10 ani ≈ 6 GB |
| 09 | `09_seceta_cdd.py` | cel mai lung șir de zile fără ploaie (CDD) | un an ≈ 0,1 GB |
| 10 | `10_ploi_torentiale_rx.py` | Rx1day, Rx5day | un an ≈ 0,1 GB |
| 11 | `11_anomalie_precipitatii.py` | precipitații în % din normală | ≈ 1–3 GB |
| 12 | `12_episod_extrem.py` | NetCDF pentru Temporal Controller + GIF | ~50–100 MB |
| 13 | `13_atlas_zonal.py` | atlas pe UAT/bazine: mai mulți indicatori în tabela GPKG | depinde de zonă |
| 14 | `14_dungi_incalzire.py` | dungile încălzirii + seria pe punct sau pe județe | ≈ 1,5–3 GB |
| 15 | `15_grafice_serii.py` | **grafice complexe pe zone**: serie zilnică cu climatologia (p10–p90) și capcana 2050, serii anuale, multiple mici, bare pe zone (medie · anomalie · tendință), dungi pe toate zonele, dungi + anomalii anuale, harta an × lună, hartă coropletă | prima rulare 1961–2025 ≈ 13 GB (~20–25 min); apoi din cache, câteva secunde |
| 16 | `16_analiza_episod.py` | **analiza unei perioade / a unui episod excepțional** (ex. o săptămână ploioasă la București): statistici, anomalie față de climatologie / an / lună / perioadă, raritate (rang, top episoade, perioada de revenire, șiruri, ziua extremă), context (zilele dinainte, alte variabile, comparații, frecvență), hărți + rangul per pixel, extindere, GIF, calendar, raport .md/.json | prima rulare: seria zonei pe tot istoricul (punct ≈ 1,6 GB, ~3 min; țara ≈ 13 GB) + ferestrele pentru hărți (≈ 0,2–2 GB); apoi câteva secunde |
| 17 | `17_statistici_perioada.py` | **media / minima / maxima (+ suma, suma medie anuală, abaterea standard…) per pixel**, din toate zilele unei perioade (opțional doar un sezon), pe toată grila sau pe o zonă; COG multi-bandă + câte un tif pe statistică | ≈ 0,2 GB pe an (o temperatură), ≈ 0,1 GB pe an (precipitații); 20 de ani Tmax ≈ 4 GB, ~10–20 min |
| 18 | `18_statistici_zonale.py` | **statistici zilnice pe județe / regiuni** (min, max, media pixelilor din fiecare zonă, zi cu zi) + agregări lunare și sezoniere (pe ani și multianuale), pe perioada aleasă; CSV | ≈ 0,2 GB pe an (o temperatură), ≈ 0,1 GB pe an (precipitații); 2020–2025, trei variabile ≈ 3 GB |
| – | `02_zile_tropicale_judete.py` | scriptul 02, pregătit pe cele 42 de județe | 5 ani ≈ 1 GB |

Scriptul 15 păstrează seriile zilnice ale zonelor în `rezultate/cache_serii`: după prima rulare puteți schimba
graficele, zonele de detaliu, fereastra zilnică sau perioadele fără a mai descărca nimic (doar anii noi se citesc).

Pentru o zonă mică (un județ, un dreptunghi) costurile scad proporțional cu numărul de sectoare atinse.

## Scriptul 16 — analiza unui episod

Se setează în antet (fiecare variantă are o linie comentată, gata de activat):

```python
PARAMETRU = "precipitation"            # sau "max_temp", "min_temp", "tmedie"
PERIOADA  = ("2026-10-09", "2026-10-15")   # sfârșitul None = până la frontiera datelor
REFERINTA = ("climatologie", 1991, 2020)   # sau ("an", 2005) · ("luna", "2025-10") · ("perioada", "2025-10-01", "2025-10-20")
ZONA      = zc.Zona.punct(26.1025, 44.4268, nume="București")   # sau Zona.poligoane(…) / Zona.dreptunghi(…)
HARTI_ZONA = zc.Zona.tara()            # zona hărților (punctul apare ca stea, poligoanele ca contur)
```

Ce primiți (prefixul `16_<parametru>_<data>`):

| Fișier | Conținut |
|---|---|
| `_01_rang_fereastra` | aceeași fereastră calendaristică în fiecare an din 1961; episodul în roșu, normala, top 3 |
| `_02_top_episoade` | cele mai mari episoade de aceeași lungime, oricând în an (fără suprapuneri), și locul episodului |
| `_03_gumbel` | perioada de revenire (Gumbel, metoda momentelor — orientativă) |
| `_04_siruri` | cele mai lungi șiruri de zile ploioase (≥ `PRAG_ZI_PLOIOASA`) sau peste p90 / sub p10 |
| `_05_zile_episod` | zilele episodului (și 30 de zile dinainte) față de climatologie și pragurile p95 / p99 |
| `_07_context_anterior` | cumulul / anomaliile din cele 90 de zile dinainte, cu plicul p10–p90 |
| `_08_harta_*` | suma / media, media zilnică, minima, maxima, normala, anomalia, %, zile ploioase, **rangul per pixel** |
| `_09_extindere` | ce fracție din teritoriu a depășit pragurile și unde a fost record / top 3 |
| `_10_context` | celelalte variabile în episod față de normală (ex. ploaie rece sau caldă, amplitudinea diurnă) |
| `_11_calendar` | fiecare zi din tot istoricul (rânduri = ani), episodul încadrat |
| `_12_animatie.gif` | zi cu zi: valoarea zilei și cumulul / media de la început |
| `_13_comparatii` | episodul față de top 3 istoric și de episoadele din `EPISOADE_COMPARATIE` |
| `_14_frecventa` | numărul anual de episoade similare și de șiruri lungi, mediile pe decenii, tendința |
| **`_fisa.html`** | **fișa interactivă** (vezi mai jos): hărți cu glisor pe zile, grafice interactive, tabel pe zone, raport — un singur fișier |
| `_harti.tif` | COG multi-bandă cu toate hărțile |
| `_punct.gpkg` / `_zone.gpkg`, `_zone.csv` | rezultatele în atribute (cu mai multe poligoane: un rând pe zonă) |
| `_raport.md`, `_rezultate.json` | frazele-cheie gata de folosit și toate cifrele, cu avertismentele |

### Fișa interactivă (`_fisa.html`)

Se activează cu `IESIRI["html"] = True`; rezoluția hărților cu `HTML_REZOLUTIE` (1 = 0,01°, ≈ 6–15 MB; 2 = 0,02°, de ~4× mai mic; 3 = 0,03°).
Fișa este **un singur fișier .html**: se deschide cu dublu-clic, funcționează fără internet și poate fi trimis prin e-mail.

* **Hărți**: straturile statistice, anomalia, %, rangul per pixel, zilele ploioase; **glisor pe zile** (valoarea zilei sau cumulul / media de la început, cu animație); zoom și deplasare; clic pe hartă = valorile pixelului și seria zilnică a episodului; cu mai multe poligoane, straturi pe zone (tabelul și harta sunt legate).
* **Grafice interactive** (cursor, legendă care ascunde serii): rang pe fereastră, top episoade, Gumbel, șiruri, zilele episodului, contextul anterior, comparații, frecvență, calendar.
* **Raport**: același text ca `_raport.md`.
* Ce **nu** face: nu recalculează nimic în browser — alege între produsele calculate la rulare (de aceea nu apare seria de 65 de ani a unui pixel oarecare, ci doar valorile episodului).
* Cerințe: browser modern (Chrome, Edge, Firefox, Safari actuale). Dacă fișa pare lentă sau prea mare, setați `HTML_REZOLUTIE = 2`.
* Fișierele necesare în folderul scripturilor: `zarr_html.py`, `fisa_episod_sablon.html`, `chart.umd.js` (Chart.js 4.4.4, inclus în fișă la export).

Observații:
* dacă perioada depășește frontiera `last_*_time`, se taie automat, iar comparațiile istorice folosesc aceeași lungime;
* pentru temperaturi, `SENS = "auto"` decide după semnul anomaliei dacă episodul e cald („mare”) sau rece („mic”);
* într-un poligon, valorile zilnice sunt medii pe suprafață: șirurile ploioase sunt mai lungi, maximele mai mici decât într-un punct;
* seriile se păstrează în `rezultate/cache_serii` (comun cu scriptul 15), ferestrele hărților în `rezultate/cache_episod`.

## Scriptul 17 — statistici pe o perioadă, per pixel

Statisticile se calculează din **toate zilele** perioadei (și ale sezonului, dacă e ales), pixel cu pixel:

| Statistică | Ce înseamnă (ex. Tmax, 2006–2025) | Precipitații |
|---|---|---|
| `medie` | media celor ~7300 de valori zilnice | mm/zi |
| `minima` | cea mai mică valoare zilnică din perioadă | (de obicei 0) |
| `maxima` | cea mai mare valoare zilnică din perioadă | cea mai ploioasă zi, mm/24 h |
| `suma` | suma tuturor valorilor zilnice | totalul perioadei, mm |
| `suma_medie_anuala` | media zilnică × zilele unui an (sau ale sezonului) | mm/an (mm/sezon) |
| `abatere_standard`, `amplitudine`, `zile_valide` | variabilitatea zilnică, maxima − minima, zile cu date | |

* Implicit: `medie, minima, maxima` (temperaturi); `suma, suma_medie_anuala, medie, maxima` (precipitații).
* Un pixel are valoare doar dacă are date în cel puțin 90 % din zile (`zc.PRAG_VALID`).
* Perioada se taie automat la frontiera datelor (`last_*_time`).
* Datele se citesc în blocuri de ~90 de zile: memoria nu crește cu lungimea perioadei.
* Cu poligoane, `DECUPARE = "masca"` pune NoData în afara lor; `"dreptunghi"` păstrează tot dreptunghiul.

## Scriptul 18 — statistici zonale zilnice, lunare și sezoniere

Înlocuiește `statistici_nc.py` + `statistici_anotimpuale.py`, cu datele luate direct din cub, pe perioada aleasă.

* `ZONARI`: câte o zonare pe coloană (ex. județele din `name`, regiunile din `region`). Entitățile cu aceeași valoare se unesc.
* Pe fiecare zi și zonă: `min` / `max` = cel mai mic / mare pixel; `media` = media pixelilor.
* Agregări (aceleași coloane ca în scripturile vechi): lunar pe ani, lunar multianual, sezonier pe ani climatici
  (decembrie → iarna anului următor), sezonier multianual.
* `sezon_complet` = DA când sezonul are toate zilele (90, 91 sau 92). Precipitațiile multianuale = media zilnică
  × lungimea medie a lunii / sezonului (identic cu „suma / numărul de ani” pentru ani compleți; corect și pentru
  perioade care încep sau se termină în mijlocul unei luni).
* `FORMAT_CSV = "standard"` (virgulă, punct zecimal, ca înainte) sau `"ro"` (punct și virgulă, virgulă zecimală).

## Datele vectoriale

Scripturile folosesc implicit:
* județele: `date\ro_judete_poligon.gpkg`
* frontiera (conturul hărților): `date\ro_frontiera_poligon.gpkg`

## Zona analizei

Patru forme, fiecare cu numele ei:

```python
ZONA = zc.Zona.tara()                                            # toată țara
ZONA = zc.Zona.dreptunghi(25.5, 44.0, 27.0, 45.0)                 # lon_min, lat_min, lon_max, lat_max
ZONA = zc.Zona.punct(26.1025, 44.4268, nume="București")         # un pixel (scripturile 14, 15, 16)
ZONA = zc.Zona.poligoane(r"C:\date\judete.gpkg", coloana="NAME")  # poligoane: fiecare valoare a coloanei = o zonă
```

Pentru poligoane:

| Parametru | Ce face |
|---|---|
| `coloana` | coloana din care se iau numele zonelor. **O alegeți voi** — scriptul nu mai ghicește. |
| `valori` | ce zone se păstrează, ex. `valori=["Iași", "Vaslui"]`; `None` = toate. Majusculele și diacriticele nu contează („iasi” = „Iași”). |
| `unite` | `True` = zonele selectate devin **una singură** (ex. „Iași + Vaslui”); `False` = fiecare separat. |
| `strat` | stratul din fișier; necesar doar dacă fișierul are mai multe straturi cu geometrie. |
| `nume` | (opțional) numele afișat al zonei, în titluri și rapoarte. |

* Fișierul poate fi GPKG, SHP, GeoJSON etc., în orice CRS (de ex. Stereo70): se reproiectează automat.
* Mai multe entități cu aceeași valoare în `coloana` (ex. un județ format din mai multe bucăți) se unesc automat.
* **Pentru un fișier nou**, rulați întâi `00b_inspecteaza_vector.py`: afișează straturile, coloanele (cu exemple)
  și liniile `ZONA = …` gata de lipit.
* Dacă greșiți coloana sau o valoare, mesajul de eroare arată coloanele disponibile, respectiv valorile apropiate
  („«Bihr» → poate: Bihor”).
* Forma veche `zc.Zona(gpkg=…, camp=…, filtru=…)` funcționează în continuare; la rulare se afișează forma nouă echivalentă.
* `ZONA_ANALIZA` (scriptul 16) și `ZONE_DETALIU` (scriptul 15) folosesc aceeași comparație tolerantă.

## Parametrii comuni

```python
SEZON = "anual" | "DJF" | "MAM" | "JJA" | "SON" | (4, 9) | ("06-15", "08-15")

IESIRI = dict(cog=True, png=True, grafic=True, gpkg=True, csv=False)
```


### Conturul pe hărțile PNG

Hărțile nu mai au un contur implicit. Poligoanele din `ZONA` se desenează mereu; în plus, puteți adăuga orice vector:

```python
zc.CONTUR_HARTI = None                                   # fără contur
zc.CONTUR_HARTI = r"C:\...\ro_frontiera_poligon.gpkg"   # primul strat din fișier (GPKG, SHP, GeoJSON; orice CRS)
zc.CONTUR_HARTI = (r"C:\date\limite.gpkg", "tara")       # un strat anume
zc.CONTUR_HARTI = (r"C:\date\limite.gpkg", "judete", "cod = 'IS'")   # strat + filtru SQL
zc.CONTUR_GROSIME = 0.6                                  # grosimea liniei
```

## Reguli aplicate automat

1. Timpul se taie la frontiera `last_*_time` (minimul variabilelor folosite).
2. Un an care depășește frontiera (de ex. 2026) e **exclus** — se poate accepta cu `zc.ACCEPTA_PARTIAL = True`.
3. Un pixel cu sub 90 % zile valide într-o perioadă devine NaN (`zc.PRAG_VALID`); de ex. golul din aprilie–mai 2026.
4. Erorile de rețea se reiau automat (până la 6 încercări).
5. Statisticile zonale raportează și numărul de pixeli (`n_pixeli`): o valoare pe 1–5 pixeli e orientativă.
6. Temperatura medie este aproximată ca (Tmax + Tmin) / 2.

## Definiții

| Indicator | Definiție |
|---|---|
| Zi tropicală / caniculară | Tmax ≥ 30 °C / ≥ 35 °C (praguri ANM) |
| Noapte tropicală | Tmin > 20 °C (ETCCDI TR) |
| Ultimul îngheț de primăvară | ultima zi cu Tmin < 0 °C între 1 ian. și 30 iun. (ziua din an) |
| Primul îngheț de toamnă | prima zi cu Tmin < 0 °C între 1 iul. și 31 dec. |
| GDD | Σ max((Tmax+Tmin)/2 − bază, 0) |
| De Martonne | P_an / (T + 10); P adus la scara anuală |
| CDD | cel mai lung șir de zile cu P < 1 mm (ETCCDI) |
| Rx1day / Rx5day | maximul precipitațiilor în 1 / 5 zile consecutive (ETCCDI) |
| Tendință | regresie liniară pe valorile anuale; p-valoare din testul t (aprox. normală) |

## Ideea 15 (fuziune cu Sentinel-2)

Nu este inclusă: colecția `sentinel-2-l2a-mosaic-monthly` de pe EOCube nu are banda NIR (B08), deci nu permite NDVI,
iar reflectanțele cer autentificare. Variante: NDVI din `sentinel-2-l2a` (cont EOCube) sau comparație vizuală
anomalie ANM vs. mozaicul RGB public, agregată la nivel de UAT.

Date: ANM / MeteoRomania · procesare: UVT – EOCube.Ro · CC-BY-4.0
