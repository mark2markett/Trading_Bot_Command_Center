python -m pytest -q; if ($LASTEXITCODE -ne 0) { exit 1 }
Set-Location cc_web; npm test --silent
