"""Run model jobs on a bounded worker pool, checkpointing each result as it lands."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import nullcontext

#: Seconds between checks for finished jobs; short so Stop and new work are noticed quickly.
POLL_SECONDS = 0.2


def run_jobs(jobs, apply, workers, refill=None, acceptance=nullcontext):
    """Run a bounded number of model jobs and checkpoint every finished result."""
    if workers == 1 and refill is None:
        for job in jobs:
            with acceptance():
                pass
            result = job()
            with acceptance():
                apply(result)
        return
    pending, remaining, error = {}, iter(jobs), None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        def submit_one():
            """Keep only one queued job per available worker."""
            nonlocal remaining
            with acceptance():
                pass
            try:
                job = next(remaining)
            except StopIteration:
                if refill is None:
                    return False
                remaining = iter(refill())
                job = next(remaining, None)
                if job is None:
                    return False
            pending[pool.submit(job)] = None
            return True

        for _ in range(workers):
            if not submit_one():
                break
        while pending:
            if error is None:
                while len(pending) < workers and submit_one():
                    pass
            completed, _ = wait(pending, timeout=POLL_SECONDS, return_when=FIRST_COMPLETED)
            if not completed:
                continue
            future = next(iter(completed))
            del pending[future]
            try:
                result = future.result()
                with acceptance():
                    apply(result)
            except Exception as failure:
                if error is None:
                    error = failure
            if error is None:
                submit_one()
    if error is not None:
        raise error
