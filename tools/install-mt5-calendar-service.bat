@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-mt5-calendar-service.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
    echo Concluido. Inicie o servico no Navegador do MT5.
) else (
    echo Falha ao instalar o servico. Revise a mensagem acima.
)
pause
exit /b %RESULT%
