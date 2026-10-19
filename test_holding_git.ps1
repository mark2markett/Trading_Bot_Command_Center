$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'INSTALL-HOLDING-MAINTENANCE.ps1'),[ref]$tokens,[ref]$errors)
$definition=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Import-HoldingBundle'},$true)
if (!$definition) { throw 'Bundle import has no explicit maintenance suppression helper.' }
Invoke-Expression $definition.Extent.Text
$root=Join-Path ([IO.Path]::GetTempPath()) ('holding-git-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$oldTrace=$env:GIT_TRACE2_EVENT
$initialCCVar=$env:CC_VAR
Push-Location $root
try {
    git init --quiet source
    git -C source config user.name 'Isolated repair test'
    git -C source config user.email 'test@example.invalid'
    Set-Content -LiteralPath source/proof.txt -Value 'before'
    git -C source add proof.txt
    git -C source commit --quiet -m before
    git clone --quiet --no-hardlinks source receiver
    Set-Content -LiteralPath source/proof.txt -Value 'after'
    git -C source add proof.txt
    git -C source commit --quiet -m after
    git -C source branch reviewed
    $tip=(git -C source rev-parse HEAD).Trim()
    $bundle=Join-Path $root source.bundle
    git -C source bundle create $bundle reviewed
    Push-Location receiver
    try {
        git config maintenance.strategy incremental
        $control=Join-Path $root control.trace
        $env:GIT_TRACE2_EVENT=$control
        git -c gc.auto=0 fetch $bundle reviewed:refs/test/control 2>&1 | Out-Null
        $prior=@(Get-Content -LiteralPath $control | ConvertFrom-Json | Where-Object { $_.event -eq 'child_start' -and $_.argv -contains 'maintenance' })
        if (!$prior.Count) { throw 'Control failed to demonstrate automatic Git maintenance.' }
        $trace=Join-Path $root fixed.trace
        $env:GIT_TRACE2_EVENT=$trace
        Import-HoldingBundle -Bundle $bundle -Branch reviewed -Expected $tip
        $unexpected=@(Get-Content -LiteralPath $trace | ConvertFrom-Json | Where-Object { $_.event -eq 'child_start' -and ($_.argv -contains 'maintenance' -or $_.argv -contains 'gc' -or $_.argv -contains 'repack') })
        if ($unexpected.Count) { throw 'Patched import still launches housekeeping.' }
        $tokens=$null;$errors=$null
        $installer=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'INSTALL-HOLDING-MAINTENANCE.ps1'),[ref]$tokens,[ref]$errors)
        $staging=$installer.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Export-HoldingSource'},$true)
        if (!$staging) {
            # Exercise the currently shipped expression verbatim to reproduce its native argv.
            $stage=Join-Path $root 'stage with spaces';New-Item -ItemType Directory -Path $stage | Out-Null
            $release=[pscustomobject]@{tip=$tip}
            $command=$installer.Find({param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'git' -and $n.Extent.Text -like 'git archive*'},$true)
            Invoke-Expression $command.Extent.Text
            if ($LASTEXITCODE -ne 0) { throw 'Native PowerShell archive staging rejected the output argument.' }
        } else {
            Invoke-Expression $staging.Extent.Text
            $stage=Join-Path $root 'stage with spaces';New-Item -ItemType Directory -Path $stage | Out-Null
            Export-HoldingSource -Stage $stage -Commit $tip
            if (!(Test-Path -LiteralPath (Join-Path $stage 'proof.txt')) -or (Get-Content -LiteralPath (Join-Path $stage 'proof.txt') -Raw).Trim() -ne 'after') { throw 'Staged source differs from the reviewed commit.' }
        }
        $refused=$false
        try { Import-HoldingBundle -Bundle $bundle -Branch reviewed -Expected ('0'*40) } catch { $refused=$true }
        if (!$refused) { throw 'Unexpected imported head was accepted.' }
        if ($env:CC_TEST_PYTHON) {
            $testDefinition=$installer.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-HoldingSource'},$true)
            Invoke-Expression $testDefinition.Extent.Text
            $fullRepo=Join-Path $root 'full-repo'
            git clone --quiet --no-checkout (Join-Path $PSScriptRoot 'holding-maintenance.bundle') $fullRepo
            $fullStage=Join-Path $root 'full stage with spaces';New-Item -ItemType Directory -Path $fullStage | Out-Null
            $fullTip=(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'HOLDING-MAINTENANCE-SOURCE.json') -Raw | ConvertFrom-Json).tip
            Push-Location $fullRepo
            try {
                Export-HoldingSource -Stage $fullStage -Commit $fullTip
                Test-HoldingSource -Stage $fullStage -Python $env:CC_TEST_PYTHON
            } finally { Pop-Location }
            if ($env:CC_VAR -cne $initialCCVar) { throw 'Staged tests leaked their isolated runtime setting.' }
        }
        Write-Host 'Real archive extraction and native argument handling passed, including a source path with spaces.'
        Write-Host 'Real Git control reproduced housekeeping; patched bundle import suppressed it and rejected a wrong head.'
    } finally { Pop-Location }
} finally {
    Pop-Location
    if ($null -eq $oldTrace) { Remove-Item Env:\GIT_TRACE2_EVENT -ErrorAction SilentlyContinue } else { $env:GIT_TRACE2_EVENT=$oldTrace }
    Remove-Item -LiteralPath $root -Recurse -Force
}
