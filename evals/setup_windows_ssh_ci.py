#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the native Windows SSH checks on a disposable GitHub-hosted Windows VM."""
import base64
import csv
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid


def checked(argv, timeout=25, **kwargs):
    return subprocess.run(argv, timeout=timeout, check=True, **kwargs)


def powershell(script, *, timeout=25, env=None):
    code = base64.b64encode(("$ErrorActionPreference='Stop'\n" + script).encode('utf-16le')).decode('ascii')
    return checked(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', code],
                   timeout=timeout, env={**os.environ, **(env or {})})


def require_hosted_windows():
    if not (os.name == 'nt' and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and os.environ.get('RUNNER_OS') == 'Windows' and os.environ.get('RUNNER_TEMP')):
        raise SystemExit('Disposable GitHub-hosted native Windows runner required')


def find_openssh():
    bin_dir = Path(os.environ['SystemRoot']) / 'System32/OpenSSH'
    for binary, capability in (('ssh.exe', 'Client'), ('sshd.exe', 'Server')):
        if not (bin_dir / binary).is_file():
            powershell(f'Add-WindowsCapability -Online -Name OpenSSH.{capability}~~~~0.0.1.0', timeout=150)
        if not (bin_dir / binary).is_file():
            raise FileNotFoundError(bin_dir / binary)
    return bin_dir


def lock_key(path, owner, *readers, remove_creator=None):
    grants = [f'*{sid}:F' for sid in (owner, *readers)]
    checked(['icacls.exe', str(path), '/grant:r', *grants, '/inheritance:r'])
    checked(['icacls.exe', str(path), '/setowner', '*' + owner])
    if remove_creator is not None:
        # ssh-keygen's explicit creator ACE survives removal of inherited ACEs.
        checked(['icacls.exe', str(path), '/remove', '*' + remove_creator])


def verify_server_key_permissions(host_key, authorized):
    powershell(
        "$sidType=[System.Security.Principal.SecurityIdentifier]\n"
        "foreach ($path in @($env:RW_CI_HOST_KEY, $env:RW_CI_AUTHORIZED)) {\n"
        "  $acl=Get-Acl -LiteralPath $path\n"
        "  $rules=@($acl.GetAccessRules($true, $true, $sidType))\n"
        "  $ids=@($rules | ForEach-Object { $_.IdentityReference.Value } | Sort-Object)\n"
        "  $bad=@($rules | Where-Object { $_.IsInherited -or $_.AccessControlType -ne 'Allow' "
        "-or $_.FileSystemRights -ne 'FullControl' })\n"
        "  if ($acl.GetOwner($sidType).Value -ne 'S-1-5-32-544' -or -not $acl.AreAccessRulesProtected "
        "-or ($ids -join ',') -ne 'S-1-5-18,S-1-5-32-544' -or $bad.Count -ne 0) {\n"
        "    throw ('Unexpected SSH fixture key ACL: ' + $path)\n"
        "  }\n"
        "  Write-Output ('WINDOWS_SSH_ACL verified ' + (Split-Path -Leaf $path))\n"
        "}",
        env={'RW_CI_HOST_KEY': str(host_key), 'RW_CI_AUTHORIZED': str(authorized)},
    )


def quote_config(path):
    return '"' + path.as_posix() + '"'


def fixture(root, openssh):
    user = getpass.getuser()
    if not re.fullmatch('[A-Za-z0-9_.-]+', user):
        raise ValueError('Expected the local Windows hosted runner account')
    who = checked(['whoami.exe', '/user', '/fo', 'csv', '/nh'], capture_output=True)
    sid = next(csv.reader(who.stdout.decode('ascii').splitlines()))[1]
    if not re.fullmatch(r'S-1-5-(?:\d+-)+\d+', sid):
        raise ValueError('Expected the hosted runner account SID')
    admins, system = 'S-1-5-32-544', 'S-1-5-18'

    host_key, client_key = root / 'host_key', root / 'client_key'
    for key in (host_key, client_key):
        checked([str(openssh / 'ssh-keygen.exe'), '-q', '-t', 'ed25519', '-N', '', '-f', str(key)])
    authorized = root / 'authorized_keys'
    host_public = host_key.with_suffix('.pub').read_bytes().split()[:2]
    client_public = client_key.with_suffix('.pub').read_bytes().split()[:2]
    authorized.write_bytes(b' '.join(client_public) + b'\n')
    lock_key(host_key, admins, system, remove_creator=sid)
    lock_key(authorized, admins, system, remove_creator=sid)
    lock_key(client_key, sid, system, admins)
    verify_server_key_permissions(host_key, authorized)

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    alias = 'rw-winssh-fixture'
    known = root / 'known_hosts'
    known.write_bytes(b' '.join([alias.encode('ascii'), *host_public]) + b'\n')
    (root / 'empty_known_hosts').touch()
    (root / 'wrong_known_hosts').write_bytes(b' '.join([alias.encode('ascii'), *client_public]) + b'\n')
    config = root / 'sshd_config'
    config.write_text('\n'.join([
        f'Port {port}', 'AddressFamily inet', 'ListenAddress 127.0.0.1',
        f'HostKey {quote_config(host_key)}', f'AuthorizedKeysFile {quote_config(authorized)}',
        f'AllowUsers {user.lower()}', 'AuthenticationMethods publickey', 'PubkeyAuthentication yes',
        'PasswordAuthentication no', 'AllowTcpForwarding no', 'AllowAgentForwarding no',
        'X11Forwarding no', 'PermitTTY no', 'MaxSessions 1', 'LogLevel VERBOSE',
    ]) + '\n', encoding='utf-8')
    client_config = root / 'ssh_config'
    client_config.write_text('\n'.join([
        f'Host {alias}', '  HostName 127.0.0.1', f'  Port {port}', f'  User {user.lower()}',
        f'  HostKeyAlias {alias}', f'  IdentityFile {quote_config(client_key)}', '  IdentitiesOnly yes',
        '  IdentityAgent none', f'  UserKnownHostsFile {quote_config(known)}', '  GlobalKnownHostsFile none',
    ]) + '\n', encoding='utf-8')

    env = root / 'Python space 研究'
    checked([sys.executable, '-m', 'venv', '--without-pip', str(env)])
    python = env / 'Scripts/python.exe'
    checked([str(python), '-I', '-c', 'import sys; assert sys.platform=="win32"'])
    profile = {
        'schema_version': 1, 'ssh_alias': alias, 'ssh_config': str(client_config),
        'remote_python': str(python), 'remote_root': str(root / 'Research jobs 研究'),
        'expected_hostname': socket.gethostname(), 'expected_user': user, 'connect_timeout_seconds': 5,
    }
    (root / 'profile.json').write_text(json.dumps(profile), encoding='utf-8')
    return config, port


def readiness(port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5) as sock:
                if sock.recv(32).startswith(b'SSH-'):
                    return
        except (ConnectionError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError('Isolated Windows OpenSSH listener did not become ready')


def default_shell():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\OpenSSH') as key:
            return str(winreg.QueryValueEx(key, 'DefaultShell')[0])
    except FileNotFoundError:
        return 'cmd.exe'


def cleanup_fixture(env, port):
    powershell(
        r"""
$ProgressPreference='SilentlyContinue'
function Get-FixtureTask {
  Get-ScheduledTask | Where-Object { $_.TaskPath -eq '\' -and $_.TaskName -eq $env:RW_CI_TASK }
}
$task=Get-FixtureTask
if ($null -ne $task) {
  Get-ScheduledTaskInfo -InputObject $task | Select-Object LastTaskResult | Format-List
  if ($task.State -in @('Running', 'Queued')) { Stop-ScheduledTask -InputObject $task }
  Unregister-ScheduledTask -InputObject $task -Confirm:$false
}
$timer=[System.Diagnostics.Stopwatch]::StartNew()
do {
  $listener=Get-NetTCPConnection | Where-Object {
    $_.LocalPort -eq [uint16]$env:RW_CI_PORT -and $_.State -eq 'Listen'
  }
  $fixtureTask=Get-FixtureTask
  if ($null -eq $listener -and $null -eq $fixtureTask) {
    Write-Output 'WINDOWS_SSH_CLEANUP no TCP listener at fixture port; task absent'
    exit 0
  }
  Start-Sleep -Milliseconds 150
} while ($timer.Elapsed.TotalSeconds -lt 5)
throw 'Fixture cleanup remains uncertain: listener or task still present'
""",
        env={**env, 'RW_CI_PORT': str(port)},
    )


def run_fixture(root, openssh):
    shell = default_shell()
    if Path(shell).name.casefold() != 'cmd.exe':
        raise RuntimeError(f'Expected the default cmd.exe shell in this fixture, observed {shell}')
    config, port = fixture(root, openssh)
    sshd = openssh / 'sshd.exe'
    checked([str(sshd), '-t', '-f', str(config)])
    log = root / 'sshd.log'
    task = 'ResearchWriter-CI-' + uuid.uuid4().hex
    env = {
        'RW_CI_TASK': task, 'RW_CI_SSHD': str(sshd),
        'RW_CI_ARGUMENTS': subprocess.list2cmdline(['-D', '-E', str(log), '-f', str(config)]),
    }
    primary_error = None
    try:
        powershell(
            "$action=New-ScheduledTaskAction -Execute $env:RW_CI_SSHD -Argument $env:RW_CI_ARGUMENTS\n"
            "$limits=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 6)\n"
            "Register-ScheduledTask -TaskName $env:RW_CI_TASK -Action $action -Settings $limits "
            "-User SYSTEM -RunLevel Highest | Out-Null\n"
            "Start-ScheduledTask -TaskName $env:RW_CI_TASK",
            env=env,
        )
        readiness(port)
        probe = checked([str(openssh / 'ssh.exe'), '-V'], capture_output=True)
        fingerprint = checked([str(openssh / 'ssh-keygen.exe'), '-lf', str(root / 'host_key.pub')],
                              capture_output=True)
        source_root = Path(__file__).resolve().parents[1]
        scripts = source_root / 'skills/research-writer/scripts'
        sources = [Path(__file__).resolve(), source_root / 'evals/windows_remote_checks.py',
                   *(scripts / name for name in ('windows_worker.py', 'windows_remote_tools.py',
                                                  'remote_tools.py', 'transport_common.py'))]
        print('WINDOWS_SSH_PROVENANCE ' + json.dumps({
            'github_sha': os.environ.get('GITHUB_SHA'), 'platform': platform.platform(),
            'python': sys.version, 'openssh': (probe.stdout + probe.stderr).decode('ascii', 'replace').strip(),
            'source_host_key': fingerprint.stdout.decode('ascii', 'replace').split()[1],
            'listener': '127.0.0.1', 'default_shell': shell, 'sources': {
                str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
            },
        }, sort_keys=True), flush=True)
        result = subprocess.run([sys.executable, str(source_root / 'evals/windows_remote_checks.py'), '--run-ssh'],
                                env={**os.environ, 'RW_WINSSH_FIXTURE': str(root),
                                     'PATH': str(openssh) + os.pathsep + os.environ['PATH']},
                                timeout=235)
        return result.returncode
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            cleanup_fixture(env, port)
        except Exception as exc:
            print(f'WINDOWS_SSH_CLEANUP uncertain: {exc}', file=sys.stderr, flush=True)
            if primary_error is None:
                raise
        finally:
            try:
                if log.exists():
                    with log.open('rb') as stream:
                        stream.seek(max(0, log.stat().st_size - 16 * 1024))
                        print('WINDOWS_SSHD_LOG\n' + stream.read().decode('utf-8', 'replace'), flush=True)
            except OSError as exc:
                print(f'WINDOWS_SSHD_LOG unavailable: {exc}', file=sys.stderr, flush=True)


def main():
    require_hosted_windows()
    openssh = find_openssh()
    with tempfile.TemporaryDirectory(prefix='rw-winssh-', dir=os.environ['RUNNER_TEMP']) as folder:
        return run_fixture(Path(folder).resolve(), openssh)


if __name__ == '__main__':
    raise SystemExit(main())
