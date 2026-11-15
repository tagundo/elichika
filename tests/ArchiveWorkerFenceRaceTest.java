package com.tagundo.elichika;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Executes the production fence, without Android mocks or an Android build. */
public final class ArchiveWorkerFenceRaceTest {
    private static int passed;
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void waitFor(CountDownLatch latch) throws Exception {
        check(latch.await(2, TimeUnit.SECONDS), "Timed out waiting for test worker");
    }
    private static void joined(Thread thread) throws Exception {
        thread.join(2000);
        check(!thread.isAlive(), "Test thread did not reap");
    }
    private static void passed(String name) {
        passed++;
        System.out.println("PASS " + name);
    }
    public static void main(String[] args) throws Exception {
        cancellationRetainsFence();
        destroyedOwnerBlocksAllNewCommands();
        destroyedWaiterCannotPrepare();
        waiterRechecksNewOwner();
        oldCleanupCannotTouchNewOwner();
        completionIsExactlyOnce();
        interruptedWaiterCannotReleaseOwner();
        neverStartedWorkerCanReleaseReservation();
        System.out.println("{\"status\":\"PASS\",\"production_fence_race_cases\":" + passed + "}");
    }
    private static void cancellationRetainsFence() {
        ArchiveWorkerFence fence = new ArchiveWorkerFence();
        ArchiveWorkerFence.Lease lease = fence.tryAcquire();
        check(lease != null && fence.owns(lease), "Worker must own reservation before start");
        check(fence.cancel(lease) && fence.cancelActive(), "Repeated Stop signals cancellation");
        check(lease.cancellation.get() && fence.isCancelling(), "Cancellation remains visible");
        check(fence.isBusy() && fence.tryAcquire() == null, "Cancel must not release live workers");
        check(!fence.mayClearProgress(lease), "Cancel must not erase progress");
        check(fence.complete(lease) && !fence.isBusy(), "Reaped worker releases ownership");
        check(fence.mayClearProgress(lease), "Matching completion can clear its progress");
        passed("normal cancellation/completion retains ownership until reap");
    }
    private static void destroyedOwnerBlocksAllNewCommands() throws Exception {
        final ArchiveWorkerFence fence = new ArchiveWorkerFence();
        final ArchiveWorkerFence.Lease old = fence.tryAcquire();
        fence.cancel(old); // Service destruction does not destroy the process fence.
        final AtomicBoolean poolReaped = new AtomicBoolean(false);
        final AtomicInteger mutations = new AtomicInteger();
        final AtomicReference<Throwable> failure = new AtomicReference<>();
        final CountDownLatch entered = new CountDownLatch(4), done = new CountDownLatch(4);
        Thread[] waiters = new Thread[4];
        String[] commands = {"START", "RUN", "RESET", "PREPARE_INSTALL"};
        for (int i = 0; i < waiters.length; i++) {
            waiters[i] = new Thread(() -> {
                entered.countDown();
                try {
                    fence.awaitIdle();
                    check(poolReaped.get(), "Preparation/command overlapped old transfers");
                    mutations.incrementAndGet();
                } catch (Throwable error) { failure.compareAndSet(null, error); }
                finally { done.countDown(); }
            }, commands[i]);
            waiters[i].start();
        }
        waitFor(entered);
        check(!done.await(75, TimeUnit.MILLISECONDS) && mutations.get() == 0,
              "New service preparation must stay blocked while old workers live");
        // The lifecycle/main caller remained free to set cancel/check state.
        check(fence.cancelActive() && fence.isBusy(), "Main-side cancel cannot wait for worker completion");
        poolReaped.set(true);
        check(fence.complete(old), "Old worker finally owns the release");
        waitFor(done);
        for (Thread worker : waiters) joined(worker);
        if (failure.get() != null) throw new AssertionError(failure.get());
        check(mutations.get() == 4, "All queued command types resume only after reap");
        passed("forced destroy blocks new START/RUN/RESET/install preparation");
    }
    private static void destroyedWaiterCannotPrepare() throws Exception {
        final ArchiveWorkerFence fence = new ArchiveWorkerFence();
        ArchiveWorkerFence.Lease lease = fence.tryAcquire();
        final AtomicBoolean destroyed = new AtomicBoolean(false);
        final AtomicInteger writes = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1);
        Thread preparation = new Thread(() -> {
            entered.countDown();
            try { fence.awaitIdle(); if (!destroyed.get()) writes.incrementAndGet(); }
            catch (InterruptedException error) { throw new AssertionError(error); }
        });
        preparation.start();waitFor(entered);destroyed.set(true);fence.complete(lease);joined(preparation);
        check(writes.get() == 0, "Destroyed waiting service must recheck identity before payload writes");
        passed("destroyed replacement waiter never prepares payload");
    }
    private static void waiterRechecksNewOwner() throws Exception {
        final ArchiveWorkerFence fence = new ArchiveWorkerFence();
        ArchiveWorkerFence.Lease first = fence.tryAcquire();
        final CountDownLatch entered = new CountDownLatch(1), done = new CountDownLatch(1);
        Thread waiter = new Thread(() -> {
            entered.countDown();
            try { fence.awaitIdle();done.countDown(); }
            catch (InterruptedException error) { throw new AssertionError(error); }
        });
        waiter.start();waitFor(entered);
        ArchiveWorkerFence.Lease second;
        synchronized (fence) { // Force the legal completion/new-claim race before waiter reacquires monitor.
            fence.complete(first);second = fence.tryAcquire();
        }
        check(!done.await(75, TimeUnit.MILLISECONDS), "Waiter must loop and respect replacement owner");
        fence.complete(second);waitFor(done);joined(waiter);
        passed("preparation await loops across completion/new owner race");
    }
    private static void oldCleanupCannotTouchNewOwner() {
        ArchiveWorkerFence fence = new ArchiveWorkerFence();
        ArchiveWorkerFence.Lease old = fence.tryAcquire();fence.complete(old);
        ArchiveWorkerFence.Lease fresh = fence.tryAcquire();
        check(!fence.mayClearProgress(old), "Delayed old UI clear cannot erase fresh progress");
        check(!fence.cancel(old) && !fresh.cancellation.get(), "Old destroy cannot cancel fresh owner");
        check(!fence.complete(old) && fence.owns(fresh), "Old finally cannot release fresh owner");
        fence.complete(fresh);
        check(!fence.mayClearProgress(old) && fence.mayClearProgress(fresh),
              "Old clear remains stale even after newer completion");
        passed("delayed old UI/finally/destroy cannot touch newer ownership");
    }
    private static void completionIsExactlyOnce() throws Exception {
        final ArchiveWorkerFence fence = new ArchiveWorkerFence();
        final ArchiveWorkerFence.Lease lease = fence.tryAcquire();
        CountDownLatch go = new CountDownLatch(1);
        AtomicInteger releases = new AtomicInteger();
        Runnable finish = () -> {
            try { go.await();if (fence.complete(lease)) releases.incrementAndGet(); }
            catch (InterruptedException error) { throw new AssertionError(error); }
        };
        Thread first = new Thread(finish), second = new Thread(finish);
        first.start();second.start();go.countDown();joined(first);joined(second);
        check(releases.get() == 1, "Only owning worker can release once");
        fence.awaitFinished(lease);
        passed("concurrent duplicate completion releases exactly once");
    }
    private static void interruptedWaiterCannotReleaseOwner() throws Exception {
        final ArchiveWorkerFence fence = new ArchiveWorkerFence();
        ArchiveWorkerFence.Lease lease = fence.tryAcquire();
        AtomicBoolean interrupted = new AtomicBoolean();CountDownLatch entered = new CountDownLatch(1);
        Thread waiter = new Thread(() -> {
            entered.countDown();
            try { fence.awaitIdle(); }
            catch (InterruptedException expected) { interrupted.set(true); }
        });
        waiter.start();waitFor(entered);waiter.interrupt();joined(waiter);
        check(interrupted.get() && fence.owns(lease), "Waiter cancellation cannot release active pool");
        fence.complete(lease);
        passed("interrupted preparation waiter preserves active worker ownership");
    }
    private static void neverStartedWorkerCanReleaseReservation() throws Exception {
        ArchiveWorkerFence fence = new ArchiveWorkerFence();
        ArchiveWorkerFence.Lease lease = fence.tryAcquire();
        check(fence.complete(lease), "Thread.start failure must not strand reservation");
        fence.awaitIdle();
        check(fence.tryAcquire() != null, "Next command can claim after failed worker start");
        passed("failed worker start releases unused reservation");
    }
}
