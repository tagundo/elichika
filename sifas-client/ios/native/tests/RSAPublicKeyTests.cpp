#include "../RSAPublicKey.hpp"
#include <cassert>
#include <string>
static std::vector<std::uint8_t> hex(const std::string &text) {
    std::vector<std::uint8_t> bytes;
    for (std::size_t i=0;i<text.size();i+=2) bytes.push_back(static_cast<std::uint8_t>(std::stoul(text.substr(i,2),nullptr,16)));
    return bytes;
}
int main() {
    // Actual non-secret publickey.pem in the pinned Elichika source payload.
    auto der=hex("30819f300d06092a864886f70d010101050003818d0030818902818100d6be908e406bd61206ae0abde591040e75ea0986bef3586f85e8ec1a851c7c267f9249e006e51babcfeba917e81551193a60d11bc0caae1b5f168590c9fb6ac9c0ab423f042d0786090245b5d5e0f9e9636f71c33fc673ce1fbd617247348b300987cc1585e50473fdd109e215f66a7c44554aa2bd575b8953c132c47322b2650203010001");
    std::vector<std::uint8_t> n,e;
    assert(elichika::parseRSAPublicKey(der.data(),der.size(),n,e));
    assert(n.size()==128 && n.front()==0xd6 && n.back()==0x65);
    assert((e==std::vector<std::uint8_t>{1,0,1}));
    auto wrongOID=der; wrongOID[16]^=1;
    assert(!elichika::parseRSAPublicKey(wrongOID.data(),wrongOID.size(),n,e));
    assert(!elichika::parseRSAPublicKey(der.data(),der.size()-1,n,e));
    auto trailing=der; trailing.push_back(0);
    assert(!elichika::parseRSAPublicKey(trailing.data(),trailing.size(),n,e));
    auto evenExponent=der; evenExponent.back()=2;
    assert(!elichika::parseRSAPublicKey(evenExponent.data(),evenExponent.size(),n,e));
}
