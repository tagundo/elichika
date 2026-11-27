#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>
namespace elichika {
struct DERView { const std::uint8_t *data; std::size_t size; };
inline bool derTake(DERView &input, std::uint8_t tag, DERView &value) {
    if (input.size<2 || input.data[0]!=tag) return false;
    std::size_t offset=2,length=input.data[1];
    if (length&0x80) {
        const std::size_t count=length&0x7f;
        if (!count || count>4 || input.size<2+count || input.data[2]==0) return false;
        length=0;
        for (std::size_t i=0;i<count;++i) length=(length<<8)|input.data[2+i];
        if (length<128) return false;
        offset+=count;
    }
    if (length>input.size-offset) return false;
    value={input.data+offset,length}; input={input.data+offset+length,input.size-offset-length}; return true;
}
inline bool positiveInteger(DERView input,std::vector<std::uint8_t> &output) {
    if (!input.size || input.data[0]&0x80) return false;
    if (input.size>1 && input.data[0]==0) {
        if (!(input.data[1]&0x80)) return false;
        ++input.data; --input.size;
    }
    output.assign(input.data,input.data+input.size); return true;
}
/* Accept exactly DER PKCS#1 or rsaEncryption SubjectPublicKeyInfo; no BER,
 * certificates, private keys, negative integers, or algorithm substitutions. */
inline bool parseRSAPublicKey(const std::uint8_t *bytes,std::size_t size,
                              std::vector<std::uint8_t> &modulus,std::vector<std::uint8_t> &exponent) {
    if (!bytes || size>4096) return false;
    DERView input{bytes,size},sequence{},key{};
    if (!derTake(input,0x30,sequence) || input.size) return false;
    if (sequence.size && sequence.data[0]==0x30) {
        DERView algorithm{},oid{},nullValue{},bits{};
        static const std::uint8_t rsaOID[]={0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x01};
        if (!derTake(sequence,0x30,algorithm) || !derTake(algorithm,0x06,oid) ||
            oid.size!=sizeof rsaOID || std::memcmp(oid.data,rsaOID,sizeof rsaOID)) return false;
        if (algorithm.size && (!derTake(algorithm,0x05,nullValue) || nullValue.size)) return false;
        if (algorithm.size || !derTake(sequence,0x03,bits) || sequence.size || !bits.size || bits.data[0]!=0) return false;
        DERView contained{bits.data+1,bits.size-1};
        if (!derTake(contained,0x30,key) || contained.size) return false;
    } else key=sequence;
    DERView n{},e{};
    if (!derTake(key,0x02,n) || !derTake(key,0x02,e) || key.size ||
        !positiveInteger(n,modulus) || !positiveInteger(e,exponent)) return false;
    if (modulus.size()<64 || modulus.size()>512 || !(modulus.back()&1) || exponent.empty() || exponent.size()>4) return false;
    std::uint64_t value=0; for (auto byte:exponent) value=(value<<8)|byte;
    return value>=3 && (value&1);
}
}
