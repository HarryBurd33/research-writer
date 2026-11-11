# Windows jobs over SSH

The Windows SSH client runs explicitly authorized CPU workloads on a native Windows host. It uses an existing OpenSSH alias, the adjacent Windows worker, a dedicated job root, and an explicitly selected native Python executable. The [Windows worker guide](windows-worker.md) describes the manifest, resource limits, and Job Object lifecycle.

## Select and inspect a host

Create a local JSON profile. Replace the alias, executable, root, and identity with values for the authorized host. `ssh_config` is an optional path to an existing, trusted local OpenSSH config. `connect_timeout_seconds` defaults to 10 and accepts 1–30. Set the hostname and user after inspection, or start with independently verified values.

```json
{
  "schema_version": 1,
  "ssh_alias": "existing-win-host",
  "remote_python": "C:\\Python 3.12\\python.exe",
  "remote_root": "C:\\Research Jobs\\Worker",
  "expected_hostname": "WINHOST",
  "expected_user": "worker"
}
```

The alias must already authenticate with OpenSSH and verify the server key against an independently trusted entry. The client disables host-key updates, prompts, forwarding, and connection multiplexing. The chosen SSH config and its includes, proxies, and key sources are trusted local setup. Verify the host key out of band before adding it to that setup. Job operations require both the Windows hostname and user pins, which the client and worker each check. Use a dedicated directory on a local drive, owned by the selected account and protected by its ACLs. [Windows OpenSSH configuration](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration), [OpenSSH client configuration](https://man.openbsd.org/ssh_config.5).

From the skill directory, inspect the host and review the resulting identity and Python path. Use a fresh JSON output name each time.

```bash
python scripts/windows_remote_tools.py inspect --profile windows.json --output inspect.json
```

The remote command is a static Windows PowerShell 5.1 `-EncodedCommand` passed through the Windows OpenSSH default `cmd.exe` command shell. Its stdin carries a compact UTF-8 JSON header with the executable path and exact encoded body byte count, then a UTF-8 JSON body with the exact worker source and request. The executable is passed to .NET's process launcher without shell evaluation. Python inherits the SSH stdin handle after the bounded header and consumes exactly the declared body length; a truncated body fails before worker execution. The launcher relays separate stdout and stderr byte streams and suppresses PowerShell task-completion objects. The remote command requires native Windows PowerShell and Python. [PowerShell executable arguments](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1).

## Prepare, submit and reconcile

```bash
python scripts/windows_remote_tools.py prepare --profile windows.json --state-dir state --manifest manifest.json --allow-transfer --output prepared.json
python scripts/windows_remote_tools.py submit --profile windows.json --state-dir state --job-id JOB_ID --allow-execute --output submitted.json
python scripts/windows_remote_tools.py status --profile windows.json --state-dir state --job-id JOB_ID --output status.json
python scripts/windows_remote_tools.py recover --profile windows.json --state-dir state --job-id JOB_ID --output recovered.json
python scripts/windows_remote_tools.py collect --profile windows.json --state-dir state --job-id JOB_ID --destination new-results --output collected.json
python scripts/windows_remote_tools.py cancel --profile windows.json --state-dir state --job-id JOB_ID --allow-cancel --output cancel-requested.json
```

Replace `JOB_ID` with the manifest's 32-character lowercase hexadecimal identifier. Use only the operations needed for the job. Keep the same profile and local state directory throughout. Prepare validates the manifest and input hashes, then binds the profile, manifest, job and worker source hashes in local state. The root `.collection.json` name and its descendants are reserved for collection metadata, including case variants. Collection requires a terminal job, an absent destination, and an existing destination parent. It verifies declared paths, raw artifact and log hashes, aggregate artifact bytes, per-log limits, and the partial-result declaration before publishing the destination. The JSON receipt retains the returned log data.

The client fsyncs local state file data and atomically publishes the submission intent before opening the SSH subprocess. After an interrupted or unacknowledged call, retain local state and use `recover` on the same job. Recovery only reads the existing job and never starts it. A second submit is refused once intent was recorded. Cancel uses the worker's owned job marker. A stale controller can remain uncertain and requires reconciliation. The state guarantee covers ordinary client-process restart. Directory metadata and hardware power-loss persistence are outside that guarantee.

The static SSH bootstrap selects an internal detached-controller mode. It requests Windows `CREATE_BREAKAWAY_FROM_JOB` and `DETACHED_PROCESS` with private standard handles so the controller can outlive the SSH session. The host must permit that creation mode; denial retains the single submission intent and an uncertain outcome, with no fallback or retry. The workload still runs inside its controller-owned Job Object with the existing timeout, cancellation and descendant cleanup controls. Direct local worker invocation keeps its prior launch mode. See [Windows process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags).

The SSH RPC input and stdout caps are 32 MiB each and the stderr cap is 1 MiB. A transport failure or local timeout leaves a possibly dispatched remote operation uncertain. The local transport bounds captured bytes and its own subprocess lifetime. Job resource controls apply to trusted jobs under the selected account. Same-account code can access resources available to that account, so a dedicated root and account matter.

## Runtime evidence

`python evals/windows_remote_checks.py` exercises the portable client contracts. The Windows SSH acceptance workflow runs the existing native worker controls and a separate real OpenSSH loopback fixture on disposable GitHub-hosted Windows Server 2025. It records source hashes, the runner runtime, default shell, source host-key fingerprint, operation receipts, and cleanup. Use the workflow result for the exact source revision to determine native acceptance. An independent host or a user's Windows laptop needs its own compatibility check. [Windows Server OpenSSH availability](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse).
