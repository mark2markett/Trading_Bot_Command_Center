"""Boot the exact packaged overlay through real HTTP; only external quotes are mocked."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

from test_activity_dashboard_install import installer

ROOT = Path(__file__).parent


def test_packaged_server_starts_with_existing_paper_holding(tmp_path):
    manifest, _ = installer.read_package(ROOT)
    repo = tmp_path / 'source'
    subprocess.run(['git', 'clone', '--no-checkout', str(ROOT/'activity-dashboard-source.bundle'), str(repo)],
                   check=True, capture_output=True)
    subprocess.run(['git', 'checkout', manifest['compatible_base']], cwd=repo, check=True, capture_output=True)
    with zipfile.ZipFile(ROOT/'activity-dashboard.zip') as archive:
        archive.extractall(repo)  # read_package has already verified every path and hash.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    bootstrap = tmp_path/'bootstrap.py'
    bootstrap.write_text('''
import sys,time,httpx,uvicorn
from pathlib import Path
from cc_server import main
from cc_sdk import Bot,BotManifest
from cc_sdk.paper_account import configure
from cc_sdk.schwab_feed import SchwabFeed
assert Path(main.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
class Quotes:
    def get_quote(self,symbol):
        return httpx.Response(200,request=httpx.Request('GET','https://mock-quotes.invalid'),
            json={symbol:{'quote':{'lastPrice':768,'quoteTime':time.time()*1000}}})
SchwabFeed.connect=classmethod(lambda cls,*args,**kwargs: SchwabFeed(Quotes()))
bots={name:Bot(BotManifest(id=name,name=name,version='1',strategy_line='isolated startup test',
    instrument='SPY',mode='paper')) for name in ['spy_mr','sip_orb','gap_go','gap_go_spread','nr7']}
configure(bots['spy_mr'].L,100000)
bots['spy_mr'].set_position('SPY',130,769.6,'2026-10-14',2)
bots['spy_mr'].L.order('spy_mr',side='SELL',qty=130,type_='STOP',symbol='SPY',status='sent',
    reason='paper daily stop',risk_result={},stop_price=731.12)
for bot in bots.values():bot.L.conn.close()
uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[2]),log_level='warning')
''')
    env = os.environ.copy()
    env.update(CC_VAR=str(tmp_path/'runtime'), PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=os.pathsep.join([str(repo/'cc_server'), str(repo/'cc_sdk')]))
    (tmp_path/'runtime/control').mkdir(parents=True)
    output = tmp_path/'server-output.txt'
    with output.open('w') as log:
        process = subprocess.Popen([sys.executable, '-B', str(bootstrap), str(repo), str(port)],
                                   cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            def read(route):
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/{route}', timeout=2) as response:
                    return json.load(response)
            started = time.monotonic()
            health = None
            while time.monotonic()-started < 15:
                assert process.poll() is None, output.read_text()
                try:
                    health = read('health')
                    if health.get('riskd_last', {}).get('paper_account', {}).get('ready'):
                        break
                except OSError:
                    pass
                time.sleep(.1)
            assert health and health['ok'] and health['riskd_last']['paper_account']['ready'], output.read_text()
            activity, risk = read('activity'), read('risk')
            assert activity['summary']['open_positions'] == 1
            assert activity['summary']['working_orders'] == 1
            assert risk['drawdown']['equity'] == 99792
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
