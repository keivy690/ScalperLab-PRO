@echo off
setlocal
chcp 65001 >nul

rem A validação/correção do Windows Time pode exigir privilégios administrativos.
rem Reabre este inicializador pelo UAC uma única vez antes de iniciar o aplicativo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$identity = [Security.Principal.WindowsIdentity]::GetCurrent(); $principal = New-Object -TypeName Security.Principal.WindowsPrincipal -ArgumentList $identity; if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { try { $cmdArgs = '/c ' + [char]34 + [char]34 + '%~f0' + [char]34 + [char]34; Start-Process -FilePath $env:ComSpec -ArgumentList $cmdArgs -Verb RunAs -ErrorAction Stop; exit 100 } catch { exit 1 } }"
set "ELEVATION_RESULT=%ERRORLEVEL%"
if "%ELEVATION_RESULT%"=="100" exit /b 0
if not "%ELEVATION_RESULT%"=="0" goto elevation_failed

cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    where py >nul 2>&1
    if errorlevel 1 goto no_python_launcher

    py -3.12 --version >nul 2>&1
    if errorlevel 1 goto no_python312

    echo Preparando o ambiente Python do ScalperLab...
    py -3.12 -m venv "%~dp0.venv"
    if errorlevel 1 goto setup_failed
)

"%PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto wrong_python

echo Conferindo as dependencias fixadas do ScalperLab...
"%PYTHON%" -m pip install --disable-pip-version-check -r "%~dp0requirements.lock"
if errorlevel 1 goto install_failed

tasklist /FI "IMAGENAME eq terminal64.exe" /FO CSV /NH 2>nul | find /I "terminal64.exe" >nul
if errorlevel 1 echo Aviso: o MetaTrader 5 nao foi detectado. O painel abrira, mas mostrara o estado desconectado.

echo Iniciando ScalperLab 1.0...
"%PYTHON%" "%~dp0run.py"
if errorlevel 1 goto app_failed
exit /b 0

:no_python_launcher
echo ERRO: Python Launcher nao encontrado. Instale Python 3.12 e tente novamente.
goto failed

:no_python312
echo ERRO: Python 3.12 nao encontrado. Instale Python 3.12 e tente novamente.
goto failed

:wrong_python
echo ERRO: O ambiente .venv nao usa Python 3.12. Corrija o ambiente antes de iniciar.
goto failed

:setup_failed
echo ERRO: Nao foi possivel preparar o ambiente Python.
goto failed

:install_failed
echo ERRO: Nao foi possivel instalar as dependencias. Verifique a conexao com a internet.
goto failed

:app_failed
echo ERRO: O ScalperLab encerrou com falha. Consulte a mensagem acima.
goto failed

:elevation_failed
echo ERRO: O ScalperLab precisa de permissao administrativa para validar o horario do Windows.
echo Aceite a solicitacao do UAC e execute novamente.
goto failed

:failed
pause
exit /b 1
