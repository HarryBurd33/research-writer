# v0.12 durable checkpoint validation

Local checks executed 2026-10-28 on macOS arm64. Actual Linux execution is a
required hosted gate before adoption; the exact reviewed head, hosted outcomes,
managed installation and main verification are recorded in the release PR when
observed. Workflow definitions and compiled fixtures are not passing runs.

## Executed local evidence

- All 209 prior public methods pass, including actual selected RDKit/OpenMM,
  Open Babel, small ESM-2 CPU controls and six disposable loopback SSH cases.
- All 32 new checkpoint methods pass locally: transactional save/backup/restore,
  actual killed writers/hot-journal recovery, postcommit reply loss/idempotence,
  actual SQLITE_FULL rollback, reopened page ceilings, lock process death,
  corruption/schema/policy identity checks, path/alias limits and publication
  races. Three anchored-descriptor capture tests require POSIX dir_fd facilities
  and are explicitly skipped on Windows; that skip never establishes Linux support.
- Separate nonblind agent review passes 23/23 private methods at frozen source
  hashes. Its 34-case criteria were fixed before implementation inspection.
  These include actual SQLite failure controls and portable capture fixtures;
  mocked engine bindings are distinguished from actual Linux execution.
- Full copied-install self-check passes from an unrelated directory with
  checkpoints, core/retrieval and all selected molecular/conversion/protein
  controls. Metadata validation checks 40 files/76 internal links. The portable
  bundle is generated and checked after the source freeze.

The original v0.11 has no durable store/capture command. Its existing terminal
loss/isolation behavior is retained; this stage's intended benefit is committed
application data remaining usable after loss of the original container and
client state. It is not a claim of superior prose, general scientific performance,
an expert security audit or transparent process-memory continuation.

## Construction findings and repairs

Independent evaluation reproduced a live ancestor-directory replacement that
could make a path checked earlier read outside the generation. Capture now opens
every component relative to held directory descriptors with O_NOFOLLOW, reads
bounded regular files, reopens the marker through its held parent and verifies
identity/bytes. The original escape, equal-byte marker replacement and failed-
read descriptor-leak controls pass. No writable host bind or task pause is added.

Other repaired cases include schema validation that checked table names without
foreign-key constraints, policy metadata without its fingerprint, unbounded
corrupted SQL TEXT/inventory loading, aggregate source preflight, and portable
Windows device/stream/alias names. Valid-valued policy-body changes now fail its
hash; malicious owners rewriting all evidence remain outside authentication claims.
The installed-check fixture initially used macOS's /var symlink alias; resolving
its own temporary directory fixed that harness input without weakening path rules.
Private harness import/mock corrections are recorded separately from target fixes.

## Required actual Linux suite

Six mandatory methods run after the existing ten isolation methods in the
required Ubuntu Docker job. The runtime/image are selected explicitly and the
resolved immutable local image ID is recorded; production never pulls an image.
The new methods test live counter 5 capture, removal of the original container
and client state, backup after the original store is removed, fresh-process
verification, data-only restore and an explicit fresh job continuing 5 to 8. They
also test wrong hashes, symlink/hardlink/FIFO/directory links and existing matching
traversal targets; atomic marker changes with coherent accepted generations;
wrong engine/container/nonce, old/stopped/unapproved capture refusal; and a real
postcommit client exit followed by idempotent capture without resubmission.

Nominal durable fixtures use 256 MiB headroom so file validation is separate from
the unchanged 64 MiB enforcement/OOM controls. Actual Linux fixture execution is
unavailable on this Mac. The stable aggregate still requires every existing
matrix and the Linux job; no skip or historical pass substitutes for this head.

## Boundaries and next work

A completed commit depends on the host store surviving. SQLite EXTRA/fullfsync
requests do not prove every OS/VFS/device honors durable writes; Windows directory
flush semantics differ. Process-crash tests are distinct from power cycles.
Database page quota excludes rollback-journal and backup/restore storage.
Network/cloud-synced filesystems, distributed ownership, encryption, certified
erasure and off-device replication are unvalidated. Use a verified consistent
backup and a separately authorized transfer for another device.

Application logical/scientific consistency is declared, not proved by hashes.
Capture must finish before temporary data disappears; previously unsaved files
cannot be reconstructed after failure. Saved metadata does not transfer authority,
capture process memory or automatically execute a continuation. Production
external-host/GPU, rootless/cgroup-v1/remote-Docker, Windows-worker and scheduler
acceptance remain future work. The v0.11 historical early-stop cause remains
unconfirmed; this stage does not describe it as fixed.
