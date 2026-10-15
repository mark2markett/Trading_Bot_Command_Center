"""Local release operations; no orders, controls or provider requests."""
import json
import os
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def extract(archive,destination):
    destination=Path(destination)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if 'index.html' not in names or len(names)>1000 or sum(i.file_size for i in z.infolist())>20000000:
            raise ValueError('Invalid dashboard archive')
        for name in names:
            p=Path(name.replace('\\','/'))
            if p.is_absolute() or '..' in p.parts or ':' in name or name.startswith('/'):
                raise ValueError('Unsafe dashboard archive path')
        if destination.is_symlink():
            raise ValueError('Unsafe dashboard destination')
        stage=destination.with_name(destination.name+'-attention-stage')
        if stage.exists():
            raise ValueError('Staging directory already exists')
        stage.mkdir(parents=True)
        try:
            z.extractall(stage)
            if destination.exists():
                shutil.rmtree(destination)
            stage.rename(destination)
        finally:
            if stage.exists(): shutil.rmtree(stage)


def backup(runtime,target):
    runtime,target=Path(runtime),Path(target); target.mkdir(parents=True,exist_ok=True)
    for source,name in [(runtime/'cc.db','cc.db'),(runtime/'monitor'/'incidents.db','incidents.db')]:
        if name=='incidents.db' and not source.exists(): continue
        if source.is_symlink(): raise ValueError('Unsafe database path')
        src=sqlite3.connect(source.resolve(strict=True).as_uri()+'?mode=ro',uri=True,timeout=2)
        dst=sqlite3.connect(target/name)
        try: src.backup(dst)
        finally: src.close(); dst.close()


def activate(repo,runtime):
    repo,runtime=Path(repo),Path(runtime)
    sys.path[:0]=[str(repo/'cc_server'),str(repo/'cc_sdk')]
    from cc_server.incidents.readback import read_incidents
    from cc_server.incidents.store import IncidentStore
    from cc_server.incidents.windows import WindowsTask
    now=datetime.now(timezone.utc)
    report=read_incidents(runtime,now=now)
    if report['monitor']['status']!='checking': raise ValueError('Fresh completed observations required')
    task=WindowsTask(repo).inspect_server()
    if task.get('owned') is not True or task.get('inspectable') is not True or task.get('state')!='Running' or task.get('enabled') is not True:
        raise ValueError('Owned running server required for activation')
    with IncidentStore(runtime/'monitor'/'incidents.db') as store:
        if store.state('continuity_ok') is not True: raise ValueError('Two coherent observations required')
        store.set_state('notifications_enabled',True)
    marker=runtime/'monitor'/'installed.json'
    temporary=marker.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version':1,'recovery_enabled':True})+'\n')
    temporary.replace(marker)


if __name__=='__main__':
    try:
        {'backup':backup,'extract':extract,'activate':activate}[sys.argv[1]](*sys.argv[2:])
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc))
        raise SystemExit(1)
