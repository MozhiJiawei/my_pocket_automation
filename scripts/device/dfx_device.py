"""ADB and TouchSprite transport. Authorization never enters logs or source."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request

ADB = 'D:/Program Files/Netease/MuMu/nx_main/adb.exe'


@contextmanager
def instance_lock(root, mumu_dir, vm_index):
    """Serialize both device commands for one explicit MuMu installation/VM."""
    if type(vm_index) is not int or vm_index < 0:
        raise ValueError('A nonnegative integer VM index is required')
    installation = Path(mumu_dir)
    if not installation.is_absolute():
        raise ValueError('An absolute MuMu installation path is required')
    identity = os.path.normcase(str(installation.resolve())) + ':' + str(vm_index)
    token = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    path = Path(root) / 'debug-runs/locks' / (token + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Selected MuMu instance is busy; no device action taken') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def allocate_run_id(root):
    """Reserve a unique collector-compatible YYYYMMDD_HHMMSS identifier."""
    archive_root = Path(root) / 'debug-runs'
    reservations = archive_root / 'run-ids'
    reservations.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now()
    while True:
        run_id = stamp.strftime('%Y%m%d_%H%M%S')
        if not (archive_root / run_id).exists():
            try:
                with (reservations / run_id).open('x', encoding='ascii') as handle:
                    handle.write(run_id)
                    handle.flush()
                    os.fsync(handle.fileno())
                return run_id
            except FileExistsError:
                pass
        stamp += timedelta(seconds=1)


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
        self.auth_deadline = None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def adb_call(self, *args):
        shell_text=' '.join(map(str,args[1:])) if args and args[0]=='shell' else ''
        if re.search(r'\b(input|sendevent|monkey|am|wm|settings)\b',shell_text):
            raise RuntimeError('Device UI operations must run through the Lua state machine')
        return command([self.adb, '-s', self.device, *args])

    def request(self, url, body=None, authenticated=False, timeout=20):
        headers = {'Connection': 'close'}
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(body).encode()
        if authenticated:
            headers['auth'] = self.auth
        try:
            with self.http.open(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as response:
                return response.read().decode().strip()
        except Exception:
            raise RuntimeError('TouchSprite HTTP failure; details suppressed') from None

    def authorize(self):
        if not self.port:
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
        self.auth_deadline = time.monotonic() + 3540

    def status(self):
        if self.auth_deadline is not None and time.monotonic() >= self.auth_deadline:
            self.authorize()
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
        self.auth_deadline = None
