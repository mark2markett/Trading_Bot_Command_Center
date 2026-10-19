"""Exercise the operator wrapper with isolated child release/diagnostic adapters."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest


@pytest.mark.parametrize('case',['success','release_failure','diagnostic_failure','no_approval','partial_snapshot','pause_returned'])
def test_completion_always_reports_result_without_hiding_refusal(tmp_path,case):
    power=shutil.which('pwsh') or ('/tmp/cc-pwsh/pwsh' if Path('/tmp/cc-pwsh/pwsh').exists() else None)
    if not power:pytest.skip('PowerShell is unavailable')
    script=Path(__file__).with_name('COMPLETE-FLEET-RELEASE.ps1')
    shutil.copy2(script,tmp_path/script.name)
    release=tmp_path/'RESUME-FLEET-PAPER.ps1'
    release.write_text("param($Repo,[switch]$ApproveFleetPaperEntries)\nif(!$ApproveFleetPaperEntries){throw 'approval missing'}\n"+
                       ("throw 'synthetic release refused'\n" if case=='release_failure' else "Write-Output '{\"ok\":true,\"resumed\":true,\"sip_paused\":true}'\n"))
    diagnostic=tmp_path/'DIAGNOSE-FLEET-BLOCKERS.py'
    import json
    snapshot={'collection_complete':case!='partial_snapshot','fleet_entries_paused':case=='pause_returned','marker':'SYNTHETIC_READ_ONLY_EVIDENCE'}
    diagnostic.write_text('print('+repr(json.dumps(snapshot))+')\n'+('raise SystemExit(1)\n' if case=='diagnostic_failure' else ''))
    (tmp_path/'FLEET-RESUME-SHA256.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (release,diagnostic)))
    python=tmp_path/'.venv/Scripts/python.exe';python.parent.mkdir(parents=True)
    try:python.symlink_to(sys.executable)
    except OSError:pytest.skip('Python executable link is unavailable')
    cmd=[power,'-NoLogo','-NoProfile','-File',str(tmp_path/script.name),'-Repo',str(tmp_path)]
    if case!='no_approval':cmd.append('-ApproveFleetPaperEntries')
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=20,env={**os.environ,'XDG_CACHE_HOME':'/tmp/cc-pwsh-cache','XDG_CONFIG_HOME':'/tmp/cc-pwsh-config','XDG_DATA_HOME':'/tmp/cc-pwsh-data'})
    assert (result.returncode==0)==(case=='success'),result.stdout+result.stderr
    if case=='no_approval':assert 'SYNTHETIC_READ_ONLY_EVIDENCE' not in result.stdout
    else:assert 'SYNTHETIC_READ_ONLY_EVIDENCE' in result.stdout
    if case=='release_failure':assert 'synthetic release refused' in result.stdout and 'Fleet release verified' not in result.stdout
