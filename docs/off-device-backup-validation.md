# Verified SSH backup validation — v0.13.0

This release adds an optional SSH backup route; operational use requires an
explicit existing destination. Acceptance in this stage uses a disposable
loopback server selected by the user. A different process and authenticated SSH
connection are exercised; a different physical device is not.

## Protocol and scope

`backup_tools.py` prepares a whole consistent SQLite API backup, retains format1
and all generations, binds immutable bytes/logical inventory to a private intent,
and uploads once into a pinned private vault. The receiver verifies every stored
generation and restored payload before no-replace publication. Success requires a
fresh readback and client restore drill. Fetch works with retained intent and an
independently provisioned connection after source/staged data loss. Source data
and previous backups are never automatically deleted.

Commands, exact profile and explicit limits are in [usage](../skills/research-writer/references/off-device-backups.md).
The raw database cap is explicitly 1–64 whole MiB; the JSON envelope is at most
96 MiB. Ordinary research, CPU tools and local checkpoints require no remote host.
The receiver is POSIX; core client contracts are checked across the reported
platform matrix. Trusted SSH configuration and private filesystem ownership are
prerequisites, not a hostile-user isolation guarantee.

## Acceptance evidence

Observed on the development macOS arm64 client:

| Check | Result |
| --- | --- |
| New backup contracts | 31/31 passed; storage syscall faults are injected |
| Actual isolated SSH backup controls | 5/5 passed; source/staged-copy removal, empty payload, receiver termination during staging and after publication, host-key/identity refusal and lost initialization reply |
| Existing SQLite checkpoint contracts | 32/32 passed, including actual transaction FULL/hot-journal/process-crash controls |
| Prior offline regression suites | 14 suites passed; 235 methods, with 8 optional dependency methods explicitly skipped in that invocation |
| Copied installation from unrelated cwd | Passed selected checkpoints/backup drill, molecular, Open Babel conversion and small ESM-2 CPU controls; missing catalog negative control rejected |

Hosted CI requires the backup contracts in all six core OS/Python rows and the
five actual SSH groups on both Linux and macOS, alongside existing Linux isolation
and durable checkpoint acceptance and CPU scientific controls. The stable
`Research Writer checks` aggregate remains mandatory. Release promotion requires
all current-head jobs to pass; the pull request records their actual outcome.
Windows skips the 12 POSIX receiver cases explicitly while running the 19 portable
backup client contracts. It does not imply a Windows receiver. No physical second
device is represented by the loopback results.

The frozen checks require two-generation and empty-file recovery, schema1
preservation, immutable identity/conflict/no-overwrite, changed profile/host/user/
vault refusal, readback corruption/caps, pre/post-publication storage faults,
receiver interruption, uncertain reply reconciliation and prior-backup survival.
Independent review is a nonblind agent review, not an expert security audit.

## Independent review and repairs

A separate nonblind agent froze 24 criteria before candidate evaluation and ran
27 independent methods, all passing on candidate2. These include actual receiver
SIGKILL during staging and after publication, concurrent conflicting uploads,
SQLite payload corruption with a recomputed transport hash, syscall fault
injection and read-only recovery. This is not an expert security audit.

Candidate1 was rejected when an additional placement test showed that a report
path containing `alternate/../source` bypassed lexical containment and polluted
the source store. Candidate2 rejects parent traversal components in the shared
path guard before containment checks. Report/fetch alias cases now reject before
network activity or source modification. Earlier construction also repaired
orphan-stage naming and failed success-report publication; failure evidence was
retained. One initial SSH negative fixture expected ValueError where a correct
refusal raised TransportError; accepting either refusal changed no safe outcome.

## Remaining operational acceptance

No real second machine, removable medium or cloud storage was selected. Thus
independent failure-domain recovery is unexecuted. Injected ENOSPC/EIO/short-write,
flush and rename errors test this adapter's response; they do not reproduce all
SQLite VFS, kernel, firmware, physical power-loss or device-failure behavior.
Existing SQLite transaction crash/hot-journal/FULL tests remain separate controls.
An SSH reply or SHA256 is not physical media attestation. Storage flushes remain
OS/filesystem/device dependent. No network/cloud-sync filesystem, remote Windows
worker, encryption-at-rest, scheduler, automatic replication/pruning or distributed
writer capability is established. Large stores need a separate streaming route. Recovery retains the complete pinned profile and intent; local SSH path/alias/timeout changes need an explicit verified migration route that is not implemented. The default SSH config and same alias avoid a personal config path in portable profiles.

A later operator test should select and authenticate an independent destination,
choose authorized data and limits, retain intent separately, transfer and verify,
make the original source unavailable in a controlled fixture, fetch/restore on a
fresh device/process and independently compare expected bytes and metadata.
Research application consistency and scientific correctness need their own
validation. These tests do not provision a GPU or extend scientific-engine support.
