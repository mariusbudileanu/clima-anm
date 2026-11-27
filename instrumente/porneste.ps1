# porneste.ps1 — pornește Clima ANM. La prima rulare descarcă pixi și instalează mediul portabil.
# Totul rămâne în folderul programului (instrumente\, .pixi\): nu atinge QGIS, OSGeo4W sau profilul utilizatorului.
# Ștergerea folderului programului = dezinstalare completă.
param([switch]$Reinstaleaza)
$ErrorActionPreference = "Stop"
$PIXI_VERSIUNE = "0.84.2"
$PIXI_SHA256   = "8ba2fea6c5d81174472a0d49b369ceb2b97235febd69c433de201ca0c5d8f75b"

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "Clima ANM"
$Rad = Split-Path -Parent $PSScriptRoot
Set-Location $Rad

function Linie($t, $c = "Gray") { Write-Host $t -ForegroundColor $c }
function Opreste($t) {
    Linie ""
    Linie "[eroare] $t" Red
    Linie ""
    Read-Host "Apăsați Enter pentru a închide"
    exit 1
}

Linie "======================================================================" Cyan
Linie "  Clima ANM — analize climatice pe cubul Zarr anm-daily-grids" Cyan
Linie "  Folderul programului: $Rad" Cyan
Linie "======================================================================" Cyan

# 1. Calea folderului: mediile conda nu suportă bine căile foarte lungi sau cu diacritice
if ($Rad -match '[^\x00-\x7F]') {
    Linie "[atenție] Calea conține diacritice sau caractere speciale. Dacă instalarea eșuează," Yellow
    Linie "          mutați folderul într-o cale simplă, de exemplu C:\ClimaANM" Yellow
}
if ($Rad.Length -gt 100) {
    Linie "[atenție] Calea are $($Rad.Length) caractere. Windows limitează căile la 260 de caractere;" Yellow
    Linie "          dacă instalarea eșuează, mutați folderul mai aproape de rădăcină (C:\ClimaANM)." Yellow
}

# 2. pixi: un singur executabil, păstrat în instrumente\
$Instr = Join-Path $Rad "instrumente"
$Pixi  = Join-Path $Instr "pixi.exe"
$env:PIXI_HOME      = Join-Path $Instr "pixi_home"       # configurația pixi (nu în profilul utilizatorului)
$env:PIXI_CACHE_DIR = Join-Path $Rad ".pixi\cache"       # pachetele descărcate (legate, nu copiate, în mediu)

if (-not (Test-Path $Pixi)) {
    Linie ""
    Linie "Prima pornire: descarc pixi $PIXI_VERSIUNE (~88 MB, o singură dată)..." White
    $url = "https://github.com/prefix-dev/pixi/releases/download/v$PIXI_VERSIUNE/pixi-x86_64-pc-windows-msvc.exe"
    $tmp = "$Pixi.part"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = "SilentlyContinue"            # bara de progres încetinește mult descărcarea
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    } catch {
        Opreste "Nu am putut descărca pixi: $($_.Exception.Message)`n        Verificați conexiunea la internet (sau proxy-ul instituției) și porniți din nou."
    }
    $h = (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower()
    if ($h -ne $PIXI_SHA256) {
        Remove-Item $tmp -Force
        Opreste "Fișierul descărcat nu corespunde (SHA256 $h). Încercați din nou; dacă se repetă, anunțați lectorul."
    }
    Move-Item $tmp $Pixi -Force
    Linie "   pixi descărcat și verificat." Green
}

# 3. Mediul (Python + GDAL + xarray + zarr …), exact versiunile din pixi.lock
$Mediu = Join-Path $Rad ".pixi\envs\default"
if ($Reinstaleaza -and (Test-Path $Mediu)) {
    Linie "Șterg mediul existent pentru reinstalare..." Yellow
    Remove-Item $Mediu -Recurse -Force
}
if (-not (Test-Path (Join-Path $Mediu "python.exe"))) {
    # Spațiul pe disc: ~1 GB mediul + ~0,7 GB arhivele descărcate (șterse la final). Pe FAT32/exFAT (stick-uri USB)
    # nu există legături „hard”, deci fișierele se copiază și trebuie aproape dublu.
    try {
        $lit = (Split-Path -Qualifier $Rad).TrimEnd(":")
        $liberGB = [math]::Round((Get-PSDrive -Name $lit).Free / 1GB, 1)
        $fs = ""; try { $fs = (Get-Volume -DriveLetter $lit -ErrorAction Stop).FileSystem } catch {}
        $nevoie = if ($fs -match "FAT") { 3.5 } else { 2.0 }
        if ($fs -match "FAT") {
            Linie "Atenție: discul $($lit): este $fs (stick USB?). Instalarea ocupă mai mult (~3 GB) și merge mai încet;" Yellow
            Linie "         dacă se poate, copiați folderul pe discul local (de ex. C:\ClimaANM)." Yellow
        }
        if ($liberGB -lt $nevoie) {
            Opreste ("Spațiu insuficient pe discul $($lit): $liberGB GB liberi, sunt necesari ~$nevoie GB.`n" +
                     "        Eliberați spațiu sau mutați folderul programului pe alt disc, apoi reporniți.")
        }
    } catch { }    # cale de rețea (UNC) sau informație indisponibilă: continuăm fără verificare
    Linie ""
    Linie "Instalez mediul de lucru (~1 GB, 3–10 minute, o singură dată)." White
    Linie "Pachetele vin din conda-forge, în versiunile fixate în pixi.lock." Gray
    & $Pixi install --locked --manifest-path (Join-Path $Rad "pixi.toml")
    if ($LASTEXITCODE -ne 0) {
        Opreste ("Instalarea mediului a eșuat (cod $LASTEXITCODE).`n" +
                 "        Cauze frecvente: fără internet / proxy, antivirus care blochează fișiere, cale prea lungă.`n" +
                 "        Reîncercare de la zero:  porneste.bat -Reinstaleaza")
    }
    # arhivele .conda descărcate nu mai sunt necesare (mediul are deja fișierele): eliberăm ~0,7 GB
    # în Windows PowerShell 5.1, cu ErrorActionPreference = Stop, orice text pe stderr al unui program extern
    # devine eroare fatală; curățenia e opțională, deci erorile ei nu trebuie să oprească pornirea
    $vechi = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $Pixi clean cache --conda --yes 2>&1 | Out-Null } catch { } finally { $ErrorActionPreference = $vechi }
    Linie "   Mediul este instalat." Green
}

# 4. Interfața (pixi run activează mediul: GDAL_DATA, PROJ_DATA, izolarea de OSGeo4W)
Linie ""
Linie "Pornesc interfața; browserul se deschide singur. Oprire: închideți această fereastră (sau Ctrl+C)." White
Linie ""
$ErrorActionPreference = "Continue"           # mesajele serverului pe stderr nu sunt erori fatale
& $Pixi run --locked --manifest-path (Join-Path $Rad "pixi.toml") interfata
$cod = $LASTEXITCODE
# Ctrl+C (oprirea obișnuită) nu e o eroare: 0xC000013A pe Windows, 130 pe Unix
if ($cod -ne 0 -and $cod -ne -1073741510 -and $cod -ne 130 -and $cod -ne 3221225786) {
    Opreste ("Interfața s-a oprit cu o eroare (cod $cod). Mesajul e mai sus, în această fereastră.`n" +
             "        Dacă problema persistă: porneste.bat -Reinstaleaza")
}
exit $cod
