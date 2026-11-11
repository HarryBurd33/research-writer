# Hosted platform acceptance harness

`.github/workflows/platform-acceptance.yml` is separate from the existing stable CI workflow. It runs on relevant pull requests/pushes to main or manual dispatch. Both jobs have 15-minute outer deadlines and use the repository's existing SHA-pinned checkout/setup-python actions, with `contents: read` and no persisted checkout credentials. No artifact-upload action or paid API is used.

Native Windows entrypoint: `python evals/run_platform_acceptance.py windows`. It requires Windows, runs the actual native worker cases and portable path controls, rejects missing cases and fails on any skip. A successful hosted run proves this local worker on that runner/source combination; it does not establish SSH-to-Windows bootstrap, authenticated transport or compatibility with a particular laptop.

Slurm entrypoint after the setup below:

```sh
RW_SLURM_LIVE=1 RW_SLURM_PROFILE=/absolute/owned/profile.json python evals/run_platform_acceptance.py slurm
```

The hosted Ubuntu 24.04 job installs native Ubuntu Slurm/slurmdbd/MySQL-plugin, MariaDB, munge and ACL packages, recording observed versions. It runs `setup_slurm_ci.py setup` as root only on a detected **GitHub-hosted ephemeral** runner. The helper refuses another OS, a self-hosted runner, an existing acceptance root or already-running Slurm services. It creates one localhost cluster/account/partition (`rwci`) and associates the unprivileged runner account. Its profile pins actual hostname/user and native command paths, and contains no password. The job root and exact selected interpreter are shared with the single local compute daemon. CPU topology is obtained from native `slurmd -C`; configured scheduler memory is 1 GiB with finite partition defaults/maximums, and wall limits cap at two minutes. Actual workload manifests further limit runtime and output.

Real `slurmdbd` uses a local MariaDB socket and a freshly generated password delivered on stdin and written only to its restricted configuration file. That password, SQL input and database configuration must not be printed or uploaded. The helper never relays command stderr from secret setup. It sets `AccountingStoreFlags=job_comment`; live reconciliation must observe actual preserved comments. Process tracking uses real cgroups with RAM/swap constraints and fails setup/runtime if runner capabilities cannot support them. This is a single local-node acceptance environment; it does not model a networked production cluster, cluster hardware performance, independent physical failure or hostile workloads.

Setup invocation (performed by the workflow only):

```sh
sudo --preserve-env=GITHUB_ACTIONS,RUNNER_ENVIRONMENT /absolute/python evals/setup_slurm_ci.py setup --user RUNNER_ACCOUNT --root NEW_ABSOLUTE_ROOT --profile NEW_ABSOLUTE_PROFILE
```

The live suite dispatches tiny real CPU jobs, induces loss of an actual sbatch reply, rejects duplicate submission, reconciles queue/accounting identity, checksummed collection, timeout and cancellation. `run_platform_acceptance.py` fails on skipped cases and prints the exact source hashes, Python/OS, GitHub candidate SHA and test counts. Runtime receipts remain in this owned root, and cleanup prints nonsecret per-job scheduler receipts into the CI log. It does not print daemon logs, DB configuration or environment. Do not interpret a green setup step, contract suite or mocked scheduler reply as live lifecycle acceptance.

An `always()` cleanup step requires the exact owner marker, cancels only this runner user's jobs in its owned `rwci` cluster, stops its three Slurm daemons, removes the disposable DB/user and secret configuration and stops MariaDB/munge. The hosted VM is discarded after the job. Interrupted setup/run or unavailable scheduler observations remain failures/uncertain outcomes; no new job dispatch is attempted to repair an ambiguous submission. Service-stop/setup failures are not hidden as successful acceptance. Cancelling the whole GitHub run can interrupt cleanup; the ephemeral VM teardown is the final containment boundary, not a production recovery procedure.

The harness also requires actual held-queue expiry observation, a fresh client after real controller restart, accounting-daemon outage preserving uncertainty/no retry, and cancellation of an actually started descendant before collection. It requires at least 13 Slurm methods with zero skips (8 contract, 2 base live and 3 additional live controls). These controls are ready to execute; their creation alone supplies no actual Windows or Slurm success evidence. All runtime gates remain pending until exact hosted logs are inspected.

Design sources: [Ubuntu 24.04 Slurm package](https://packages.ubuntu.com/noble/amd64/slurm-wlm), [Ubuntu slurmdbd dependencies](https://packages.ubuntu.com/noble/amd64/slurmdbd), [SchedMD accounting](https://slurm.schedmd.com/accounting.html), [slurm.conf](https://slurm.schedmd.com/slurm.conf.html), [slurmdbd.conf](https://slurm.schedmd.com/slurmdbd.conf.html). Ubuntu package versions are reported at runtime rather than assumed identical to current upstream documentation.

## Windows SSH acceptance

`.github/workflows/windows-ssh-acceptance.yml` adds a separate `windows-2025` job. It first requires the original 11 native worker methods, then calls `setup_windows_ssh_ci.py` for an isolated authenticated loopback fixture and 16 portable/native transport methods with no skips. The fixture checks that it is running on disposable GitHub-hosted Windows, pins the source host key, uses a private configuration and loopback-only port, and records runtime, source hashes, receipts and cleanup. It does not enable a user's persistent SSH service or change their firewall. Exact-run success must be inspected before claiming acceptance. Neither this fixture nor hosted CPU jobs prove a laptop connection, CUDA execution or independent backup.
