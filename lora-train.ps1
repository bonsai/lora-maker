# lora-train.ps1 — Yamazaki-Shishi SDXL LoRA Training (Kaggle)
#
# Convenience launcher for the private SDXL LoRA training pipeline.
# Prerequisites: Python ≥3.10, kaggle CLI authenticated (kaggle auth login),
#                 internet access (Kaggle kernel downloads sd-scripts + SDXL base).
#
# Usage:
#   .\lora-train.ps1          # dry-run (doctor + build only, no network)
#   .\lora-train.ps1 --run    # full pipeline (doctor → build → train → wait → fetch)
#   .\lora-train.ps1 --doctor --offline  # offline diagnosis only
#   .\lora-train.ps1 --doctor            # online diagnosis (auth, quota, remote dataset)

param(
    [switch]$Run,
    [switch]$Doctor,
    [switch]$Build,
    [switch]$Offline,
    [string]$Owner = "tyokouchi",
    [int]$Epochs,
    [int]$Dim,
    [switch]$PushDataset
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "python"
$cmd = @($python, (Join-Path $scriptDir "tools\kaggle_pipeline.py"))

function Write-Step { param($msg) Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ------------------------------------------------------------------ helpers

function Test-Dependencies {
    Write-Step "Checking dependencies"

    # Python version
    $pyVer = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
    if (-not $?) { Write-Error "Python not found"; exit 1 }
    $parts = $pyVer.Split(".")
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
        Write-Error "Python >=3.10 required, found $pyVer"; exit 1
    }
    Write-Host "  Python $pyVer OK" -ForegroundColor Green

    # kaggle CLI
    $kaggleVer = & $python -m kaggle --version 2>&1 | Select-String "Kaggle CLI"
    if (-not $?) {
        Write-Warning "kaggle CLI not available; --doctor and --run will need it"
    } else {
        Write-Host "  kaggle CLI $kaggleVer OK" -ForegroundColor Green
    }

    # Dataset ZIP
    $zip = Join-Path $scriptDir "dist\yamazaki-shishi-sdxl-dataset.zip"
    if (Test-Path $zip) {
        $size = (Get-Item $zip).Length / 1MB
        Write-Host "  Dataset ZIP $([math]::Round($size,1)) MB OK" -ForegroundColor Green
    } else {
        Write-Error "Dataset ZIP missing: $zip"
        exit 1
    }

    # Approval
    $approval = Join-Path $scriptDir "data\approvals\dataset-approval.json"
    if (Test-Path $approval) {
        Write-Host "  Approval record OK" -ForegroundColor Green
    } else {
        Write-Error "Approval record missing: $approval"
        exit 1
    }

    Write-Host ""
}

# ------------------------------------------------------------------ main

if ($Run) {
    Test-Dependencies

    $args = @("run", "--execute", "--owner", $Owner)
    if ($PushDataset) { $args += "--push-dataset" }
    if ($Epochs)      { $args += "--epochs"; $args += $Epochs }
    if ($Dim)         { $args += "--dim"; $args += $Dim }

    Write-Step "Full pipeline: doctor → build → train → wait → fetch"
    Write-Host "  Owner: $Owner"
    if ($Epochs)  { Write-Host "  Epochs: $Epochs (override)" }
    if ($Dim)     { Write-Host "  Dim: $Dim (override)" }
    Write-Host "  This will consume ~1.5-2.5h of Kaggle GPU quota." -ForegroundColor Yellow
    Write-Host "  The terminal must stay open during training." -ForegroundColor Yellow

    # Safety: require confirmation on --Run without $env:FORCE_LORA_RUN
    if (-not $env:FORCE_LORA_RUN) {
        $confirm = Read-Host "Type YES to proceed"
        if ($confirm -ne "YES") {
            Write-Host "Cancelled." -ForegroundColor Red
            exit 0
        }
    }

    Write-Host "`nExecuting: $cmd $($args -join ' ')" -ForegroundColor Gray
    & $python @cmd @args
    exit $LASTEXITCODE
}

if ($Build) {
    $args = @("build", "--owner", $Owner)
    if ($Epochs)      { $args += "--epochs"; $args += $Epochs }
    if ($Dim)         { $args += "--dim"; $args += $Dim }
    Write-Host "Building kernel bundle..."
    & $python @cmd @args
    exit $LASTEXITCODE
}

if ($Doctor) {
    $args = @("doctor")
    if ($Offline) { $args += "--offline" }
    & $python @cmd @args
    exit $LASTEXITCODE
}

# Default: dry-run doctor
Write-Step "Quick check (dry-run)"
& $python @cmd "doctor" "--offline"
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nTo start training, run:" -ForegroundColor Green
    Write-Host "  .\lora-train.ps1 --run" -ForegroundColor White
}
exit $LASTEXITCODE