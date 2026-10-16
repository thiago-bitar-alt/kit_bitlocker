@echo off
chcp 65001 >nul
rem Uso: decifrar.bat "imagem.001" "pasta de saida" [SHA-256 do relatorio da extracao] [chave de recuperacao]
if "%~2"=="" (echo Uso: decifrar.bat "imagem" "pasta de saida" [SHA-256] [chave de recuperacao] & exit /b 1)
set ARGS="%~1" "%~2"
if not "%~3"=="" set ARGS=%ARGS% --sha256 %~3
if not "%~4"=="" set ARGS=%ARGS% --chave-recuperacao %~4
"%~dp0.venv\Scripts\python.exe" -E -s "%~dp0decifrar_imagem.py" %ARGS%
