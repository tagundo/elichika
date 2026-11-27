#include "../CandidatePolicy.hpp"
#include <cassert>
int main() {
    using elichika::CandidateMode;
    assert(elichika::candidateMode(false,false,false,false)==CandidateMode::Standard);
    for (unsigned flags=0;flags<8;++flags) {
        const auto mode=elichika::candidateMode(true,flags&1,flags&2,flags&4);
        assert(mode==(flags==7 ? CandidateMode::ExperimentalArchivePending : CandidateMode::Rejected));
    }
    // A capability/config pin alone cannot turn a missing Info marker into
    // experimental mode; callers classify its presence as an inconsistent marker.
    assert(elichika::candidateMode(true,false,true,true)==CandidateMode::Rejected);
}
