@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   AfroCreator Planner
echo   1) Instalar (ou atualizar)
echo   2) Refazer as perguntas de personalizacao
echo   3) Desinstalar (seus dados ficam guardados)
echo.
set /p OPC="  Escolha [1]: "
if "%OPC%"=="2" (powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" -Reconfigurar & goto :fim)
if "%OPC%"=="3" (powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" -Desinstalar & pause & goto :fim)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
:fim
