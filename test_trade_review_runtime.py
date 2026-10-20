"""Run the actual packaged server against an owned, empty paper fleet."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

import httpx

ROOT=Path(__file__).parent


def test_actual_packaged_review_api_and_automatic_report_worker(tmp_path):
    source=tmp_path/'source'
    subprocess.run(['git','clone',str(ROOT/'activity-dashboard-source.bundle'),str(source)],check=True,capture_output=True)
    spec=importlib.util.spec_from_file_location('review_release_installer',ROOT/'INSTALL-ACTIVITY-DASHBOARD.py')
    installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
    _,payload=installer.read_package(ROOT)
    for name,value in payload.items():
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
    runtime=source/'var';runtime.mkdir();(runtime/'control').mkdir()
    env={key:value for key,value in os.environ.items() if not any(part in key.upper() for part in ('SECRET','TOKEN','SUPABASE','SCHWAB','POLYGON','OPENAI','WEBHOOK'))}
    env.update(CC_VAR=str(runtime),PYTHONPATH=os.pathsep.join([str(source/'cc_sdk'),str(source/'cc_server')]),
               HTTP_PROXY='http://127.0.0.1:1',HTTPS_PROXY='http://127.0.0.1:1',NO_PROXY='127.0.0.1')
    setup="""
from pathlib import Path
from cc_sdk import Bot,BotManifest
from cc_sdk.paper_account import configure
from cc_sdk.trade_evidence import record
from cc_sdk.ledger import var_dir
for name in ['gap_go','gap_go_spread','nr7','sip_orb','spy_mr']:
    bot=Bot(BotManifest(id=name,name=name,mode='paper',version='test',instrument='options',strategy_line='fixture',cadence={}))
    if name!='gap_go_spread':(var_dir()/'control'/f'{name}.pause').write_text('{"reason":"fixture options only"}')
    else:record(bot,'passed','SPY',details={'reason':'fixture observation'})
    if name=='spy_mr':configure(bot.L,100000)
    bot.L.conn.close()
(var_dir()/'control/OPTIONS_ONLY').write_text('{}')
"""
    subprocess.run([sys.executable,'-B','-c',setup],cwd=source,env=env,check=True,capture_output=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    log=(tmp_path/'server.log').open('w')
    process=subprocess.Popen([sys.executable,'-B','-m','uvicorn','cc_server.main:app','--host','127.0.0.1','--port',str(port)],
                             cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.monotonic()+15
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=2) as client:
            while True:
                assert process.poll() is None,'Packaged server exited; inspect owned server log'
                try:
                    response=client.get('/api/review')
                    if response.status_code==200:break
                except httpx.TransportError:
                    pass
                assert time.monotonic()<deadline,'Packaged review API did not become ready'
                time.sleep(.05)
            report=response.json()
            assert report['schema_version']==1 and report['execution']['broker_verified'] is False
            assert report['candidates'][0]['outcome']=='passed'
            while True:
                index=client.get('/api/reviews').json()
                if index['reports']:break
                assert time.monotonic()<deadline,'Automatic review did not complete'
                time.sleep(.05)
            assert index['worker']['status'] in ('written','already_saved')
            assert len(index['reports'][0]['session_date'])==10
            assert (runtime/'reviews'/(index['reports'][0]['session_date']+'.json')).is_file()
            page=client.get('/')
            assert page.status_code==200
            import re
            asset=re.search(r'src="(/assets/[^"]+\.js)"',page.text).group(1)
            script=client.get(asset)
            assert script.status_code==200 and 'Daily trading review' in script.text
    finally:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()
    with sqlite3.connect((runtime/'cc.db').as_uri()+'?mode=ro',uri=True) as ledger:
        for table in ('orders','fills','trades','positions'):
            assert ledger.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
    assert list((runtime/'reviews').glob('????-??-??.md'))
