# Reset AutoSDR to a clean state (fresh DB). Run from repo root, then restart the server.
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*autosdr*" } | Stop-Process -Force -Confirm:$false
Remove-Item -Force -ErrorAction SilentlyContinue data\autosdr.db, data\autosdr.db-journal, "data\autosdr.db-wal", "data\autosdr.db-shm"
Write-Host "DB reset. Start the server with:"
Write-Host "  .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
