"""Bounded optional acceleration for the game's symmetric asset XOR stream.

This primitive owns no paths, database state or model objects. Small inputs and
installations without NumPy retain the scalar path. Callers still validate pack
headers, section sizes and keys before passing their own mutable byte buffer.
"""
from functools import lru_cache


_CRYPTO_BLOCK_SIZE = 65536
_CRYPTO_FAST_MIN_SIZE = _CRYPTO_BLOCK_SIZE


def decrypt_section_scalar(data, key0, key1, key2):
    """Independent scalar implementation, including signed int32 key handling."""
    k0 = key0 & 0xFFFFFFFF
    k1 = key1 & 0xFFFFFFFF
    k2 = key2 & 0xFFFFFFFF
    for i in range(len(data)):
        data[i] ^= ((k1 ^ k0 ^ k2) >> 24) & 0xFF
        k0 = (0x343fd * k0 + 0x269ec3) & 0xFFFFFFFF
        k1 = (0x343fd * k1 + 0x269ec3) & 0xFFFFFFFF
        k2 = (0x343fd * k2 + 0x269ec3) & 0xFFFFFFFF


@lru_cache(maxsize=1)
def _lcg_coefficients():
    """Universal F^i(x) = A[i]*x+C[i] for one immutable uint32 block."""
    import numpy as np
    multipliers = np.empty(_CRYPTO_BLOCK_SIZE, dtype=np.uint32)
    increments = np.empty(_CRYPTO_BLOCK_SIZE, dtype=np.uint32)
    multipliers[0], increments[0] = 1, 0
    count, jump_a, jump_c = 1, 0x343fd, 0x269ec3
    while count < _CRYPTO_BLOCK_SIZE:
        multipliers[count:2 * count] = multipliers[:count] * np.uint32(jump_a)
        increments[count:2 * count] = (increments[:count] * np.uint32(jump_a)
                                     + np.uint32(jump_c))
        count *= 2
        jump_c = (jump_c * (jump_a + 1)) & 0xffffffff
        jump_a = (jump_a * jump_a) & 0xffffffff
    return (np.frombuffer(multipliers.tobytes(), dtype=np.uint32),
            np.frombuffer(increments.tobytes(), dtype=np.uint32), jump_a, jump_c)


def crypt_section(data, key0, key1, key2):
    """XOR in place and return None; never retry a partially mutated buffer.

    Keep the scalar's high byte BEFORE the LCG step and modulo-2^32 key
    arithmetic. Only the bounded coefficient table is cached, never user bytes.
    Mutable sequences without a contiguous unsigned-byte buffer keep their
    existing scalar behavior instead of acquiring a new NumPy requirement.
    """
    if len(data) < _CRYPTO_FAST_MIN_SIZE:
        return decrypt_section_scalar(data, key0, key1, key2)
    try:
        buffer = memoryview(data)
    except TypeError:
        return decrypt_section_scalar(data, key0, key1, key2)
    if (buffer.readonly or buffer.ndim != 1 or buffer.itemsize != 1
            or buffer.format != "B" or not buffer.c_contiguous):
        return decrypt_section_scalar(data, key0, key1, key2)
    try:
        import numpy as np
    except ModuleNotFoundError as exc:
        if exc.name != "numpy":
            raise
        return decrypt_section_scalar(data, key0, key1, key2)
    multipliers, increments, jump_a, jump_c = _lcg_coefficients()
    keys = [int(key & 0xffffffff) for key in (key0, key1, key2)]
    for offset in range(0, len(data), _CRYPTO_BLOCK_SIZE):
        count = min(_CRYPTO_BLOCK_SIZE, len(data) - offset)
        factors, additions = multipliers[:count], increments[:count]
        stream = factors * np.uint32(keys[0])
        np.add(stream, additions, out=stream)
        if keys[1] != keys[2]:
            other = factors * np.uint32(keys[1])
            np.add(other, additions, out=other)
            np.bitwise_xor(stream, other, out=stream)
            np.multiply(factors, np.uint32(keys[2]), out=other)
            np.add(other, additions, out=other)
            np.bitwise_xor(stream, other, out=stream)
        np.right_shift(stream, 24, out=stream)
        view = np.frombuffer(data, dtype=np.uint8, count=count, offset=offset)
        np.bitwise_xor(view, stream.astype(np.uint8), out=view)
        if offset + count < len(data):
            keys = [(jump_a * key + jump_c) & 0xffffffff for key in keys]
