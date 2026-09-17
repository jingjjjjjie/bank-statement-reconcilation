# Stopping a content review

`CodexReviewer` shares one `ProcessManager` across all parallel workers. Both
`codex login status` and `codex exec` use that manager. Stop sets its cancellation
event under the same lock used to create and register processes. Every running
owner wakes up, cleans up its process tree, and verifies exit. No new launch can
pass the cancellation check after Stop acquires that lock.

The manager exposes `run()`, `cancel()`, and `active_count`. Cancellation returns
promptly; each owner performs cleanup concurrently. The dashboard keeps showing
**Stopping review** until all process trees have verified exits and the review
worker has finished checkpointing and recording usage. A cleanup failure retains
the tracked tree, displays an error, and blocks a new review.

## Operating-system behavior

- **Windows 10 or later:** CreateProcessW receives a Job Object through
  `PROC_THREAD_ATTRIBUTE_JOB_LIST`, so assignment is atomic with process creation.
  Job descendants inherit containment, breakaway is not enabled, and closing the
  last job handle kills remaining members. Stop calls `TerminateJobObject` and
  checks `ActiveProcesses` plus the main process handle before closing handles.
  Windows job termination is immediate, not a graceful signal.
- **Linux/Docker:** Popen starts a new session. Cleanup sends SIGTERM to the
  process group, waits up to one second, then sends SIGKILL and waits up to five
  seconds. `/proc` verifies no executing group members remain; zombies have already
  exited. Children that deliberately create another session/group are outside
  this guarantee. Strong containment of such programs would require a delegated
  cgroup or separate container. The existing Docker init process reaps orphans.

The same cleanup runs after timeouts, exceptions, and normal parent exit, so a
parent cannot leave ordinary children behind. File-backed standard input/output
avoids blocking cancellation on a full or unread pipe. Only the review's owned
jobs/groups are signalled; unrelated Codex sessions are never searched or killed.

Each executed attempt's token audit record includes the main process ID, exit
code, and whether exit was verified. Cancelled requests do not become cached
successes; their reported token usage is retained, or marked unknown if absent.
Completed checkpoints remain available for resume. Local process exit cannot
confirm the exact time remote model computation ends or undo consumed tokens.

## Verification and references

Run the offline process tests on both Windows and Linux:

```console
python -m unittest tests.unit.test_process_manager tests.unit.test_codex_cancellation
```

They launch real synthetic process trees, including four simultaneous calls,
children surviving their parent, large unread input, Stop during launch, a hanging
login, timeouts, and SIGTERM-ignoring Linux processes. They also verify that an
unrelated process survives and interrupted model responses remain uncached.
Dashboard tests cover waiting for final writes and blocking restart after failure.

Implementation references:

- [Microsoft: creating a process directly in a job](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812)
- [Microsoft: process creation attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
- [Microsoft: Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Python: subprocess lifecycle and sessions](https://docs.python.org/3/library/subprocess.html)
