#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit disposable loopback SSH acceptance. No user SSH files are changed."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/research-writer/scripts/remote_tools.py'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-ssh', action='store_true', help='Require actual local OpenSSH daemon and key generation')
parser.add_argument('--skill', type=Path, default=ROOT / 'skills/research-writer')
ARGS, REST = parser.parse_known_args()
SCRIPT = ARGS.skill.absolute() / 'scripts/remote_tools.py'


@unittest.skipUnless(ARGS.run_ssh, 'Disposable SSH fixture not requested')
class LoopbackChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix':
            raise RuntimeError('Actual loopback server fixture requires POSIX; client contracts cover other OSes')
        cls.tmp = tempfile.TemporaryDirectory(prefix='rw-ssh-')
        cls.root = Path(cls.tmp.name).resolve()
        cls.server = None
        cls.log_stream = None
        try:
            sshd = shutil.which('sshd') or '/usr/sbin/sshd'
            keygen = shutil.which('ssh-keygen')
            if not Path(sshd).is_file() or not keygen or not shutil.which('ssh'):
                raise RuntimeError('Explicit SSH test requires ssh, ssh-keygen and sshd')
            for name in ('host', 'client'):
                subprocess.run([keygen, '-q', '-t', 'ed25519', '-N', '', '-f', str(cls.root / name)],
                               check=True, capture_output=True, timeout=15)
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
            sock.close()
            (cls.root / 'authorized_keys').write_bytes((cls.root / 'client.pub').read_bytes())
            os.chmod(cls.root / 'authorized_keys', 0o600)
            host_key = ' '.join((cls.root / 'host.pub').read_text().split()[:2])
            cls.known_hosts = cls.root / 'known_hosts'
            cls.known_hosts.write_text(f'[127.0.0.1]:{cls.port} {host_key}\n', encoding='utf-8')
            # This fixture's private temporary keys and loopback listener are
            # isolated; production host-key verification remains strict.
            config = '\n'.join([
                f'Port {cls.port}', 'ListenAddress 127.0.0.1', f'HostKey {cls.root / "host"}',
                f'PidFile {cls.root / "sshd.pid"}', f'AuthorizedKeysFile {cls.root / "authorized_keys"}',
                'PasswordAuthentication no', 'KbdInteractiveAuthentication no', 'PubkeyAuthentication yes',
                'UsePAM no', 'StrictModes no', 'PermitRootLogin prohibit-password', 'PrintMotd no',
                'PermitTTY no', 'DisableForwarding yes', 'UseDNS no', 'LogLevel ERROR',
                f'AllowUsers {getpass.getuser()}', ''])
            server_config = cls.root / 'sshd_config'
            server_config.write_text(config, encoding='utf-8')
            client_config = cls.root / 'ssh_config'
            client_config.write_text('\n'.join([
                'Host rw-loopback', '  HostName 127.0.0.1', f'  Port {cls.port}',
                f'  User {getpass.getuser()}', f'  IdentityFile {cls.root / "client"}',
                '  IdentitiesOnly yes', '  IdentityAgent none',
                f'  UserKnownHostsFile {cls.known_hosts}', f'  GlobalKnownHostsFile {cls.known_hosts}',
                '  StrictHostKeyChecking yes', '']), encoding='utf-8')
            cls.log_stream = (cls.root / 'server.log').open('wb')
            cls.server = subprocess.Popen([sshd, '-D', '-e', '-f', str(server_config)],
                                          stdin=subprocess.DEVNULL, stdout=cls.log_stream,
                                          stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if cls.server.poll() is not None:
                    raise RuntimeError('Disposable sshd exited: ' + (cls.root / 'server.log').read_text()[-2000:])
                with socket.socket() as connection:
                    connection.settimeout(0.2)
                    if connection.connect_ex(('127.0.0.1', cls.port)) == 0:
                        break
                time.sleep(0.1)
            else:
                raise RuntimeError('Disposable sshd did not listen before deadline')
            cls.profile = cls.root / 'profile.json'
            cls.profile.write_text(json.dumps({
                'schema_version': 1, 'ssh_alias': 'rw-loopback', 'ssh_config': str(client_config),
                'remote_python': sys.executable, 'remote_root': str(cls.root / 'remote-jobs'),
                'expected_hostname': socket.gethostname(), 'expected_user': getpass.getuser(),
                'connect_timeout_seconds': 5}), encoding='utf-8')
        except BaseException:
            cls.cleanup()
            raise

    @classmethod
    def cleanup(cls):
        server = getattr(cls, 'server', None)
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait(timeout=3)
        if getattr(cls, 'log_stream', None):
            cls.log_stream.close()
        # Fixture jobs have <=4 seconds wall time. Let an interrupted test's
        # already-owning controller stop its child before removing private files.
        time.sleep(4.5)
        if getattr(cls, 'tmp', None):
            cls.tmp.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    def setUp(self):
        self.local = self.root / ('case-' + uuid.uuid4().hex)
        self.local.mkdir()
        self.state = self.local / 'state'
        self.counter = 0

    def call(self, operation, *extra, expected=0, profile=None):
        self.counter += 1
        output = self.local / f'reply-{self.counter}.json'
        command = [sys.executable, str(SCRIPT), operation, '--profile', str(profile or self.profile),
                   '--output', str(output), *map(str, extra)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}

    def job(self, delay=0, wall=4):
        identity = uuid.uuid4().hex
        source = self.local / 'job.py'
        source.write_text('import json,time\nfrom pathlib import Path\n'
                          f'time.sleep({delay!r})\n'
                          'Path("result.json").write_text(json.dumps({"signal":0,"kind":"loopback-control"}))\n', encoding='utf-8')
        manifest = {'schema_version': 1, 'job_id': identity, 'argv': [sys.executable, 'job.py'],
                    'inputs': [{'source': 'job.py', 'destination': 'job.py',
                                'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
                    'outputs': ['result.json'], 'required_device': 'cpu',
                    'resources': {'wall_seconds': wall, 'max_output_bytes': 65536,
                                  'max_log_bytes': 65536, 'threads': 1}}
        path = self.local / 'manifest.json'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        return identity, path

    def prepare_submit(self, identity, manifest):
        self.call('prepare', '--manifest', manifest, '--state-dir', self.state, '--allow-transfer')
        self.call('submit', '--job-id', identity, '--state-dir', self.state, '--allow-execute')

    def terminal(self, identity):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            reply = self.call('status', '--job-id', identity, '--state-dir', self.state)
            if reply.get('status') in ('succeeded', 'failed', 'timed_out', 'cancelled', 'uncertain'):
                return reply
            time.sleep(0.1)
        self.fail('Bounded fixture job did not become terminal')

    def test_actual_lifecycle_and_collection(self):
        inventory = self.call('inspect')
        self.assertTrue(inventory.get('ok'))
        identity, manifest = self.job()
        self.prepare_submit(identity, manifest)
        self.assertEqual(self.terminal(identity)['status'], 'succeeded')
        destination = self.local / 'collected'
        self.call('collect', '--job-id', identity, '--state-dir', self.state, '--destination', destination)
        self.assertEqual(json.loads((destination / 'result.json').read_text())['signal'], 0)
        self.call('submit', '--job-id', identity, '--state-dir', self.state, '--allow-execute', expected=2)

    def test_actual_identity_refusal(self):
        profile = self.local / 'wrong-profile.json'
        data = json.loads(self.profile.read_text()); data['expected_hostname'] = 'different.invalid'
        profile.write_text(json.dumps(data), encoding='utf-8')
        identity, manifest = self.job()
        self.call('prepare', '--manifest', manifest, '--state-dir', self.state, '--allow-transfer',
                  expected=2, profile=profile)
        self.assertFalse((self.root / 'remote-jobs' / identity).exists())

    def test_actual_hostkey_refusal(self):
        original = self.known_hosts.read_bytes()
        other_key = ' '.join((self.root / 'client.pub').read_text().split()[:2])
        try:
            self.known_hosts.write_text(f'[127.0.0.1]:{self.port} {other_key}\n', encoding='utf-8')
            self.call('inspect', expected=2)
        finally:
            self.known_hosts.write_bytes(original)

    def test_actual_timeout(self):
        identity, manifest = self.job(delay=10, wall=1)
        self.prepare_submit(identity, manifest)
        self.assertEqual(self.terminal(identity)['status'], 'timed_out')

    def test_actual_cancel(self):
        identity, manifest = self.job(delay=10, wall=4)
        self.prepare_submit(identity, manifest)
        self.call('cancel', '--job-id', identity, '--state-dir', self.state, '--allow-cancel')
        self.assertEqual(self.terminal(identity)['status'], 'cancelled')

    def test_actual_collected_artifact_tamper(self):
        identity, manifest = self.job()
        self.prepare_submit(identity, manifest)
        self.assertEqual(self.terminal(identity)['status'], 'succeeded')
        artifact = self.root / 'remote-jobs' / identity / 'work' / 'result.json'
        artifact.write_text('tampered', encoding='utf-8')
        destination = self.local / 'must-not-publish'
        self.call('collect', '--job-id', identity, '--state-dir', self.state, '--destination', destination, expected=2)
        self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]] + REST)
