@echo off
rem ---------------------------------------------------------------------------
rem  Builds two Windows programs into .\dist :
rem    VideoVaultPlayer.exe   - the player stub (each protected .exe is a copy of this + your video)
rem    VideoVaultCreator.exe  - the creator GUI (has the player stub bundled inside)
rem  Requires Python 3.10+ for Windows (the "py" launcher). Internet needed once for pip.
rem  To use your own icon, replace assets\icon.ico BEFORE running this script.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" not found. Install Python from python.org first.
  exit /b 1
)

if not exist .venv (
  py -3 -m venv .venv || exit /b 1
)
call .venv\Scripts\activate.bat || exit /b 1

python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt || exit /b 1

if not exist assets\icon.ico (
  python make_icon.py || exit /b 1
)

echo.
echo === Building player ===
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name VideoVaultPlayer --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  player_app.py || exit /b 1

echo.
echo === Building creator (bundles the player) ===
pyinstaller --noconfirm --onefile --windowed ^
  --name VideoVaultCreator --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  --add-data "dist\VideoVaultPlayer.exe;." ^
  creator_app.py || exit /b 1

echo.
echo Done. Run dist\VideoVaultCreator.exe
endlocal
