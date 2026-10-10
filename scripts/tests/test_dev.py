"""Run the real supervisor with disposable child processes, including POSIX sh."""
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'dev.sh'


@pytest.fixture
def supervisor(tmp_path):
    (tmp_path / 'scripts').mkdir()
    shutil.copyfile(SCRIPT, tmp_path / 'scripts/dev.sh')
    (tmp_path / '.venv/bin').mkdir(parents=True)
    (tmp_path / 'frontend/node_modules').mkdir(parents=True)
    (tmp_path / 'bin').mkdir()
    for role, target in [('backend', '.venv/bin/python'), ('frontend', 'bin/node')]:
        child = tmp_path / target
        child.write_text('''#!/usr/bin/env python3
import os,signal,time
from pathlib import Path
role = %r
Path(role + '.pid').write_text(str(os.getpid()))
if os.environ.get('TEST_STUBBORN') == role:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
code = os.environ.get('TEST_EXIT_' + role.upper())
if code is not None:
    time.sleep(.3)
    raise SystemExit(int(code))
while True: time.sleep(.1)
''' % role)
        child.chmod(0o755)
    processes = []
    def start(shell='bash', **extra):
        env = {**os.environ, 'PATH': str(tmp_path / 'bin') + ':' + os.environ['PATH'], **extra}
        proc = subprocess.Popen([shell, str(tmp_path / 'scripts/dev.sh')], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(proc)
        return proc
    yield tmp_path, start
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=9)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
    # Ensure a failed test cannot leave fixture processes behind.
    for path in tmp_path.rglob('*.pid'):
        try: os.kill(int(path.read_text()), signal.SIGKILL)
        except ProcessLookupError: pass


def children(root):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        paths = [root / 'backend.pid', root / 'frontend/frontend.pid']
        if all(p.exists() for p in paths):
            return [int(p.read_text()) for p in paths]
        time.sleep(.05)
    raise AssertionError('Both children did not start')


def stopped(pids):
    for pid in pids:
        with pytest.raises(ProcessLookupError): os.kill(pid, 0)


@pytest.mark.parametrize('shell', ['bash', 'sh'])
@pytest.mark.parametrize('role,code', [('backend', 7), ('frontend', 9), ('frontend', 0)])
def test_child_exit_is_detected_and_other_child_stops(supervisor, shell, role, code):
    root, start = supervisor
    proc = start(shell, **{'TEST_EXIT_' + role.upper(): str(code)})
    pids = children(root)
    _, stderr = proc.communicate(timeout=10)
    assert proc.returncode == (code or 1)
    assert f'{role} exited unexpectedly (status {code})' in stderr
    stopped(pids)


@pytest.mark.parametrize('shell', ['bash', 'sh'])
@pytest.mark.parametrize('sig,code', [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_signal_stops_both_children(supervisor, shell, sig, code):
    root, start = supervisor
    proc = start(shell)
    pids = children(root)
    proc.send_signal(sig)
    proc.communicate(timeout=10)
    assert proc.returncode == code
    stopped(pids)


def test_stuck_child_is_killed_after_grace_period(supervisor):
    root, start = supervisor
    proc = start(TEST_EXIT_BACKEND='7', TEST_STUBBORN='frontend')
    pids = children(root)
    proc.communicate(timeout=12)
    assert proc.returncode == 7
    stopped(pids)
