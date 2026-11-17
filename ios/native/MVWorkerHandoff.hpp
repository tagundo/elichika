#pragma once
#import <Foundation/Foundation.h>

namespace elichika {
// Main waits for one bounded attempt on its serial worker, never readiness.
// dispatch_sync may run on its caller; dispatch_async guarantees a non-main
// attempt. The worker must never synchronously depend on the main queue.
inline void MVWorkerHandoff(dispatch_queue_t worker,dispatch_block_t attempt) {
    NSCAssert(NSThread.isMainThread,@"MV worker handoff belongs to main");
    dispatch_semaphore_t attempted=dispatch_semaphore_create(0);
    dispatch_async(worker, ^{
        @try { attempt(); }
        @finally { dispatch_semaphore_signal(attempted); }
    });
    dispatch_semaphore_wait(attempted,DISPATCH_TIME_FOREVER);
}
}
