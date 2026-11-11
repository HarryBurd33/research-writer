# Bounded Linux startup diagnostic

`evals/linux_startup_diagnostic.py` is an opt-in CI diagnostic for early supervisor failures. It uses the original first symlink-output fixture and captures stdout/stderr before container startup through foreground `docker run`. Production execution and ordinary detached acceptance remain unchanged. Foreground attachment changes timing, so non-reproduction does not establish a repair.

Each dispatch admits at most three fresh sequential fixtures, with a 90-second outer watchdog, fixed work/cleanup deadlines, two 8 KiB binary stream limits and a 1 MiB journal limit. It retains the original CPU, memory, PID, walltime and output limits. The full production container validator must establish identity and startup; a CID file alone is insufficient. Launch intent and validated identity are durable before later observations. Cleanup uses the validated immutable container ID, and an unknown mutation stops admission without retry.

The workflow requires successful diagnostic contract tests and image provisioning. Select only `linux_startup_diagnostic`; selecting both diagnostic inputs refuses both batches. A reviewed invocation against an exact task branch is:

```text
gh workflow run research-writer-ci.yml --repo HarryBurd33/research-writer --ref REVIEWED_BRANCH --raw-field linux_startup_diagnostic=true --raw-field linux_cpu_diagnostic=false
```

Replace `REVIEWED_BRANCH` only after verifying its exact reviewed commit and recording one dispatch intent. An uncertain CLI response requires run discovery, not another dispatch. The synthetic JSONL artifact is uploaded even after failure when available. Keep the artifact, job log, commit, run ID and attempt together. The ordinary Linux and durable-recovery tests run separately; a diagnostic pass cannot replace them.

Three accepted fixtures mean `not_reproduced_in_3`. Fewer fixtures, truncated capture, an unknown launch/removal or unverified cleanup produces a nonzero/incomplete result. A watchdog kill does not prove daemon cleanup. Retained raw stderr may identify a failing transition, but a production repair still needs causal evidence and regression verification.

The [single observed startup batch](https://github.com/HarryBurd33/research-writer/actions/runs/43008873517) completed with non-reproduction. It must not be repeated automatically or treated as authority for another diagnostic episode. A new investigation needs a distinct evidence-based hypothesis, bounded protocol and current task authorization. See [validation](capability-validation.md) for results and retained limitations.
