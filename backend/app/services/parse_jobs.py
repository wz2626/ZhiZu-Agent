"""Task-owned upload resources; waiter cancellation never ends a worker lease."""

import asyncio
import logging
from threading import BoundedSemaphore, Lock

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

logger = logging.getLogger(__name__)


def close_form(form):
    if form is None:
        return
    seen = set()
    for _, item in form.multi_items():
        if isinstance(item, UploadFile) and id(item.file) not in seen:
            seen.add(id(item.file))
            try:
                item.file.close()
            except Exception:
                logger.warning("contract_import_cleanup_failed")


class Lease:
    def __init__(self, runtime):
        self.runtime, self.lock, self.released = runtime, Lock(), False

    def release(self):
        with self.lock:
            if not self.released:
                self.released = True
                self.runtime.slots.release()


class ParseRuntime:
    def __init__(self, capacity=2):
        self.slots = BoundedSemaphore(capacity)
        self.jobs, self.lock = set(), Lock()

    def admit(self):
        return Lease(self) if self.slots.acquire(blocking=False) else None

    def start(self, form, lease, work):
        job = ParseJob(self, form, lease, work)
        coroutine, task = None, None
        try:
            # Register first. The coroutine cannot reach the worker until all
            # registration steps succeed and this gate has been opened.
            with self.lock:
                self.jobs.add(job)
            coroutine = job.run()
            task = asyncio.create_task(coroutine)
            job.task = task
            task.add_done_callback(job.task_done)
            job.accepted.set()
            return job
        except BaseException:
            # Transfer has not happened: the route remains the sole cleaner.
            # Suppress work and callback cleanup before cancelling a created task.
            with job.lock:
                job.cleaned = True
            if task is not None:
                task.cancel()
            elif coroutine is not None:
                coroutine.close()
            with self.lock:
                self.jobs.discard(job)
            raise


class ParseJob:
    def __init__(self, runtime, form, lease, work):
        self.runtime, self.form, self.lease, self.work = runtime, form, lease, work
        self.lock, self.started, self.cleaned = Lock(), False, False
        self.task = None
        self.accepted = asyncio.Event()

    def finish(self):
        # Called only after actual work, or atomically before it may start.
        with self.lock:
            if self.cleaned:
                return
            self.cleaned = True
        try:
            close_form(self.form)
        finally:
            self.lease.release()
            with self.runtime.lock:
                self.runtime.jobs.discard(self)

    def execute(self):
        with self.lock:
            if self.cleaned:
                return None
            self.started = True
        try:
            return self.work()
        finally:
            self.finish()

    async def run(self):
        await self.accepted.wait()
        return await run_in_threadpool(self.execute)

    def task_done(self, task):
        # A cancelled asyncio task is not evidence that its worker ended.
        with self.lock:
            if not self.started and not self.cleaned:
                self.cleaned = True
                cleanup = True
            else:
                cleanup = False
        if cleanup:
            try:
                close_form(self.form)
            finally:
                self.lease.release()
                with self.runtime.lock:
                    self.runtime.jobs.discard(self)
        if not task.cancelled():
            task.exception()  # Retrieve detached errors without logging payloads.


parse_runtime = ParseRuntime()
