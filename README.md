# Clima ANM

[![teste](https://github.com/mariusbudileanu/clima-anm/actions/workflows/teste.yml/badge.svg)](https://github.com/mariusbudileanu/clima-anm/actions/workflows/teste.yml)
[![licență: MIT](https://img.shields.io/badge/licen%C8%9B%C4%83-MIT-0f6b8c)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24564871.svg)](https://doi.org/10.5281/zenodo.24564871)

Analize climatice pe datele zilnice ANM pentru România, 1961 – prezent, grilă de 1 km, citite direct din cubul Zarr
[`anm-daily-grids`](https://eocube.ro) de pe EOCube.ro. Un program local, cu interfața în browser, făcut pentru
studenții de la masterat: se dezarhivează, se pornește cu dublu-clic, fără drepturi de administrator și fără Python
instalat.

*English: a portable desktop program with a browser interface for climate analyses on Romania's daily 1 km gridded
ANM data (1961–present), read from the EOCube.ro Zarr cube. Interface and documentation in Romanian.*

## Pornire

1. Descărcați ultima versiune (*Releases* → `Source code (zip)`) și dezarhivați-o într-o cale scurtă, de ex. `C:\ClimaANM`.
2. Dublu-clic pe **`porneste.bat`** (Linux / macOS: `./porneste.sh`).

Prima pornire descarcă `pixi` și instalează mediul fixat în `pixi.lock` (Python 3.12, GDAL, xarray, zarr…) în folderul
programului: 3–10 minute, o singură dată. Ștergerea folderului înseamnă dezinstalare completă.
Manualul complet: [`CITESTE_MA.md`](CITESTE_MA.md).

## Ce face

* **Hărți și serii**: medii pe ani, anomalii, trenduri (OLS cu test Student, Sen + Mann–Kendall), praguri,
  indicatori ETCCDI, percentile față de o perioadă de bază (implicit 1991–2020), SPI și SPEI, ariditate, îngheț,
  grade-zile, legătura cu altitudinea; pe toată țara, pe un dreptunghi sau pe poligoane proprii.
* **Analize rapide**: sub 1 GB de descărcat și în jur de un minut de calcul.
* **Superlative**: cea mai caldă vară, cea mai ploioasă lună mai, cea mai geroasă săptămână din noiembrie, pe
  pixel sau pe zone.
* **Rezultate reproductibile**: un folder pe rulare cu GeoTIFF (COG), PNG, GeoPackage, CSV, o fișă vizuală
  `index.html` și parametrii necesari refacerii. Fiecare metodă are o fișă teoretică în tabul *Indicatori*.
* **Harta interactivă**: comparație A | B cu cortină, relief, animația pe ani cu export video, modul prezentare.
* **Verifică datele**: chunk-urile lipsă și blocurile nescrise din cub sunt găsite și tratate ca date lipsă, nu ca 0.

## Teste

```
pixi run --locked python instrumente/teste_cunoscute.py     # răspunsuri cunoscute, câteva secunde
pixi run --locked python instrumente/testeaza_retete.py     # toate rețetele, pe un cub sintetic (~4 min)
```

Rulează automat pe GitHub la fiecare modificare.

## Citare

Budileanu, M. (2026). *Clima ANM: analize climatice pe cubul Zarr anm-daily-grids (EOCube.ro)* [Software].
Zenodo. https://doi.org/10.5281/zenodo.24564871

DOI-ul de mai sus e al proiectului și duce mereu la ultima versiune. Fiecare versiune are și DOI-ul ei, pe pagina
Zenodo (de ex. 1.0.0: [10.5281/zenodo.24564872](https://doi.org/10.5281/zenodo.24564872)); într-o lucrare, citați
versiunea folosită. Vezi și [`CITATION.cff`](CITATION.cff) (butonul *Cite this repository*).

## Licențe și atribuiri

* Cod: [MIT](LICENSE). Documentație: [CC BY 4.0](LICENSE-DOCS.md).
* Datele analizate (nu sunt incluse): ANM / MeteoRomania, procesare UVT – EOCube.Ro, CC BY 4.0.
* Relieful inclus (`date/dem_grila_zarr.tif`): Copernicus DEM GLO-30 © DLR e.V. 2010–2014 și © Airbus Defence and
  Space GmbH 2014–2018, furnizat în cadrul COPERNICUS de Uniunea Europeană și ESA.
* Chart.js 4.4.4 (MIT), inclus în `clima/chart.umd.js`.

Marius Budileanu · Universitatea din București, Facultatea de Geografie ·
[ORCID 0000-0002-4840-5707](https://orcid.org/0000-0002-4840-5707)
