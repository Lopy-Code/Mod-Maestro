@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py -3 main.py %* & goto :end)
where python >nul 2>nul && (python main.py %* & goto :end)
echo Python 3.11+ est requis : https://www.python.org/downloads/
pause
:end
