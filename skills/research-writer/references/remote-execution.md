# Bounded SSH job lifecycle

The optional original `scripts/remote_tools.py` client uses existing OpenSSH
connections to a selected POSIX Python 3.10+ host. Linux/macOS remote workers are
supported as the initial target; a Windows client may use OpenSSH, but Windows
remote shells, schedulers and GPU execution are not established by these tools.
Nothing connects on skill load. A profile is configuration, not permission.

## Select and inspect a connection

Create a user-owned JSON profile outside this skill:

```json
{
  "schema_version": 1,
  "ssh_alias": "research-host",
  "ssh_config": null,
  "remote_python": "python3",
  "remote_root": "/home/researcher/research-writer-jobs",
  "expected_hostname": null,
  "expected_user": null,
  "connect_timeout_seconds": 10
}
```

Use an already configured trusted SSH alias. An explicit existing `ssh_config`
path may select the user's own configuration or an isolated test fixture.
Passwords, key bytes, tokens and arbitrary SSH options are rejected as unknown
profile fields. Authentication remains in existing SSH configuration/agents;
this helper neither scans nor copies credentials or changes `known_hosts`.
Host-key verification is strict, prompts/forwarding are disabled, and a POSIX
remote Python command is quoted separately from JSON request data on stdin.

```sh
python PATH_TO_SKILL/scripts/remote_tools.py inspect --profile PROJECT/remote.json --output PROJECT/inspection.json
```

Inspection executes the packaged bounded worker over SSH and reports actual
host/user/runtime/space. Set `expected_hostname` and `expected_user` from separately
verified inspection before any job operation. Strict SSH host keys and these
identity fields provide different checks; names alone are not authentication.
The remote root must be a dedicated absolute POSIX job directory owned/writable
by the selected user. No environment, model or package is automatically installed.

## Prepare an explicit task

A manifest contains exactly `schema_version: 1`, a new 32-character lower-case
hex `job_id`, trusted `argv` array, `inputs`, `outputs`, `resources` and
`required_device: "cpu"`. `inputs` records have `source`, `destination` and
lower-case `sha256`; source paths are relative to the manifest's directory.
Destination/output paths are confined POSIX relative file names, unique and
nonoverlapping. Inputs are at most 8 MiB each/16 MiB total, with at most 32 files.
Outputs are explicit (1–32 names), never an implicit directory upload. Symlinks,
traversal and obvious credential/configuration paths are refused. This is not a
universal content/secret scanner: review every selected input before transfer.

Resources require `wall_seconds` (1–3600), `max_output_bytes` (1–16 MiB total),
`max_log_bytes` (1–1 MiB) and `threads` (1–16). These are cooperative trusted-job
bounds (thread settings are environment hints, not a hard CPU-core quota),
not an OS security sandbox or a guarantee against malicious descendants.
A selected interpreter/executable and compatible engine/assets must already exist
on the host; CPU transport success does not validate an engine or GPU backend.

```sh
python PATH_TO_SKILL/scripts/remote_tools.py prepare --profile PROJECT/remote.json --manifest PROJECT/job.json --state-dir PROJECT/jobs --allow-transfer --output PROJECT/prepared.json
python PATH_TO_SKILL/scripts/remote_tools.py submit --profile PROJECT/remote.json --job-id JOB_ID --state-dir PROJECT/jobs --allow-execute --output PROJECT/submitted.json
```

`prepare` explicitly transfers only the manifest, selected hash-verified inputs
and packaged controller source. `submit` separately starts the bounded task.
The task argv is executed without a shell. Obtain current user authorization for
the target, data transfer and actual task before running either command; the
flags do not manufacture human authorization or accept paid-service spending.
The local state binds the profile, job and manifest hash and records attempts
before network mutation. It contains task metadata and paths, not key bytes or raw collected artifact/log
payloads. Collection receipts retain names and digests so large valid outputs do
not prevent later restart/status operations.
Do not edit/delete it to bypass a submission guard.

## Reconcile, collect and cancel

```sh
python PATH_TO_SKILL/scripts/remote_tools.py status --profile PROJECT/remote.json --job-id JOB_ID --state-dir PROJECT/jobs --output PROJECT/status.json
python PATH_TO_SKILL/scripts/remote_tools.py collect --profile PROJECT/remote.json --job-id JOB_ID --state-dir PROJECT/jobs --destination PROJECT/new-results --output PROJECT/collection.json
python PATH_TO_SKILL/scripts/remote_tools.py cancel --profile PROJECT/remote.json --job-id JOB_ID --state-dir PROJECT/jobs --allow-cancel --output PROJECT/cancel-request.json
```

Use a new report path each time; existing output is preserved. A lost or malformed
reply after a mutating attempt becomes `uncertain`, never automatic resubmission.
The same local job cannot be submitted a second time, including after restart.
`status` reconciles the existing remote identity/hash and never executes the task.
Local job exclusion uses OS file locks that release after client process death;
the durable submission intent remains and prevents a resend. Keep the lock file
inode in place rather than deleting/replacing it. An unresolved launch or missing
controller needs operator investigation, not a new launch or stale-PID takeover. Creating a different job while the old one
is uncertain can still duplicate scientific work; resolve the original first.

Collect requires a terminal state. It checks all returned names, byte limits and
hashes in a private stage before publishing to a new destination under an
exclusive collection lock. The completion metadata is `.collection.json`;
failed/timed-out/cancelled jobs keep their actual status and missing-output list,
never become successful merely because some files exist. A successful job cannot
omit expected artifacts. Existing results are not overwritten. Atomic publication
assumes normal cooperating writers and filesystem rename behavior, not protection
against an adversarial local filesystem actor.

Cancellation requests are consumed by the owning live controller, which manages
its own child process. The RPC never blindly signals a PID from stale JSON.
A running cancel acknowledgment is only a request: query status for the terminal
`cancelled` result. Disconnecting SSH does not establish that remote work stopped.
All states, errors and partial artifacts must remain visible in the research
record; a complete transport run does not establish scientific validity.
