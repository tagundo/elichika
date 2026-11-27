#pragma once
namespace elichika {
enum class CandidateMode { Standard, ExperimentalArchivePending, Rejected };
inline CandidateMode candidateMode(bool anyExperimentalMarker,bool signedInfoMatches,
                                   bool signedCapabilityMatches,bool archiveSourcePinMatches) {
    if (!anyExperimentalMarker) return CandidateMode::Standard;
    return signedInfoMatches && signedCapabilityMatches && archiveSourcePinMatches
        ? CandidateMode::ExperimentalArchivePending : CandidateMode::Rejected;
}
}
