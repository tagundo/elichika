// Native macOS Foundation/GCD test; no Simulator, encoder or game required.
#import <Foundation/Foundation.h>
#include "MVExportClock.hpp"
#include "MVWorkerHandoff.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>

static void Require(bool condition,const char *message) {
    if (!condition) { std::fprintf(stderr,"MV worker handoff failed: %s\n",message); std::exit(1); }
}

int main() {
    @autoreleasepool {
        Require(NSThread.isMainThread,"test must begin on main");
        dispatch_queue_t worker=dispatch_queue_create("app.sifas.test.mv-worker-handoff",DISPATCH_QUEUE_SERIAL);
        __block int order=0;
        dispatch_async(worker, ^{ order=1; });
        elichika::MVWorkerHandoff(worker, ^{
            Require(!NSThread.isMainThread,"append attempt ran on main");
            Require(order==1,"handoff bypassed earlier serial worker work");
            order=2;
        });
        Require(order==2,"handoff returned before its attempt completed");

        constexpr uint64_t generation=7;
        elichika::MVExportClock clock(3,60,60,generation);
        uint64_t tick=99; int64_t capture=-1;
        Require(clock.grant(generation,tick,capture)&&tick==0&&capture==0,"initial grant changed");
        Require(clock.received(generation,capture),"initial frame was not received");

        NSMutableData *pixels=[NSMutableData dataWithLength:64];
        std::memset(pixels.mutableBytes,37,pixels.length);
        __block NSData *encoded=nil,*pending=nil;
        __block int64_t accepted=0;
        __block bool appended=false;
        elichika::MVWorkerHandoff(worker, ^{
            @autoreleasepool {
                Require(!NSThread.isMainThread,"ready append ran on main");
                encoded=[pixels copy]; ++accepted; appended=true;
            }
        });
        Require(appended&&accepted==1,"ready attempt did not finish before handoff returned");
        Require(clock.accepted(generation,0),"ready frame was not acknowledged on main");
        Require(clock.grant(generation,tick,capture)&&tick==1&&capture==1,"ready ACK did not permit the same-boundary next grant");
        std::memset(pixels.mutableBytes,91,pixels.length);
        Require(((const uint8_t *)encoded.bytes)[0]==37,"reusing capture storage changed the accepted copy");

        Require(clock.received(generation,capture),"second frame was not received");
        appended=false;
        elichika::MVWorkerHandoff(worker, ^{
            Require(!NSThread.isMainThread,"Retry attempt ran on main");
            pending=pixels; // Retry consumes no frame index or capture bytes.
        });
        Require(!appended&&accepted==1&&pending==pixels,"Retry consumed or replaced the pending frame");
        Require(!clock.grant(generation,tick,capture),"Retry advanced before encoder acceptance");

        __block bool acknowledged=false;
        elichika::MVExportClock *clockPointer=&clock;
        elichika::MVWorkerHandoff(worker, ^{
            @autoreleasepool {
                Require(!NSThread.isMainThread,"asynchronous Retry append ran on main");
                Require(pending==pixels&&((const uint8_t *)pending.bytes)[0]==91,"Retry lost its immutable frame");
                encoded=[pending copy]; pending=nil; ++accepted;
                dispatch_async(dispatch_get_main_queue(), ^{
                    Require(NSThread.isMainThread,"Retry acknowledgment left main");
                    Require(clockPointer->accepted(generation,1),"Retry acknowledgment changed frame order");
                    acknowledged=true;
                });
            }
        });
        Require(accepted==2&&!pending&&!acknowledged,"Retry append or main acknowledgment order changed");
        Require(!clock.grant(generation,tick,capture),"Retry advanced before its queued main ACK");
        NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:2];
        while (!acknowledged&&deadline.timeIntervalSinceNow>0)
            [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
        Require(acknowledged,"asynchronous main acknowledgment did not run");
        Require(clock.grant(generation,tick,capture)&&tick==2&&capture==2,"Retry ACK did not release the next contiguous frame");
        Require(clock.received(generation,capture),"final frame was not received");
        Require(clock.accepted(generation,2)&&clock.complete(),"final frame did not complete the clock");

        // Early returns still complete the handoff, including stopped/error
        // paths in a caller's one-attempt block. No readiness loop runs here.
        elichika::MVWorkerHandoff(worker, ^{ return; });
        __block bool failed=false;
        elichika::MVWorkerHandoff(worker, ^{ failed=true; return; });
        Require(failed,"failure return did not finish its handoff");
        std::puts("PASS_MV_WORKER_HANDOFF: non-main worker, serial order, immediate ACK, Retry ownership/async ACK, capture reuse, final frame, early return");
    }
    return 0;
}
