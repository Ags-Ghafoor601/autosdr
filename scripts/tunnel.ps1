# Start a Cloudflare quick tunnel to the local AutoSDR server, print the public
# URL, patch BOOKING_BASE_URL in .env, and restart the server so email booking
# links become publicly clickable. Run with pwsh from anywhere.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) { $cf = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cf)) { Write-Host "cloudflared not found — run: winget install Cloudflare.cloudflared"; exit 1 }

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
Start-Sleep 1
Remove-Item "$root\tunnel.log" -Force -ErrorAction SilentlyContinue
Start-Process -WindowStyle Hidden $cf -ArgumentList "tunnel","--url","http://localhost:8000","--no-autoupdate","--logfile","$root\tunnel.log"

$url = $null
foreach ($i in 1..30) {
    Start-Sleep 1
    if (Test-Path "$root\tunnel.log") {
        $m = Select-String -Path "$root\tunnel.log" -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches | Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value; break }
    }
}
if (-not $url) { Write-Host "tunnel failed to start — see tunnel.log"; exit 1 }

$envText = Get-Content "$root\.env" -Raw
$envText = $envText -replace "BOOKING_BASE_URL=.*", "BOOKING_BASE_URL=$url"
Set-Content "$root\.env" -Value $envText -NoNewline

Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*autosdr*" } | Stop-Process -Force -Confirm:$false
Start-Sleep 1
Start-Process -WindowStyle Hidden "$root\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","app.main:app","--port","8000"

Write-Host ""
Write-Host "  AutoSDR is PUBLIC at:  $url" -ForegroundColor Green
Write-Host "  booking links in emails now use this URL"
Write-Host ""
