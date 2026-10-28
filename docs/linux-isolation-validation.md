# v0.11 Linux isolation and controller recovery validation

Local checks executed 2026-10-28 on macOS arm64. Actual Linux enforcement is a
required release gate; the hosted run, immutable head and final installed/main
identities are recorded in the release pull request when observed. A workflow
definition is not a passing run. This Mac has no configured Docker/Linux runtime.

## Executed local evidence

- All 179 prior public methods pass with applicable existing runtimes, including
  actual RDKit/OpenMM, Open Babel, small ESM-2 CPU controls and six disposable
  loopback SSH lifecycle tests. No user production host or GPU was selected.
- Four new legacy lock/recovery methods pass: actual process death releases the
  same retained lock inode, unsafe/old locks are refused, and stale recovery with
  a live stored PID cannot launch or signal anything or change job artifacts.
- All 25 new portable Linux-client methods pass. They exercise strict schemas,
  no automatic pull or execution during preparation, engine/image/object binding,
  permanent intent before uncertain submission, no-repeat recovery, loss honesty,
  bounded verified collection, reserved names, symlink refusal and atomic no-replace
  publication. These use controlled Docker responses, not actual Linux enforcement.
- Separate private independent tests cover the same contracts with fresh fixtures.
  Their frozen 26-case protocol includes seven actual Linux groups. Final counts,
  source hashes and hosted outcomes are recorded in the release review.
- Full copied-install self-check passes from an unrelated working directory with
  all selected molecular/conversion/protein controls. Metadata validates 38 files
  and 71 internal links. Portable-bundle consistency is checked after source freeze.

The first molecular harness invocation resolved the virtual-environment Python
symlink to the bare interpreter and failed missing-package checks. It was rerun
using the intended environment path; all actual controls passed. This was a test
invocation correction, with initial failures retained privately, and no production
or assertion change. Construction review also caught and repaired symlink error
reporting, publication races, nested input permissions and container-ID/name
reconciliation before the first hosted candidate.

Baseline v0.10 has no Linux executor. Under the same local interpreter, independent
legacy cases pass 1/3 before the update and 3/3 after it. This demonstrates the
specific legacy benefit, not security or writing superiority. The research workflow
and source access/semantic boundaries are preserved; this stage changes execution
lifecycle behavior rather than prose-generation methods.

## Required actual Linux suite

Ten mandatory methods run on a disposable Ubuntu Docker Linux/cgroup-v2 engine.
CI explicitly provisions an official Python image, records the resolved image
identity/digest, then passes its immutable local ID to the utility. The utility
itself never pulls. The suite fails rather than skips if its engine is unavailable.

It checks effective memory/swap/PID/CPU controls and actual memory/fork/CPU pressure;
read-only root/metadata, restricted interfaces and ENOSPC byte/inode exhaustion;
UID/GID 65534, no capabilities, no-new-privileges, control and supervisor-signal
denial; nested inputs and verified collection; a real client process exiting after
accepted submission before saving the container ID, repeated recovery and escaped
session cleanup; cancellation, log/output bounds and unsafe files; retention and
PID1 loss; and changed identity refusal. Disposable objects are cleaned finally.
The stable required aggregate includes this job and every earlier matrix.

## First hosted candidate and interface repair

The first actual Linux job (CI run 19, head 52a32ddd0ab20dcdffaa401d06de27259d636791)
failed at capability configuration comparison. Docker 28.0.4 reports normalized
`CAP_`-prefixed names; the checker expected unprefixed names. No Linux acceptance
was inferred from that failed run. The repair canonicalizes one documented
optional prefix and still requires exactly SETUID, SETGID, KILL and DAC_OVERRIDE
with drop ALL. Added negative controls reject extra, duplicate, malformed and
double-prefixed names. No resource, privilege or frozen acceptance bound changed.
See the release pull request for the fresh hosted outcome on the repaired head.

## Remaining boundaries

Only the tested Docker Linux/cgroup-v2 CPU configuration is an enforcement claim.
No external user machine, GPU, rootless/cgroup-v1 engine, remote Docker daemon,
Windows worker or scheduler is accepted by this release. Engine/image/kernel are
trusted. CPU quota bounds rate. Workload tmpfs limits do not bound host image,
daemon or client disk use. Outputs must be collected within finite retention;
OOM, PID1 failure, stop or host reboot can lose them. Recovery never reexecutes.
Legacy SSH retains cooperative trusted-task limits and cannot prove liveness from
a stale heartbeat or PID. Scientific performance and semantic truth remain
separate from lifecycle tests. Independent review is nonblind agent review, not
an expert security audit.
