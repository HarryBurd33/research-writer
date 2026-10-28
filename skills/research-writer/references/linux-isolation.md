# Optional Linux isolation and recovery

Use this route only for an authorized CPU task on an explicitly selected existing
Docker Linux/cgroup-v2 engine and existing compatible image. Ordinary research,
writing, retrieval and molecular tools require no Docker. The existing
[SSH controller](remote-execution.md) remains a separate trusted-task route.
The Linux client is not an automatic SSH launcher; to use it on another machine,
select and authorize that host, stage the approved package/data there, then run
this lifecycle on that host. Never migrate an uncertain job by resubmitting it.

## Boundary and device requirements

The selected engine, image and Linux kernel are trusted. Containers share a
kernel; this is not a claim of protection from a malicious Docker administrator,
image, host root or kernel escape. CPU only is accepted. GPU devices, rootless
engines, cgroup v1, remote Docker TCP/SSH contexts, Windows workers and schedulers
need separate implementation or acceptance. Supported limits must be observed;
missing controls cause failure rather than fallback to the trusted SSH mode.

Provide an existing Docker executable, explicit local context, engine identity
pin and existing immutable image ID. The tool never installs or starts a daemon,
pulls an image, accepts model terms or downloads a scientific model. Docker
Desktop and other clients may expose Linux engines, but only the documented
Linux CI configuration has actual enforcement acceptance. A profile or permission
flag records configuration; it does not authorize a host, task or data transfer.

The engine's cgroup-v2 memory and matching swap limit, CPU quota, PID cap and
monotonic wall deadline bound execution. CPU quota bounds **rate**, not aggregate
CPU seconds. Work, temporary files, control state and shared memory use separately
bounded tmpfs filesystems. Tmpfs also consumes container memory, so allow headroom
for the task and Python supervisor. Image layers, daemon metadata, approved staged
inputs and host-side collection are outside the workload scratch-space cap.

The root filesystem is read-only and network mode is `none`. Only loopback is
available. Safe staged `/etc/hosts`, `/etc/hostname` and `/etc/resolv.conf` are
also bound read-only; Docker's generated versions otherwise need separate care.
Inputs and supervisor mounts are read-only, with no writable host bind, daemon
socket, credentials, GPU or host namespace exposed. Image-declared volumes are
rejected; entrypoint, user, working directory, logging, healthcheck and restart
policy are explicitly set. Default Docker seccomp remains enabled.

A root PID1 supervisor retains only capabilities needed to change task UID/GID,
read task artifacts and terminate namespace descendants. The task runs as
UID/GID65534 with no supplementary groups or capabilities and no-new-privileges.
Its control receipt is root-protected. Namespace cleanup also catches descendants
that create a new process session; cancellation never targets a saved host PID.
Use a compatible image containing Python 3.10+ at the selected absolute path and
the task's existing dependencies. Programs requiring a writable root filesystem,
network, privileged operations or unsupported assets need another explicit plan.

## Profile and manifest

Store profiles and job state outside the installed skill. Example profile:

```json
{
  "schema_version": 1,
  "docker_executable": "/usr/bin/docker",
  "context": "default",
  "expected_engine_id": null,
  "container_python": "/usr/local/bin/python3"
}
```

Run inspection first, then copy its actual engine identity into
`expected_engine_id` before preparing work. `null` permits inspection only.
The context must use a local `unix://` or `npipe://` endpoint; a remote daemon
cannot interpret local bind paths safely under this contract. Paths containing
commas or newlines are refused; ordinary spaces are supported. Do not publish a
personal profile, host identity, credentials or approved scientific input data.

Use a fresh 32-character lowercase hexadecimal job ID and an existing local
`sha256:` followed by a 64-character immutable image ID, obtained by inspecting the selected
engine's existing image. Mutable image tags are refused. Example manifest:

```json
{
  "schema_version": 1,
  "job_id": "0123456789abcdef0123456789abcdef",
  "image_id": "sha256:REPLACE_WITH_64_LOWERCASE_HEX_IMAGE_ID",
  "argv": ["/usr/local/bin/python3", "-c", "from pathlib import Path; Path('result.txt').write_text('control: zero')"],
  "inputs": [],
  "outputs": ["result.txt"],
  "required_device": "cpu",
  "resources": {
    "wall_seconds": 30,
    "retention_seconds": 120,
    "memory_bytes": 268435456,
    "cpu_millis": 1000,
    "pids": 64,
    "work_bytes": 33554432,
    "tmp_bytes": 8388608,
    "max_log_bytes": 65536,
    "max_output_bytes": 1048576
  }
}
```

The image placeholder is intentionally invalid until replaced. Each input record
has exactly `source`, `destination` and `sha256`; source is relative to the
manifest and destination relative to `/work`. Only explicitly named, normalized
relative regular files with verified hashes may be staged. Symlinks, hardlinks,
special files, traversal, configuration/credential paths, duplicate names and
file/directory overlaps are refused. Generated collection receipt/log names are
reserved. Inputs are capped at 8 MiB per file and 16 MiB total, with at most 32 files;
outputs 1–32 names and 16 MiB total maximum. No arbitrary archive extraction occurs.

All resource values are integers: wall 1–3600 seconds, retention 5–3600 seconds,
memory 64 MiB–8 GiB, CPU 100–16000 millis (1000 means one core of quota), PID limit 16–512,
work 1–256 MiB, temp 1–64 MiB, log 1 byte–1 MiB per stream, outputs 1 byte–16 MiB total.
Memory, work and temp byte budgets must be multiples of 1 MiB to avoid kernel
page rounding above the ceiling. Control tmpfs is 4 MiB and shared memory 1 MiB. Work and temp each
have 1024 inodes; control has 128, including directory entries. Choose sufficient work space for
inputs and memory for every tmpfs plus execution; these are explicit ceilings,
not a promise that an undersized task can finish.

## Lifecycle

Use new report paths for every invocation. The state directory and collection
destination must be new at preparation/publication; never overwrite another run.
Replace the placeholders below with the actual installed skill/project paths.

```sh
python PATH_TO_SKILL/scripts/linux_tools.py inspect --profile PROJECT/linux.json --report PROJECT/inspection.json
python PATH_TO_SKILL/scripts/linux_tools.py prepare --profile PROJECT/linux.json --manifest PROJECT/job.json --state PROJECT/job-state --allow-stage --report PROJECT/prepared.json
python PATH_TO_SKILL/scripts/linux_tools.py submit --state PROJECT/job-state --allow-execute --report PROJECT/submitted.json
python PATH_TO_SKILL/scripts/linux_tools.py status --state PROJECT/job-state --report PROJECT/status.json
python PATH_TO_SKILL/scripts/linux_tools.py recover --state PROJECT/job-state --report PROJECT/recovered.json
python PATH_TO_SKILL/scripts/linux_tools.py collect --state PROJECT/job-state --destination PROJECT/new-results --report PROJECT/collected.json
python PATH_TO_SKILL/scripts/linux_tools.py cancel --state PROJECT/job-state --allow-cancel --report PROJECT/cancelled.json
python PATH_TO_SKILL/scripts/linux_tools.py cleanup --state PROJECT/job-state --allow-remove --report PROJECT/removed.json
```

Preparation verifies inputs and stages the pinned controller without running the
task. Submission persists a permanent intent before creation. State binds the
selected engine, image, manifest, controller hash, random nonce and deterministic
container name; the full immutable container ID is recorded when recovered.
Stable OS locks release on client death while retaining the lock inode.

After an interrupted client, use `recover` on the **same state and engine**.
It inspects and validates the original object; it never creates, starts, restarts
or resubmits. If the create reply was lost, matching labels and the deterministic
name permit reconciling that original ID. A missing object after intent remains
uncertain. A created but unstarted object is not started by recovery. Changed
engine, object, nonce, image, manifest, controller or runtime configuration causes
refusal. Read-only Docker-exec queries can briefly fail during namespace cleanup;
retry status/recovery after inspecting the report, never submission.

Collection reads the root receipt and bounded declared files through `docker
exec`, validates names, sizes and hashes, then atomically publishes a new host
directory with `.collection.json`. It never uses `docker cp` for tmpfs. Failed,
cancelled and timed-out results retain honest partial/missing state. Exit 0 on a
stopped container is insufficient to call a scientific job successful. Cleanup
removes only the verified full container ID; it never deletes an arbitrary name.

## Retention and failure recovery

The supervisor survives host-client interruption and enforces the task deadline
without that client. After task completion it stays alive for the explicit finite
retention interval so outputs can be collected. **Collect before that interval
expires.** Temporary artifacts vanish when the container stops. Host reboot,
PID1 death, daemon failure or OOM can lose them earlier. Recovery reports lost or
unavailable artifacts rather than inventing a result or repeating the task.
Containers do not restart automatically. Stopped metadata may need explicit
cleanup. This release does not supply durable checkpointing or guarantee output
survival across host/controller death. A new job ID can duplicate scientific work;
resolve uncertainty about the original first.

Kernel enforcement evidence is distinct from scientific validation. A successful
control run proves only the stated lifecycle behavior for that configuration.
Predictions, simulations and embeddings still need suitable controls and task
specific validation. See the repository's phase-7 validation report for observed
platforms and unexecuted combinations.

## Primary interface references

The implementation is original MIT code. It uses Docker's documented CLI;
Docker, selected images and their components retain their own terms. See
[resource constraints](https://docs.docker.com/engine/containers/resource_constraints/),
[run options](https://docs.docker.com/reference/cli/docker/container/run/),
[tmpfs](https://docs.docker.com/engine/storage/tmpfs/),
[exec](https://docs.docker.com/reference/cli/docker/container/exec/) and
[copy limitations](https://docs.docker.com/reference/cli/docker/container/cp/).


## Durable application files (v0.12)

A newly prepared schema-2 job can explicitly declare a cooperative checkpoint
area. [Durable checkpoints](durable-checkpoints.md) capture its immutable published
files through read-only exec and commit them in a host-side store. Existing
schema-1 jobs remain unchanged. A checkpoint must be committed before the
container disappears; restoring it does not relaunch that job. The original
execution must be reconciled before preparing a permitted new continuation.
No writable host mount or automatic background watcher is added.
