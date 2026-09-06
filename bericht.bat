@echo off
REM Erstellt einen Lagebericht und schickt ihn per Telegram.
REM Fuer die Windows-Aufgabenplanung gedacht - siehe README.
cd /d "%~dp0"

where python >nul 2>nul && (
    python run.py report --telegram --datei berichte.txt
    exit /b
)
where py >nul 2>nul && (
    py run.py report --telegram --datei berichte.txt
    exit /b
)
echo Python nicht gefunden. >> berichte-fehler.log
