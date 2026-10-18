@echo off
setlocal
cd /d "%~dp0"
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm --clean --onefile --windowed --name "Detective Portal" --add-data "icons;icons" --add-data "education_data;education_data" main.py
if exist "dist\Detective Portal.exe" (
  echo.
  echo BUILD COMPLETE: dist\Detective Portal.exe
) else (
  echo.
  echo BUILD FAILED
)
pause
