# Verified SSH checkpoint backups

Use this optional route when the user requests a backup to an explicitly selected
existing trusted POSIX machine. Local research and checkpoints need no SSH.
First establish destination, permitted contents, transfer/temporary disk budget
and whether it is actually an independent failure domain. Different hostnames or
directories, including loopback, do not prove independence. Do not upload research
merely because a profile exists. The commands below perform data operations only;
saved notes and recovered artifacts never grant execution permission.

## Select the device and vault

The client needs Python with SQLite and system OpenSSH; the receiver needs a
compatible POSIX Python/SQLite and private local filesystem. No GPU, cloud account,
new SSH service or model download is required. Use separately provisioned trusted
SSH authentication and known-host entries. No password/key contents belong in the
JSON profile, skill or repository. The explicitly selected SSH config is trusted
executable policy: ProxyCommand/Match exec may run programs. The adapter uses batch
mode, strict host-key verification, no forwarding and quoted remote program argv.
It sends its bounded receiver/helper source over the authenticated connection;
it does not install a permanent worker or service.

Make a private profile outside the installed skill; substitute actual values:

```json
{
  "schema_version": 1,
  "ssh_alias": "existing-backup-host",
  "ssh_config": null,
  "remote_python": "/usr/bin/python3",
  "remote_root": "/absolute/private/backup-vault",
  "expected_hostname": "actual-hostname",
  "expected_user": "actual-user",
  "connect_timeout_seconds": 10,
  "vault_id": "0123456789abcdef0123456789abcdef",
  "max_backup_bytes": 67108864,
  "rpc_timeout_seconds": 120
}
```

`ssh_config: null` uses the independently provisioned default SSH configuration. For portable recovery, recreate the same alias with verified host keys on each client; an explicit config path is also supported but remains pinned in the intent.

Choose a fresh random 32-character lowercase hexadecimal vault ID and backup ID,
for example with `python -c "import uuid; print(uuid.uuid4().hex)"`. The shown ID is
an illustration. A remote root beneath a directory containing `SKILL.md` is refused; select a dedicated external location. The root must be a new dedicated private directory on the first
initialization; do not select an existing unrelated directory. The user and host
pins are mandatory. `max_backup_bytes` is an explicit whole-MiB ceiling from 1 to
64 MiB for the entire closed SQLite database, preserving all generations and its
released format1 policy. A larger local store is refused, even if its store policy
permits more. The JSON/base64 wire envelope is separately bounded at 96 MiB.
`rpc_timeout_seconds` is 5–300 seconds. Size checks bound supported payloads, not
all Python/SQLite memory overhead. Budget several copies plus a generation restore
and metadata; a free-space check is advisory because availability can change.

## Prepare, transfer and reconcile

Run the installed `scripts/backup_tools.py` with an actual interpreter and paths.
Every `--report` must be a new path outside the skill. Parent traversal (`..`) components and symlink paths are refused rather than normalized across protected locations. Transfer-state and fetch destinations require an existing current-user private parent (POSIX mode 0700); create that parent explicitly on the selected device. Commands use no default host,
store or destination:

```bash
python /absolute/skill/scripts/backup_tools.py init-remote --profile /absolute/profile.json --allow-transfer --report /absolute/init-report.json
python /absolute/skill/scripts/backup_tools.py prepare --profile /absolute/profile.json --store /absolute/local-store --backup-id 11111111111111111111111111111111 --state-dir /absolute/new-transfer-state --report /absolute/prepare-report.json
python /absolute/skill/scripts/backup_tools.py push --profile /absolute/profile.json --state-dir /absolute/new-transfer-state --allow-transfer --report /absolute/push-report.json
python /absolute/skill/scripts/backup_tools.py verify --profile /absolute/profile.json --state-dir /absolute/new-transfer-state --report /absolute/verify-report.json
```

Preparation uses SQLite's backup API, closes the consistent copy and records its
size/hash and pinned profile in private transfer state before uploading. The
source remains intact. Keep a separate authorized copy of the small transfer
intent needed for recovery; keeping it only beside the source leaves a recovery
gap if that device is lost. Do not publish private receipts in the public repo.
The source database and journals are never copied live as unrelated files.

Upload is one-shot for that state. A failed connection, timeout, flush or report
can leave a published backup with an uncertain outcome. Do not delete state or
repeat upload to guess what happened. Use `verify` to look up the same immutable
ID and expected hash. Verification downloads the closed bytes through a fresh
request, compares them to the intent, checks the SQLite schema/data and performs a
full data-only restore drill. It never submits a research job. An existing ID
with different content is an error; no previous backup is overwritten or pruned.
A missing backup requires explicit operator investigation before planning a new
transfer. Source and previous verified generations are retained. The per-backup byte cap is not a total vault quota; provision and monitor capacity separately. An interrupted receiver may leave a private staging directory, which never counts as a completed backup. Inspect and remove such data only through an explicitly authorized maintenance action after reconciling active transfers.

The receiver stages private files, verifies schema/policy, every generation and
payload hash, drills restoration, flushes and publishes with atomic no-replace
rename. It takes a stable OS lock. A failure after publication is different from a
failure before publication; a later byte verification does not retroactively prove
that a failed flush reached physical media. Verification claims describe observed
bytes, not a hardware attestation. Directory and SQLite flush semantics depend on
the platform, VFS, filesystem and device.

## Recovery drill and normal restore

```bash
python /absolute/skill/scripts/backup_tools.py fetch --profile /absolute/profile.json --state-dir /absolute/retained-transfer-state --destination /absolute/new-recovered-store --allow-restore --report /absolute/fetch-report.json
python /absolute/skill/scripts/checkpoint_tools.py list --store /absolute/new-recovered-store --report /absolute/list-report.json
python /absolute/skill/scripts/checkpoint_tools.py restore --store /absolute/new-recovered-store --checkpoint-id ACTUAL_32_HEX_ID --destination /absolute/new-restored-files --allow-restore --report /absolute/restore-report.json
```

Fetching needs the retained intent and independently provisioned connection,
but not the original source store or local staged database. Preserve the exact normalized profile values: the intent currently pins local config paths, alias and timeouts as well as destination identity. It rejects changed values; there is no implicit profile migration. Using the default SSH config (`null`) and the same alias permits independently provisioned client credentials without embedding a machine-specific config path. Explicit path remapping requires a future verified migration route. It creates a new
verified store and never overwrites a destination. Inspect restored bytes and
application requirements before deciding on any separately authorized continuation.
For a real off-device acceptance drill, make the original source unavailable,
fetch from the actual second machine, restore all required artifacts, compare
independent expected hashes and record destination/failure-domain evidence. Use
synthetic data for a destructive device-loss experiment; do not destroy real work.

## Limits and troubleshooting

- Only explicit per-backup transfer and verification; no automatic schedule,
  replication, deletion, distributed lock, cloud sync or background recovery.
- Receiver identity/configuration is trusted. Private directories are cooperative
  protection, not a sandbox against a malicious same-user process or administrator.
- SSH protects transport; at-rest encryption, credential/key recovery, independent
  failure domains, backup retention and operational monitoring are operator choices.
- Windows clients are tested where reported; this is not a Windows remote receiver.
  Unsupported atomic publication/flush primitives fail rather than claiming support.
- Injected ENOSPC/EIO/short-write/flush/publication faults, process interruption and
  loopback SSH do not certify actual hardware failure, physical power-loss survival,
  network/cloud filesystems or firmware. No content hash proves scientific validity
  or an application's multi-file logical consistency.

See [local checkpoints](durable-checkpoints.md), [device profiles](device-profiles.md)
and [testing](testing.md) for adjacent operations. SQLite documentation supplies
the [consistent backup API](https://www.sqlite.org/backup.html); the implementation
uses the installed Python SQLite library, not a bundled database engine.
