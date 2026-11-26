@echo off
rem Clima ANM - pregateste DEM-ul coregistrat pe grila Zarr (o singura data; ~1,5 GB descarcati temporar)
chcp 65001 >nul
cd /d "%~dp0.."
if not exist "instrumente\pixi.exe" ( echo Porniti intai porneste.bat o data, ca sa se instaleze mediul. & pause & exit /b 1 )
set "PIXI_HOME=%CD%\instrumente\pixi_home"
set "PIXI_CACHE_DIR=%CD%\.pixi\cache"
set "PYTHONIOENCODING=utf-8"
instrumente\pixi.exe run --locked --manifest-path "%CD%\pixi.toml" python instrumente\pregateste_dem.py %*
echo.
echo Jurnalul complet este in dem_jurnal.txt (in folderul programului).
pause
