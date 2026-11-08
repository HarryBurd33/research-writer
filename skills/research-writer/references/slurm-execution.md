# Selected-host Slurm lifecycle (CPU)

`slurm_tools.py` is an explicit Slurm adapter run on a selected POSIX submission host. It does not provision a scheduler, SSH to a cluster, choose an account, acquire credentials or infer authorization. Native scheduler runtime acceptance remains pending until actual Slurm is exercised. Command-mock tests establish a bounded interface contract only.

Profiles use exactly these fields; replace every example with approved local values:

```json
{
  "schema_version": 1,
  "job_root": "/home/research/rw-jobs",
  "expected_hostname": "selected-login-host",
  "expected_user": "research",
  "commands": {
    "sbatch": "/usr/bin/sbatch",
    "squeue": "/usr/bin/squeue",
    "sacct": "/usr/bin/sacct",
    "scancel": "/usr/bin/scancel"
  },
  "partition": "approved-cpu",
  "account": "approved-account",
  "cluster": "approved-cluster",
  "queue_seconds": 120
}
```

No unknown profile fields or credentials are accepted. The commands must be explicitly selected installed absolute executables. Their selection is trust, not executable attestation. The host/user pins must match the running process. The dedicated job root must belong to the current account and must not be group/world writable. The submission host, Python interpreter, staged controller and root must also be accessible at the same absolute paths on the selected compute nodes. Configure native Slurm authentication separately. Only one explicit cluster, account and partition are accepted. This release accepts the original CPU-only v1 manifest and cooperative limits; it does not request GPU resources or guarantee memory/network isolation.

## CLI

Every command requires a new `--output` report path. Prepare requires a v1 manifest with input hashes and paths relative to its directory. Transfer, execution and cancellation each require their explicit flag in the CLI.

```sh
python slurm_tools.py inspect --profile cluster.json --output inspection.json
python slurm_tools.py prepare --profile cluster.json --manifest manifest.json --allow-transfer --output preparation.json
python slurm_tools.py submit --profile cluster.json --job-id JOB_HEX --allow-execute --output submission.json
python slurm_tools.py status --profile cluster.json --job-id JOB_HEX --output status.json
python slurm_tools.py recover --profile cluster.json --job-id JOB_HEX --output recovery.json
python slurm_tools.py collect --profile cluster.json --job-id JOB_HEX --destination NEW_DIRECTORY --output collection.json
python slurm_tools.py cancel --profile cluster.json --job-id JOB_HEX --allow-cancel --output cancellation.json
```

Preparation stages checksummed inputs, reviewed POSIX controller source and a fixed batch wrapper. Only validated immutable absolute interpreter/controller/job paths enter the shell wrapper through argument quoting; the workload is read as an argv array from the checked manifest. Native command calls use subprocess argv with no shell evaluation. `sbatch` gets explicit cluster/account/partition, threads, wall limit rounded up to minutes, `--no-requeue`, CPU environment isolation via the controller and a token `rw:JOB_HEX:MANIFEST_SHA256`. Scheduler stdout/stderr go to `/dev/null`; workload diagnostics are independently bounded in the job directory.

A persistent per-job OS lock serializes mutations. The durable submit marker is written before `sbatch`. Any lost/malformed reply or native-command timeout preserves uncertainty; repeating submit is refused, including after process restart. Status/recovery query `squeue` and `sacct` for the selected cluster and account owner and require one exact immutable comment token plus consistent numeric and submit-time identity. Both command replies must be available. Missing/duplicate/mismatched observations remain uncertain. A numeric ID by itself never grants cancellation authority. The adapter passes `--duplicates` to accounting and rejects changed submit identity rather than adopting a recycled/requeued job.

Accounting must retain job comments (`AccountingStoreFlags=job_comment`) and user/cluster/account data. Without that configuration, queue removal cannot become terminal proof. Native command replies have a 20-second/1-MiB stdout/64-KiB stderr bound; an exceeded mutation reply bound can leave the remote outcome uncertain. No blind retry is safe.

States distinguish prepared, queued, running, succeeded, failed, cancelled, timed_out and uncertain. `queue_deadline_exceeded: true` marks a queue budget overrun separately from runtime timeout. It is an observation requiring explicitly authorized cancel; status never silently cancels a job and there is no background watchdog. Slurm's whole-minute runtime limit backs up the controller's exact-second wall bound. `COMPLETED` requires scheduler exit `0:0`, successful worker checkpoint and present matching declared artifacts before accepted success. Workload return code remains in its worker checkpoint even if the wrapper itself exits zero. Scheduler terminal cancellation/failure may lack a final worker checkpoint; explicit collection then makes a bounded, confined postmortem artifact index after scheduler terminal proof and marks partial results. Successful collection requires a fresh destination and verified hashes; it does not overwrite an existing directory.

## Actual acceptance gate

Portable command contract checks: `python evals/slurm_checks.py`. Two real-scheduler tests skip unless both `RW_SLURM_LIVE=1` and `RW_SLURM_PROFILE=/absolute/approved/profile.json` are explicitly provided. That opt-in executes tiny CPU jobs, preserves immutable job evidence under the selected root, induces loss of a real submission reply, confirms no second dispatch, reconciles from scheduler observations, verifies checksummed collection, tests timeout and cancels an owned job. It does not prove a production cluster, queue exhaustion, arbitrary workload performance or scheduler-level fault tolerance.

A disposable real Slurm CI job should be separately reviewed before use: pin the container/image or package hashes and license; configure one local controller, compute node and accounting service with job comments retained; create a dedicated unprivileged account and partition with finite CPU/memory/disk/time limits; verify Slurm versions and observed cluster identity; run the opt-in suite with a bounded outer CI timeout; archive source hashes, profile without secrets, raw job/worker receipts and accounting rows. Add a real held queue/deadline case, process-tree cancellation, deliberate controller/client restart, accounting outage and a reply lost after real `sbatch`. Tear down only the owned disposable environment after confirming all submitted jobs are terminal. No such environment was provisioned by the portable checks.

Sources: [SchedMD squeue](https://slurm.schedmd.com/squeue.html), [sacct](https://slurm.schedmd.com/sacct.html), [sbatch](https://slurm.schedmd.com/sbatch.html), [scancel](https://slurm.schedmd.com/scancel.html). Scheduler/version/site compatibility must be verified on the selected installation.
