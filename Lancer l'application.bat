@echo off
title YouTube vers MP3
echo.
echo  ================================
echo   Lancement YouTube vers MP3...
echo  ================================
echo.

cd /d "D:\Claude plateforme\Transfer youtube au mp3"
start "" "http://localhost:5001"
python app.py

pause
