#requires -Version 5.1
<#
.SYNOPSIS
  One-click full-stack E2E test for ServerKit on Windows. Sequential edition.

.DESCRIPTION
  For each distro, in turn: launch VM via Multipass, upload local working
  tree, run installer, run pytest harness, collect results. Aggregates into
  a single HTML report.

  Sequential by design — Start-Job's separate runspace makes parameter
  passing and command resolution fragile enough that parallel is not worth
  the debugging cost.

.PARAMETER Distros
  Distros to test. Default: ubuntu22, ubuntu24, debian12.

.PARAMETER Only
  Comma-separated subset (e.g. -Only "ubuntu24").

.PARAMETER Keep
  Don't delete VMs at end.

.PARAMETER ReuseVm
  Skip launch + install; use an already-running sk-test-* VM. Useful for
  re-running just the harness after an install succeeded.
#>
[CmdletBinding()]
param(
    [string[]] $Distros = @('ubuntu22','ubuntu24','debian12'),
    [string]   $Only,
    [switch]   $Keep,
    [string]   $ReuseVm,
    [int]      $Cpus = 2,
    [int]      $MemoryGB = 4,
    [int]      $DiskGB = 15
)

# NB: keep ErrorActionPreference at Continue. Multipass writes harmless
# warnings to stderr (e.g. "cannot set permissions" when transferring to
# NTFS) and 'Stop' turns those into fatal script errors.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$ImageMap = @{
    'ubuntu22' = '22.04'
    'ubuntu24' = '24.04'
    'debian12' = 'daily:debian12'
}

if ($Only) {
    $requested = $Only -split ','
    $Distros = $Distros | Where-Object { $_ -in $requested }
}

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$RunId    = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutDir   = Join-Path $PSScriptRoot "output\$RunId"
$null     = New-Item -ItemType Directory -Force -Path $OutDir

# Seed state.json immediately so any early refresh of the report shows
# "running" rather than treating an empty dir as a failed run.
Set-Content -Path (Join-Path $OutDir 'state.json') -Value '{"running":true,"vms":{}}' -Encoding utf8

# --- locate multipass ----------------------------------------------------
$MpExe = $null
$candidates = @(
    'C:\Program Files\Multipass\bin\multipass.exe',
    "$env:LOCALAPPDATA\Programs\Multipass\bin\multipass.exe"
)
foreach ($c in $candidates) { if (Test-Path $c) { $MpExe = $c; break } }
if (-not $MpExe) {
    $MpExe = (Get-Command multipass -ErrorAction SilentlyContinue).Source
}
if (-not $MpExe) {
    Write-Host "Multipass not found. Install via: winget install Canonical.Multipass" -ForegroundColor Red
    exit 2
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " ServerKit E2E Test - run $RunId" -ForegroundColor Cyan
Write-Host " Multipass: $MpExe" -ForegroundColor Cyan
Write-Host " Distros:   $($Distros -join ', ')" -ForegroundColor Cyan
Write-Host " Output:    $OutDir" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# NB: 'mp' is a built-in PS alias for Move-ItemProperty, so we must NOT
# define a helper function named Mp. Use $MpExe directly everywhere.

# --- live state + report regen ------------------------------------------
$script:State = @{ running = $true; vms = @{} }
function Save-State {
    $json = $script:State | ConvertTo-Json -Depth 5 -Compress
    Set-Content -Path (Join-Path $OutDir 'state.json') -Value $json -Encoding utf8
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python (Join-Path $PSScriptRoot 'report.py') $OutDir 2>&1 | Out-Null
    }
}
function Set-VmStage {
    param([string]$Vm, [string]$Stage)
    if (-not $script:State.vms.ContainsKey($Vm)) { $script:State.vms[$Vm] = @{} }
    $script:State.vms[$Vm].stage = $Stage
    Save-State
}

function Test-VmInstall {
    param([string]$Vm, [string]$VmOut, [string]$Tarball, [string]$VmInstallScript, [string]$HarnessDir)

    New-Item -ItemType Directory -Force -Path $VmOut | Out-Null
    $statusFile = Join-Path $VmOut 'install-status'

    Set-VmStage -Vm $Vm -Stage 'transferring source'
    Write-Host "  [$Vm] transferring source ($([math]::Round((Get-Item $Tarball).Length/1MB,1)) MB)..." -ForegroundColor DarkCyan
    & $MpExe transfer $Tarball "${Vm}:/tmp/serverkit-src.tar.gz" 2>&1 | Out-Null
    & $MpExe transfer $VmInstallScript "${Vm}:/tmp/vm-install.sh" 2>&1 | Out-Null
    & $MpExe exec $Vm -- sudo mkdir -p /opt/serverkit-src 2>&1 | Out-Null
    & $MpExe exec $Vm -- sudo tar -xzf /tmp/serverkit-src.tar.gz -C /opt/serverkit-src 2>&1 | Out-Null
    & $MpExe exec $Vm -- sudo chmod +x /tmp/vm-install.sh 2>&1 | Out-Null

    Set-VmStage -Vm $Vm -Stage 'installing (npm ci + build, ~10 min)'
    Write-Host "  [$Vm] running install (this is the long part)..." -ForegroundColor DarkCyan
    & $MpExe exec $Vm -- sh -c "sudo bash /tmp/vm-install.sh > /tmp/vm-install-stdout.log 2>&1; rc=`$?; echo EXIT_RC=`$rc; exit `$rc" `
        | Out-File (Join-Path $VmOut 'install.log') -Encoding utf8
    $installRC = $LASTEXITCODE

    & $MpExe transfer "${Vm}:/var/log/serverkit-test-install.log" "$VmOut\vm-install.log" 2>&1 | Out-Null
    & $MpExe transfer "${Vm}:/tmp/serverkit-install-status" $statusFile 2>&1 | Out-Null
    if (-not (Test-Path $statusFile) -or (Get-Content $statusFile -Raw -ErrorAction SilentlyContinue).Trim() -eq '') {
        $fallback = if ($installRC -eq 0) { 'OK' } else { 'FAIL' }
        Set-Content -Path $statusFile -Value $fallback -Encoding ascii
    }
    & $MpExe exec $Vm -- sudo journalctl -u serverkit --no-pager -n 500 2>&1 `
        | Out-File (Join-Path $VmOut 'journalctl.log') -Encoding utf8

    $status = (Get-Content $statusFile -Raw).Trim()
    Write-Host "  [$Vm] install status: $status" -ForegroundColor $(if ($status -eq 'OK') { 'Green' } else { 'Red' })
    Save-State  # regenerate so install log + journalctl show up

    if ($status -ne 'OK') {
        Set-VmStage -Vm $Vm -Stage 'install failed'
        return $status
    }

    Set-VmStage -Vm $Vm -Stage 'running pytest'
    Write-Host "  [$Vm] running pytest harness..." -ForegroundColor DarkCyan
    & $MpExe exec $Vm -- sudo mkdir -p /opt/serverkit-test 2>&1 | Out-Null
    & $MpExe exec $Vm -- sudo chown ubuntu:ubuntu /opt/serverkit-test 2>&1 | Out-Null
    Get-ChildItem $HarnessDir -File | ForEach-Object {
        & $MpExe transfer $_.FullName "${Vm}:/opt/serverkit-test/$($_.Name)" 2>&1 | Out-Null
    }
    & $MpExe exec $Vm -- sudo /opt/serverkit/venv/bin/pip install -r /opt/serverkit-test/requirements.txt 2>&1 `
        | Out-File (Join-Path $VmOut 'harness-deps.log') -Encoding utf8
    & $MpExe exec $Vm -- sh -c "sudo /opt/serverkit/venv/bin/python -m pytest /opt/serverkit-test --json-report --json-report-file=/opt/serverkit-test/pytest-report.json -v > /tmp/pytest-stdout.log 2>&1; rc=`$?; echo EXIT_RC=`$rc; exit `$rc" `
        | Out-File (Join-Path $VmOut 'pytest.log') -Encoding utf8
    & $MpExe transfer "${Vm}:/tmp/pytest-stdout.log" (Join-Path $VmOut 'pytest-stdout.log') 2>&1 | Out-Null
    & $MpExe transfer "${Vm}:/opt/serverkit-test/pytest-report.json" (Join-Path $VmOut 'pytest-report.json') 2>&1 | Out-Null

    Set-VmStage -Vm $Vm -Stage 'done'
    return $status
}

# --- pack source --------------------------------------------------------
$Tarball = Join-Path $OutDir 'serverkit-src.tar.gz'
Write-Host "`n[1/4] Packing local working tree -> $Tarball" -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    & tar --exclude='.git' `
          --exclude='venv' `
          --exclude='.venv' `
          --exclude='.venv-wsl' `
          --exclude='node_modules' `
          --exclude='dist' `
          --exclude='__pycache__' `
          --exclude='instance' `
          --exclude='target' `
          --exclude='build' `
          --exclude='*.exe' `
          --exclude='*.msi' `
          --exclude='scripts/test/output' `
          -czf $Tarball -C $RepoRoot .
    if ($LASTEXITCODE -ne 0) { throw "tar failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}
Write-Host ("    Tarball: {0:N1} MB" -f ((Get-Item $Tarball).Length / 1MB))

# --- main loop ----------------------------------------------------------
$results = @()
$liveVMs = @()
$vmInstallScript = Join-Path $PSScriptRoot 'vm-install.sh'
$cloudInit = Join-Path $PSScriptRoot 'cloud-init\base.yaml'
$harnessDir = Join-Path $PSScriptRoot 'harness'

# Pre-populate stages and seed the live report, then open it in the browser.
foreach ($d in $Distros) {
    $vmName = if ($ReuseVm) { $ReuseVm } else { "sk-test-$d-$RunId" }
    $script:State.vms[$vmName] = @{ stage = 'pending' }
    if ($ReuseVm) { break }
}
Save-State
$reportPath = Join-Path $OutDir 'report.html'
if (Test-Path $reportPath) {
    Write-Host "`nLive report: $reportPath (opening in browser)" -ForegroundColor Cyan
    Start-Process $reportPath
}

if ($ReuseVm) {
    Write-Host "`n[2-3/4] Reusing VM: $ReuseVm" -ForegroundColor Yellow
    $vmOut = Join-Path $OutDir $ReuseVm
    $status = Test-VmInstall -Vm $ReuseVm -VmOut $vmOut -Tarball $Tarball `
                              -VmInstallScript $vmInstallScript -HarnessDir $harnessDir
    $results += @{ Name = $ReuseVm; Status = $status }
    $liveVMs += $ReuseVm
} else {
    Write-Host "`n[2/4] Launching + testing $($Distros.Count) VM(s) sequentially..." -ForegroundColor Yellow
    foreach ($d in $Distros) {
        $vmName = "sk-test-$d-$RunId"
        $image = $ImageMap[$d]
        if (-not $image) { Write-Warning "Unknown distro $d, skipping"; continue }

        Write-Host "`n--- $d ---" -ForegroundColor Yellow
        Write-Host "  Launching $vmName from image $image..." -ForegroundColor DarkCyan
        & $MpExe launch $image --name $vmName --cpus $Cpus --memory "${MemoryGB}G" --disk "${DiskGB}G" --cloud-init $cloudInit
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [FAIL] $vmName launch failed" -ForegroundColor Red
            $results += @{ Name = $vmName; Status = 'LAUNCH_FAILED' }
            continue
        }
        Write-Host "  [OK] $vmName launched" -ForegroundColor Green
        $liveVMs += $vmName

        $vmOut = Join-Path $OutDir $vmName
        $status = Test-VmInstall -Vm $vmName -VmOut $vmOut -Tarball $Tarball `
                                  -VmInstallScript $vmInstallScript -HarnessDir $harnessDir
        $results += @{ Name = $vmName; Status = $status }
    }
}

# --- report -------------------------------------------------------------
Write-Host "`n[4/4] Finalizing HTML report..." -ForegroundColor Yellow
$script:State.running = $false
Save-State
$reportHtml = Join-Path $OutDir 'report.html'
if (Test-Path $reportHtml) {
    Write-Host "    Report: $reportHtml" -ForegroundColor Green
} else {
    Write-Host "    python not on PATH. Raw output: $OutDir" -ForegroundColor Yellow
    $reportHtml = $null
}

# --- teardown -----------------------------------------------------------
if ($Keep -or $ReuseVm) {
    Write-Host "`nVMs left running:" -ForegroundColor Yellow
    $liveVMs | ForEach-Object { Write-Host "  - $_" }
} else {
    Write-Host "`nTearing down VMs..." -ForegroundColor Yellow
    foreach ($vm in $liveVMs) { & $MpExe delete $vm 2>&1 | Out-Null }
    & $MpExe purge 2>&1 | Out-Null
}

# --- summary ------------------------------------------------------------
$failed = @($results | Where-Object { $_.Status -ne 'OK' })
Write-Host ""
if ($failed.Count -eq 0 -and $results.Count -gt 0) {
    Write-Host "ALL GREEN - $($results.Count) VM(s) passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "FAILURES on $($failed.Count) VM(s):" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "  - $($_.Name): $($_.Status)" -ForegroundColor Red }
    exit 1
}
