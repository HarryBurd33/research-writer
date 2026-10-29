# Streaming and connection-profile migration validation — v0.14.0

This release extends the optional backup route with bounded binary transfer and
explicit migration of client connection settings. The original v0.13 JSON route,
SQLite format1 and writing/research contracts remain regression requirements.
User-selected acceptance uses disposable isolated loopback SSH, not an independent
physical device. See [usage](../skills/research-writer/references/streaming-backups.md).

The protocol bounds metadata, chunk reads/writes and whole-store bytes, verifies
exact length/EOF and hashes, and preserves immutable publication, one-shot upload,
read-only reconciliation and complete restoration drills. Disk spooling is explicit;
no constant total memory, disk-free transfer or partial-upload resume is claimed.
Migration preserves destination/data pins and old state, verifies via the new
connection and publishes separate read-only recovery state with lineage.

## Observed evidence

Observed on the macOS arm64 development client:

| Control | Observed result |
| --- | --- |
| New public stream/migration contracts | 20/20 passed, including three actual Python subprocess file-stdio controls |
| Actual isolated SSH | 7/7 passed: large backup, legacy/new intent-only migration, lost reply, receiver termination, deadline and host-key/identity refusal |
| Large SSH fixture | 73,506,816-byte valid SQLite store, five generations and zero-byte files; 147,013,632 bytes copied for upload and fresh readback |
| Transfer-loop measurement | Maximum requested database read 65,536 bytes; transfer-loop-only Python tracemalloc peak 131,810 bytes |
| Separate independent review | 27/27 methods passed, zero skips, against the frozen criteria; source/hash binding retained privately |
| Independent larger-than-64-MiB fixture | 73,515,008-byte, seven-generation store; 14,743 instrumented client database reads, maximum 1 MiB, 1,102,725,120 cumulative bytes across operations; whole-database C.regular reads forbidden |
| Previous public contracts | All 14 prior offline suites passed: 235 methods, 8 optional dependency skips; original 32 backup contracts passed |
| Copied installation | Selected checkpoints/stream preparation, molecular, Open Babel and small ESM-2 CPU controls passed from unrelated cwd; missing catalog negative control rejected |

The transfer-loop measurement excludes SQLite generation processing, restoration,
interpreter/runtime overhead and other command phases. It is not a whole-process
memory claim. A full 512 MiB physical database was not part of the executed fixtures;
512 MiB was a selected migration cap and its input boundaries were checked.

The baseline v0.13 JSON helper remains unchanged and refuses caps above 64 MiB or
an edited profile. The new route demonstrates the requested benefit through actual
larger transfer and verified changed-connection migration without relaxing pins.
Complete source inspection sufficed; no new binary dependency or upstream code was
copied. Separate review is nonblind agent review, not an expert security audit.

Before formal candidate1 evaluation, construction repaired default-umask database
permissions, missing-local-snapshot migration, dangling state aliases and metadata
bounds. The frozen criteria were unchanged. Candidate1 passed the local checks but failed actual Windows acceptance. Candidate2 is the current release candidate.

CI37 first exposed an invalid Windows test fixture: its remote root used a Windows
drive path for a POSIX receiver. The fixture-only repair retained all methods,
assertions and skips. CI38 then exposed a production false-positive change detector:
full timestamp metadata was compared across pathname and file-descriptor APIs.
Candidate2 compares complete metadata within each API before/after reading and
retains cross-API device, inode and size checks. Added positive metadata-variation
and negative mutation/replacement controls preserve rejection of real changes.
The exact Windows observations and final method counts remain a raw-log release
gate. [CPython 3.12.10 pathname handling](https://github.com/python/cpython/blob/v3.12.10/Modules/posixmodule.c#L2008)
and [descriptor metadata handling](https://github.com/python/cpython/blob/v3.12.10/Python/fileutils.c#L1026)
provide primary implementation context; no upstream code was copied.

Hosted gates remain all six core OS/Python rows, Linux/macOS actual SSH, prior Linux
isolation/durable controls, selected scientific controls and the stable Research
Writer checks aggregate. Windows raw summaries and explicit Bash fail-fast handling
must be inspected in addition to status. Promotion requires all current-head jobs;
the pull request records their actual result.

## Unexecuted operational acceptance

Real second-device/failure-domain recovery, physical power or device failure and
all SQLite VFS/firmware/filesystem faults remain unexecuted. Receiver storage must
be a trusted private POSIX local filesystem. No remote Windows receiver, encryption,
automatic replication/pruning/cleanup, destination relocation or new GPU/scheduler/
scientific-engine validation is established. Migration requires preserved expected
intent/profile values and separately provisioned authentication. Source loss without
that retained identity remains a recovery gap. User permissions are never imported
from saved state.
