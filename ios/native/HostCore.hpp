#pragma once
#include <cstdint>
#include <string>

namespace elichika {
/* Main-thread-owned policy, independent of UIKit, Python, Go and Unity. A new
 * backend generation never permits a stale result to release game startup. */
class HostCore {
public:
    std::uint64_t begin() {
        ++generation_; preparing_ = true; ready_ = false; failed_ = false;
        error_.clear(); return generation_;
    }
    bool capture(std::uintptr_t controller) {
        if (!controller || (controller_ && controller_ != controller)) {
            fail("The game startup controller changed."); return false;
        }
        controller_ = controller; return true;
    }
    bool report(std::uint64_t generation, bool ready, const std::string &error) {
        if (generation != generation_ || !preparing_ || failed_) return false;
        if (!error.empty()) { fail(error); return true; }
        ready_ = ready; return true;
    }
    void foreground(bool value) { foreground_ = value; }
    bool canStart() const {
        return controller_ && preparing_ && ready_ && foreground_ && !failed_ && !started_;
    }
    bool takeStart() {
        if (!canStart()) return false;
        started_ = true; return true;
    }
    void fail(const std::string &message) {
        failed_ = true; ready_ = false; error_ = message;
    }
    void stopped() { preparing_ = false; ready_ = false; }
    std::uint64_t generation() const { return generation_; }
    bool started() const { return started_; }
    bool ready() const { return ready_ && !failed_; }
    bool captured() const { return controller_ != 0; }
    bool failed() const { return failed_; }
    bool foreground() const { return foreground_; }
    const std::string &error() const { return error_; }
    const char *phase() const {
        if (failed_) return "error";
        if (!foreground_) return "background";
        if (started_) return ready_ ? "running" : "recovering";
        if (ready_) return "ready";
        return preparing_ ? "starting" : "idle";
    }
private:
    std::uint64_t generation_ = 0;
    std::uintptr_t controller_ = 0;
    bool preparing_ = false, ready_ = false, started_ = false;
    bool foreground_ = true, failed_ = false;
    std::string error_;
};
}
