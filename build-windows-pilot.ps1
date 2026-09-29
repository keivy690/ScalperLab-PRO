param(
    [switch]$SkipArchive
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$distRoot = Join-Path $projectRoot "dist"
$bundleRoot = Join-Path $distRoot "ScalperLab"
foreach ($serviceSource in @("ScalperLabClockService", "ScalperLabCalendarService")) {
    $sourceText = Get-Content -LiteralPath (Join-Path $projectRoot "MT5\$serviceSource.mq5") -Raw
    if ($sourceText -notmatch '(?m)^\s*#property\s+service\s*$') {
        throw "$serviceSource deve declarar #property service; script de grafico nao e aceito."
    }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python 3.12 do ambiente do projeto não foi encontrado: $python"
}

$pythonVersion = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $pythonVersion.Trim() -ne "3.12") {
    throw "O build exige o Python 3.12 do ambiente do projeto; encontrado: $pythonVersion"
}

& $python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller não está instalado. Instale as dependências de desenvolvimento antes do build."
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean --distpath $distRoot `
        --workpath (Join-Path $projectRoot "build\pyinstaller") `
        (Join-Path $projectRoot "ScalperLab.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller encerrou com código $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$appExecutable = Join-Path $bundleRoot "ScalperLab.exe"
$validatorExecutable = Join-Path $bundleRoot "ScalperLabStrategyValidator.exe"
foreach ($requiredFile in @($appExecutable, $validatorExecutable,
        (Join-Path $bundleRoot "_internal\templates\index.html"),
        (Join-Path $bundleRoot "_internal\static\app.js"),
        (Join-Path $bundleRoot "_internal\MT5\ScalperLabCalendarService.mq5"),
        (Join-Path $bundleRoot "_internal\MT5\ScalperLabCalendarService.ex5"),
        (Join-Path $bundleRoot "_internal\MT5\ScalperLabClockService.mq5"),
        (Join-Path $bundleRoot "_internal\MT5\ScalperLabClockService.ex5"))) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Arquivo esperado não foi incluído no pacote: $requiredFile"
    }
}

Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination (Join-Path $bundleRoot "LICENSE.txt") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "docs\BUILD_WINDOWS_PILOT.md") `
    -Destination (Join-Path $bundleRoot "LEIA-ME-PRIMEIRO.txt") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "tools\install-mt5-calendar-service.ps1") `
    -Destination (Join-Path $bundleRoot "Instalar-Servico-Calendario-MT5.ps1") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "tools\install-mt5-calendar-service.bat") `
    -Destination (Join-Path $bundleRoot "Instalar-Servico-Calendario-MT5.bat") -Force

$manifest = [ordered]@{
    product = "ScalperLab PRO"
    package_type = "onedir-pilot"
    built_at_utc = [DateTime]::UtcNow.ToString("o")
    python = $pythonVersion.Trim()
    pyinstaller = (& $python -m PyInstaller --version).Trim()
    git_commit = (& git -C $projectRoot rev-parse HEAD).Trim()
    working_tree_has_uncommitted_changes = [bool](& git -C $projectRoot status --porcelain)
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $bundleRoot "BUILD-MANIFEST.json") -Encoding utf8

if (-not $SkipArchive) {
    $archive = Join-Path $distRoot "ScalperLab-Pilot-onedir.zip"
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
    Compress-Archive -Path $bundleRoot -DestinationPath $archive -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    Set-Content -LiteralPath "$archive.sha256" -Value "$hash  ScalperLab-Pilot-onedir.zip" -Encoding ascii
}

Write-Output "Pacote piloto gerado em: $bundleRoot"
Write-Output "Executável: $appExecutable"
if (-not $SkipArchive) {
    Write-Output "Arquivo ZIP: $(Join-Path $distRoot 'ScalperLab-Pilot-onedir.zip')"
}
