# Start server and web dev server (Windows). Run from repo root.
Start-Process -NoNewWindow python -ArgumentList "-m","cc_server.main","--reload"
Set-Location cc_web; npm run dev
