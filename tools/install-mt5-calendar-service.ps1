param(
    [string]$TerminalDataPath
)

$ErrorActionPreference = "Stop"
$bundleMt5 = Join-Path $PSScriptRoot "_internal\MT5"
if (-not (Test-Path -LiteralPath $bundleMt5 -PathType Container)) {
    $bundleMt5 = Join-Path $PSScriptRoot "..\mt5"
}
$serviceName = "ScalperLabCalendarService"
$sourceFiles = @("$serviceName.mq5", "$serviceName.ex5", "ScalperLabClockService.mq5", "ScalperLabClockService.ex5")

foreach ($file in $sourceFiles) {
    $source = Join-Path $bundleMt5 $file
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Arquivo do serviço não encontrado no pacote: $source"
    }
}

if (-not $TerminalDataPath) {
    $standardRoot = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    $candidates = @()
    if (Test-Path -LiteralPath $standardRoot -PathType Container) {
        $candidates = @(Get-ChildItem -LiteralPath $standardRoot -Directory |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "MQL5") -PathType Container })
    }

    if ($candidates.Count -eq 1) {
        $candidate = $candidates[0].FullName
        Write-Host "Pasta de dados MT5 encontrada: $candidate"
        $confirmation = Read-Host "Digite S para instalar o serviço nesta pasta, ou Enter para informar outra"
        if ($confirmation -match "^[sS]$") {
            $TerminalDataPath = $candidate
        }
    }
    elseif ($candidates.Count -gt 1) {
        Write-Host "Foram encontradas várias pastas de dados MT5:"
        for ($index = 0; $index -lt $candidates.Count; $index++) {
            Write-Host ("{0}. {1}" -f ($index + 1), $candidates[$index].FullName)
        }
        $choice = Read-Host "Digite o número da instalação MT5 desejada, ou Enter para informar outra pasta"
        if ($choice -match "^\d+$" -and [int]$choice -ge 1 -and [int]$choice -le $candidates.Count) {
            $TerminalDataPath = $candidates[[int]$choice - 1].FullName
        }
    }

    if (-not $TerminalDataPath) {
        Write-Host "No MT5: Arquivo > Abrir pasta de dados. Informe a pasta aberta que contém MQL5."
        $TerminalDataPath = Read-Host "Pasta de dados MT5"
    }
}

$resolvedDataPath = (Resolve-Path -LiteralPath $TerminalDataPath -ErrorAction Stop).Path
$mql5Path = Join-Path $resolvedDataPath "MQL5"
if (-not (Test-Path -LiteralPath $mql5Path -PathType Container)) {
    throw "A pasta informada não contém MQL5. Use a pasta de dados aberta pelo próprio terminal MT5."
}

$servicesPath = Join-Path $mql5Path "Services"
if (-not (Test-Path -LiteralPath $servicesPath -PathType Container)) {
    New-Item -ItemType Directory -Path $servicesPath -Force | Out-Null
}

$backupStamp = Get-Date -Format "yyyyMMdd-HHmmss"
foreach ($file in $sourceFiles) {
    $source = Join-Path $bundleMt5 $file
    $destination = Join-Path $servicesPath $file
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash

    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $destinationHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
        if ($destinationHash -eq $sourceHash) {
            Write-Host "Já está atualizado: $destination"
            continue
        }

        $backup = "$destination.backup-$backupStamp"
        Copy-Item -LiteralPath $destination -Destination $backup
        Write-Host "Versão anterior preservada em: $backup"
    }

    Copy-Item -LiteralPath $source -Destination $destination -Force
    $installedHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
    if ($installedHash -ne $sourceHash) {
        throw "A verificação SHA-256 falhou após copiar: $destination"
    }
    Write-Host "Instalado e verificado: $destination"
}

Write-Host ""
Write-Host "Este serviço exporta apenas o calendário econômico para o arquivo comum do MT5."
Write-Host "Ele não envia ordens e não substitui o conector Python incluído em ScalperLab.exe."
Write-Host "No MT5, atualize Serviços no Navegador, localize $serviceName e inicie-o."
Write-Host "Inicie também ScalperLabClockService: relógio independente, atualizado a cada 10 segundos."
Write-Host "O relógio publica na pasta MQL5\Files deste terminal; o calendário permanece separado."
