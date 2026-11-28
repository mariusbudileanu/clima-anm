# -*- coding: utf-8 -*-
"""
teorie_indicatori.py — fișele teoretice ale indicatorilor (tabul „Indicatori” din interfață)
============================================================================================
Pentru fiecare cod din registru (indicatori.py): definiția, formula, simbolurile, pașii EXACȚI pe care îi face codul,
interpretarea, standardul (ETCCDI / ANM), limitările și o întrebare pentru studenți.
Formulele pot conține <sub>, <sup>, <b>, <i> (HTML simplu).

Un indicator nou primește fișa lui aici, cu aceeași cheie ca în registru. Fără fișă, interfața arată doar descrierea
scurtă și codul Python.
"""

# -------------------------------------------------------------------------------------------------
# Pașii comuni: ce se întâmplă cu ORICE indicator, înainte și după funcția lui
# -------------------------------------------------------------------------------------------------
PASI_COMUNI = [
    ("Deschiderea cubului",
     "Se citește un singur fișier mic, <code>.zmetadata</code> (~8 KB), cu toate metadatele store-ului Zarr, plus "
     "coordonatele <code>time</code>, <code>y</code>, <code>x</code>. Nu se descarcă încă nicio valoare climatică."),
    ("Frontiera datelor",
     "Se citesc scalarii <code>last_max_temp_time</code>, <code>last_min_temp_time</code>, <code>last_precipitation_time</code>: "
     "ultima zi scrisă, pe variabilă. Axa timpului e pre-alocată până în 2050, iar zilele nescrise conțin 0,0 (nu NaN!). "
     "Tot ce e după frontieră este ignorat; la mai multe variabile se folosește frontiera comună (minimul)."),
    ("Fereastra zonei",
     "Zona (țara, un dreptunghi, un punct, poligoane) se transformă în indici de rând și coloană pe grila de 0,01°. "
     "Poligoanele (în orice proiecție) se reproiectează în WGS 84 și se rasterizează pe grilă: fiecare pixel primește "
     "numărul poligonului în care cade centrul lui."),
    ("Perioada fiecărui an",
     "Pentru fiecare an se calculează intervalul sezonului: <i>anual</i> = 1 ian.–31 dec., <i>JJA</i> = 1 iun.–31 aug., "
     "<i>DJF</i> = 1 dec. din anul precedent – 28/29 feb. Un an care depășește frontiera datelor e <b>exclus</b> "
     "(altfel media ar fi falsă), cu excepția setării „Acceptă perioade incomplete”."),
    ("Citirea datelor",
     "Se descarcă doar chunk-urile Zarr care se intersectează cu intervalul și fereastra (blocuri de 90 de zile × "
     "161 × 324 pixeli), se decomprimă și rezultă un tablou <code>(zile, rânduri, coloane)</code> în float32. "
     "O variabilă se citește o singură dată pe an, chiar dacă o folosesc mai mulți indicatori."),
    ("Controlul validității",
     "Pentru fiecare pixel se calculează fracția zilelor în care <b>toate</b> variabilele necesare au valori. "
     "Dacă e sub pragul de validitate (implicit 90 %), pixelul devine NoData pentru acel an. Astfel golurile de date "
     "(de ex. aprilie–mai 2026 în unele sectoare) nu produc hărți false."),
    ("Funcția indicatorului",
     "Abia acum se aplică formula indicatorului, pixel cu pixel, pe zilele anului: rezultă <b>o hartă 2D pe an</b>. "
     "Pașii specifici fiecărui indicator sunt descriși în fișa lui."),
    ("Combinarea anilor (motorul)",
     "Hărțile anuale se combină după motorul ales: <b>hartă</b> = media pe ani (NaN ignorate); <b>anomalie</b> = "
     "media țintă − media de referință (sau 100 × țintă / referință); <b>tendință</b> = panta regresiei liniare pe ani, "
     "× 10 (unitate pe deceniu), cu p-valoarea testului t (distribuția Student, n − 2 grade de libertate) sau panta Theil–Sen cu testul Mann–Kendall, calculată doar unde există ≥ 10 ani; "
     "<b>atlas</b> = media pe ani, apoi media pixelilor fiecărui poligon."),
    ("Rezultatele",
     "GeoTIFF (COG, EPSG:4326, NoData = NaN, cu paleta în metadate), hartă PNG cu contur, grafic cu seria pe ani "
     "(media zonei), GeoPackage și CSV pe zone. Fiecare rulare are folderul ei, "
     "<code>rezultate/&lt;data_ora&gt;_&lt;analiza&gt;/</code>, cu rezultatele, jurnalul (<code>jurnal.txt</code>) și "
     "fișa de reproducere (<code>reproducere.json</code>: rețeta, parametrii, sursa datelor, frontiera, versiunile)."),
]

# -------------------------------------------------------------------------------------------------
# Fișele
# -------------------------------------------------------------------------------------------------
TEORIE = {
    "medie": dict(
        rezumat="Media valorilor zilnice ale unei variabile într-o perioadă.",
        definitie="Pentru fiecare pixel, se adună valorile zilnice ale variabilei alese (Tmax, Tmin sau P) din perioadă "
                  "și se împart la numărul zilelor cu date. Este cel mai simplu descriptor al climei unei perioade.",
        formula="X̄ = (1 / n) · Σ<sub>z=1…n</sub> X<sub>z</sub>",
        simboluri=[["X<sub>z</sub>", "valoarea variabilei în ziua z (°C sau mm)"],
                   ["n", "numărul zilelor cu date din perioadă (zilele NaN nu intră nici la sumă, nici la numitor)"]],
        pasi=["Ia tabloul variabilei alese, de forma (zile, rânduri, coloane).",
              "Calculează <code>np.nanmean</code> pe axa zilelor: media fiecărui pixel, ignorând zilele fără date.",
              "Rezultă o hartă cu media perioadei (pentru un an); motorul face apoi media pe ani."],
        interpretare="Tmax medie a verii (JJA) descrie cât de calde sunt după-amiezile; Tmin medie, cât de calde sunt nopțile. "
                     "Pentru precipitații, media zilnică (mm/zi) e mai puțin intuitivă: pentru totaluri folosiți indicatorul „Suma”.",
        standard="ETCCDI nu are un indice „medie” separat; e baza climatologiei (normale OMM 1991–2020).",
        limitari=["Media ascunde extremele: două veri cu aceeași medie pot avea număr foarte diferit de zile caniculare.",
                  "Media pe ani a mediilor anuale este egală cu media tuturor zilelor doar dacă anii au același număr de zile valide."],
        intrebare="De ce Tmin medie de vară a crescut, în multe orașe, mai repede decât Tmax medie? (Gândiți-vă la insula de căldură urbană.)",
        calculator="medie"),
    "tmedie": dict(
        rezumat="Temperatura medie zilnică aproximată ca (Tmax + Tmin) / 2, mediată pe perioadă.",
        definitie="Cubul ANM nu conține temperatura medie zilnică. O aproximare standard este media dintre maxima și minima "
                  "zilei. Se calculează zi cu zi, apoi se face media pe perioadă.",
        formula="T̄ = (1 / n) · Σ<sub>z</sub> (Tmax<sub>z</sub> + Tmin<sub>z</sub>) / 2",
        simboluri=[["Tmax<sub>z</sub>, Tmin<sub>z</sub>", "temperatura maximă / minimă a zilei z (°C)"],
                   ["n", "numărul zilelor cu ambele valori"]],
        pasi=["Ia tablourile Tmax și Tmin ale perioadei.",
              "Calculează, pentru fiecare zi și pixel, (Tmax + Tmin) / 2.",
              "Face media pe zile cu <code>np.nanmean</code> (o zi lipsă la oricare variabilă dă NaN în ziua aceea și e ignorată)."],
        interpretare="Este temperatura „climatică” obișnuită din atlase. Diferă puțin de media a 24 de valori orare "
                     "(în general cu câteva zecimi de grad).",
        standard="Aproximarea (Tmax + Tmin)/2 este folosită și de ETCCDI pentru temperatura medie zilnică (TG) când lipsesc datele orare.",
        limitari=["Pentru zilele cu răcire sau încălzire bruscă (front atmosferic), aproximarea poate fi mai slabă.",
                  "O zi lipsă la oricare dintre cele două variabile scoate ziua din medie."],
        intrebare="Ce se întâmplă cu Tmed aproximată într-o zi cu advecție de aer rece după-amiaza?",
        calculator="tmedie"),
    "suma": dict(
        rezumat="Suma valorilor zilnice pe perioadă: precipitațiile totale (mm).",
        definitie="Pentru precipitații, suma zilnică pe o perioadă dă cantitatea totală căzută: 1 mm = 1 litru pe metru pătrat.",
        formula="P<sub>tot</sub> = Σ<sub>z=1…n</sub> P<sub>z</sub>",
        simboluri=[["P<sub>z</sub>", "precipitațiile zilei z (mm)"], ["n", "zilele cu date din perioadă"]],
        pasi=["Ia tabloul variabilei (de obicei precipitațiile).",
              "Calculează <code>np.nansum</code> pe zile: zilele NaN sunt tratate ca 0.",
              "Pixelii fără nicio zi cu date devin NoData (altfel ar apărea fals cu 0 mm)."],
        interpretare="Media pe ani a sumei anuale este „precipitația medie anuală” din atlase. "
                     "Pe sezoane (de ex. aprilie–septembrie), descrie apa disponibilă pentru culturi.",
        standard="ETCCDI PRCPTOT adună doar zilele ude (P ≥ 1 mm); aici se adună toate zilele (diferența e de obicei mică).",
        limitari=["Zilele lipsă se numără ca 0 mm: cu pragul de validitate de 90 %, suma unui pixel poate fi subestimată "
                  "cu până la ~10 %. Pentru studii fine, ridicați pragul de validitate la 1,0.",
                  "Pentru temperaturi, suma nu are sens fizic (folosiți media sau GDD)."],
        intrebare="De ce o hartă a sumei anuale arată maxime pe munte, dar o hartă a zilelor ploioase poate arăta alt model spațial?",
        calculator="suma"),
    "zile_peste": dict(
        rezumat="Numărul de zile în care variabila depășește (sau egalează) un prag.",
        definitie="Se numără, pentru fiecare pixel, zilele în care valoarea e mai mare sau egală cu pragul (sau strict mai mare). "
                  "Cu pragurile potrivite, obținem indicii clasici ai extremelor de căldură și ai ploilor puternice.",
        formula="N = Σ<sub>z</sub> 1[X<sub>z</sub> ≥ prag]     (strict: 1[X<sub>z</sub> &gt; prag])",
        simboluri=[["1[·]", "funcția indicator: 1 dacă condiția e adevărată, 0 altfel"],
                   ["X<sub>z</sub>", "valoarea zilei z"], ["prag", "pragul ales (°C sau mm)"]],
        pasi=["Ia tabloul variabilei alese.",
              "Compară fiecare zi cu pragul: rezultă un tablou adevărat/fals (o zi NaN dă „fals”: nu se numără).",
              "Adună zilele adevărate pe axa timpului (<code>sum(axis=0)</code>).",
              "Pixelii fără nicio zi cu date devin NoData."],
        interpretare="Tmax ≥ 30 °C = zile tropicale; Tmax ≥ 35 °C = zile caniculare (definițiile ANM); Tmax > 25 °C = zile de vară; "
                     "Tmin > 20 °C = nopți tropicale; P ≥ 10 mm = zile cu ploi abundente. Indicatorii de prag sunt mult mai "
                     "sensibili la încălzire decât media: o creștere mică a mediei poate dubla zilele peste un prag ridicat.",
        standard="ETCCDI: SU (Tmax > 25 °C), TR (Tmin > 20 °C), R10mm / R20mm (P ≥ 10 / 20 mm). ANM: zi tropicală Tmax ≥ 30 °C, zi caniculară Tmax ≥ 35 °C.",
        limitari=["Zilele lipsă nu se numără: cu 90 % zile valide, numărul poate fi ușor subestimat.",
                  "Pragurile absolute nu țin seama de clima locală (la munte, 30 °C e extrem de rar; la câmpie, frecvent).",
                  "Valorile sunt cuantizate la 0,1 °C: „≥ 30” și „> 29,9” dau același rezultat."],
        intrebare="Dacă media verii crește cu 1 °C, de ce numărul zilelor ≥ 35 °C poate crește mult mai mult decât cel al zilelor ≥ 30 °C, în proporție?",
        calculator="zile_peste"),
    "zile_sub": dict(
        rezumat="Numărul de zile în care variabila e sub un prag (îngheț, ger).",
        definitie="Simetricul indicatorului „Zile peste prag”: se numără zilele cu valoarea sub prag (implicit strict sub).",
        formula="N = Σ<sub>z</sub> 1[X<sub>z</sub> &lt; prag]     (nestrict: 1[X<sub>z</sub> ≤ prag])",
        simboluri=[["X<sub>z</sub>", "valoarea zilei z"], ["prag", "pragul ales"]],
        pasi=["Ia tabloul variabilei alese.",
              "Compară fiecare zi cu pragul (zilele NaN nu se numără).",
              "Adună zilele care îndeplinesc condiția.",
              "Pixelii fără date devin NoData."],
        interpretare="Tmin < 0 °C = zile de îngheț; Tmax < 0 °C = zile de iarnă (îngheț toată ziua); Tmin ≤ −10 °C = zile geroase. "
                     "Scăderea lor în timp este unul dintre cele mai clare semnale ale încălzirii.",
        standard="ETCCDI: FD (Tmin < 0 °C), ID (Tmax < 0 °C).",
        limitari=["La fel ca la „peste prag”: zilele lipsă nu se numără.",
                  "Pentru iarnă, alegeți sezonul DJF sau „iarna extinsă” (noi.–mar.): un an calendaristic taie iarna în două."],
        intrebare="De ce numărul zilelor de îngheț poate scădea chiar dacă iernile au încă episoade foarte reci?",
        calculator="zile_sub"),
    "amplitudine_medie": dict(
        rezumat="Diferența medie dintre maxima și minima zilei (DTR).",
        definitie="Amplitudinea termică diurnă arată cât de mare e diferența dintre zi și noapte. Este mare în climatele "
                  "continentale, pe cer senin și sol uscat; mică pe cer acoperit, lângă apă sau în orașe.",
        formula="DTR = (1 / n) · Σ<sub>z</sub> (Tmax<sub>z</sub> − Tmin<sub>z</sub>)",
        simboluri=[["Tmax<sub>z</sub> − Tmin<sub>z</sub>", "amplitudinea zilei z (°C)"]],
        pasi=["Calculează, zi cu zi și pixel cu pixel, Tmax − Tmin.",
              "Face media pe zile cu <code>np.nanmean</code>."],
        interpretare="Valori mari: Bărăganul, depresiunile intramontane (inversiuni, răcire nocturnă puternică). "
                     "Valori mici: litoralul, vârfurile montane expuse, marile orașe (nopți calde).",
        standard="ETCCDI: DTR.",
        limitari=["Nebulozitatea și umiditatea solului nu sunt în cub: interpretarea lor rămâne calitativă."],
        intrebare="De ce amplitudinea diurnă e mai mică în centrul unui oraș mare decât în câmpia din jur?",
        calculator="amplitudine_medie"),
    "amplitudine_absoluta": dict(
        rezumat="Diferența dintre cea mai mare Tmax și cea mai mică Tmin a perioadei.",
        definitie="Nu este o medie, ci distanța dintre cele două extreme ale perioadei, care pot fi în zile diferite.",
        formula="A = max<sub>z</sub>(Tmax<sub>z</sub>) − min<sub>z</sub>(Tmin<sub>z</sub>)",
        simboluri=[["max, min", "pe toate zilele perioadei"]],
        pasi=["Găsește maximul Tmax pe zile (<code>np.nanmax</code>).",
              "Găsește minimul Tmin pe zile (<code>np.nanmin</code>).",
              "Scade cele două hărți."],
        interpretare="Pe un an întreg, arată continentalismul: diferența dintre cea mai caldă zi a verii și cea mai rece noapte a iernii. "
                     "Valorile cele mai mari apar în depresiunile cu inversiuni termice iarna.",
        standard="ETCCDI: TXx − TNn (cei doi indici separat: TXx = max Tmax, TNn = min Tmin).",
        limitari=["Depinde de o singură zi la fiecare capăt: e sensibilă la erori izolate ale datelor.",
                  "În rețetele pe ani (harta, trendul) se calculează A în fiecare an și apoi se face media anilor. "
                  "Rezultatul este mai mic (de regulă cu 5–10 °C) decât amplitudinea absolută a întregului deceniu, "
                  "care combină cea mai caldă zi și cea mai rece noapte din ani diferiți (rețeta 17)."],
        intrebare="De ce această amplitudine e mai mare la Miercurea Ciuc decât la Constanța?",
        calculator="amplitudine_absoluta"),
    "gdd": dict(
        rezumat="Grade-zile de creștere: căldura acumulată peste o temperatură de bază.",
        definitie="Plantele cresc doar peste o temperatură de bază. Fiecare zi contribuie cu numărul de grade cu care "
                  "temperatura medie depășește baza; zilele mai reci contribuie cu 0. Suma pe sezon estimează dacă o cultură "
                  "ajunge la maturitate.",
        formula="GDD = Σ<sub>z</sub> max( (Tmax<sub>z</sub> + Tmin<sub>z</sub>) / 2 − T<sub>bază</sub> , 0 )",
        simboluri=[["T<sub>bază</sub>", "temperatura de bază: 10 °C (porumb, vița-de-vie), 5 °C (cereale păioase)"],
                   ["max(·, 0)", "zilele sub bază nu scad suma"]],
        pasi=["Calculează temperatura medie aproximată (Tmax + Tmin)/2 pentru fiecare zi.",
              "Scade temperatura de bază și taie valorile negative la 0 (<code>np.clip</code>).",
              "Adună pe zile cu <code>np.nansum</code>; pixelii fără date devin NoData."],
        interpretare="Exemplu orientativ: un hibrid de porumb timpuriu cere de ordinul a 1200–1400 GDD (bază 10 °C), unul târziu peste 1600. "
                     "Comparați harta cu cerințele hibrizilor pentru a vedea unde se pot cultiva.",
        standard="Metoda „medie simplă”. Există variante (Tmax limitat la 30 °C, metoda sinusoidală) care dau valori ușor diferite.",
        limitari=["Fără plafon superior: zilele foarte calde (peste ~30 °C), în care creșterea încetinește, contribuie la maximum.",
                  "Rezultatul depinde direct de sezonul ales: folosiți sezonul de vegetație (aprilie–septembrie)."],
        intrebare="De ce suma GDD a crescut mai repede în ultimele decenii decât temperatura medie anuală?",
        calculator="gdd"),
    "ultimul_inghet": dict(
        rezumat="Data (ziua din an) a ultimei zile cu îngheț primăvara.",
        definitie="Ultima zi dintre 1 ianuarie și 30 iunie în care Tmin coboară sub prag (implicit 0 °C). După ea, riscul de "
                  "îngheț pentru culturi și pomi scade mult.",
        formula="DOY<sub>ultim</sub> = max{ z ∈ [1 ian., 30 iun.] : Tmin<sub>z</sub> &lt; prag }",
        simboluri=[["DOY", "ziua din an (1 = 1 ianuarie, 100 ≈ 10 aprilie, 121 ≈ 1 mai)"]],
        pasi=["Marchează zilele din prima jumătate a anului (ianuarie–iunie) în care Tmin < prag.",
              "Pentru fiecare pixel, găsește ultima zi marcată (căutare de la sfârșit).",
              "Transformă indicele zilei în ziua din an (DOY).",
              "Dacă nu există nicio zi cu îngheț în interval, pixelul primește NoData (nu 0)."],
        interpretare="Valori mari = înghețuri târzii (zone reci, depresiuni). În timp, data scade (înghețurile se termină mai devreme), "
                     "dar înflorirea pomilor se grăbește și ea, deci riscul nu dispare.",
        standard="Definiție agroclimatică clasică; nu este un indice ETCCDI.",
        limitari=["Cere sezonul „anual” (perioada trebuie să înceapă la 1 ianuarie).",
                  "O zi lipsă exact în ziua ultimului îngheț îl poate muta mai devreme.",
                  "Un an fără îngheț primăvara dă NoData pentru acel an: media pe ani se face doar pe anii cu îngheț. "
                  "Pentru durata sezonului fără îngheț folosiți fișa dedicată, care tratează corect acești ani."],
        intrebare="De ce un singur îngheț târziu (de ex. pe 20 aprilie) poate distruge recolta de caise, deși media datei ultimului îngheț e în martie?",
        calculator=None),
    "primul_inghet": dict(
        rezumat="Data (ziua din an) a primei zile cu îngheț toamna.",
        definitie="Prima zi dintre 1 iulie și 31 decembrie în care Tmin coboară sub prag.",
        formula="DOY<sub>prim</sub> = min{ z ∈ [1 iul., 31 dec.] : Tmin<sub>z</sub> &lt; prag }",
        simboluri=[["DOY", "ziua din an (274 ≈ 1 octombrie, 305 ≈ 1 noiembrie)"]],
        pasi=["Marchează zilele din a doua jumătate a anului (iulie–decembrie) cu Tmin < prag.",
              "Pentru fiecare pixel, găsește prima zi marcată.",
              "Transformă indicele în ziua din an; fără îngheț → NoData."],
        interpretare="Valori mici = înghețuri timpurii (munte, depresiuni). O dată mai târzie în timp lungește sezonul de vegetație.",
        standard="Definiție agroclimatică clasică.",
        limitari=["Cere sezonul „anual”.",
                  "Anii fără îngheț până la 31 decembrie dau NoData pentru acel an; media pe ani se face doar pe anii cu îngheț."],
        intrebare="Ce culturi profită de amânarea primului îngheț de toamnă?",
        calculator=None),
    "sezon_fara_inghet": dict(
        rezumat="Numărul de zile dintre ultimul îngheț de primăvară și primul îngheț de toamnă.",
        definitie="Numărul de zile <b>strict între</b> ultimul îngheț de primăvară și primul îngheț de toamnă, în același an. "
                  "Exemplu: îngheț în ziua 100 și apoi în ziua 101 → 0 zile fără îngheț (nu 1).",
        formula="D = DOY<sub>prim</sub> − DOY<sub>ultim</sub> − 1",
        simboluri=[["DOY<sub>prim</sub>", "primul îngheț de toamnă"], ["DOY<sub>ultim</sub>", "ultimul îngheț de primăvară"]],
        pasi=["Calculează ultimul îngheț de primăvară (fișa „Ultimul îngheț”).",
              "Calculează primul îngheț de toamnă (fișa „Primul îngheț”).",
              "Dacă primăvara nu a fost niciun îngheț, sezonul începe la 1 ianuarie: DOY<sub>ultim</sub> = 0.",
              "Dacă toamna nu a fost niciun îngheț, sezonul ține până la 31 decembrie: DOY<sub>prim</sub> = zilele anului + 1.",
              "D = DOY<sub>prim</sub> − DOY<sub>ultim</sub> − 1; NoData doar unde pixelul nu are deloc date."],
        interpretare="Un sezon mai lung permite culturi cu perioadă de vegetație mai lungă sau două recolte.",
        standard="Diferit de ETCCDI GSL (growing season length), care folosește șiruri de 6 zile cu temperatura medie peste / sub 5 °C.",
        limitari=["Moștenește limitările celor două date.",
                  "De ce nu NoData pentru anii fără îngheț: altfel media ar exclude exact anii cei mai calzi și ar subestima "
                  "durata în zonele calde (bias de cenzurare). Un an complet fără îngheț dă D = 365 sau 366."],
        intrebare="De ce sezonul fără îngheț și GSL (ETCCDI) pot da rezultate diferite pentru același loc?",
        calculator=None),
    "cdd": dict(
        rezumat="Cel mai lung șir de zile consecutive fără precipitații (zile uscate).",
        definitie="O zi este „uscată” dacă precipitațiile sunt sub prag (implicit 1 mm). Indicatorul este lungimea celui mai lung "
                  "șir neîntrerupt de zile uscate din perioadă: o măsură simplă a secetei meteorologice.",
        formula="CDD = max (lungimea șirurilor de zile consecutive cu P<sub>z</sub> &lt; prag)",
        simboluri=[["P<sub>z</sub>", "precipitațiile zilei z (mm)"], ["prag", "1 mm (o zi cu 0,4 mm e tot uscată)"]],
        pasi=["Marchează zilele uscate: P < prag <b>și</b> valoare existentă.",
              "Parcurge zilele în ordine, cu un contor pentru fiecare pixel: +1 la o zi uscată, revenire la 0 la o zi udă.",
              "Păstrează maximul atins de contor.",
              "Atenție: o zi <b>lipsă</b> (NaN) întrerupe șirul, ca o zi udă."],
        interpretare="Valori mari vara în sudul și estul țării indică secetă. Un CDD de 30+ zile în sezonul de vegetație afectează grav culturile.",
        standard="ETCCDI: CDD. Aici șirul se numără doar în interiorul perioadei: un șir care începe în decembrie și continuă în ianuarie se rupe la sfârșitul anului.",
        limitari=["Zilele lipsă rup șirurile: CDD poate fi subestimat unde datele au goluri.",
                  "Nu ține seama de evaporație: 20 de zile uscate în iulie înseamnă mai multă secetă decât în noiembrie."],
        intrebare="De ce două veri cu aceeași cantitate de precipitații pot avea CDD foarte diferit?",
        calculator="cdd"),
    "cwd": dict(
        rezumat="Cel mai lung șir de zile consecutive cu ploaie.",
        definitie="O zi este „ploioasă” dacă au căzut cel puțin 1 mm. CWD este lungimea celui mai lung șir neîntrerupt de zile "
                  "ploioase: perechea lui CDD, pentru perioadele umede persistente.",
        formula="CWD = max (lungimea șirurilor de zile consecutive cu P<sub>z</sub> ≥ prag)",
        simboluri=[["P<sub>z</sub>", "precipitațiile zilei z (mm)"], ["prag", "1 mm (o zi cu 0,6 mm nu e ploioasă)"]],
        pasi=["Marchează zilele ploioase: P ≥ prag <b>și</b> valoare existentă.",
              "Parcurge zilele în ordine, cu un contor pentru fiecare pixel: +1 la o zi ploioasă, revenire la 0 altfel.",
              "Păstrează maximul atins de contor.",
              "O zi <b>lipsă</b> rupe șirul, ca o zi uscată: șirul real ar putea fi mai lung."],
        interpretare="CWD mare apare în Carpați și în anii cu blocaje atmosferice ploioase: sol saturat, risc de alunecări "
                     "și viituri chiar fără o zi extremă.",
        standard="ETCCDI: CWD. Șirul se numără doar în interiorul perioadei analizate (se rupe la capetele ei).",
        limitari=["Pragul de 1 mm e convențional: pe o grilă interpolată, multe zile au urme de ploaie „împrăștiate” din stații vecine.",
                  "Zilele lipsă rup șirurile: CWD poate fi subestimat unde datele au goluri."],
        intrebare="Poate o lună să aibă CWD mare și totuși precipitații sub normală? Cum?",
        calculator="cwd"),
    "sdii": dict(
        rezumat="Cât plouă, în medie, într-o zi în care plouă.",
        definitie="Suma precipitațiilor din zilele ploioase (≥ 1 mm) împărțită la numărul acestor zile. Separă „plouă des” de "
                  "„plouă tare”: două veri cu aceeași sumă pot avea SDII foarte diferit.",
        formula="SDII = Σ P<sub>z</sub> (zile cu P<sub>z</sub> ≥ prag) / W",
        simboluri=[["W", "numărul zilelor cu P ≥ prag"], ["prag", "1 mm"]],
        pasi=["Marchează zilele ploioase (P ≥ prag, valoare existentă).",
              "Adună precipitațiile doar din aceste zile; numără-le (W).",
              "Împarte suma la W.",
              "Dacă W = 0 (nicio zi ploioasă), indicele e <b>nedefinit</b> (NoData), nu 0."],
        interpretare="SDII crește în multe regiuni ale Europei: aceeași cantitate de apă cade în mai puține zile, mai intens. "
                     "Comparați tendința SDII cu cea a numărului de zile ploioase.",
        standard="ETCCDI: SDII (simple daily intensity index).",
        limitari=["Interpolarea netezește aversele: SDII pe grilă e mai mic decât la o stație.",
                  "Cu puține zile ploioase (iarna în sud, sezoane scurte), SDII devine instabil: o singură zi îl schimbă mult."],
        intrebare="De ce SDII nu poate fi calculat simplu ca „suma pe perioadă / numărul de zile ale perioadei”?",
        calculator="sdii"),
    "prcptot": dict(
        rezumat="Precipitațiile totale, numărate doar din zilele cu cel puțin 1 mm.",
        definitie="Suma precipitațiilor din zilele ploioase. Diferă puțin de suma tuturor zilelor: urmele (sub 1 mm) nu intră. "
                  "Este totalul folosit ca numitor de indicatorii ETCCDI de tip R95pTOT (ce fracție vine din zilele extreme).",
        formula="PRCPTOT = Σ P<sub>z</sub> (zile cu P<sub>z</sub> ≥ prag)",
        simboluri=[["P<sub>z</sub>", "precipitațiile zilei z (mm)"], ["prag", "1 mm"]],
        pasi=["Marchează zilele ploioase (P ≥ prag, valoare existentă).",
              "Adună precipitațiile acestor zile.",
              "Zilele lipsă nu contribuie (ca la suma obișnuită); pragul PRAG_VALID decide dacă pixelul rămâne valid."],
        interpretare="Comparați PRCPTOT cu suma tuturor zilelor: diferența arată cât contează urmele de ploaie, mai mari pe "
                     "grila interpolată decât la stații.",
        standard="ETCCDI: PRCPTOT.",
        limitari=["Diferența față de suma simplă e mică (de regulă câteva procente) și depinde de pragul ales."],
        intrebare="Unde vă așteptați ca diferența dintre suma tuturor zilelor și PRCPTOT să fie cea mai mare? De ce?",
        calculator="prcptot"),
    "rxnday": dict(
        rezumat="Cea mai mare cantitate de precipitații căzută în n zile consecutive.",
        definitie="Pentru n = 1, este ziua cea mai ploioasă; pentru n = 5, cel mai ploios episod de 5 zile. Descrie ploile "
                  "torențiale, legate de viituri și inundații.",
        formula="Rx<i>n</i>day = max<sub>z</sub> ( P<sub>z</sub> + P<sub>z+1</sub> + … + P<sub>z+n−1</sub> )",
        simboluri=[["n", "durata ferestrei (zile)"], ["P<sub>z</sub>", "precipitațiile zilei z (mm)"]],
        pasi=["Înlocuiește zilele lipsă cu 0 mm.",
              "Pentru n > 1: adună cele n zile consecutive prin deplasări succesive ale seriei, pe benzi de rânduri (memorie mică pentru toată harta).",
              "Ia maximul pe toate pozițiile ferestrei.",
              "Pixelii fără date devin NoData."],
        interpretare="Rx1day mare: averse convective intense (vara) sau ploi orografice. Rx5day mare: episoade lungi de ploaie "
                     "(ex. sistemele mediteraneene), periculoase pentru bazinele mari.",
        standard="ETCCDI: Rx1day, Rx5day.",
        limitari=["Zilele lipsă sunt considerate fără ploaie: un episod cu o zi lipsă poate fi subestimat.",
                  "Datele sunt interpolate din stații: averse locale foarte intense, între stații, pot fi atenuate."],
        intrebare="De ce Rx1day pe o grilă interpolată este, de regulă, mai mic decât recordul unei stații?",
        calculator="rxnday"),
    "de_martonne": dict(
        rezumat="Indicele de ariditate De Martonne: raportul dintre precipitații și temperatură.",
        definitie="Un indice clasic al umidității climatului: precipitațiile anuale împărțite la temperatura medie + 10. "
                  "Cu cât e mai mic, cu atât clima e mai uscată.",
        formula="I<sub>DM</sub> = P<sub>an</sub> / (T + 10)",
        simboluri=[["P<sub>an</sub>", "precipitațiile perioadei aduse la un an: Σ P × 365,25 / n (mm)"],
                   ["T", "temperatura medie (Tmax + Tmin)/2 a perioadei (°C)"], ["n", "zilele cu precipitații valide"]],
        pasi=["Adună precipitațiile perioadei și le aduce la un an (× 365,25 / numărul zilelor valide).",
              "Calculează temperatura medie aproximată (Tmax + Tmin)/2, mediată pe perioadă.",
              "Folosește aceleași zile pentru P și T (doar zilele în care toate cele trei variabile au valori).",
              "Împarte: P<sub>an</sub> / (T + 10); unde T ≤ −10 °C, rezultatul este NoData."],
        interpretare="Clase: < 10 arid · 10–20 semiarid · 20–24 mediteranean · 24–28 semiumed · 28–35 umed · > 35 foarte umed. "
                     "În România: valorile cele mai mici în Dobrogea și Bărăgan, cele mai mari pe munte.",
        standard="Indice clasic (De Martonne, 1926), folosit în climatologia românească și în studiile de deșertificare.",
        limitari=["Formula are sens doar pentru T + 10 > 0. Pentru T ≤ −10 °C (iarna, pe crestele Carpaților) indicele ar ieși "
                  "negativ și ar fi clasat „arid”: de aceea programul pune acolo NoData.",
                  "Calculat pe un sezon, P<sub>an</sub> e „anualizat”: comparați doar sezoane de același tip."],
        intrebare="De ce indicele scade dacă temperatura crește, chiar dacă precipitațiile rămân aceleași?",
        calculator="de_martonne"),
}


# =====================================================================================
# METODE STATISTICE — fișe ca ale indicatorilor, pentru pașii care NU țin de un indicator anume
# (cum se trage o tendință, cât de sigură e, cum se trece de la pixeli la o zonă).
# „functii” = funcțiile din zarr_clima.py al căror cod exact apare în fișă.
# =====================================================================================
METODE = {
    "ols": dict(
        titlu="Tendința prin regresie liniară (OLS) și testul t",
        rezumat="Dreapta care trece cel mai aproape de valorile anuale; panta ei, × 10, este tendința pe deceniu.",
        definitie="Pentru fiecare pixel (sau pentru seria unei zone) se ajustează dreapta y = a + b·an prin metoda celor mai mici "
                  "pătrate: dintre toate dreptele posibile, cea care face minimă suma pătratelor abaterilor verticale. "
                  "Panta b este schimbarea medie pe an; o raportăm la deceniu (× 10). Testul t verifică dacă panta "
                  "se poate deosebi de zero, dată fiind împrăștierea anilor în jurul dreptei.",
        formula="b = Σ (x<sub>i</sub> − x̄)(y<sub>i</sub> − ȳ) / Σ (x<sub>i</sub> − x̄)² &nbsp;·&nbsp; "
                "SE(b) = √[ Σ e<sub>i</sub>² / (n − 2) / Σ (x<sub>i</sub> − x̄)² ] &nbsp;·&nbsp; t = b / SE(b)",
        simboluri=[["x<sub>i</sub>, y<sub>i</sub>", "anul și valoarea indicatorului în anul i (ani lipsă: nu intră)"],
                   ["e<sub>i</sub>", "reziduul: y<sub>i</sub> − (a + b·x<sub>i</sub>)"],
                   ["n", "numărul anilor cu date; sub 10 ani nu se calculează tendința"],
                   ["p", "probabilitatea unui |t| cel puțin atât de mare dacă panta reală ar fi zero; distribuția Student cu n − 2 grade de libertate"]],
        pasi=["Pentru fiecare pixel, păstrează doar anii cu valoare (NaN nu intră nici în medii, nici în sume).",
              "Calculează mediile x̄ și ȳ, apoi Sxx = Σ(x − x̄)² și Sxy = Σ(x − x̄)(y − ȳ); panta b = Sxy / Sxx.",
              "Calculează reziduurile și eroarea standard a pantei, SE(b); apoi t = b / SE(b).",
              "p-valoarea bilaterală vine din distribuția Student cu n − 2 grade de libertate (funcția <code>p_student</code>, "
              "scrisă cu beta incompletă, fără scipy).",
              "Panta se înmulțește cu 10 (unitate/deceniu); pixelii cu sub 10 ani valizi devin NoData. "
              "Harta de semnificație marchează p &lt; α (implicit 0,05)."],
        interpretare="+0,5 °C/deceniu la Tmax de vară înseamnă, în medie, o vară cu 0,5 °C mai caldă la fiecare 10 ani. "
                     "p &lt; 0,05 spune doar că o pantă atât de mare ar fi rar obținută din întâmplare dacă nu ar exista "
                     "nicio tendință; nu spune cât de mare e schimbarea sau de ce s-a produs.",
        standard="Metoda clasică din rapoartele IPCC AR6 (alături de Theil–Sen) și din ghidurile OMM pentru analiza seriilor climatice. "
                 "Până în v5.0 programul folosea aproximarea normală a testului t; acum folosește distribuția Student, "
                 "corectă și pentru serii scurte.",
        limitari=["Sensibilă la valori extreme: un singur an foarte cald la capătul seriei poate schimba vizibil panta "
                  "(vedeți fișa „Sensibilitatea la un singur an” și metoda Theil–Sen).",
                  "Presupune ani independenți. Seriile climatice au adesea autocorelare pozitivă (un an cald urmat de altul), "
                  "iar atunci p-valoarea este prea mică: semnificația e supraestimată.",
                  "O pantă descrie o schimbare liniară; o schimbare în trepte (de exemplu după 1990) apare tot ca „tendință”.",
                  "Pe o hartă cu sute de mii de pixeli, la α = 0,05 aproximativ 5 % dintre pixeli ar ieși „semnificativi” "
                  "chiar fără nicio tendință reală. Contează zonele întinse și coerente, nu pixelii izolați.",
                  "Tendința depinde de perioadă: 1961–2025 și 1991–2025 pot da pante foarte diferite. Precizați mereu anii."],
        intrebare="Pe 12 ani, aproximarea normală dădea p = 0,046 acolo unde distribuția Student dă p = 0,073. Ce ar fi scris "
                  "un student în concluzii în fiecare caz? Ce înseamnă asta pentru seriile scurte?",
        functii=["panta_deceniu", "p_student", "_beta_inc"],
        calculator="trend"),
    "sen_mk": dict(
        titlu="Theil–Sen și testul Mann–Kendall",
        rezumat="Tendința robustă: mediana pantelor dintre toate perechile de ani, cu un test care nu presupune distribuție normală.",
        definitie="Theil–Sen ia toate perechile de ani (i, j), calculează panta fiecărei perechi, (y<sub>j</sub> − y<sub>i</sub>) / "
                  "(x<sub>j</sub> − x<sub>i</sub>), și alege mediana lor. Un an excepțional influențează doar perechile din care "
                  "face parte, iar mediana le ignoră practic. Mann–Kendall numără, pe toate perechile, de câte ori valoarea "
                  "crește și de câte ori scade: dacă diferența (S) e mare față de cât ar da întâmplarea, seria are o "
                  "tendință monotonă.",
        formula="b<sub>Sen</sub> = mediana<sub>i&lt;j</sub> (y<sub>j</sub> − y<sub>i</sub>) / (x<sub>j</sub> − x<sub>i</sub>) &nbsp;·&nbsp; "
                "S = Σ<sub>i&lt;j</sub> semn(y<sub>j</sub> − y<sub>i</sub>) &nbsp;·&nbsp; "
                "Var(S) = [n(n−1)(2n+5) − Σ t(t−1)(2t+5)] / 18 &nbsp;·&nbsp; Z = (S − semn S) / √Var(S)",
        simboluri=[["semn(·)", "+1 dacă valoarea crește, −1 dacă scade, 0 dacă rămâne egală"],
                   ["t", "mărimea fiecărui grup de valori egale (frecvent la numărări de zile: mai mulți ani cu 0 zile)"],
                   ["S − semn S", "corecția de continuitate (S e un număr întreg, aproximăm cu o distribuție continuă)"],
                   ["p", "bilateral, din distribuția normală a lui Z (corectă pentru MK de la ~10 ani)"]],
        pasi=["Pentru fiecare pixel, formează toate perechile de ani (65 de ani → 2 080 de perechi); perechile cu un an lipsă nu intră.",
              "Panta Sen = mediana pantelor perechilor, × 10 pentru deceniu.",
              "S = numărul creșterilor minus numărul scăderilor.",
              "Varianța lui S se corectează pentru grupurile de valori egale; Z = (S − semn S)/√Var(S); p = erfc(|Z|/√2).",
              "Calculul e vectorizat pe blocuri de 8 000 de pixeli: ~38 s pentru 65 de ani pe toată țara, față de ~2 s la OLS."],
        interpretare="Când panta Sen și panta OLS sunt apropiate, tendința nu atârnă de câțiva ani extremi. Când diferă mult, "
                     "câteva valori extreme trag dreapta OLS: în jurnal programul notează diferența. Pentru indicatori de "
                     "numărare (zile tropicale, nopți tropicale) sau precipitații, Theil–Sen + MK sunt alegerea mai sigură.",
        standard="Recomandate de OMM și folosite în ETCCDI/ClimPACT, în rapoartele IPCC și în majoritatea studiilor de extreme climatice "
                 "(Sen, 1968; Mann, 1945; Kendall, 1975).",
        limitari=["Tot presupune ani independenți; cu autocorelare pozitivă p-valoarea e prea mică "
                  "(există variante „pre-whitening” sau Hamed–Rao, neincluse aici).",
                  "MK testează monotonia, nu liniaritatea: o serie care crește brusc și apoi rămâne constantă poate fi „semnificativă”.",
                  "La serii cu foarte multe valori egale (de exemplu zero zile în majoritatea anilor), panta Sen poate fi exact 0 "
                  "chiar dacă MK arată o tendință: mediana unor pante în mare parte nule este nulă.",
                  "Aceeași problemă a testelor multiple pe hartă ca la OLS: urmăriți tiparul spațial, nu pixelii izolați."],
        intrebare="Introduceți în calculator o serie plată cu un singur an foarte mare la final. Ce face panta OLS? Dar panta Sen? "
                  "Ce metodă ați alege pentru numărul de zile cu Tmax ≥ 35 °C la munte?",
        functii=["sen_mk_deceniu", "tendinta_deceniu"],
        calculator="trend"),
    "sensibilitate": dict(
        titlu="Sensibilitatea la un singur an",
        rezumat="Scoatem, pe rând, câte un an și refacem calculul: concluzia rezistă sau atârnă de un an excepțional?",
        definitie="Este un test „leave-one-out”. Pentru seria unei zone, programul recalculează de n ori media perioadei recente "
                  "și tendința, de fiecare dată fără un alt an. Dacă semnul tendinței sau semnificația ei se schimbă când "
                  "lipsește un singur an, concluzia trebuie formulată cu prudență.",
        formula="T<sub>(−k)</sub> = tendința calculată fără anul k &nbsp;·&nbsp; "
                "anul cel mai influent = argmax<sub>k</sub> |T<sub>(−k)</sub> − T|",
        simboluri=[["T", "tendința pe toți anii (metoda aleasă: OLS sau Theil–Sen)"],
                   ["T<sub>(−k)</sub>", "tendința fără anul k"],
                   ["M<sub>(−k)</sub>", "media perioadei recente fără anul k (doar pentru anii din perioada recentă)"]],
        pasi=["Calculează media perioadei recente și tendința pe toți anii.",
              "Pentru fiecare an k: îl scoate din serie și recalculează tendința (și media, dacă anul e în perioada recentă).",
              "Reține anul cu cea mai mare influență asupra tendinței și anul cu cea mai mare influență asupra mediei.",
              "Notează în jurnal dacă, fără vreun an, se schimbă semnul tendinței, trecerea pragului p = 0,05 sau mărimea "
              "pantei (cu peste jumătate) — aceeași regulă ca în calculatorul de mai jos.",
              "Scrie un grafic cu două panouri (puncte = fără anul respectiv, linie = toți anii) și un CSV cu toate valorile."],
        interpretare="Dacă toate punctele stau aproape de linie, rezultatul e robust. Un punct departe de linie identifică anul care "
                     "„face” rezultatul (adesea 2007, 2012 sau 2024 pentru căldură). Mesajul „semnificația se schimbă” "
                     "nu înseamnă că tendința nu există, ci că dovada statistică e la limită.",
        standard="Analiză de influență obișnuită în statistica aplicată (jackknife, diagnosticul DFBETA din regresie).",
        limitari=["Nu este un interval de încredere și nu corectează autocorelarea: arată doar dependența de un singur an.",
                  "Doi ani excepționali consecutivi se „acoperă” reciproc: scoaterea unuia nu arată influența amândurora.",
                  "Se aplică seriilor zonelor (graficele de serii), nu fiecărui pixel al hărții."],
        intrebare="Ce ar trebui să scrieți într-un raport dacă tendința Tmax de vară devine nesemnificativă fără anul 2024?",
        functii=["sensibilitate_un_an"],
        calculator="trend"),
    "pixel_zona": dict(
        titlu="Întâi pixelul, apoi zona",
        rezumat="Valoarea unui indicator pe o zonă = media indicatorului calculat în fiecare pixel, nu indicatorul mediei zonei.",
        definitie="Sunt două căi posibile. (A) Mai întâi facem media zilnică a zonei (o singură serie), apoi calculăm indicatorul "
                  "pe ea. (B) Calculăm indicatorul în fiecare pixel, apoi facem media pe pixelii zonei. Pentru indicatorii "
                  "liniari (medie, sumă) rezultatul e același; pentru praguri și extreme, nu. Programul folosește (B) pentru "
                  "toate valorile anuale pe zone, aceeași cale ca la hărți, ca un tabel și harta aceleiași analize să nu se contrazică.",
        formula="I<sub>zonă</sub> = (1 / N) · Σ<sub>pixeli</sub> I(x<sub>pixel</sub>) &nbsp;≠&nbsp; I( (1 / N) · Σ<sub>pixeli</sub> x<sub>pixel</sub> ) "
                "&nbsp;·&nbsp; % din normală pe zonă = 100 · media(țintă) / media(referință)",
        simboluri=[["I", "indicatorul (de exemplu numărul de zile cu Tmax ≥ 30 °C)"],
                   ["N", "pixelii zonei cu valoare validă (după filtrul de altitudine, dacă e folosit)"],
                   ["x<sub>pixel</sub>", "seria zilnică a pixelului"]],
        pasi=["Pentru fiecare an, calculează harta indicatorului (pași comuni + funcția indicatorului).",
              "Ia pixelii zonei (poligon rasterizat, dreptunghi, punct sau țara, eventual filtrați după altitudine).",
              "Face media acestor pixeli; NaN nu intră. Rezultatul e valoarea anuală a zonei.",
              "Valorile anuale se salvează în cache, ca un an deja calculat să nu mai fie recitit.",
              "Pentru procente (precipitații în % din normală), zona primește raportul mediilor, nu media rapoartelor."],
        interpretare="Exemplu: într-o zonă cu jumătate câmpie (40 de zile tropicale) și jumătate munte (0 zile), media pixelilor dă 20 "
                     "de zile, adică media a ceea ce trăiesc locurile zonei. Media zilnică a zonei (câmpie + munte) rămâne însă adesea sub 30 °C "
                     "chiar în zilele în care câmpia depășește pragul, deci calea (A) dă mult mai puține zile: un rezultat care nu "
                     "corespunde niciunui loc real.",
        standard="Aceeași regulă ca în produsele grilate ETCCDI (HadEX, Copernicus C3S): indicii se calculează la nivel de celulă, "
                 "apoi se agregă spațial.",
        limitari=["Media pixelilor nu ține cont că pixelii de 0,01° au arii diferite cu latitudinea: aria e proporțională cu cos φ, deci un pixel din sudul țării (43,5° N) e cu ~9 % mai mare decât unul din nord (48,4° N). Media zonei supraponderează astfel ușor nordul; pe o zonă cât un județ efectul e neglijabil.",
                  "Seriile zilnice și lunare din graficele de serii folosesc tot media zilnică a zonei (calea A): sunt utile pentru "
                  "a vedea evoluția, dar pragurile se citesc din valorile anuale.",
                  "Raportul mediilor (pentru %) dă mai multă greutate pixelilor umezi; media rapoartelor ar da greutate egală "
                  "fiecărui pixel. Sunt întrebări diferite; programul răspunde la „cât a plouat pe zonă față de normal”."],
        intrebare="Pentru un județ cu munte și câmpie, de ce cele două căi dau numere diferite de zile de îngheț? "
                  "În ce direcție vă așteptați să fie diferența și de ce depinde ea de prag?",
        functii=["anuale_indicator", "medie_raport_zona"],
        calculator="pixel_zona"),
}


# =====================================================================================
# v5.0 livrarea B: indicatori cu perioadă de bază (percentile ETCCDI, bilanț hidric, SPI, SPEI)
# =====================================================================================
_PRAG_ZILNIC = ("O singură dată pentru zonă: citește toți anii perioadei de bază (implicit normala OMM 1991–2020) pe blocuri "
                "de pixeli aliniate la chunk-urile cubului (sub ~0,6 GB de memorie) și scoate zilele de 29 februarie.")
_PRAG_FEREASTRA = ("Pentru fiecare dintre cele 365 de zile calendaristice adună, din toți anii de bază, valorile ferestrei de "
                   "5 zile centrate pe ea (30 × 5 = 150 de valori) și calculează percentila cu definiția de tip 8 "
                   "(Hyndman &amp; Fan), aceeași ca în ClimPACT / climdex. Sub 90 % din valori → NoData.")
_PRAG_CACHE = ("Pragurile (365 × pixeli) se salvează în <code>rezultate/_cache/praguri/</code>; rulările următoare, pe aceeași "
               "zonă și bază, le citesc direct de pe disc.")
_BAZA_STANDARD = ("Perioada de bază implicită este normala climatologică OMM actuală, 1991–2020 (WMO-No. 1203, 2017); ETCCDI "
                  "și seturile HadEX / climdex folosesc adesea 1961–1990. Valorile se compară doar între rezultate cu aceeași bază.")
_BAZA_LIMITA = ("Fără „bootstrap”: în anii din interiorul perioadei de bază indicii sunt ușor deplasați față de anii din afara ei "
                "(Zhang et al., 2005). ETCCDI corectează prin re-eșantionare; aici nu. Comparați cu prudență anii din bază "
                "cu cei de după ea.")

TEORIE.update({
    "pct_zile": dict(
        rezumat="Procentul zilelor mai calde (sau mai reci) decât percentila 90 (10) a aceleiași zile calendaristice "
                "din perioada de bază: TX90p, TN90p, TX10p, TN10p.",
        definitie="Pragul nu e o valoare fixă (30 °C), ci depinde de loc și de zi: percentila 90 a Tmax pentru 24 iulie, "
                  "în pixelul respectiv, estimată din anii de bază. O zi e „caldă” dacă Tmax depășește pragul zilei ei "
                  "calendaristice. Indicele este procentul acestor zile. Pentru că pragul e relativ la clima locului, "
                  "valorile se pot compara între munte și câmpie, iar în anii de bază sunt, prin construcție, în jur de 10 %.",
        formula="TX90p = 100 · #{z : Tmax<sub>z</sub> &gt; P90<sub>d(z)</sub>} / #{z cu date} &nbsp;·&nbsp; "
                "P90<sub>d</sub> = cuantila<sub>0,9</sub> { Tmax<sub>a, d+k</sub> : a ∈ bază, k = −2…2 }",
        simboluri=[["P90<sub>d</sub>", "pragul zilei calendaristice d (1…365), pe pixel"],
                   ["d(z)", "ziua calendaristică a zilei z; 29 februarie folosește pragul lui 28 februarie"],
                   ["TX10p, TN10p", "aceeași construcție cu percentila 10 și comparația „&lt;”"],
                   ["TN90p, TN10p", "pe Tmin: nopți calde / reci"]],
        pasi=[_PRAG_ZILNIC, _PRAG_FEREASTRA, _PRAG_CACHE,
              "Pentru fiecare an: ia pragul fiecărei zile după ziua ei calendaristică și numără zilele cu Tmax &gt; P90 "
              "(sau &lt; P10). Rezultatul = 100 × depășiri / zile cu date (o zi fără date sau fără prag nu intră)."],
        interpretare="În anii de bază, ~10 %. 20 % înseamnă de două ori mai multe zile calde decât în normală. Tendința "
                     "TX90p / TN90p este unul dintre cele mai clare semnale ale încălzirii în seriile ETCCDI; nopțile calde "
                     "(TN90p) contează pentru sănătate și pentru insula de căldură urbană.",
        standard="Indicii ETCCDI TX90p, TX10p, TN90p, TN10p (Zhang et al., 2011, WIREs Climate Change). " + _BAZA_STANDARD,
        limitari=[_BAZA_LIMITA,
                  "Pragurile pentru toată țara ocupă ~0,7 GB în cache (365 × 469 000 de valori) și se calculează în câteva "
                  "minute; pentru un județ, câțiva MB și câteva secunde.",
                  "Pe un sezon (de exemplu vara), procentul se raportează la zilele sezonului: TX90p de vară nu e o parte din TX90p anual.",
                  "Datele grilate netezesc extremele locale: pragul unui pixel e mai „blând” decât al unei stații."],
        intrebare="De ce TX90p e aproximativ 10 % în anii de bază? Ce ar însemna o tendință de +3 puncte procentuale pe deceniu?",
        calculator="pct_zile"),
    "wsdi": dict(
        rezumat="Câte zile fac parte din valuri de căldură: cel puțin 6 zile la rând cu Tmax peste percentila 90 a zilei.",
        definitie="Se marchează zilele cu Tmax peste pragul P90 al zilei calendaristice (ca la TX90p). Un șir de cel puțin "
                  "6 zile consecutive marcate e un val de căldură, iar toate zilele lui se numără. Zilele calde izolate "
                  "sau șirurile de 5 zile nu contează.",
        formula="WSDI = Σ<sub>șiruri cu L ≥ 6</sub> L",
        simboluri=[["L", "lungimea unui șir de zile consecutive cu Tmax &gt; P90<sub>d</sub>"],
                   ["6", "durata minimă ETCCDI (modificabilă în formular)"]],
        pasi=[_PRAG_ZILNIC + " Pragurile sunt aceleași ca la TX90p (același cache).", _PRAG_FEREASTRA,
              "Parcurge zilele perioadei și ține lungimea șirului curent; o zi neîndeplinită sau lipsă îl rupe.",
              "Când șirul ajunge la 6 zile adaugă 6, iar fiecare zi în plus adaugă 1. Șirurile nu trec peste capetele perioadei."],
        interpretare="Mulți ani au WSDI = 0; un singur val de 10 zile dă 10. Media pe ani amestecă ani fără valuri cu ani "
                     "extremi: priviți și seria anuală. Indicele e relativ la clima locului (un val de căldură la munte are "
                     "praguri mai joase decât la câmpie).",
        standard="ETCCDI WSDI (Warm Spell Duration Index). " + _BAZA_STANDARD,
        limitari=["Șirurile se taie la capetele perioadei: un val între 28 iunie și 5 iulie, analizat doar pe iulie, are 5 zile.",
                  "Mulți de zero: panta Theil–Sen e adesea exact 0; folosiți testul Mann–Kendall și seria anuală.",
                  _BAZA_LIMITA],
        intrebare="Două veri au același TX90p (15 %), dar WSDI 0 și, respectiv, 14. Cum arătau cele două veri?",
        calculator="wsdi"),
    "csdi": dict(
        rezumat="Câte zile fac parte din valuri de frig: cel puțin 6 zile la rând cu Tmin sub percentila 10 a zilei.",
        definitie="Simetric cu WSDI, pe Tmin și percentila 10: un șir de cel puțin 6 nopți consecutive mai reci decât "
                  "pragul P10 al zilei calendaristice; se numără toate zilele șirului.",
        formula="CSDI = Σ<sub>șiruri cu L ≥ 6</sub> L &nbsp;·&nbsp; zi marcată: Tmin<sub>z</sub> &lt; P10<sub>d(z)</sub>",
        simboluri=[["P10<sub>d</sub>", "percentila 10 a Tmin pentru ziua calendaristică d, din anii de bază"],
                   ["L", "lungimea unui șir de zile consecutive marcate"]],
        pasi=[_PRAG_ZILNIC, _PRAG_FEREASTRA,
              "Marchează zilele cu Tmin &lt; P10 și numără zilele din șirurile de cel puțin 6 zile (ca la WSDI)."],
        interpretare="Iernile recente au adesea CSDI = 0; o scădere a CSDI e de așteptat într-un climat care se încălzește. "
                     "Valurile de frig rămân importante pentru agricultură și energie.",
        standard="ETCCDI CSDI (Cold Spell Duration Index). " + _BAZA_STANDARD,
        limitari=["Pentru iarnă (DJF) perioada începe în decembrie anului precedent: alegeți sezonul și anii cu atenție.",
                  "Mulți de zero, ca la WSDI.", _BAZA_LIMITA],
        intrebare="De ce un CSDI mai mic nu înseamnă că nu mai există ierni geroase?",
        calculator="csdi"),
    "rnnp": dict(
        rezumat="Cantitatea de precipitații căzută în zilele foarte ploioase: peste percentila 95 (99) a zilelor ploioase din bază.",
        definitie="Pragul se calculează o singură dată, pe pixel: percentila 95 a tuturor zilelor cu P ≥ 1 mm din anii de "
                  "bază (zilele fără ploaie nu intră, altfel pragul ar fi aproape 0). Indicele adună precipitațiile zilelor "
                  "care depășesc acest prag.",
        formula="R95p = Σ<sub>z</sub> P<sub>z</sub> · [P<sub>z</sub> &gt; P95<sub>u</sub>] &nbsp;·&nbsp; "
                "P95<sub>u</sub> = cuantila<sub>0,95</sub> { P<sub>z</sub> ≥ 1 mm : z ∈ bază }",
        simboluri=[["P95<sub>u</sub>", "pragul zilelor foarte ploioase al pixelului (mm), din perioada de bază"],
                   ["[·]", "1 dacă condiția e adevărată, 0 altfel"]],
        pasi=["O singură dată: citește precipitațiile anilor de bază pe blocuri, păstrează doar zilele cu P ≥ 1 mm și calculează "
              "percentila (tip 8) pe pixel; sub 20 de zile ploioase → NoData. Pragul se salvează în cache.",
              "Pentru fiecare an: suma precipitațiilor din zilele cu P &gt; prag."],
        interpretare="Un R95p în creștere arată mai multă apă căzută în episoade intense. Pentru a deosebi „plouă mai mult” "
                     "de „plouă mai concentrat”, priviți R95pTOT (ponderea din total).",
        standard="ETCCDI R95p și R99p (Zhang et al., 2011). " + _BAZA_STANDARD,
        limitari=["Pragul e anual: în sezonul cald, ploile convective depășesc mai ușor un prag calculat pe tot anul.",
                  "Grila interpolată netezește extremele: valorile maxime locale sunt subestimate față de stații.",
                  _BAZA_LIMITA],
        intrebare="R95p crește, dar PRCPTOT rămâne constant. Ce s-a schimbat în felul în care plouă?",
        calculator="rnnp"),
    "rnnptot": dict(
        rezumat="Ce procent din precipitațiile zilelor ploioase a căzut în zilele foarte ploioase (peste p95 al bazei).",
        definitie="Raportul dintre R95p și PRCPTOT (suma zilelor cu P ≥ 1 mm). Arată cât de concentrată e ploaia: "
                  "la aceeași cantitate totală, o pondere mai mare înseamnă mai puține zile, dar mai intense.",
        formula="R95pTOT = 100 · R95p / PRCPTOT",
        simboluri=[["R95p", "precipitațiile zilelor cu P &gt; P95<sub>u</sub> (mm)"],
                   ["PRCPTOT", "suma precipitațiilor zilelor cu P ≥ 1 mm (mm)"]],
        pasi=["Pragul P95<sub>u</sub> al pixelului, ca la R95p (același cache).",
              "Pentru fiecare an: R95p și PRCPTOT pe aceleași zile, apoi raportul × 100. Fără nicio zi ≥ 1 mm → NoData (0/0)."],
        interpretare="Valori tipice: 15–35 %. O creștere arată concentrarea precipitațiilor în episoade intense, cu risc "
                     "mai mare de viituri rapide și, între episoade, de secetă.",
        standard="ETCCDI R95pTOT / R99pTOT (în ClimPACT). " + _BAZA_STANDARD,
        limitari=["Pe perioade scurte sau uscate, numitorul mic face raportul instabil.",
                  "Media pe ani a rapoartelor nu e raportul sumelor: harta „medie anuală” dă greutate egală fiecărui an."],
        intrebare="De ce R95pTOT poate crește chiar și într-un climat în care precipitațiile anuale scad?",
        calculator="rnnptot"),
    "pet": dict(
        rezumat="Evapotranspirația potențială Hargreaves: cât ar evapora o suprafață cu apă din belșug, estimat din temperaturi.",
        definitie="Formula Hargreaves–Samani folosește amplitudinea termică diurnă ca înlocuitor al radiației solare care "
                  "ajunge la sol (zilele senine au amplitudine mare), radiația extraterestră Ra (depinde doar de latitudine "
                  "și de ziua din an) și temperatura medie. E recomandată de FAO-56 când lipsesc datele de radiație, umiditate și vânt.",
        formula="PET = 0,0023 · (T<sub>med</sub> + 17,8) · √(Tmax − Tmin) · 0,408 · Ra",
        simboluri=[["T<sub>med</sub>", "(Tmax + Tmin) / 2, °C"],
                   ["Ra", "radiația extraterestră, MJ m⁻² zi⁻¹ (FAO-56 ec. 21); × 0,408 o transformă în mm/zi"],
                   ["PET", "mm/zi; indicele = suma pe perioadă"]],
        pasi=["Pentru fiecare zi și pixel: Ra din latitudinea rândului și ziua din an (declinația solară, unghiul orar la apus).",
              "PET zilnică după formulă; amplitudinea negativă (date eronate) se ia 0, PET negativă se ia 0.",
              "Suma pe perioadă; zilele fără Tmax sau Tmin nu contribuie."],
        interpretare="În România, vara (iunie–august) are de obicei 350–500 mm PET la câmpie, mult peste precipitații: "
                     "diferența e deficitul climatic al apei.",
        standard="Hargreaves &amp; Samani (1985); Allen et al. (1998), FAO Irrigation and Drainage Paper 56, ec. 52.",
        limitari=["Nu folosește umiditatea și vântul: supraestimează în zonele umede și subestimează în cele cu vânt puternic.",
                  "Formula a fost calibrată pentru perioade de cel puțin 5 zile; valorile zilnice izolate sunt aproximative.",
                  "Prin construcție crește odată cu temperatura: o parte din tendința PET reflectă direct încălzirea."],
        intrebare="De ce amplitudinea termică diurnă poate înlocui radiația solară în formulă?",
        calculator="pet"),
    "bilant": dict(
        rezumat="Bilanțul climatic al apei: precipitațiile minus evapotranspirația potențială (Hargreaves), pe perioadă.",
        definitie="Diferența zilnică P − PET, adunată pe perioadă. Negativ = atmosfera „cere” mai multă apă decât cade; "
                  "pozitiv = surplus. Este mărimea pe care se calculează SPEI.",
        formula="D = Σ<sub>z</sub> (P<sub>z</sub> − PET<sub>z</sub>)",
        simboluri=[["P<sub>z</sub>", "precipitațiile zilei (mm)"], ["PET<sub>z</sub>", "evapotranspirația potențială Hargreaves (mm)"]],
        pasi=["PET zilnică, ca la indicatorul PET.", "D zilnic = P − PET; o zi cu oricare variabilă lipsă nu contribuie.",
              "Suma pe perioadă."],
        interpretare="Vara, la câmpie, bilanțul e aproape mereu negativ (−200…−350 mm); contează abaterea față de normal, "
                     "pe care o măsoară SPEI.",
        standard="Bilanțul climatic al apei (Thornthwaite, 1948), cu PET după FAO-56; baza indicelui SPEI.",
        limitari=["Este un bilanț „climatic”: nu ține cont de sol, de rezerva de apă sau de vegetație reală.",
                  "Moștenește limitările formulei Hargreaves."],
        intrebare="Două veri au aceleași precipitații, dar una e cu 2 °C mai caldă. Cum diferă bilanțul?",
        calculator="bilant"),
    "spi": dict(
        rezumat="Indicele standardizat al precipitațiilor: cât de neobișnuit de secetoasă sau de ploioasă a fost perioada aleasă, "
                "în unități de abatere standard.",
        definitie="Se adună precipitațiile perioadei alese (sezonul dă „scara”: anual = SPI-12, iunie–august = SPI-3, o lună = SPI-1). "
                  "În fiecare pixel, totalurile aceleiași perioade din anii de bază se descriu printr-o distribuție gamma "
                  "(cu o probabilitate separată pentru totalul 0). Probabilitatea cumulată a valorii din anul analizat se "
                  "transformă în scorul normal standard echivalent: SPI = 0 e mediana, −1 e o valoare depășită în jos "
                  "în ~16 % din ani.",
        formula="H(x) = q + (1 − q) · G(x; α, β) &nbsp;·&nbsp; SPI = Φ⁻¹(H(x))",
        simboluri=[["x", "totalul precipitațiilor perioadei (mm)"],
                   ["q", "proporția anilor de bază cu total 0"],
                   ["G(x; α, β)", "funcția de repartiție gamma: P(α, x/β), gamma incompletă regularizată"],
                   ["α, β", "estimate prin verosimilitate maximă (aproximarea Thom): A = ln x̄ − mean(ln x), α = (1 + √(1 + 4A/3)) / 4A, β = x̄/α"],
                   ["Φ⁻¹", "inversa funcției de repartiție normale standard"]],
        pasi=["O singură dată pentru zonă și sezon: totalurile perioadei în fiecare an de bază (aceeași validitate ca la orice hartă).",
              "Pe pixel: q, apoi α și β din totalurile pozitive (cel puțin 10). Parametrii se salvează în <code>rezultate/_cache/spi/</code>.",
              "Pentru fiecare an analizat: totalul perioadei → H(x) → SPI. Probabilitățile se limitează la [10⁻⁶; 1 − 10⁻⁶], "
              "deci SPI rămâne în ±4,75.",
              "Totalul se corectează pentru zilele lipsă (× n / n<sub>valide</sub>), atât în anii de bază, cât și în anul analizat; "
              "o perioadă incompletă (ex. vara în curs) nu primește SPI, chiar dacă „Acceptă perioade incomplete” e bifat.",
              "Funcțiile gamma incompletă și Φ⁻¹ sunt scrise de mână (fără scipy) și verificate cu valori din tabele."],
        interpretare="Clasele OMM (McKee et al., 1993): ≥ 2 extrem de umed · 1,5…2 foarte umed · 1…1,5 moderat umed · −1…1 aproape "
                     "normal · −1,5…−1 secetă moderată · −2…−1,5 secetă severă · ≤ −2 secetă extremă. Pentru un an anume alegeți "
                     "anii X–X; harta „medie anuală” pe mai mulți ani este media SPI-urilor, nu SPI-ul mediei.",
        standard="McKee, Doesken &amp; Kleist (1993); WMO-No. 1090 (2012), Standardized Precipitation Index User Guide — "
                 "recomandă cel puțin 30 de ani de bază. " + _BAZA_STANDARD,
        limitari=["Scara e dată de sezonul ales (perioade calendaristice fixe), nu de o fereastră glisantă lună de lună.",
                  "Nu ține cont de temperatură: o vară caldă cu ploi normale are SPI ≈ 0, deși solul se usucă mai repede (vezi SPEI).",
                  "Pentru totalurile 0 se folosește H(0) = q; în climatele foarte uscate, Stagge et al. (2015) recomandă o corecție.",
                  "Cu o bază scurtă (sub 30 de ani), parametrii gamma sunt instabili, iar valorile extreme mai puțin sigure."],
        intrebare="SPI-3 de vară = −1,5 în 2024. Aproximativ o dată la câți ani apare o vară cel puțin atât de secetoasă în clima de bază?",
        calculator="spi"),
    "spei": dict(
        rezumat="Indicele standardizat precipitații–evapotranspirație: ca SPI, dar pe bilanțul P − PET, deci ține cont și de căldură.",
        definitie="Pentru perioada aleasă se calculează bilanțul D = Σ (P − PET Hargreaves). În fiecare pixel, valorile D din anii de "
                  "bază se descriu printr-o distribuție log-logistică cu trei parametri, iar probabilitatea valorii analizate se "
                  "transformă în scor normal standard. Aceeași ploaie într-o vară mai caldă dă un SPEI mai mic.",
        formula="F(D) = 1 / (1 + e<sup>−y</sup>), &nbsp;y = −ln(1 − κ(D − ξ)/α) / κ &nbsp;·&nbsp; SPEI = Φ⁻¹(F(D))",
        simboluri=[["D", "bilanțul P − PET al perioadei (mm)"],
                   ["ξ, α, κ", "poziția, scara și forma (logistica generalizată, forma Hosking a log-logisticii)"],
                   ["λ1, λ2, λ3", "L-momentele din momente ponderate nedeplasate; κ = −λ3/λ2, α = λ2·sin(κπ)/(κπ), ξ = λ1 − α(1/κ − π/sin(κπ))"]],
        pasi=["O singură dată pentru zonă și sezon: bilanțul P − PET al perioadei în fiecare an de bază.",
              "Pe pixel: L-momentele nedeplasate și parametrii ξ, α, κ (necesită |κ| &lt; 1 și cel puțin 10 ani). Cache în "
              "<code>rezultate/_cache/spei/</code>.",
              "Pentru fiecare an: D → F(D) → SPEI. În afara domeniului distribuției F = 0 sau 1, limitate ca la SPI (±4,75).",
              "Bilanțul se corectează pentru zilele lipsă ca totalul SPI; perioadele incomplete nu primesc SPEI."],
        interpretare="Aceleași clase ca SPI. Diferența SPEI − SPI arată rolul temperaturii: în verile foarte calde SPEI e mult "
                     "sub SPI. Pentru tendințe de secetă într-un climat care se încălzește, SPEI e de obicei mai relevant.",
        standard="Vicente-Serrano, Beguería &amp; López-Moreno (2010), J. Climate; ajustarea prin L-momente nedeplasate și logistica "
                 "generalizată urmează pachetul de referință SPEI (Beguería et al., 2014, Int. J. Climatol.). Formula din articolul "
                 "original, cu poziții de reprezentare, a dat în simulările noastre (log-logistică cunoscută, 30 de ani) o abatere "
                 "standard de ~1,5 în loc de 1; varianta folosită dă ~1,0 (test în instrumente/teste_cunoscute.py). " + _BAZA_STANDARD,
        limitari=["Moștenește simplificările PET Hargreaves (fără umiditate și vânt).",
                  "Trei parametri cer o bază lungă: cu 10 ani, o parte din pixeli nu se pot ajusta (|κ| ≥ 1) și rămân NoData.",
                  "Valorile din afara domeniului distribuției ajung la limita ±4,75: tratați-le ca „mai extrem decât orice an de bază”.",
                  "Scara = sezonul ales, ca la SPI."],
        intrebare="În vara 2024, SPI = −0,8 și SPEI = −1,9 în același pixel. Ce s-a întâmplat?",
        calculator="spei"),
})


METODE["validitate"] = dict(
    titlu="Date lipsă și validitate",
    rezumat="Ce face programul când lipsesc zile: pragul de 90 %, corecția sumelor, perioadele incomplete, golurile din cub "
            "(fragmente lipsă sau nescrise) și ce înseamnă toate acestea pentru o hartă.",
    definitie="O valoare anuală sau sezonieră se calculează pentru un pixel doar dacă perioada are date în cel puțin 90 % din "
              "zile (pragul se poate schimba în Setări avansate). Mediile folosesc zilele valide. Sumele (precipitații, PET, "
              "bilanț, grade-zile, PRCPTOT, SPI, SPEI) se corectează proporțional: totalul zilelor valide × n / n<sub>valide</sub>, "
              "ca și cum zilele lipsă ar fi avut media celorlalte. Numărătorile (zile tropicale, zile de îngheț…) nu se corectează: "
              "ele numără doar zilele cu date. O perioadă care iese din date (anul în curs) se exclude, dacă nu bifați „Acceptă "
              "perioade incomplete”; SPI și SPEI le exclud oricum.",
    formula="valid ⇔ n<sub>valide</sub> ≥ 0,9 · n &nbsp;·&nbsp; Σ<sub>corectat</sub> = Σ<sub>valide</sub> · n / n<sub>valide</sub>",
    simboluri=[["n", "numărul de zile ale perioadei (ex. 92 pentru vară)"],
               ["n<sub>valide</sub>", "zilele cu date pentru acel pixel"],
               ["gol în cub", "fragment (chunk) de 90 de zile × 161 × 324 pixeli care lipsește sau a fost creat fără date (valori exact 0)"]],
    pasi=["La citire: fragmentele lipsă din cub și blocurile nescrise (toți pixelii exact 0 la temperatură) devin date lipsă, "
          "nu 0 °C. La un punct sau o zonă mică, blocul se judecă întreg; la precipitații, unde 0 e o valoare reală, după Tmax.",
          "Pe pixel și perioadă: se numără zilele valide; sub prag → fără valoare (NoData) pentru acel an.",
          "Sumele se corectează proporțional; mediile și numărătorile nu au nevoie.",
          "Media pe ani (harta finală) folosește anii cu valoare; o zonă primește valoare dacă cel puțin jumătate din pixelii ei au.",
          "Jurnalul și fișa rulării spun ce goluri s-au întâlnit („Date cu goluri”); butonul „Verifică datele” arată unde sunt."],
    interpretare="Pragul de 90 % e cel din recomandările ETCCDI și OMM pentru indicatorii anuali. Corecția sumelor evită o "
                 "eroare sistematică: fără ea, o vară cu 8 zile lipsă ar avea cu ~9 % mai puține precipitații și ar apărea mai "
                 "uscată decât a fost. Pentru o hartă de medii pe 30 de ani, câteva zile lipsă nu contează; pentru un singur "
                 "an sau un record, contează.",
    standard="Zhang et al. (2011), WIREs Climate Change (regulile de completitudine ETCCDI); WMO-No. 1203 (2017), regulile "
             "pentru normale climatice.",
    limitari=["Corecția presupune că zilele lipsă seamănă cu celelalte; într-o lună cu o singură ploaie torențială lipsă, "
              "totalul rămâne subestimat.",
              "Numărătorile pe perioade cu zile lipsă sunt ușor subestimate (până la 10 %).",
              "Fișa „Verifică datele” arată doar golurile; cauza lor (stații, procesare) e la producătorul datelor."],
    intrebare="O vară are 92 de zile, iar un pixel are 85 cu date, care însumează 170 mm. Ce total folosește programul? "
              "(170 × 92 / 85 ≈ 184 mm.) Dar dacă ar avea doar 80 de zile cu date?",
    functii=["zarr_clima._suma_corectata", "zarr_clima.zile_bloc_zero", "zarr_clima._corecteaza_bucata"])

METODE["fdr"] = dict(
    titlu="Testele multiple: corecția FDR",
    rezumat="De ce o hartă de trend cu „5 % pixeli semnificativi” poate să nu arate nimic real și cum o corectează "
            "procedura Benjamini–Hochberg (opțiunea avansată a hărților de tendință).",
    definitie="Pe o hartă de trend se face câte un test pe pixel: zeci de mii de teste deodată. La α = 0,05, chiar fără nicio "
              "tendință reală, ~5 % din pixeli ies „semnificativi” din întâmplare. Corecția FDR (false discovery rate) ține "
              "sub α proporția descoperirilor false printre pixelii declarați semnificativi: p-valorile se ordonează "
              "crescător, iar p-valoarea de rang k se compară cu k·α/m în loc de α.",
    formula="q<sub>(k)</sub> = min<sub>j ≥ k</sub> ( p<sub>(j)</sub> · m / j ) &nbsp;·&nbsp; semnificativ ⇔ q &lt; α",
    simboluri=[["m", "numărul de pixeli cu p-valoare din zonă"], ["p<sub>(k)</sub>", "a k-a p-valoare, în ordine crescătoare"],
               ["q", "p-valoarea ajustată FDR (banda „p ajustat FDR” din GeoTIFF)"]],
    pasi=["Testul obișnuit pe fiecare pixel (OLS + t sau Mann–Kendall), ca până acum.",
          "Toate p-valorile valide din zonă se ordonează; fiecare se înmulțește cu m / rang.",
          "Monotonie: de la cel mai mare rang spre cel mai mic, q = minimul valorilor de deasupra (și cel mult 1).",
          "Hașura se face după q ≥ α; GeoTIFF-ul primește o bandă în plus cu q; jurnalul spune câți pixeli rămân semnificativi."],
    interpretare="Dacă după corecție rămân mulți pixeli semnificativi, tendința e solidă la nivelul hărții. Dacă dispar aproape "
                 "toți, pixelii „semnificativi” de dinainte nu se pot distinge de hazard. Pentru temperaturi pe 1961–2025, "
                 "tendințele sunt atât de clare încât corecția schimbă puțin; la precipitații, schimbă mult.",
    standard="Benjamini &amp; Hochberg (1995), J. R. Stat. Soc. B; recomandat pentru hărți climatice de Wilks (2016), BAMS.",
    limitari=["Procedura presupune teste independente sau pozitiv dependente; pixelii vecini sunt puternic corelați, caz în "
              "care BH rămâne de obicei prudentă (Wilks, 2016).",
              "Rezultatul depinde de zonă: aceeași tendință poate fi semnificativă pe un județ și nesemnificativă pe toată țara, "
              "pentru că m diferă.",
              "Corecția nu tratează autocorelația în timp a seriei unui pixel (alt subiect: pre-whitening)."],
    intrebare="O hartă are 20 000 de pixeli și 1 200 dintre ei au p < 0,05. Câți v-ați aștepta să apară din întâmplare dacă "
              "n-ar exista nicio tendință? Ce vă spune asta despre hartă înainte de orice corecție?",
    functii=["zarr_clima.fdr_bh"])

METODE["climatograma"] = dict(
    titlu="Climatograma Walter–Lieth",
    rezumat="Diagrama climatică clasică: temperatura și precipitațiile lunare pe aceeași figură, la o scară care arată direct "
            "lunile aride, plus înghețul și extremele.",
    definitie="Pentru fiecare lună: temperatura medie, (Tmax + Tmin)/2, și precipitațiile medii lunare, ca medii pe anii perioadei, "
              "din seria zilnică medie a zonei (pentru un punct, a pixelului). Axele sunt legate: 10 °C ↔ 20 mm. Unde curba "
              "precipitațiilor coboară sub cea a temperaturii (P &lt; 2T), luna e considerată aridă (punctat); deasupra, umedă "
              "(hașură verticală). Peste 100 mm, scara precipitațiilor se comprimă de 10 ori (fond albastru plin).",
    formula="aridă ⇔ P &lt; 2·T &nbsp;·&nbsp; y(P) = P/2 pentru P ≤ 100 mm, 50 + (P − 100)/20 peste",
    simboluri=[["T", "temperatura medie lunară (°C)"], ["P", "precipitațiile medii lunare (mm)"],
               ["îngheț sigur", "media minimelor lunii &lt; 0 °C (bară plină)"],
               ["îngheț probabil", "minima absolută a lunii &lt; 0 °C (bară hașurată)"]],
    pasi=["Seriile zilnice ale zonei (Tmax, Tmin, P) pentru toți anii, din cache-ul seriilor.",
          "Pentru fiecare an și lună: media temperaturilor și suma precipitațiilor (corectată pentru zilele lipsă).",
          "Pentru fiecare lună: media pe anii perioadei; luna intră doar dacă are date în cel puțin 80 % din ani.",
          "Extremele absolute: cea mai mare Tmax și cea mai mică Tmin zilnică a fiecărei luni din perioadă.",
          "Cu două perioade: aceleași axe pentru amândouă și un grafic cu diferențele lunare (°C și %)."],
    interpretare="Forma curbelor arată regimul: maximul de precipitații la începutul verii (mai–iunie) e tipic pentru climatul "
                 "temperat-continental al României. Un „ochi” arid vara apare în Dobrogea și în sudul Câmpiei Române; la munte, "
                 "bara de îngheț acoperă aproape tot anul. Comparația 1961–1990 / 1991–2020 arată direct ce s-a schimbat în "
                 "fiecare lună.",
    standard="Walter &amp; Lieth (1960–1967), Klimadiagramm-Weltatlas; normalele climatice: WMO-No. 1203 (2017).",
    limitari=["Pragul P = 2T e o convenție grafică (Gaussen), nu un bilanț hidric: nu ține seama de evapotranspirația reală.",
              "Valorile sunt ale seriei medii a zonei: pe o zonă întinsă, contrastele de relief se netezesc.",
              "Datele grilate netezesc extremele absolute față de stații."],
    intrebare="De ce o lună cu 60 mm poate fi aridă în iulie, dar umedă în aprilie? Ce s-ar întâmpla cu lunile aride dacă "
              "precipitațiile ar rămâne aceleași, iar temperatura ar crește cu 2 °C?",
    functii=["zarr_climatograma.statistici_perioada", "zarr_climatograma.png_climatograma"])

METODE["superlative"] = dict(
    titlu="Superlative și recorduri",
    rezumat="Cum se caută „cel mai ploios mai” sau „cea mai caldă zi”: candidații fiecărui an, regula de validitate, "
            "clasamentul și ce înseamnă un record pe zonă față de un record pe pixel.",
    definitie="Pentru fiecare an se formează candidații unității alese: fiecare zi, fiecare șir de N zile consecutive, "
              "luna aleasă, fiecare dintre cele 12 luni, sezonul, anul sau un interval fix. Precipitațiile se adună pe "
              "candidat, temperaturile se mediază. Toți candidații valizi din toți anii se ordonează: primul este recordul. "
              "În modul „clasament” seria folosită e media zilnică a zonei; în modul „hartă” fiecare pixel are propriul "
              "clasament, iar hărțile arată valoarea recordului, anul și data lui, marja față de al doilea și locul unui an ales.",
    formula="candidat = Σ P<sub>z</sub> (precipitații) sau (1/n) Σ T<sub>z</sub> (temperaturi), z ∈ zilele candidatului "
            "&nbsp;·&nbsp; loc(v) = 1 + #{candidați mai extremi decât v}",
    simboluri=[["candidat", "o zi, o fereastră de N zile, o lună, un sezon, un an sau un interval fix al unui an"],
               ["valid", "cu date în cel puțin 90 % din zilele lui și în întregime în datele cubului"],
               ["anul candidatului", "anul începutului; la sezoane și intervale peste Anul Nou, anul sfârșitului (iarna 2026 = dec. 2025 – feb. 2026)"]],
    pasi=["Pentru fiecare an, intervalele candidaților unității alese (ferestrele: toate cele care încep în acel an).",
          "Valorile candidaților din sume cumulate pe serie: o singură trecere prin date, oricât de multe ferestre.",
          "Candidații cu sub 90 % zile valide sau care ies din date se exclud (excepție: zilele și ferestrele anului "
          "curent, până la ultima zi cu date, ca un record recent să poată apărea).",
          "Clasament: ordonare; la ferestre, un episod apare o singură dată (24–26 și 25–27 iulie se suprapun: rămâne cel mai extrem).",
          "Hartă: pentru fiecare pixel și an, cel mai extrem candidat al anului; apoi, peste ani, recordul, anul lui, "
          "al doilea (marja) și locul anului ales. Calculul se face an cu an, pe benzi de rânduri, deci memoria rămâne mică."],
    interpretare="Într-un climat fără schimbare (ani independenți, aceeași distribuție), fiecare an are aceeași șansă să fie "
                 "record: ultimul dintr-o serie de n ani e record cu probabilitatea 1/n (1/65 ≈ 1,5 % pentru 1961–2025). "
                 "Când harta anului recordului arată 2024 în jumătate din pixeli, abaterea de la acest 1,5 % e mesajul. "
                 "Un record pe zonă (media zonei) e de obicei mai mic decât recordul celui mai extrem pixel din zonă.",
    standard="Analiza recordurilor climatice: Benestad (2003, Climate Research), Coumou &amp; Rahmstorf (2012); valabilitatea "
             "datelor ca la indicatorii ETCCDI (90 % zile valide).",
    limitari=["Datele grilate netezesc extremele: recordurile pixelilor sunt mai mici decât cele măsurate la stații, iar datele "
              "lor pot diferi.",
              "Recordurile vechi depind de densitatea rețelei de stații din acei ani (grila e interpolată din stații).",
              "Valorile egale împart locul; data afișată e a primului candidat cu acea valoare.",
              "Clasamentul pe zonă folosește media zilnică a zonei: „cea mai caldă zi a județului” nu e ziua cu cel mai "
              "fierbinte loc din județ."],
    intrebare="Dacă temperaturile n-ar avea nicio tendință, în câți dintre cei 65 de ani v-ați aștepta să apară un nou record "
              "de vară, într-un pixel? (Indiciu: 1 + 1/2 + 1/3 + … + 1/65 ≈ 4,8.) Cum citiți atunci harta anului recordului?",
    functii=["zarr_superlative.intervale_an", "zarr_superlative.candidati", "zarr_superlative.clasament_zona"])
