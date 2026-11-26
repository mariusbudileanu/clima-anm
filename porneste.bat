@echo off
rem Clima ANM - pornire (Windows). La prima rulare instaleaza mediul portabil.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instrumente\porneste.ps1" %*
