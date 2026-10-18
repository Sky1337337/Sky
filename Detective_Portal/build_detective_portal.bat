@echo off
cd /d "%~dp0"
echo Building Helper NPU...

python -m PyInstaller ^
--clean ^
--onefile ^
--windowed ^
--name "Helper НПУ" ^
--icon=detective_portal_icon.ico ^
--collect-all selenium ^
--hidden-import=selenium.webdriver.chrome.webdriver ^
--hidden-import=selenium.webdriver.chrome.service ^
--hidden-import=selenium.webdriver.common.by ^
--hidden-import=selenium.webdriver.common.keys ^
--hidden-import=browser_service ^
--hidden-import=selenium_fill ^
--hidden-import=excel_data ^
--hidden-import=app_state ^
main.py

pause