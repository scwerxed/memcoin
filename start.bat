@echo off
REM Doppelklicken startet memecoin-radar. Kein Terminal noetig.
cd /d "%~dp0"
title memecoin-radar

where python >nul 2>nul
if %errorlevel%==0 (
    python run.py %*
    goto ende
)
where py >nul 2>nul
if %errorlevel%==0 (
    py run.py %*
    goto ende
)

echo.
echo   Python wurde nicht gefunden.
echo.
echo   Bitte von https://www.python.org/downloads/ installieren.
echo   WICHTIG: bei der Installation "Add Python to PATH" ankreuzen.
echo.
echo   Danach diese Datei erneut doppelklicken.
echo.

:ende
echo.
pause
