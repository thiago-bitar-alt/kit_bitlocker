@echo off
chcp 65001 >nul
rem Instala o kit (uma vez por maquina). Precisa do Python 3.12 ou 3.13 (64 bits) instalado.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version || (echo [ERRO] Python nao encontrado. Instale o Python 3.12 ou 3.13 - ver tutorial, PASSO 1. & pause & exit /b 1)
if not exist .venv %PY% -m venv .venv || (echo [ERRO] falha ao criar o ambiente & pause & exit /b 1)
rem Instala dos pacotes da pasta "pacotes" (sem internet); se faltar algum, tenta pela internet.
.venv\Scripts\python.exe -m pip install --no-index --find-links pacotes -r requirements.txt || .venv\Scripts\python.exe -m pip install -r requirements.txt || (echo [ERRO] falha na instalacao & pause & exit /b 1)
echo.
echo [OK] Kit instalado. Proximo passo: checar.bat "caminho da imagem"
pause
