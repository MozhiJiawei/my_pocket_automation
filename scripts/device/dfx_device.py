"""ADB and TouchSprite transport. Authorization never enters logs or source."""
from pathlib import Path
import json
import re
import subprocess
import time
import urllib.request

ADB = 'D:/Program Files/Netease/MuMu/nx_main/adb.exe'


def command(args, timeout=45, env=None):
    result = subprocess.run(args, capture_output=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError(f'{Path(args[0]).name} failed; details suppressed')
    return result.stdout.decode('utf-8', errors='replace').strip()


class Device:
    def __init__(self, device, adb=ADB):
        self.adb = adb
        self.device = device
        self.port = None
        self.auth = None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def adb_call(self, *args):
        shell_text=' '.join(map(str,args[1:])) if args and args[0]=='shell' else ''
        if re.search(r'\b(input|sendevent|monkey|am|wm|settings)\b',shell_text):
            raise RuntimeError('Device UI operations must run through the Lua state machine')
        return command([self.adb, '-s', self.device, *args])

    def request(self, url, body=None, authenticated=False):
        headers = {'Connection': 'close'}
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(body).encode()
        if authenticated:
            headers['auth'] = self.auth
        try:
            with self.http.open(urllib.request.Request(url, data=data, headers=headers), timeout=20) as response:
                return response.read().decode().strip()
        except Exception:
            raise RuntimeError('TouchSprite HTTP failure; details suppressed') from None

    def authorize(self):
        self.port = self.adb_call('forward', 'tcp:0', 'tcp:50005')
        if not self.port.isdigit():
            raise RuntimeError('Invalid forwarded port')
        identity = self.request(f'http://127.0.0.1:{self.port}/deviceid')
        if not re.fullmatch(r'[\w-]{16,64}', identity):
            raise RuntimeError('Invalid API identity')
        key = (Path.home() / '.my_pocket_automation/touchsprite-access-key').read_text(encoding='utf-8').strip()
        reply = json.loads(self.request('https://openapi.touchsprite.com/api/openapi', {
            'action': 'getAuth', 'key': key, 'devices': [identity], 'valid': 3600, 'time': int(time.time())}))
        if reply.get('status') != 200 or not reply.get('auth'):
            raise RuntimeError('API authorization rejected; details suppressed')
        self.auth = reply['auth']

    def status(self):
        for attempt in range(3):
            try:
                return self.request(f'http://127.0.0.1:{self.port}/status', authenticated=True)
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(1)

    def close(self):
        if self.port and self.port.isdigit():
            self.adb_call('forward', '--remove', f'tcp:{self.port}')
        self.auth = None
