@echo off
setlocal

echo Building FlutterDevLauncher Windows executable...
pyinstaller --clean --noconfirm FlutterDevLauncher.spec
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

echo.
echo Build complete.
echo Executable: dist\FlutterDevLauncher.exe
endlocal
