# Istoricul versiunilor

Cele mai noi sus. Manualul de utilizare este în `CITESTE_MA.md`.

Versiunea publică **1.0.0** corespunde versiunii interne 5.2. Versiunile interne 3.x – 5.2 au fost etapele de
dezvoltare de dinaintea publicării; sunt păstrate mai jos ca istoric al metodelor și al deciziilor.

## 1.1.0 — în lucru

### Nou

* **Stil QGIS pentru fiecare GeoTIFF:** lângă fiecare `.tif` colorat se scrie un `.qml` cu același nume, pe care QGIS
  îl încarcă automat: aceeași paletă, aceeași scară (2–98 % sau limitele alese) și aceleași clase ca harta PNG.
* **„Date și metode”:** fiecare rulare primește un paragraf descriptiv, în română și în engleză (datele, perioada,
  sezonul, zona, indicatorii, metoda, regulile de validitate, golurile întâlnite, versiunea programului) și
  bibliografia în format APA, alese după indicatorii și metoda folosite. Apar în fișa vizuală, cu butoane de copiere,
  și în `metode.md`. Textul nu conține interpretări.

### Corecturi (auditul independent din 27.11.2026, fiecare cu test de regresie)

* **Blocurile nescrise (valori exact 0) pe puncte și zone mici** sunt acum tratate ca date lipsă: verificarea se
  face pe blocul întreg de 161 × 324 pixeli, nu pe fereastra decupată (sub 50 de pixeli nu se putea decide). Înainte,
  o analiză pe un oraș putea lua zilele nescrise drept 0 °C.
* **Sumele pe perioadă** (precipitații, PRCPTOT, grade-zile, PET, bilanț, SPI, SPEI) se corectează proporțional pentru
  zilele lipsă (× n / n valide), ca seriile pe zone. Înainte, până la 10 % zile lipsă intrau ca 0: SPI ieșea mai uscat,
  SPEI mai umed. Parametrii SPI / SPEI din cache se recalculează automat.
* **SPI / SPEI refuză perioadele incomplete**, și cu „Acceptă perioade incomplete” bifat (o vară tăiată ieșea „secetă
  extremă”).
* **Trendul pe serii constante** (ex. 0 zile tropicale pe munte): p = 1, deci hașurat ca nesemnificativ; seriile
  perfect liniare: p = 0.
* **Superlative:** GeoPackage-ul pe zone nu se mai decalează când o zonă nu are candidați; rangul anului evidențiat se
  face mereu între ani („locul 3 din 65 de ani”), și la unitatea „zi”; anul evidențiat se colorează corect și la iarnă.
* **Punctul din afara grilei** e refuzat cu un mesaj clar, care recunoaște coordonatele inversate (lat, lon).
* **Dungile și harta an × lună**: un an lipsă devine o coloană goală, nu mai decalează anii de după el.
* **Scrierea GeoTIFF-urilor** se verifică: un fișier blocat (deschis în QGIS) sau un disc plin dau un mesaj clar,
  nu un fișier lipsă raportat ca scris.
* **Windows:** mutarea la coș a unei rulări deschise pe hartă (fișier blocat de GDAL); fereastra de pornire nu se mai
  închide fără mesaj la o eroare; curățenia de după instalare nu mai poate opri pornirea.
* **Harta:** etichetele legendei pe clase („10–20”, nu „20”); o bandă fără date nu mai blochează panoul.
* **Titlul mediilor multianuale:** „media 2020–2025 (6 ani)” în loc de „medie anuală”.
* **Rețetele rapide nu mai îmbătrânesc:** „Vara trecută”, „Iarna trecută” și „Medii” folosesc ultima perioadă
  încheiată (reperele `ultima_vara`, `ultima_iarna`, `ultimul_an`).
* **Documentație:** variația ariei pixelilor e ~9 % între sud și nord (nu „sub 2 %”); comenzile de test pentru Windows;
  vechiul manual al scripturilor marcat ca istoric.

## 1.0.1 — 2026-11-27 · primele observații ale utilizatorilor

* **Analize rapide → „Medii: temperatura și precipitațiile”** (rețeta `r6`): temperatura medie, media maximelor și a
  minimelor și cantitatea medie de precipitații. Formularul are doar trei alegeri: anii, sezonul (an, anotimp, luni
  alese, interval de zile) și zona. Implicit: ultimul an încheiat, toată țara (≈ 0,6 GB).
* **Harta**: playerul animației și eticheta anului de pe hartă sunt mult mai mici (anul apare deja în titlu și în player).

## 1.0.0 (intern 5.2) — 2026-11-26 · prima versiune publică · animație, comparație, relief, pagina de start, prezentare

**Pagina de start** (tabul *Start*, deschis implicit): trei intrări (analize rapide, toate analizele, harta) și ultimele 24 de rulări ca fișe cu imagine. Fiecare fișă are butoanele *Fișa*, *Pe hartă* și, dacă rularea are o serie pe ani, *Prezintă*. Rulările fără PNG primesc o miniatură generată din GeoTIFF (în `rezultate/_cache/miniaturi/`).

**Animația pe ani.** Motorul *Hartă — media pe ani* are o ieșire nouă, bifată implicit: **GeoTIFF pe ani** (`…_pe_ani.tif`). Fișierul are câte o bandă pentru fiecare an, iar descrierea benzii e anul; paleta și o scară comună tuturor anilor sunt în metadate, ca anii să se poată compara după culoare. În tabul Hartă, aceste fișiere sunt marcate cu „▶ pe ani” și au un player: pornire/oprire, cursor, viteză și **⬇ video** (MP4 sau WebM, după browser, cu titlu, legendă și atribuire).

**Comparația A | B** e acum la vedere: butonul *A|B* de pe hartă (sau tasta C) și caseta „Compară cu o hartă B” din panoul din dreapta. La o serie pe ani, *A|B* pune direct primul an lângă ultimul; animația merge pe A, iar B rămâne fix.

**Relieful** (butonul ⛰ sau tasta R): umbrirea calculată în browser din `date/dem_grila_zarr.tif`, sub orice hartă. Apare și în PNG-urile și video-urile salvate.

**Modul prezentare** (butonul ⛶ sau tasta P): ecran complet, cu titlu mare, legendă și anul pe hartă. Tastele: ← → anii (sau benzile), spațiu = pornește/oprește, ↑ ↓ = rasterul anterior/următor din aceeași rulare (cu aceeași încadrare), C = comparație, R = relief, Esc = ieșire.

## intern 5.1.1 — verificarea datelor

În antet, lângă „date până la …”, a apărut butonul **verifică datele**. El pornește rețeta *00 · Verifică datele cubului*:

- **istoricul complet** (fără descărcare): pentru fiecare variabilă se verifică existența fiecărui chunk; un chunk care lipsește într-un bloc care are de regulă date apare în listă;
- **ultimele 150 de zile** (citire efectivă, ~0,35 GB): pe fiecare bloc de 161 × 324 pixeli se caută zilele în care toți pixelii au exact 0 (blocuri nescrise, ca în GIF-ul cu dreptunghiuri la 0).

Rezultate: graficul disponibilității (verde = date, roșu = chunk lipsă, portocaliu = bloc nescris), harta chunk-urilor pe istoric, `*_probleme.csv` (variabilă, tip, perioadă, bloc, coordonate) și ultima zi sigură pentru fiecare variabilă. Eticheta din antet devine **date verificate ✓** sau **⚠ sigure până la ZZ.LL.AAAA**.

**Protecția e automată, cu sau fără buton.** Orice analiză tratează golurile ca *date lipsă* (NaN), nu ca 0: chunk-urile lipsă, blocurile de temperatură cu toate valorile exact 0 și, în ultimele două trimestre, precipitațiile din blocurile în care Tmax e nescris (la precipitații, 0 e o valoare reală, deci nu poate fi judecat singur). Când se întâmplă, jurnalul și fișa vizuală afișează un avertisment portocaliu „Date cu goluri”.

## intern 5.1.0 — etapa 3a: ordine și aspect

* **Fișa vizuală a fiecărei rulări** (`index.html` în folderul rulării): titlul, harta principală, faptele-cheie
  (recordul, locul anului ales, perioada, ultima zi cu date), **comparația cu cortină** între oricare două hărți ale
  rulării, galeria graficelor, fișierele, parametrii, refacerea și citarea. Se deschide din program („fișa”) sau
  direct din folder; folderul se poate copia sau trimite întreg.
* **Relieful sub hărțile PNG**: umbrirea din DEM-ul coregistrat (lumină din nord-vest); în afara zonei, relieful
  apare în gri, ca fundal. Setare avansată „Relieful (umbrire) sub hărțile PNG”. Hărțile PNG sunt decupate strâns.
* **Tabul Hartă, ordonat**: rasterele grupate pe rulări (cea mai recentă deschisă, celelalte pliate, ultimele 8
  vizibile), nume scurte, acțiuni pe rulare (fișa, folderul, **la coș** = `rezultate\_cos`, golit explicit).
* **Numele spun ce s-a calculat**: titlul rulării se construiește din parametri (de ex. „Cele mai reci 7 zile
  consecutive din noiembrie (după Tmin) · București”) și dă numele folderului, al fișierelor, al istoricului și al fișei.
* **Superlative restrânse la o parte a anului**: la „o zi” și „N zile consecutive”, câmpul „Doar în această parte
  a anului” (o lună, un sezon, un interval): de ex. cea mai geroasă săptămână din noiembrie.
* Clasamentele de minime (cele mai reci) au barele orientate astfel încât recordul să aibă bara cea mai lungă.

## v5.1 etapa 2 (superlative)

* **Motorul „Superlative”** și grupul lui de rețete (s1–s7): cel mai ploios mai, cele mai calde zile din istorie,
  cele mai ploioase 3 zile consecutive, cea mai rece lună din toată seria, recordurile județelor, harta anului
  celei mai calde veri și varianta liberă.
  - Variabile: Tmax, Tmin, Tmed, P; maximul sau minimul.
  - Unități: o zi, N zile consecutive (fereastră glisantă), o lună anume de-a lungul anilor, oricare lună din serie,
    un sezon, anul, un interval fix din fiecare an (și peste Anul Nou, de ex. 12-15 → 01-15).
  - **Clasament** (punct, dreptunghi, țară sau fiecare poligon dintr-un fișier vectorial): media zilnică a zonei,
    top N, recordul, al doilea, media, locul unui an ales; CSV, grafice, GeoPackage cu recordul fiecărui poligon.
    Folosește cache-ul seriilor zonale, comun cu graficele de serii: a doua analiză pe aceeași zonă e instantanee.
  - **Hărți pe pixel**: valoarea recordului, **anul recordului**, data lui (luna sau ziua din an), marja față de
    al doilea și locul unui an ales; plus graficul „în ce procent din zonă deține fiecare an recordul”.
  - Fișa „Superlative și recorduri” în Indicatori → Metode statistice.
* Formularul ascunde câmpurile care nu se aplică (de ex. „Luna” când unitatea e „o zi”); jurnalul la fel.

## v5.1 etapa 1 (resurse și analize rapide)

* **Memorie de 2–4 ori mai mică**, cu rezultate identice (toate GeoTIFF-urile suitei comparate bit cu bit):
  citirea pe bucăți de chunk (fără copia dublă a asamblării dask), indicatorii calculați pe benzi de 64 de rânduri,
  variabilele încărcate doar când le cere un indicator și eliberate imediat, un singur an în memorie, pragurile
  percentile mapate de pe disc. Exemple pe toată țara: zile tropicale 2,4 → 1,1 GB; De Martonne 5,0 → 2,5 GB;
  extreme percentile (rețeta 23) 6 GB (eșua pe 7 GB) → 1,3 GB.
* **„Verifică” arată și memoria, și timpul de calcul**, pe lângă descărcare, și avertizează când memoria cerută
  depășește ce e liber pe calculator. Modelul e calibrat pe un calculator cu 2 nuclee și 7 GB
  (`instrumente/masoara_resurse.py`, `instrumente/calibreaza_indicatori.py` → `clima/cost_indicatori.json`);
  pe alt calculator se poate recalibra rulând al doilea instrument. Precizia: ±10 % la memorie, ±50 % la timp.
* **Tabul „⚡ Analize rapide”**: analize care, cu valorile implicite, descarcă sub 1 GB și calculează sub un minut
  (verificat automat de suita de teste): ultimele 30 de zile zi cu zi, județele în ultimele 30 de zile (CSV),
  vara trecută, ploile unui an, iarna trecută, plus 09, 10 și 12.
* **Perioade relative:** în rețete, începutul `"-30"` înseamnă ultimele 30 de zile până la ultima zi cu date;
  fișa de reproducere păstrează datele exacte.
* Corecturi: estimarea pentru serii și dungi (14, 15) nu funcționa din v5.0; numele ieșirilor urmează rețeta.

## v5.0 livrarea B (percentile și secetă)

* **Indici ETCCDI pe percentile** (grupul „Percentile (ETCCDI)”): TX90p, TN90p, TX10p, TN10p, WSDI, CSDI, R95p/R99p și
  R95pTOT/R99pTOT. Pragurile sunt percentilele zilei calendaristice (fereastră de 5 zile, cuantila de tip 8, ca în
  ClimPACT) sau ale zilelor ploioase, din **perioada de bază, implicit normala OMM 1991–2020**, modificabilă în formular
  (cel puțin 10 ani). Fără bootstrap (limitare documentată în fișe).
* **Seceta** (grupul „Secetă și bilanț hidric”): **SPI** (gamma cu zerouri), **SPEI** (P − PET, logistica generalizată
  prin L-momente nedeplasate, ca pachetul de referință SPEI), **PET Hargreaves** (FAO-56) și **bilanțul P − PET**.
  Sezonul ales dă scara: iunie–august = SPI-3 de vară, anual = SPI-12. Hărțile SPI/SPEI au scala fixă ±3, centrată pe 0.
* **Rețete noi:** 23 (extreme termice relative) și 24 (seceta: SPI și SPEI).
* **Prima rulare pe o zonă** citește și anii de bază (estimarea din „Verifică” îi include): pentru TX90p + TN90p pe toată
  țara ≈ 20 GB, pentru SPI/SPEI de vară ≈ 7 GB. Rezultatul se păstrează în `rezultate\_cache\praguri`, `spi`, `spei`;
  rulările următoare durează cât o analiză obișnuită. „Verifică” avertizează dacă baza nu e acoperită de date.
* Statistica e scrisă fără scipy și verificată cu valori din tabele (29 de teste cu răspuns cunoscut).
* **Rețeta 15:** avertismentul de sensibilitate semnalează acum și când, fără un singur an, panta se schimbă cu peste
  jumătate (aceeași regulă ca în calculatorul din tabul Indicatori).

## v5.0 livrarea A (rezultate ordonate și metode documentate)

* **Un folder pentru fiecare rulare:** `rezultate\2026-11-21_0724_02_zile_tropicale\` (data și ora în față, ca
  folderele să se ordoneze singure). În el: rezultatele, `jurnal.txt` și `reproducere.json`. Rulările repetate
  în același minut primesc `_2`, `_3`… Numele fișierelor nu mai au nevoie de amprenta parametrilor.
* **Fișa de reproducere** (`reproducere.json`) conține rețeta, parametrii efectivi, sursa datelor, frontiera datelor
  la momentul rulării, versiunile bibliotecilor și amprenta mediului (`pixi.lock`). Este și un job valid: analiza
  se reface, într-un folder nou, cu `instrumente\pixi.exe run python clima\ruleaza.py <folder>\reproducere.json`.
* **Cache-ul analizelor** (serii zonale, ferestrele episoadelor) e comun tuturor rulărilor: `rezultate\_cache\`.
  Folderele vechi `rezultate\cache_serii` și `rezultate\cache_episod` pot fi șterse.
* **Tabul Indicatori → Metode statistice:** fișe pentru tendința OLS și testul t, Theil–Sen + Mann–Kendall,
  sensibilitatea la un singur an și regula „întâi pixelul, apoi zona”, cu codul Python exact și două calculatoare
  (tendința pe o serie editabilă de 12 ani; patru pixeli × o săptămână, pe cele două căi de agregare).
* **Corecție de metodă:** p-valoarea tendinței OLS (hărți, serii, altitudine) folosește acum distribuția Student
  cu n − 2 grade de libertate, nu aproximarea normală. Pe serii lungi (60+ ani) diferența e neglijabilă; pe 10–20
  de ani, versiunile vechi arătau tendințe „semnificative” prea des (ex. t = 2,0 pe 12 ani: p = 0,046 → 0,073).
  Hărțile de semnificație OLS pe perioade scurte trebuie refăcute. Theil–Sen + Mann–Kendall nu sunt afectate.

## v5 etapa 2a (metode verificabile)

* **Indici ETCCDI de precipitații:** CWD (cel mai lung șir ploios), SDII (intensitatea unei zile ploioase),
  PRCPTOT (precipitațiile zilelor ≥ 1 mm), fiecare cu fișă teoretică și calculator pe 14 zile. Rețeta **10b**
  le adună pe județe, împreună cu Rx1day, Rx5day, R10mm, R20mm și CDD.
* **Tendința robustă:** rețetele 05 (hartă) și 15 (serii, în „Setări avansate”) au câmpul „Metoda tendinței”:
  regresie liniară (OLS) sau **Theil–Sen + Mann–Kendall** (cu corecția pentru valori egale). La harta Theil–Sen,
  jurnalul arată cât diferă de OLS. Pe toată țara, 65 de ani: ~40 s în plus.
* **Sensibilitatea la un singur an** (rețeta 15, graficul „sensibilitatea la un singur an”): media recentă și
  tendința recalculate fără câte un an; jurnalul avertizează dacă un singur an schimbă semnul sau verdictul p < 0,05.
* **Teste cu răspuns cunoscut:** 17 (acum 19, cu testul Student), inclusiv o comparație Theil–Sen / Mann–Kendall cu definiția, pe 200 de serii.

## Ce s-a schimbat în v4.1 (după al doilea audit independent)

* **Valorile anuale** din seriile pe zone (rețetele 15, 15b) se calculează acum mereu per pixel, apoi pe zonă,
  cu aceeași regulă de validitate ca hărțile. Seriile și tabelele vechi pot diferi ușor acolo unde lipseau zile.
* **Filtrul de altitudine** ajunge acum pe toate traseele (serii fără poligoane, statistici pe dreptunghi,
  normala episodului, zonările rețetei 18).
* **Numele rezultatelor** primesc o amprentă scurtă a parametrilor (ex. `…_2016-2025_3f9a1c_…`): două rulări
  cu zone sau setări diferite nu se mai suprascriu. (Din v5.0, doar când folderul rezultatelor e ales explicit.)
* **Cache-ul de date** e separat pe sursă (`cache_date/<amprenta sursei>/`). Folderele vechi de chunk-uri din
  `cache_date/` pot fi șterse; programul le curăță oricum treptat.
* **Teste cu răspuns calculat de mână**: `instrumente/teste_cunoscute.py` (rulate și de `testeaza_retete.py`).
  Model pentru oricine adaugă un indicator nou.

