@echo off
REM Build TapeCalc as a standalone Windows .exe
REM Requires Python 3.10+ and pip

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Building standalone executable...
pyinstaller --clean tapecalc.spec

echo.
echo Done! Executable is at: dist\TapeCalc.exe
pause
