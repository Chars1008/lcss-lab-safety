<#
.SYNOPSIS
    Windows Bootstrapper for Laboratory Chemical Safety System (LCSS).
    Checks/installs uv + Python 3.12, creates isolated .venv, installs dependencies,
    and creates Desktop / Start Menu shortcuts launching without a console window.
#>
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\LCSS"
)

$ErrorActionPreference = "Stop"
Write-Host "=== 實驗室藥品安全管理系統 (LCSS) 環境安裝引導程式 ===" -ForegroundColor Cyan

$SourceRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# Step 1: Locate or install portable uv
$UvExe = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $UvExe) {
    $LocalUv = Join-Path $InstallDir "bin\uv.exe"
    if (-not (Test-Path $LocalUv)) {
        Write-Host "[1/4] 正在下載獨立版 uv 套件管理器..." -ForegroundColor Yellow
        $BinDir = Join-Path $InstallDir "bin"
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
        $env:UV_INSTALL_DIR = $BinDir
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
    $UvExe = $LocalUv
}
Write-Host "[1/4] uv 就緒: $UvExe" -ForegroundColor Green

# Step 2: Ensure Python 3.12 via uv
Write-Host "[2/4] 檢查 / 安裝 Python 3.12..." -ForegroundColor Yellow
& $UvExe python install 3.12

# Step 3: Create isolated .venv and install dependencies
$VenvDir = Join-Path $SourceRoot ".venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[3/4] 建立獨立虛擬環境 (.venv)..." -ForegroundColor Yellow
    & $UvExe venv --python 3.12 $VenvDir
}

Write-Host "[3/4] 安裝 LCSS 專案依賴套件..." -ForegroundColor Yellow
Push-Location $SourceRoot
try {
    $Wheelhouse = Join-Path $SourceRoot "wheelhouse"
    if (Test-Path $Wheelhouse) {
        & $UvExe pip install --python "$VenvDir\Scripts\python.exe" --no-index --find-links $Wheelhouse -e .
    } else {
        & $UvExe pip install --python "$VenvDir\Scripts\python.exe" -e .
    }
} finally {
    Pop-Location
}

# Step 4: Create Desktop shortcut pointing to launch.vbs (silent pythonw)
Write-Host "[4/4] 建立桌面捷徑..." -ForegroundColor Yellow
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$Shortcut = $WshShell.CreateShortcut((Join-Path $DesktopPath "LCSS 實驗室藥品安全管理系統.lnk"))
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"$(Join-Path $SourceRoot 'installer\launch.vbs')`""
$Shortcut.WorkingDirectory = $SourceRoot
$Shortcut.Description = "Laboratory Chemical Safety System (LCSS)"
$Shortcut.Save()

Write-Host "=== 安裝完成！可雙擊桌面捷徑啟動 LCSS ===" -ForegroundColor Green
