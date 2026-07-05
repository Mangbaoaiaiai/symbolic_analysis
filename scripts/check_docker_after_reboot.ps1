$ErrorActionPreference = "Continue"

$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"

Write-Host "== Docker executable =="
if (-not (Test-Path -LiteralPath $docker)) {
  Write-Error "docker.exe not found at $docker"
  exit 1
}
& $docker --version

Write-Host "`n== Starting Docker Desktop =="
if (Test-Path -LiteralPath $desktop) {
  Start-Process -FilePath $desktop
}

Write-Host "`n== Waiting for Docker engine =="
$ready = $false
for ($i = 1; $i -le 60; $i++) {
  & $docker --context desktop-linux info *> $null
  if ($LASTEXITCODE -eq 0) {
    $ready = $true
    break
  }
  Start-Sleep -Seconds 5
  Write-Host "waited $($i * 5)s..."
}

if (-not $ready) {
  Write-Host "`nDocker engine did not become ready. Current status:"
  & $docker desktop status 2>&1
  & wsl.exe --status 2>&1
  & wsl.exe -l -v 2>&1
  exit 2
}

Write-Host "`n== Docker info =="
& $docker --context desktop-linux info

Write-Host "`n== Hello world =="
& $docker --context desktop-linux run --rm hello-world

Write-Host "`nDocker is ready."
