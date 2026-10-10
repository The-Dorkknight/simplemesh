@echo off
rem Double-click me. Opens the SimpleMesh installer window.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 install.py %* & goto :eof)
where python >nul 2>nul && (python install.py %* & goto :eof)
echo Python 3 was not found. Install it from https://www.python.org/downloads/ and try again.
pause
