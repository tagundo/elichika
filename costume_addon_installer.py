"""Costume addon installer for elichika (refactored).

기능은 원본 costume_addon_installer-2.py와 100% 동일하게 유지하면서
중복 코드를 데이터 테이블과 헬퍼 함수로 정리한 버전입니다.

구조:
  1. 데이터 테이블  - 캐릭터 이름 / 기본 썸네일 / member_model 의존성
  2. 헬퍼 함수      - 백업, zip 처리, 암호화, 해시 생성, DB 삽입
  3. 메인 흐름      - zip 선택 -> 추출/설정 exec -> 암호화 -> DB 등록

주의: 애드온 zip 안의 .txt 설정 파일은 원본과 동일하게 모듈 전역
네임스페이스에서 exec 되므로, 설정 변수(costume_file 등)는 모듈
전역 변수로 유지됩니다. (애드온 간 값이 이월되는 원본 동작 포함)
"""

import sqlite3
import os
import zipfile
import io
import platform
import random
import sys
import shutil
import json
import hashlib
import zlib
from datetime import datetime

# ============================================================
# 1. 데이터 테이블
# ============================================================

# 백업 대상 파일 목록
filelist = [
    "assets/db/gl/asset_a_en.db",
    "assets/db/gl/asset_i_en.db",
    "assets/db/gl/asset_a_ko.db",
    "assets/db/gl/asset_i_ko.db",
    "assets/db/gl/asset_a_zh.db",
    "assets/db/gl/asset_i_zh.db",
    "assets/db/gl/dictionary_en_k.db",
    "assets/db/gl/dictionary_ko_k.db",
    "assets/db/gl/dictionary_zh_k.db",
    "assets/db/gl/masterdata.db",
    "assets/db/jp/asset_a_ja.db",
    "assets/db/jp/asset_i_ja.db",
    "assets/db/jp/dictionary_ja_k.db",
    "assets/db/jp/masterdata.db",
    "serverdata.db",
    "userdata.db",
]

# 에셋 DB 등록 순서 (원본의 처리 순서 그대로)
ASSET_DB_PATHS = [
    "assets/db/jp/asset_a_ja.db",
    "assets/db/jp/asset_i_ja.db",
    "assets/db/gl/asset_a_en.db",
    "assets/db/gl/asset_i_en.db",
    "assets/db/gl/asset_a_ko.db",
    "assets/db/gl/asset_i_ko.db",
    "assets/db/gl/asset_a_zh.db",
    "assets/db/gl/asset_i_zh.db",
]

# 패키지 매핑 등록 순서 (원본은 GL 먼저, JP 나중)
PACKAGE_DB_PATHS = [
    "assets/db/gl/asset_a_en.db",
    "assets/db/gl/asset_i_en.db",
    "assets/db/gl/asset_a_ko.db",
    "assets/db/gl/asset_i_ko.db",
    "assets/db/gl/asset_a_zh.db",
    "assets/db/gl/asset_i_zh.db",
    "assets/db/jp/asset_a_ja.db",
    "assets/db/jp/asset_i_ja.db",
]

# 사전(코스튬 이름) DB: (경로, 사용할 이름 변수 키)
DICTIONARY_DBS = [
    ("assets/db/gl/dictionary_en_k.db", "en"),
    ("assets/db/gl/dictionary_ko_k.db", "ko"),
    ("assets/db/gl/dictionary_zh_k.db", "zh"),
    ("assets/db/jp/dictionary_ja_k.db", "ja"),
]

CHARACTER_NAMES = {1: 'Honoka Kousaka',
 2: 'Eli Ayase',
 3: 'Kotori Minami',
 4: 'Umi Sonoda',
 5: 'Rin Hoshizora',
 6: 'Maki Nishikino',
 7: 'Nozomi Tojo',
 8: 'Hanayo Koizumi',
 9: 'Nico Yazawa',
 101: 'Chika Takami',
 102: 'Riko Sakurauchi',
 103: 'Kanan Matsuura',
 104: 'Dia Kurosawa',
 105: 'You Watanabe',
 106: 'Yoshiko Tsushima',
 107: 'Hanamaru Kunikida',
 108: 'Mari Ohara',
 109: 'Ruby Kurosawa',
 201: 'Ayumu Uehara',
 202: 'Kasumi Nakasu',
 203: 'Shizuku Osaka',
 204: 'Karin Asaka',
 205: 'Ai Miyashita',
 206: 'Kanata Konoe',
 207: 'Setsuna Yuki',
 208: 'Emma Verde',
 209: 'Rina Tennoji',
 210: 'Shioriko Mifune',
 211: 'Mia Taylor',
 212: 'Lanzhu Zhong'}

DEFAULT_THUMBNAILS = {1: 'Y0',
 2: 'y{',
 3: 'q[',
 4: '~5',
 5: 'hE',
 6: 'r5',
 7: 'd>',
 8: 'uY',
 9: ';s',
 101: 'h\\',
 102: '(+',
 103: 'j{',
 104: '<_',
 105: 'a6',
 106: 'O_',
 107: '`8',
 108: 'fQ',
 109: "Y'",
 201: 'a}',
 202: 'E|',
 203: 'TO',
 204: 'TF',
 205: '4]',
 206: 'R)',
 207: ',',
 208: '7`',
 209: '-/',
 210: '[]Z',
 211: '5|[',
 212: '-C;'}

DEPENDENCIES = {1: [('face_or', 'C', '{#'),
     ('dep', 'C', 'Q9'),
     ('dep', 'C', 'aE'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§~+'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§M|')],
 2: [('face_or', 'C', '.]'),
     ('dep', 'C', '8C'),
     ('dep', 'C', 'k?'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§~+'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§M|')],
 3: [('face_or', 'C', 'g4'),
     ('dep', 'C', 'T1'),
     ('dep', 'C', 'v'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§~+'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§M|')],
 4: [('face_or', 'C', 'M!'),
     ('dep', 'C', '_|'),
     ('dep', 'C', 't$'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§M|'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§~+')],
 5: [('face_or', 'C', '!{'),
     ('dep', 'C', '?A'),
     ('dep', 'C', 'M_'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§~+'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§M|')],
 6: [('dep', 'C', '1Q'),
     ('face_or', 'C', 'YS'),
     ('dep', 'C', '~Y'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§M|'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§~+')],
 7: [('face_or', 'C', 'J9'),
     ('dep', 'C', 'L_'),
     ('dep', 'C', '}x'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§M|'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§~+')],
 8: [('dep', 'C', 'BX'),
     ('face_or', 'C', '[*'),
     ('dep', 'C', 'dR'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§M|'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§~+')],
 9: [('face_or', 'C', 'Z7'),
     ('dep', 'C', 'C{'),
     ('dep', 'C', '#s'),
     ('dep', 'C', '§?D#'),
     ('dep', 'C', '§n8#'),
     ('dep', 'C', '§~+'),
     ('dep', 'C', '§y7'),
     ('dep', 'C', '§j^'),
     ('dep', 'C', '§Vr'),
     ('dep', 'C', '§M|')],
 101: [('face_or', 'C', '5]'),
       ('dep', 'C', '85'),
       ('dep', 'C', 'MS'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')],
 102: [('face_or', 'C', 'Bz'),
       ('dep', 'C', 'F$'),
       ('dep', 'C', '0*'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 103: [('dep', 'C', "'x"),
       ('face_or', 'C', '(A'),
       ('dep', 'C', 't~'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')],
 104: [('face_or', 'C', '.q'),
       ('dep', 'C', 'Iu'),
       ('dep', 'C', 'x='),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 105: [('dep', 'C', 'iy'),
       ('face_or', 'C', 'jo'),
       ('dep', 'C', 'lR'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')],
 106: [('face_or', 'C', 'Wm'),
       ('dep', 'C', "Z'"),
       ('dep', 'C', 'di'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 107: [('dep', 'C', '2*'),
       ('dep', 'C', ';L'),
       ('face_or', 'C', 'Tv'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')],
 108: [('face_or', 'C', 'B*'),
       ('dep', 'C', '^5'),
       ('dep', 'C', '_v'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 109: [('face_or', 'C', 'p2'),
       ('dep', 'C', 'a|'),
       ('dep', 'C', 'U}'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 201: [('dep', 'C', ".'"),
       ('face_or', 'C', 'f%'),
       ('dep', 'C', 'sq'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')],
 202: [('face_or', 'C', '"{'),
       ('dep', 'C', '_K'),
       ('dep', 'C', 'uK'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')],
 203: [('face_or', 'C', '^g'),
       ('dep', 'C', 'bS'),
       ('dep', 'C', '#M'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 204: [('dep', 'C', '7,'),
       ('dep', 'C', 'Aa'),
       ('face_or', 'C', 'io'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')],
 205: [('face_or', 'C', '("'),
       ('dep', 'C', '1]'),
       ('dep', 'C', 'a+'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 206: [('dep', 'C', ')#'),
       ('face_or', 'C', 'LB'),
       ('dep', 'C', 'Si'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')],
 207: [('face_or', 'C', '8m'),
       ('dep', 'C', 'fl'),
       ('dep', 'C', '(Q'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 208: [('face_or', 'C', 'g_'),
       ('dep', 'C', 'dE'),
       ('dep', 'C', '28'),
       ('dep', 'C', '§?D#'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§j^'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 209: [('dep', 'C', 'ID'),
       ('dep', 'C', 'wS'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+'),
       ('face_or', 'R', 'Z$'),
       ('dep', 'R', 'xU'),
       ('dep', 'R', ';k'),
       ('dep', 'R', '§?D#'),
       ('dep', 'R', '§n8#'),
       ('dep', 'R', '§~+'),
       ('dep', 'R', '§y7'),
       ('dep', 'R', '§j^'),
       ('dep', 'R', '§Vr'),
       ('dep', 'R', '§M|')],
 210: [('face_or', 'C', '^/)'),
       ('dep', 'C', '$EZ'),
       ('dep', 'C', 'sgs'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 211: [('face_or', 'C', 'w";'),
       ('dep', 'C', '0W='),
       ('dep', 'C', 'Qp?'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§~+'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§M|')],
 212: [('dep', 'C', '4fS'),
       ('dep', 'C', '?l='),
       ('face_or', 'C', 'oq0'),
       ('dep', 'C', '§M|'),
       ('dep', 'C', '§Vr'),
       ('dep', 'C', '§n8#'),
       ('dep', 'C', '§y7'),
       ('dep', 'C', '§~+')]}

# DEPENDENCIES 형식:
#   ('dep',     target, value) -> 무조건 (target_path, value) 삽입
#   ('face_or', target, value) -> facedynamic 파일이 있으면 (costume_path, facedynamic_path) 삽입,
#                                 없으면 (target_path, value) 삽입
#   target: 'C' = costume_path, 'R' = rina_unmask_costume_path (리나 가면 해제 전용)


# ============================================================
# 1.5 유니티 에셋번들 플랫폼 감지 (Android / iOS)
# ============================================================
# 유니티 SerializedFile 메타데이터의 m_TargetPlatform 값으로 판별한다.
#   13 = Android, 9 = iOS(iPhone)
# UnityFS 번들은 블록이 LZ4/LZMA로 압축돼 있어, 외부 패키지 없이 동작하도록
# 순수 파이썬 LZ4 블록 디코더를 포함한다. 감지에 실패하면 None을 반환하고
# 설치 흐름은 사용자에게 플랫폼을 물어본다 (절대 크래시하지 않음).

import struct
import lzma

UNITY_PLATFORM_NAMES = {13: 'android', 9: 'ios'}

def _lz4_block_decompress(data, uncompressed_size):
    """LZ4 블록 포맷 디코더 (프레임 헤더 없음)."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n and len(out) < uncompressed_size:
        token = data[i]; i += 1
        # 리터럴
        lit_len = token >> 4
        if lit_len == 15:
            while True:
                b = data[i]; i += 1
                lit_len += b
                if b != 255:
                    break
        out += data[i:i + lit_len]
        i += lit_len
        if i >= n or len(out) >= uncompressed_size:
            break
        # 매치 (오프셋은 리틀엔디언 u16)
        offset = data[i] | (data[i + 1] << 8); i += 2
        match_len = token & 0xF
        if match_len == 15:
            while True:
                b = data[i]; i += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4
        start = len(out) - offset
        for k in range(match_len):
            out.append(out[start + k])
    return bytes(out)

def _lzma_raw_decompress(data, uncompressed_size):
    """유니티 번들의 LZMA 블록(5바이트 props + raw 스트림) 디코더."""
    props = data[0]
    lc = props % 9
    rem = props // 9
    lp = rem % 5
    pb = rem // 5
    dict_size = struct.unpack('<I', data[1:5])[0]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_LZMA1, "lc": lc, "lp": lp, "pb": pb, "dict_size": dict_size}])
    return dec.decompress(data[5:], max_length=uncompressed_size)

def _decompress_bundle_block(data, uncompressed_size, compression):
    if compression == 0:
        return data[:uncompressed_size]
    if compression == 1:
        return _lzma_raw_decompress(data, uncompressed_size)
    if compression in (2, 3):  # LZ4 / LZ4HC
        return _lz4_block_decompress(data, uncompressed_size)
    raise ValueError(f"unsupported block compression {compression}")

def _read_cstring(buf, pos):
    end = buf.index(b'\x00', pos)
    return buf[pos:end], end + 1

def _platform_from_serialized(buf):
    """SerializedFile 헤더/메타데이터에서 m_TargetPlatform을 읽는다."""
    if len(buf) < 24:
        return None
    metadata_size, file_size, version, data_offset = struct.unpack_from('>IIII', buf, 0)
    if not (9 <= version <= 99):
        return None  # 구버전/비정상 헤더는 판별 포기
    pos = 16
    endianess = buf[pos]
    pos += 4  # endianess(1) + reserved(3)
    if version >= 22:
        pos += 4 + 8 + 8 + 8  # metadataSize(u32) + fileSize(i64) + dataOffset(i64) + unknown(i64)
    _, pos = _read_cstring(buf, pos)            # 유니티 버전 문자열
    fmt = '>i' if endianess else '<i'
    target_platform = struct.unpack_from(fmt, buf, pos)[0]
    return UNITY_PLATFORM_NAMES.get(target_platform)

def _platform_from_unityfs(f):
    """UnityFS 번들에서 첫 노드(SerializedFile)의 플랫폼을 읽는다."""
    header = f.read(8)
    if header[:7] != b'UnityFS':
        return None
    f.seek(7 + 1)  # 시그니처 + 널
    bundle_version = struct.unpack('>I', f.read(4))[0]
    _, _ = _read_cstring_file(f), _read_cstring_file(f)  # player/engine 버전
    total_size, comp_info_size, uncomp_info_size, flags = struct.unpack('>qIII', f.read(20))
    if bundle_version >= 7:
        pos = f.tell()
        f.seek((pos + 15) // 16 * 16)
    if flags & 0x80:  # blocksInfo가 파일 끝에 있음
        data_start = f.tell()
        f.seek(-comp_info_size, 2)
        blocks_info_raw = f.read(comp_info_size)
        f.seek(data_start)
    else:
        blocks_info_raw = f.read(comp_info_size)
    blocks_info = _decompress_bundle_block(blocks_info_raw, uncomp_info_size, flags & 0x3F)

    pos = 16  # uncompressedDataHash
    block_count = struct.unpack_from('>i', blocks_info, pos)[0]; pos += 4
    blocks = []
    for _ in range(block_count):
        u_size, c_size, b_flags = struct.unpack_from('>IIH', blocks_info, pos); pos += 10
        blocks.append((u_size, c_size, b_flags & 0x3F))
    node_count = struct.unpack_from('>i', blocks_info, pos)[0]; pos += 4
    nodes = []
    for _ in range(node_count):
        offset, size, n_flags = struct.unpack_from('>qqI', blocks_info, pos); pos += 20
        _, pos = _read_cstring(blocks_info, pos)
        nodes.append((offset, size))
    if not nodes:
        return None
    first_offset = min(n[0] for n in nodes)

    # 첫 노드 헤더를 읽을 만큼만 블록을 순차 해제
    needed = first_offset + 4096
    stream = bytearray()
    for u_size, c_size, b_comp in blocks:
        stream += _decompress_bundle_block(f.read(c_size), u_size, b_comp)
        if len(stream) >= needed:
            break
    return _platform_from_serialized(bytes(stream[first_offset:first_offset + 4096]))

def _read_cstring_file(f):
    out = bytearray()
    while True:
        b = f.read(1)
        if not b or b == b'\x00':
            return bytes(out)
        out += b

def detect_unity_platform(path):
    """유니티 파일의 타깃 플랫폼('android'/'ios')을 반환. 실패 시 None."""
    try:
        with open(path, 'rb') as f:
            head = f.read(8)
            f.seek(0)
            if head[:7] == b'UnityFS':
                return _platform_from_unityfs(f)
            # UnityFS 래퍼 없는 단독 SerializedFile일 수도 있음
            return _platform_from_serialized(f.read(4096))
    except Exception:
        return None

def filter_dbs_by_platform(paths, target):
    """플랫폼에 맞는 에셋 DB 경로만 남긴다. target이 None이면 전체(기존 동작)."""
    if target == 'android':
        return [p for p in paths if '/asset_a_' in p]
    if target == 'ios':
        return [p for p in paths if '/asset_i_' in p]
    return list(paths)

def db_platform(db_path):
    """에셋 DB 경로에서 플랫폼을 알아낸다 ('android' / 'ios')."""
    return 'ios' if '/asset_i_' in db_path else 'android'

def detect_addon_platform(file_labels):
    """애드온의 유니티 파일들을 검사해 플랫폼을 결정한다.

    file_labels: [(경로, 라벨), ...]  (첫 항목 = 코스튬 본체, 결정 기준)
    반환: 'android' / 'ios' / None(판별 실패)
    """
    detected = []
    for fpath, label in file_labels:
        plat = detect_unity_platform(fpath)
        detected.append((label, plat))
        shown = plat if plat else "unknown"
        print(f"  [{label}] platform: {shown}")
    main_platform = detected[0][1]
    known = [p for _, p in detected if p]
    if known and any(p != known[0] for p in known):
        print("WARNING: mixed platforms inside this addon! "
              f"Using costume file's platform ({main_platform}).")
    return main_platform


# ============================================================
# 2. 헬퍼 함수
# ============================================================

def backup_operate(files):
    """디렉토리 구조를 유지하며 백업 폴더에 DB 파일들을 복사한다."""
    backup_folder = datetime.now().strftime("backup_db/%Y-%m-%d_%H-%M-%S")
    os.makedirs(backup_folder)
    for file_path in files:
        relative_path = os.path.relpath(file_path, start=".")
        dest_path = os.path.join(backup_folder, relative_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy(file_path, dest_path)
    print("Backup completed successfully.")


def is_termux():
    return 'com.termux' in os.getenv('PREFIX', '')


def clear_terminal():
    system = platform.system()
    if system == 'Windows':
        os.system('cls')
    elif system == 'Linux' or system == 'Darwin':
        os.system('clear')


def generate_crc32(path):
    """파일의 CRC32 체크섬을 8자리 16진수 문자열로 반환한다."""
    with open(path, 'rb') as f:
        file_data = f.read()
    return f"{zlib.crc32(file_data) & 0xFFFFFFFF:08x}"


def manipulate_file(data, keys_0, keys_1, keys_2):
    """게임 클라이언트가 읽을 수 있도록 XOR 스트림 암호화를 적용한다 (in-place)."""
    for i in range(len(data)):
        data[i] = data[i] ^ ((keys_1 ^ keys_0 ^ keys_2) >> 24 & 0xFF)
        keys_0 = (0x343fd * keys_0 + 0x269ec3) & 0xFFFFFFFF
        keys_1 = (0x343fd * keys_1 + 0x269ec3) & 0xFFFFFFFF
        keys_2 = (0x343fd * keys_2 + 0x269ec3) & 0xFFFFFFFF


def generate_unique_costume_id(cursor):
    """m_suit에 없는 무작위 코스튬 ID(0~999999999)를 생성한다."""
    while True:
        new_id = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_suit WHERE id = ?;", (new_id,))
        if cursor.fetchone()[0] == 0:
            return new_id


def generate_unique_trade_id(cursor, channel_exchange_trade):
    """m_trade_product에 없는 무작위 교환소 ID 꼬리(0~999)를 생성한다."""
    while True:
        new_id = random.randint(0, 999)
        formatted_id = f"{channel_exchange_trade}{new_id:03}"
        cursor.execute("SELECT COUNT(*) FROM main.m_trade_product WHERE id = ?;", (formatted_id,))
        if cursor.fetchone()[0] == 0:
            return new_id


def unique_asset_path(cursor, table):
    """지정 테이블(member_model 또는 texture)에 없는 무작위 asset_path를 생성한다."""
    while True:
        new_hash = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute(f"SELECT COUNT(*) FROM main.{table} WHERE asset_path = ?;", (new_hash,))
        if cursor.fetchone()[0] == 0:
            return new_hash


def parse_selection(user_input, max_n):
    """번호 선택 문자열을 인덱스 리스트(1-base)로 파싱한다.

    지원 형식:
      - "all" / "a"      : 전체 선택
      - "3"              : 단일 번호
      - "1,4,7"          : 쉼표 구분 다중 선택
      - "4-8"            : 범위 (4,5,6,7,8)
      - "1, 4-8, 14-23"  : 혼합 (공백 허용)
      - "8-4"            : 역순 범위도 4-8로 해석

    잘못된 토큰이나 범위를 벗어난 번호가 있으면 ValueError를 던진다.
    중복 선택은 처음 등장한 순서를 유지하며 제거된다.
    """
    text = user_input.strip().lower()
    if text in ('all', 'a', '*'):
        return list(range(1, max_n + 1))

    chosen = []
    seen = set()
    for token in text.split(','):
        token = token.strip()
        if not token:
            continue
        if '-' in token:
            parts = token.split('-')
            if len(parts) != 2 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
                raise ValueError(f"Invalid range: '{token}'")
            start, end = int(parts[0]), int(parts[1])
            if start > end:
                start, end = end, start
            if start < 1 or end > max_n:
                raise ValueError(f"Range out of bounds (1-{max_n}): '{token}'")
            nums = range(start, end + 1)
        else:
            if not token.isdigit():
                raise ValueError(f"Invalid number: '{token}'")
            num = int(token)
            if not (1 <= num <= max_n):
                raise ValueError(f"Number out of bounds (1-{max_n}): '{token}'")
            nums = (num,)
        for n in nums:
            if n not in seen:
                seen.add(n)
                chosen.append(n)

    if not chosen:
        raise ValueError("Nothing selected")
    return chosen


def open_and_check_zip(file_path):
    """zip 내용을 나열하고, 중첩 zip이면 .nested 폴더에 풀고,
    아니면 batch_proccess_list에 추가한다."""
    global is_nested
    try:
        is_nested = False
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            print(f"Contents of '{file_path}':")
            for file_name in zip_ref.namelist():
                print(f" - {file_name}")
                if file_name.endswith('.zip'):
                    print(f"  -> Found nested zip file: {file_name}")
                    is_nested = True
            if is_nested:
                extracted_path = os.path.splitext(os.path.basename(file_path))[0]
                nested_path = os.path.join("assets", "package", ".nested", extracted_path)
                os.makedirs(nested_path, exist_ok=True)
                zip_ref.extractall(nested_path)
            else:
                batch_proccess_list.append(file_path)
    except zipfile.BadZipFile:
        print(f"Error: '{file_path}' is not a valid zip file.")
    except Exception as e:
        print(f"An error occurred: {e}")


def _pack_output_dir():
    """Directory where encrypted packs are written.

    - Termux: straight into the server's packs cache dir (config.json
      'cdn_cache_dir', or the default when unset/empty). The server serves
      /static/<name> from there directly, skipping both the static->cache
      migration and the slow first-load index rebuild over the (huge,
      FUSE-backed) packs dir - the ~8s stall on Android.
    - PC / macOS: the elichika static/ folder. It sits right next to the server
      (easy to find and manage), and on a normal filesystem the migration +
      index build are cheap, so there's no downside to keeping packs there."""
    if not is_termux():
        return "static/"
    cdir = "~/storage/downloads/sukusta/packs"   # server default (DefaultCdnCacheDir)
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            v = json.load(f).get("cdn_cache_dir", "")
        if isinstance(v, str) and v.strip():
            cdir = v                             # explicit dir wins
        # empty / missing -> default (matches the server)
    except Exception:
        pass                                     # no/unreadable config.json -> default
    cdir = os.path.expanduser(cdir)
    if not cdir.endswith("/"):
        cdir += "/"
    return cdir


# Where encrypted packs are written (see _pack_output_dir): the packs cache dir
# on Termux, the static/ folder on PC/macOS.
PACK_DEST_DIR = _pack_output_dir()


def crc32_prefix_rename(rel_name):
    """temp 내 파일을 CRC32 접두사로 개명하고
    (새 경로, 파일명(확장자 제외), 크기, 팩 저장 대상 경로)를 반환한다."""
    src = temp_directory + rel_name
    checksum = generate_crc32(src)
    renamed = temp_directory + checksum + rel_name
    os.rename(src, renamed)
    filename = os.path.splitext(renamed.split("/")[-1])[0]
    filesize = os.path.getsize(renamed)
    encrypted = PACK_DEST_DIR + os.path.splitext(renamed.split("/")[-1])[0]
    return renamed, filename, filesize, encrypted


def valid_pack_filename(filename):
    """팩 파일명은 소문자 영숫자만 허용된다."""
    return filename.isalnum() and filename.islower()


def encrypt_to_static(src_path, dest_path, label):
    """파일을 XOR 암호화하여 팩 저장 폴더(PACK_DEST_DIR)에 저장한다. 이미 있으면 건너뛴다."""
    if not os.path.exists(dest_path):
        with open(src_path, "rb") as f:
            data = bytearray(f.read())
            print(f"encrypting {label}")
            manipulate_file(data, 12345, 0, 0)
            with open(dest_path, "wb") as out:
                out.write(data)
    else:
        print(f"{label} already encrypted")


def insert_dependencies(cursor, chara, costume_path, facedynamic_path, rina_path, has_facedynamic):
    """캐릭터별 member_model 의존성을 DEPENDENCIES 테이블에 따라 삽입한다."""
    entries = DEPENDENCIES.get(chara)
    if entries is None:
        return
    targets = {'C': costume_path, 'R': rina_path}
    for kind, target, value in entries:
        if kind == 'face_or' and has_facedynamic:
            cursor.execute(
                "INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);",
                (costume_path, facedynamic_path))
        else:
            cursor.execute(
                "INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);",
                (targets[target], value))


def insert_asset_records(db_path, ctx, first_db=False):
    """에셋 DB 한 곳에 팩/모델/텍스처/의존성 레코드를 삽입한다.

    first_db=True(asset_a_ja)일 때만:
      - 중복 코스튬 검사 (있으면 False 반환 -> 해당 애드온 건너뜀)
      - 무작위 asset_path 생성 (원본과 동일한 생성 순서 유지)

    듀얼 플랫폼 모드(ctx['dual']=True)에서는 asset_path는 공유하되,
    iOS DB(asset_i_*)에는 iOS 팩 파일명/크기를 등록한다.
    """
    use_ios = ctx.get('dual') and db_platform(db_path) == 'ios'
    costume_filename = ctx['costume_filename_ios'] if use_ios else ctx['costume_filename']
    costume_size = ctx['costume_size_ios'] if use_ios else ctx['costume_size']
    rina_filename = ctx.get('rina_filename_ios') if use_ios else ctx.get('rina_filename')
    rina_size = ctx.get('rina_size_ios') if use_ios else ctx.get('rina_size')

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        if first_db:
            cursor.execute("SELECT COUNT(*) FROM m_asset_pack WHERE pack_name = ?",
                           (ctx['costume_filename'],))
            if cursor.fetchone()[0] > 0:
                print(f"This costume already exists in the database (skip)")
                return False

        if ctx['has_facedynamic']:
            if first_db:
                ctx['facedynamic_path'] = unique_asset_path(cursor, 'member_model')
            cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');",
                           (ctx['facedynamic_filename'],))
            cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                           (ctx['facedynamic_path'], ctx['facedynamic_filename'], ctx['facedynamic_size']))

        if first_db:
            ctx['costume_path'] = unique_asset_path(cursor, 'member_model')

        if ctx['has_thumbnail']:
            if first_db:
                ctx['thumbnail_path'] = unique_asset_path(cursor, 'texture')
            cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');",
                           (ctx['thumbnail_filename'],))
            cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                           (ctx['thumbnail_path'], ctx['thumbnail_filename'], ctx['thumbnail_size']))

        # (light download auto delete fix)
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');",
                       (costume_filename,))

        if ctx['chara_id'] == 209:
            cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');",
                           (rina_filename,))

        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (ctx['costume_path'], costume_filename, costume_size))

        if ctx['chara_id'] == 209:
            if first_db:
                ctx['rina_path'] = unique_asset_path(cursor, 'texture')
            cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                           (ctx['rina_path'], rina_filename, rina_size))

        insert_dependencies(cursor, ctx['chara_id'], ctx['costume_path'],
                            ctx['facedynamic_path'], ctx['rina_path'], ctx['has_facedynamic'])
    return True


def insert_package_records(db_path, ctx):
    """에셋 DB 한 곳에 m_asset_package(_mapping) 레코드를 삽입한다.

    듀얼 플랫폼 모드에서는 iOS DB(asset_i_*)에 iOS 팩 파일을 매핑한다."""
    use_ios = ctx.get('dual') and db_platform(db_path) == 'ios'
    costume_filename = ctx['costume_filename_ios'] if use_ios else ctx['costume_filename']
    costume_size = ctx['costume_size_ios'] if use_ios else ctx['costume_size']
    rina_filename = ctx.get('rina_filename_ios') if use_ios else ctx.get('rina_filename')
    rina_size = ctx.get('rina_size_ios') if use_ios else ctx.get('rina_size')

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        donot_insert = None
        package_key_costume = "suit:" + str(ctx['costume_id'])
        package_key_thumbnail = "main"
        category_costume = '3'
        category_thumbnail = '8'
        fresh_version = hashlib.sha1(str(random.random()).encode()).hexdigest()
        fresh_version_main = hashlib.sha1(str(random.random()).encode()).hexdigest()

        cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
        update_main_asset = cursor.fetchone()[0] + 1

        def map_costume(pack_name, file_size):
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                           (package_key_costume, pack_name, file_size, donot_insert, category_costume))

        # 코스튬 패키지: 항상 본체, 209는 가면 해제 모델, facedynamic이 있으면 추가
        map_costume(costume_filename, costume_size)
        pack_num = 1
        if ctx['chara_id'] == 209:
            map_costume(rina_filename, rina_size)
            pack_num += 1
        if ctx['has_facedynamic']:
            map_costume(ctx['facedynamic_filename'], ctx['facedynamic_size'])
            pack_num += 1
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, ?);",
                       (package_key_costume, fresh_version, str(pack_num)))

        if ctx['has_thumbnail']:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                           (package_key_thumbnail, ctx['thumbnail_filename'], ctx['thumbnail_size'], donot_insert, category_thumbnail))
            cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                           (fresh_version_main, update_main_asset))


# ============================================================
# 3. 메인 흐름
# ============================================================

# ---- 애드온 설정 기본값 (zip 안의 .txt가 exec로 덮어씀) ----
costume_name_en = ""
costume_name_ko = costume_name_en
costume_name_zh = costume_name_en
costume_name_ja = costume_name_en
costume_description = ""

costume_file = ""
costume_facedynamic_file = ""
rina_unmask_costume_file = ""
thumbnail_file = ""
# 듀얼 플랫폼(합본) 애드온용 - 구버전 인스톨러는 이 변수를 몰라 무시한다
costume_file_ios = ""
rina_unmask_costume_file_ios = ""
chara_id = None
chara_id_append = None
id_costume = None
id_trade_product = None

check_json_config = "config.json"

if not os.path.exists(check_json_config):
    print('Config file is missing, Exiting...')
    sys.exit(1)

if is_termux():
    modding_elichika_path = os.path.expanduser('~/storage/downloads/sukusta/suit/')
    termux_storage_chc = os.path.expanduser('~/storage/')
    if not os.path.exists(termux_storage_chc):
        print('Path is missing, please execute termux-setup-storage command and allow it')
        sys.exit(1)
    if not os.path.exists(modding_elichika_path):
        os.makedirs(modding_elichika_path)

encrypted_folder = PACK_DEST_DIR
print(f"packs are written to: {encrypted_folder}  ({'termux: packs cache' if is_termux() else 'static/'})")
if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)

batch_proccess_list = []
is_nested = False
mod_installed = False

# ---- 작업 폴더 초기화 ----
temp_directory = "assets/package/.cache/"
shutil.rmtree(temp_directory, ignore_errors=True)
nested_path_batch = "assets/package/.nested/"
shutil.rmtree(nested_path_batch, ignore_errors=True)

# ---- zip 파일 선택 (termux: 번호 입력 / PC: 파일 선택 대화상자) ----
if is_termux():
    zip_files = []
    for root, dirs, files in os.walk(modding_elichika_path):
        for file in files:
            if file.endswith(".zip"):
                zip_files.append(os.path.relpath(os.path.join(root, file), modding_elichika_path))
    zip_files.sort()

    print("Available .zip files:")
    for i, zip_file in enumerate(zip_files, start=1):
        print(f"{i}. {zip_file}")

    if not zip_files:
        print("No .zip files found in " + modding_elichika_path)
        sys.exit(1)

    # 선택 형식: 3 / 1,4,7 / 4-8 / 1, 4-8, 14-23 / all
    while True:
        user_input = input("Select zip(s) - e.g. '3', '1,4,7', '4-8', '1, 4-8, 14-23', or 'all': ")
        try:
            chosen_numbers = parse_selection(user_input, len(zip_files))
            break
        except ValueError as e:
            print(f"Invalid input: {e}. Try again.")

    zip_file_paths = []
    for num in chosen_numbers:
        zip_file_paths.append(os.path.join(modding_elichika_path, zip_files[num-1]))
        print(f"Added: {zip_files[num-1]}")
    print(f"You chose {len(zip_file_paths)} file(s)")

    for zf_p in zip_file_paths:
        open_and_check_zip(zf_p)

    do_you_think_want_add_this = input("Do you want to proceed? (y/n): ")
    if do_you_think_want_add_this != "n":
        pass
    else:
        clear_terminal()
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1)

    do_backup_is_important = input("would you like backup database? (y/n): ")
    if do_backup_is_important == "y":
        backup_operate(filelist)
    else:
        print('well then do your own risk')
else:
    import tkinter as tk
    from tkinter import filedialog
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()  # 메인 창 숨김
    zip_file_path = filedialog.askopenfilenames(title="Locate Zip File")
    if zip_file_path:
        for print_addon in zip_file_path:
            print(f"Selected: {print_addon}")
    else:
        print("No file selected")
        sys.exit(1)
    response = messagebox.askyesnocancel("Confirmation", "Do you want to backup database?")
    if response is True:
        print("User chose Yes.")
        backup_operate(filelist)
    elif response is False:
        print("User chose No.")
    elif response is None:
        sys.exit(1)

# termux는 위에서 이미 open_and_check_zip 처리를 끝냈으므로
# 여기서는 PC(tkinter) 선택 결과만 처리한다 (기존의 이중 처리 버그 수정)
if not is_termux():
    for zip_file_path_batch in zip_file_path:
        open_and_check_zip(zip_file_path_batch)

# 중첩 zip에서 풀린 zip들을 처리 목록에 추가
for nested_root, dirs, nested_files in os.walk(nested_path_batch):
    for nested_file in nested_files:
        if nested_file.endswith(".zip"):
            batch_proccess_list.append(os.path.join(nested_root, nested_file))

# ---- 애드온별 설치 루프 ----
for mass_addon in batch_proccess_list:
    if os.path.exists(temp_directory):
        print(f"cleaning up temp folder")
        shutil.rmtree(temp_directory, ignore_errors=True)
        os.makedirs(temp_directory, exist_ok=True)

    # 듀얼 플랫폼 변수는 애드온 간 이월되면 위험하므로 매번 초기화한다
    # (구형 애드온 zip의 modinstall.txt에는 이 변수가 없어 리셋되지 않기 때문)
    costume_file_ios = ""
    rina_unmask_costume_file_ios = ""

    with open(mass_addon, 'rb') as zip_file:
        zip_data = zip_file.read()
    zip_buffer = io.BytesIO(zip_data)

    with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
        zip_ref.extractall(temp_directory)
        # .txt 설정 파일을 모듈 전역에서 실행 (원본과 동일한 동작)
        for file_info in zip_ref.infolist():
            if file_info.filename.endswith('.txt'):
                txt_file_path = os.path.join(temp_directory, file_info.filename)
                with open(txt_file_path, 'r', encoding='utf-8') as txt_file:
                    try:
                        file_content = txt_file.read()
                        exec(file_content)
                    except Exception as e:
                        print(f"Error executing file: {file_info.filename}\nError: {e}")

    # ---- CRC32 개명 + 파일명 검증 ----
    start_encrypt1 = temp_directory + costume_file
    crc32_checksum_costume = generate_crc32(start_encrypt1)
    crc32_rename_costume = temp_directory + crc32_checksum_costume + costume_file
    os.rename(start_encrypt1, crc32_rename_costume)
    start_encrypt1 = crc32_rename_costume
    costume_filename = os.path.splitext(start_encrypt1.split("/")[-1])[0]
    costume_filesize = os.path.getsize(start_encrypt1)
    encrypted_costume = PACK_DEST_DIR + os.path.splitext(start_encrypt1.split("/")[-1])[0]
    file_extension = start_encrypt1.split(".")[-1]

    # 코스튬 파일 확장자가 숫자면 캐릭터 ID로 사용
    if file_extension.isdigit():
        chara_id = int(file_extension)

    if not valid_pack_filename(costume_filename):
        print('Invalid Costume Filename, Exiting.')
        shutil.rmtree(temp_directory, ignore_errors=True)
        continue

    if thumbnail_file != "":
        start_encrypt2, thumbnail_costume_filename, thumbnail_costume_size, encrypted_thumbnail = crc32_prefix_rename(thumbnail_file)
        if not valid_pack_filename(thumbnail_costume_filename):
            print('Invalid Thumbnail Filename, Exiting.')
            shutil.rmtree(temp_directory, ignore_errors=True)
            continue

    if costume_facedynamic_file != "":
        start_encrypt4, facedynamic_costume_filename, facedynamic_costume_size, encrypted_facedynamic = crc32_prefix_rename(costume_facedynamic_file)
        if not valid_pack_filename(facedynamic_costume_filename):
            print('Invalid Facedynamic Filename, Exiting.')
            shutil.rmtree(temp_directory, ignore_errors=True)
            continue

    if chara_id == 209:
        start_encrypt3, rina_unmask_costume_filename, rina_unmask_costume_filesize, encrypted_rina_unmask = crc32_prefix_rename(rina_unmask_costume_file)
        if not valid_pack_filename(rina_unmask_costume_filename):
            print('Invalid Rina Unmasked Costume Filename, Exiting.')
            shutil.rmtree(temp_directory, ignore_errors=True)
            continue

    # ---- 듀얼 플랫폼(합본) 애드온: iOS 번들 처리 ----
    is_dual_platform = costume_file_ios != ""
    if is_dual_platform:
        start_encrypt1_ios, costume_filename_ios, costume_filesize_ios, encrypted_costume_ios = crc32_prefix_rename(costume_file_ios)
        if not valid_pack_filename(costume_filename_ios):
            print('Invalid iOS Costume Filename, Exiting.')
            shutil.rmtree(temp_directory, ignore_errors=True)
            continue

        rina_has_own_ios_file = False
        if chara_id == 209:
            if rina_unmask_costume_file_ios != "":
                start_encrypt3_ios, rina_unmask_costume_filename_ios, rina_unmask_costume_filesize_ios, encrypted_rina_unmask_ios = crc32_prefix_rename(rina_unmask_costume_file_ios)
                if not valid_pack_filename(rina_unmask_costume_filename_ios):
                    print('Invalid iOS Rina Unmasked Costume Filename, Exiting.')
                    shutil.rmtree(temp_directory, ignore_errors=True)
                    continue
                rina_has_own_ios_file = True
            else:
                # iOS용 가면 해제 모델이 없으면 안드로이드 파일로 대체 (경고)
                print('WARNING: no iOS rina unmask file - reusing the android one for iOS databases')
                rina_unmask_costume_filename_ios = rina_unmask_costume_filename
                rina_unmask_costume_filesize_ios = rina_unmask_costume_filesize

    # ---- 캐릭터 ID 정규화 (란쥬/미아 ID 교환) 및 그룹 결정 ----
    if chara_id == 212:
        chara_id = 211
    elif chara_id == 211:
        chara_id = 212

    if 1 <= chara_id <= 9:
        chara_id_group = 13      # 뮤즈
    elif 101 <= chara_id <= 109:
        chara_id_group = 14      # 아쿠아
    elif 201 <= chara_id <= 212:
        chara_id_group = 15      # 니지가사키

    if chara_id in CHARACTER_NAMES:
        print(f'Adding {costume_name_en} to {CHARACTER_NAMES[chara_id]}')
    else:
        print("Invalid chara id")
        continue

    if costume_description != "":
        print('Description: ' + costume_description)

    # ---- 유니티 파일 플랫폼 감지 (Android / iOS) ----
    if is_dual_platform:
        # 합본 애드온: costume_file=안드로이드, costume_file_ios=iOS 로 명시되어 있음
        print("Dual platform addon detected (android + ios in one package)")
        plat_and = detect_unity_platform(start_encrypt1)
        plat_ios = detect_unity_platform(start_encrypt1_ios)
        print(f"  [costume android] platform: {plat_and if plat_and else 'unknown'}")
        print(f"  [costume ios] platform: {plat_ios if plat_ios else 'unknown'}")
        if plat_and == 'ios' or plat_ios == 'android':
            print("WARNING: bundle platforms look swapped or mismatched against the config!")
        print("-> Registering android bundle into asset_a_* and ios bundle into asset_i_*")
        addon_platform = None
        addon_asset_db_paths = list(ASSET_DB_PATHS)
        addon_package_db_paths = list(PACKAGE_DB_PATHS)
    else:
        platform_check_files = [(start_encrypt1, "costume")]
        if costume_facedynamic_file != "":
            platform_check_files.append((start_encrypt4, "facedynamic"))
        if chara_id == 209:
            platform_check_files.append((start_encrypt3, "rina unmask"))
        if thumbnail_file != "":
            platform_check_files.append((start_encrypt2, "thumbnail"))

        print("Checking unity bundle platform...")
        addon_platform = detect_addon_platform(platform_check_files)
        if addon_platform is None:
            while True:
                plat_input = input("Could not detect platform. Install for [a]ndroid / [i]os / [b]oth?: ").strip().lower()
                if plat_input in ('a', 'android'):
                    addon_platform = 'android'
                    break
                if plat_input in ('i', 'ios'):
                    addon_platform = 'ios'
                    break
                if plat_input in ('b', 'both'):
                    addon_platform = None  # 기존 동작: 양쪽 모두 등록
                    break
                print("Please answer 'a', 'i' or 'b'.")
        if addon_platform:
            print(f"-> Registering into {addon_platform.upper()} asset databases only")
        else:
            print("-> Registering into BOTH android & ios asset databases")
        addon_asset_db_paths = filter_dbs_by_platform(ASSET_DB_PATHS, addon_platform)
        addon_package_db_paths = filter_dbs_by_platform(PACKAGE_DB_PATHS, addon_platform)

    # ---- 캐시 폴더(packs)로 암호화 저장 ----
    encrypt_to_static(start_encrypt1, encrypted_costume, "costume")
    if thumbnail_file != "":
        encrypt_to_static(start_encrypt2, encrypted_thumbnail, "thumbnail")
    if costume_facedynamic_file != "":
        encrypt_to_static(start_encrypt4, encrypted_facedynamic, "facedynamic")
    if chara_id == 209:
        encrypt_to_static(start_encrypt3, encrypted_rina_unmask, "rina unmask costume")
    if is_dual_platform:
        encrypt_to_static(start_encrypt1_ios, encrypted_costume_ios, "costume (ios)")
        if chara_id == 209 and rina_has_own_ios_file:
            encrypt_to_static(start_encrypt3_ios, encrypted_rina_unmask_ios, "rina unmask costume (ios)")
    print("assets encrypted")

    # ---- 플랫폼에 맞는 에셋 DB에 팩/모델/의존성 등록 ----
    asset_ctx = {
        'chara_id': chara_id,
        'costume_filename': costume_filename,
        'costume_size': costume_filesize,
        'has_facedynamic': costume_facedynamic_file != "",
        'facedynamic_filename': facedynamic_costume_filename if costume_facedynamic_file != "" else None,
        'facedynamic_size': facedynamic_costume_size if costume_facedynamic_file != "" else None,
        'has_thumbnail': thumbnail_file != "",
        'thumbnail_filename': thumbnail_costume_filename if thumbnail_file != "" else None,
        'thumbnail_size': thumbnail_costume_size if thumbnail_file != "" else None,
        'rina_filename': rina_unmask_costume_filename if chara_id == 209 else None,
        'rina_size': rina_unmask_costume_filesize if chara_id == 209 else None,
        'costume_path': None,
        'facedynamic_path': None,
        'thumbnail_path': None,
        'rina_path': None,
        # 듀얼 플랫폼: iOS DB(asset_i_*)에는 이 팩 파일을 등록한다
        'dual': is_dual_platform,
        'costume_filename_ios': costume_filename_ios if is_dual_platform else None,
        'costume_size_ios': costume_filesize_ios if is_dual_platform else None,
        'rina_filename_ios': rina_unmask_costume_filename_ios if (is_dual_platform and chara_id == 209) else None,
        'rina_size_ios': rina_unmask_costume_filesize_ios if (is_dual_platform and chara_id == 209) else None,
    }

    if not insert_asset_records(addon_asset_db_paths[0], asset_ctx, first_db=True):
        shutil.rmtree(temp_directory, ignore_errors=True)
        continue
    for db_path in addon_asset_db_paths[1:]:
        insert_asset_records(db_path, asset_ctx)

    costume_path = asset_ctx['costume_path']
    thumbnail_costume_path = asset_ctx['thumbnail_path']
    rina_unmask_costume_path = asset_ctx['rina_path']

    # ---- masterdata (JP) : 코스튬/교환소 ID, m_suit ----
    with sqlite3.connect('assets/db/jp/masterdata.db') as conn:
        cursor = conn.cursor()

        channel_exchange_trade = 50000 + int(chara_id)
        if id_costume is None:
            costume_id_masterdata = generate_unique_costume_id(cursor)
        else:
            costume_id_masterdata = id_costume

        if id_trade_product is None:
            zgenerate_id = generate_unique_trade_id(cursor, channel_exchange_trade)
            trade_id_into_json = str(channel_exchange_trade) + str(zgenerate_id)
        else:
            formatted_id_trade_product = f"{id_trade_product:03}"
            trade_id_into_json = str(channel_exchange_trade) + str(formatted_id_trade_product)

        if chara_id_append is None:
            chara_id_suit = chara_id
        else:
            chara_id_suit = chara_id_append

        trade_content_into_json = str(trade_id_into_json) + "01"

        costume_dictionary = "suit_name_" + str(costume_id_masterdata)
        costume_dictionary_masterdata = "k." + costume_dictionary
        donot_insert = None

        cursor.execute("SELECT MAX(display_order) FROM main.m_suit WHERE member_m_id = ?;", (chara_id,))
        result = cursor.fetchone()
        display_order_new_ja = (result[0] if result[0] is not None else 0) + 1

        # 썸네일이 없으면 캐릭터 기본 썸네일 사용
        if thumbnail_file == "" and chara_id in DEFAULT_THUMBNAILS:
            thumbnail_costume_path = DEFAULT_THUMBNAILS[chara_id]

        cursor.execute("INSERT INTO main.m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, '2', '0', ?, ?);",
                       (costume_id_masterdata, chara_id_suit, costume_dictionary_masterdata, thumbnail_costume_path, costume_path, display_order_new_ja))

        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_suit_view (suit_master_id, view_status, model_asset_path) VALUES (?, '2', ?);", (costume_id_masterdata, rina_unmask_costume_path))

    # ---- masterdata (GL) ----
    with sqlite3.connect('assets/db/gl/masterdata.db') as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT MAX(display_order) FROM main.m_suit WHERE member_m_id = ?;", (chara_id,))
        result = cursor.fetchone()
        display_order_new_gl = (result[0] if result[0] is not None else 0) + 1

        cursor.execute("INSERT INTO main.m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, '2', '0', ?, ?);",
                       (costume_id_masterdata, chara_id_suit, costume_dictionary_masterdata, thumbnail_costume_path, costume_path, display_order_new_gl))

        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_suit_view (suit_master_id, view_status, model_asset_path) VALUES (?, '2', ?);", (costume_id_masterdata, rina_unmask_costume_path))

    # ---- userdata : 모든 유저에게 지급 + 나비 코스튬 교체 ----
    with sqlite3.connect('userdata.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM u_status")
        user_ids = cursor.fetchall()
        for user_id_ins in user_ids:
            user_id_ins = user_id_ins[0]
            cursor.execute("INSERT INTO main.u_suit (user_id, suit_master_id, is_new) VALUES (?, ?, '0');", (user_id_ins, costume_id_masterdata))
            cursor.execute("UPDATE u_member SET suit_master_id = ? WHERE user_id = ? AND member_master_id = ?;", (costume_id_masterdata, user_id_ins, chara_id))
            print(f"added to user id {user_id_ins} & changed navi costume")

    # ---- 플랫폼에 맞는 에셋 DB에 다운로드 패키지 등록 ----
    package_ctx = dict(asset_ctx)
    package_ctx['costume_id'] = costume_id_masterdata
    for db_path in addon_package_db_paths:
        insert_package_records(db_path, package_ctx)

    # ---- 사전(코스튬 이름) 등록 ----
    if costume_name_en == "":
        costume_name_en = "suit:" + str(costume_id_masterdata)
    costume_names = {"en": costume_name_en, "ko": costume_name_ko,
                     "zh": costume_name_zh, "ja": costume_name_ja}
    for dict_db, lang in DICTIONARY_DBS:
        with sqlite3.connect(dict_db) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);",
                           (costume_dictionary, costume_names[lang]))

    print("deleting temp folder")
    shutil.rmtree(temp_directory, ignore_errors=True)
    mod_installed = True

# ---- 마무리: CDN 주소 보정 및 임시 폴더 정리 ----
if mod_installed:
    with open(check_json_config, 'r') as f:
        config_elichika = json.load(f)
        xcheck_cdn = config_elichika.get('cdn_server')
        if xcheck_cdn != "http://127.0.0.1:8080/static":
            config_elichika['cdn_server'] = "http://127.0.0.1:8080/static"
            with open(check_json_config, 'w') as f:
                json.dump(config_elichika, f, indent=4)
                print("CDN server updated to http://127.0.0.1:8080/static")

    print("deleting nested folder")
    shutil.rmtree(nested_path_batch, ignore_errors=True)
    print("FINISHED")
else:
    print("Nothing installed")
