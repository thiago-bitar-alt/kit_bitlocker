@echo off
chcp 65001 >nul
rem Uso: checar.bat "D:\caso\DDCapture.001"
if "%~1"=="" (echo Uso: checar.bat "caminho da imagem .dd ou .001" & exit /b 1)
"%~dp0.venv\Scripts\python.exe" -E -s "%~dp0checa_bitlocker.py" "%~1"
