package com.tagundo.elichika;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicBoolean;

/** Process-owned archive transfers survive Service destruction until reaped. */
final class ArchiveWorkerFence {
    static final class Lease {
        final AtomicBoolean cancellation = new AtomicBoolean(false);
        private final CountDownLatch finished = new CountDownLatch(1);
    }

    private Lease active;
    private Lease completed;

    synchronized Lease tryAcquire() {
        if (active != null) return null;
        active = new Lease();
        completed = null;
        return active;
    }

    synchronized boolean isBusy() {
        return active != null;
    }

    synchronized boolean isCancelling() {
        return active != null && active.cancellation.get();
    }

    synchronized boolean owns(Lease lease) {
        return active == lease;
    }

    synchronized boolean cancel(Lease lease) {
        if (active == null || active != lease) return false;
        active.cancellation.set(true);
        return true;
    }

    synchronized boolean cancelActive() {
        return active != null && cancel(active);
    }

    /** Call only after this worker has reaped its pool, or if it never started. */
    synchronized boolean complete(Lease lease) {
        if (active == null || active != lease) return false;
        active = null;
        completed = lease;
        lease.finished.countDown();
        return true;
    }

    /** Delayed old UI cleanup must not erase a newer operation's progress. */
    synchronized boolean mayClearProgress(Lease lease) {
        return active == null && completed == lease;
    }

    /** Preparation workers wait outside the monitor; lifecycle callbacks never wait. */
    void awaitIdle() throws InterruptedException {
        while (true) {
            final Lease observed;
            synchronized (this) {
                observed = active;
            }
            if (observed == null) return;
            observed.finished.await();
        }
    }

    void awaitFinished(Lease lease) throws InterruptedException {
        lease.finished.await();
    }
}
