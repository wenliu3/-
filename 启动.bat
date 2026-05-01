@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo  ========================================
echo  紊流番剧 - AGE动漫
echo  ========================================
echo.
python app.py
pause
