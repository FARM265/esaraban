"""
ตัดคำภาษาไทยเพื่อขึ้นบรรทัดใหม่ (ภาษาไทยไม่เว้นวรรคระหว่างคำ)

ใช้ libthai ของระบบผ่าน ctypes (Docker image ติดตั้ง libthai0 ไว้แล้ว) ถ้าไม่มี libthai
จะตัดได้เฉพาะที่ช่องว่าง และตัดกลางคำเมื่อคำยาวเกินบรรทัด (ไม่ตัดแยกสระ/วรรณยุกต์ออกจากพยัญชนะ)
ไม่ import Django จึงทดสอบแยกได้
"""
import ctypes
import ctypes.util
import re
from functools import lru_cache

THAI_RUN = re.compile(r"[ก-๛]+")
# สระบน สระล่าง วรรณยุกต์ ไม้ไต่คู้ การันต์ ซึ่งต้องอยู่ติดกับพยัญชนะตัวหน้าเสมอ
COMBINING = set("\u0E31\u0E33\u0E34\u0E35\u0E36\u0E37\u0E38\u0E39\u0E3A\u0E47\u0E48\u0E49\u0E4A\u0E4B\u0E4C\u0E4D\u0E4E")


@lru_cache(maxsize=1)
def _libthai():
    name = ctypes.util.find_library("thai") or "libthai.so.0"
    try:
        lib = ctypes.CDLL(name)
        lib.th_brk_new.restype = ctypes.c_void_p
        lib.th_brk_new.argtypes = [ctypes.c_char_p]
        lib.th_brk_find_breaks.restype = ctypes.c_int
        lib.th_brk_find_breaks.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int), ctypes.c_size_t
        ]
        handle = lib.th_brk_new(None)
        if not handle:
            return None
        return lib, handle
    except (OSError, AttributeError):
        return None


def available():
    return _libthai() is not None


def _thai_breaks(run):
    found = _libthai()
    if found is None:
        return []
    lib, handle = found
    data = run.encode("tis-620", errors="replace")  # 1 ตัวอักษร = 1 ไบต์ ตำแหน่งจึงตรงกัน
    positions = (ctypes.c_int * (len(data) + 1))()
    count = lib.th_brk_find_breaks(handle, data, positions, len(data) + 1)
    return [p for p in positions[:max(count, 0)] if 0 < p < len(run)]


def atoms(text):
    """
    แบ่งข้อความเป็นชิ้นที่ขึ้นบรรทัดใหม่ระหว่างชิ้นได้ ต่อกันแล้วได้ข้อความเดิมทุกตัวอักษร
    ช่องว่างติดอยู่ท้ายชิ้นก่อนหน้า
    """
    cuts = set()
    for match in THAI_RUN.finditer(text):
        cuts.update(match.start() + p for p in _thai_breaks(match.group()))
    for index, char in enumerate(text):
        if char == " " and index + 1 < len(text) and text[index + 1] != " ":
            cuts.add(index + 1)
    cuts = sorted(c for c in cuts if 0 < c < len(text))
    edges = [0, *cuts, len(text)]
    return [text[a:b] for a, b in zip(edges, edges[1:]) if b > a]


def clusters(word):
    """แบ่งคำเป็นกลุ่มอักษร (พยัญชนะ + สระ/วรรณยุกต์ที่กำกับ) ใช้ตัดคำที่ยาวเกินบรรทัด"""
    out = []
    for char in word:
        if out and char in COMBINING:
            out[-1] += char
        else:
            out.append(char)
    return out
