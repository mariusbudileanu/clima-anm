# Clima ANM — analize climatice pe cubul Zarr `anm-daily-grids`

Program local: o pagină web în browser care pornește analizele Python pe datele zilnice ANM (1961–prezent) de pe EOCube.ro.
Nu necesită QGIS, OSGeo4W, drepturi de administrator sau Python instalat.

## Instalare și pornire

1. Dezarhivați folderul într-o cale **scurtă și fără diacritice**, de exemplu `C:\ClimaANM`.
2. Copiați fișierele vectoriale în `date\` (vezi `date\CITESTE_MA.txt`).
3. Dublu-clic pe **`porneste.bat`** (Linux / macOS: `./porneste.sh`).

La **prima pornire** (necesită internet, 3–10 minute, o singură dată):
* se descarcă `pixi` (~88 MB, verificat cu SHA256) în `instrumente\`;
* se instalează mediul de lucru (~1 GB) în `.pixi\`: Python 3.12, GDAL, xarray, zarr, matplotlib… exact versiunile din `pixi.lock`, identice pe toate calculatoarele.

La pornirile următoare, interfața se deschide în câteva secunde. **Fereastra neagră trebuie să rămână deschisă** cât lucrați; închiderea ei oprește programul.

## Ce nu atinge

Mediul este izolat: nu folosește și nu modifică QGIS, OSGeo4W sau pachetele instalate cu `pip install --user`
(variabilele `PYTHONNOUSERSITE`, `PYTHONPATH`, `PYTHONHOME` sunt neutralizate). Totul stă în folderul programului:
**ștergerea folderului = dezinstalare completă.**

## Ce poate face

* **Analize pe hartă** (medii pe ani, anomalii, trenduri cu test statistic, praguri, indicatori ETCCDI, percentile față
  de o perioadă de bază, SPI / SPEI, ariditate, îngheț, grade-zile, relieful și altitudinea), pe toată țara, pe un
  dreptunghi sau pe poligoane (județe, bazine, orice GPKG / SHP / GeoJSON).
* **Analize rapide**: sub 1 GB de descărcat și în jur de un minut de calcul.
* **Superlative**: cea mai caldă vară, cea mai ploioasă lună mai, cea mai geroasă săptămână din noiembrie — pe pixel
  sau pe zone, cu clasamente, anul recordului și marja.
* **Rezultate ordonate**: fiecare rulare are folderul ei (data în față), cu GeoTIFF (COG), PNG, GPKG, CSV, o fișă
  vizuală `index.html` și o fișă de reproducere.
* **Tabul Hartă**: rasterele pe rulări, comparație A | B cu cortină, relief, **animația pe ani** cu export video și
  **modul prezentare**.
* **Verifică datele**: chunk-urile lipsă și blocurile nescrise din cub; analizele tratează automat golurile ca date
  lipsă, nu ca 0.

Istoricul versiunilor: `CHANGELOG.md`. Licențe: `LICENSE` (cod, MIT), `LICENSE-DOCS.md` (documentație, CC BY 4.0).

## Relieful (DEM pe grila Zarr)

`date/dem_grila_zarr.tif` este Copernicus DEM GLO-30 adus pixel cu pixel pe grila cubului (altitudinea medie, minimă,
maximă, abaterea standard, panta, acoperirea). Vine gata făcut cu programul; se regenerează doar dacă e nevoie, cu
`instrumente\pregateste_dem.bat` (descarcă temporar ~2 GB, ~8 minute, jurnalul în `dem_jurnal.txt`).

* **Filtrul de altitudine**, în caseta „Zona analizei” a oricărei rețete: de ex. doar pixelii de peste 1500 m.
  Nu micșorează descărcarea (se citesc aceleași chunk-uri), doar pixelii analizați.
* **Rețeta 19, „Indicatorul față de altitudine”**: gradientul pe 100 m, media pe trepte, harta reziduului.
* În tabul **Hartă**, DEM-ul apare primul în listă și poate fi comparat („B”) cu orice rezultat.
* Teoria (ponderi de arie, DSM față de DTM, capcana prezentărilor generale din COG): tabul **Zarr info → Relieful**.

## Cache-ul de date și laboratorul

Chunk-urile descărcate din cub se păstrează în `cache_date/` (doar perioadele încheiate; datele recente se citesc
mereu proaspăt). A doua rulare pe aceeași zonă și perioadă este mult mai rapidă. Folderul poate fi șters oricând.

| Variabilă de mediu | Implicit | Rol |
|---|---|---|
| `CLIMA_CONCURENTA` | 8 | cereri simultane către server; **în laborator, cu mulți studenți pe aceeași rețea, folosiți 4** |
| `CLIMA_CACHE_GB` | 5 | dimensiunea maximă a cache-ului (cele mai vechi fișiere se șterg primele) |
| `CLIMA_CACHE_ZILE` | 30 | vechimea maximă a unui chunk din cache |
| `CLIMA_CACHE_DATE` | `cache_date/` | alt folder pentru cache (de ex. un disc local mai mare) |
| `CLIMA_REZULTATE` | `rezultate/` | alt folder pentru rezultate (aici se creează folderul fiecărei rulări) |
| `CLIMA_CACHE_ANALIZE` | `rezultate/_cache/` | cache-ul seriilor zonale și al episoadelor |
| `CLIMA_DEPANARE` | — | `1` = afișează traceback-ul complet al erorilor (pentru depanare) |

Pe Windows: `set CLIMA_CONCURENTA=4` înainte de `porneste.bat`; pe Linux/macOS: `CLIMA_CONCURENTA=4 ./porneste.sh`.
Liniile portocalii din jurnal înseamnă reîncercări de rețea: sunt normale și nu afectează rezultatul.

## Probleme frecvente

| Simptom | Remediu |
|---|---|
| Instalarea eșuează la prima pornire | verificați internetul / proxy-ul; mutați folderul în `C:\ClimaANM`; apoi `porneste.bat -Reinstaleaza` |
| „Spațiu insuficient” la prima pornire | instalarea cere ~2 GB liberi (~3,5 GB pe stick-uri FAT32/exFAT, unde fișierele se copiază); arhivele descărcate se șterg automat la final |
| Antivirusul blochează `pixi.exe` | adăugați folderul programului la excepții (executabilul este verificat cu SHA256) |
| „Nu găsesc un port liber” | o altă copie a programului rulează deja: închideți fereastra ei |
| Browserul nu se deschide singur | deschideți manual adresa afișată în fereastra neagră (`http://127.0.0.1:8765`) |

## Analizele: motoare, indicatori, rețete

* **Indicatorii** (`clima/indicatori.py`): zile peste / sub prag, medii, sume, GDD, înghețuri, CDD, RxNday, De Martonne…
  Fiecare își declară parametrii; apare automat în toate motoarele și în formular.
* **Motoarele** (`clima/motoare.py`), zece: *hartă* (media pe ani), *anomalie*, *tendință*, *episod zilnic* (NetCDF / GIF),
  *atlas* pe poligoane, *dungile încălzirii*, *serii de timp pe zone*, *analiza unui episod* (fișa HTML),
  *statistici pe perioadă* (GeoTIFF), *statistici zonale* (CSV).
* **Rețetele** (`retete/*.json`): o analiză = un motor + indicatori + valorile implicite. Toate analizele 01–18 sunt rețete;
  scripturile vechi din `clima/` rămân și pot fi rulate manual, ca înainte.

În interfață:
* **Verifică parametrii** — validează formularul și **calculează cât se va descărca** (GB, chunk-uri, durata estimată la
  ~10 MB/s), fără să descarce date; viteza se poate ajusta cu variabila de mediu `CLIMA_MBS`;
* în timpul rulării: bara de progres, cu faza curentă și timpul rămas; în antet: până la ce zi sunt date
  (sau „EOCube indisponibil”, cu reîncercare la clic);
* **Hartă** (butonul din antet) — orice GeoTIFF din `rezultate\` (și orice alt GeoTIFF copiat acolo, în orice
  proiecție: se reproiectează în EPSG:4326 pentru afișare): benzi, palete, scara culorilor (2–98 %, min–max, divergentă),
  valoarea și județul de sub cursor, conturul din `date\`, **comparație A | B cu glisor**, salvare PNG cu legendă și
  atribuire. La fiecare GeoTIFF din rezultatele unei rulări: linkul „pe hartă”;
* **Indicatori** (tab) — fișa teoretică a fiecărui indicator: definiția, formula, pașii exacți ai codului, interpretarea,
  standardul (ETCCDI / ANM), limitările, o întrebare pentru discuție, codul Python real și un calculator pe 14 zile
  (valorile se pot modifica). Fișele sunt în `clima\teorie_indicatori.py`: un indicator nou își aduce fișa cu el;
* **Zarr info** (tab) — teoria formatului Zarr pe cubul ANM, metadatele store-ului citite live, calculatorul cheii unui
  chunk, costul hartă / serie, capcanele cubului și simulatorul 3D (`interfata\zarr\`);
* în formulare, la punct și dreptunghi: **🗺 alege pe hartă** (clic = punct, tragere = dreptunghi);
* **Exportă Python** — scriptul echivalent formularului (în `rezultate/_scripturi/`), rulabil fără interfață;
* **Salvează ca rețetă** — setările curente devin o analiză proprie, în `retete/utilizator/` (se poate copia
  pe alt calculator sau da studenților).

**O analiză nouă**, fără cod: copiați un fișier din `retete/`, schimbați `titlu`, `descriere` și `parametri`.
Câmpul `mod_indicatori`: `liber` (orice indicator), `acelasi` (același indicator, mai multe rânduri), `blocat`.
**Un indicator nou**: o funcție + un apel `inregistreaza(...)` în `clima/indicatori.py` (exemplu în antetul fișierului).
Lista indicatorilor și a parametrilor: `instrumente\pixi.exe run python clima\ruleaza.py --indicatori`.

**Testul automat** — după orice modificare în nucleu, indicatori sau motoare (fără internet, ~1–2 minute):
`instrumente\pixi.exe run python instrumente\testeaza_retete.py`. Rulează toate rețetele, inclusiv cele din
`retete\utilizator\`, pe un cub SINTETIC cu structura exactă a celui de pe EOCube (`instrumente\cub_test.py`).

## Structura

```
ClimaANM\
  porneste.bat / porneste.sh    pornirea (instalează mediul la prima rulare)
  pixi.toml, pixi.lock          definiția mediului și versiunile fixate
  interfata\                    serverul local (server_clima.py) și pagina (index.html)
  clima\                        nucleul, indicatorii, motoarele (scripturile vechi rulează și manual, ca înainte)
  retete\                       analizele (JSON); retete\utilizator\ = rețetele salvate din interfață
  date\                         fișierele vectoriale (județe, frontieră …)
  rezultate\                    un folder per rulare (<data_ora>_<analiza>: rezultate, jurnal.txt, reproducere.json);
                                _cache\ = serii refolosite; _joburi\ = istoricul interfeței; _scripturi\ = exporturi
  instrumente\, .pixi\          create automat (pixi și mediul)
```

Rularea manuală a unui script, în mediul programului: `instrumente\pixi.exe run python clima\02_zile_tropicale.py`.

Date: ANM / MeteoRomania · procesare: UVT – EOCube.Ro · CC-BY-4.0

