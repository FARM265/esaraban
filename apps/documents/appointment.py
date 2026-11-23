"""
อ่านวันนัดหมายจากข้อความในหนังสือราชการ แล้วสร้างลิงก์ Google Calendar หรือไฟล์ .ics

ไม่พึ่ง Django เพื่อทดสอบได้ง่าย ผลลัพธ์เป็นเพียง "ค่าที่เดาไว้ให้" ผู้ใช้ต้องตรวจและแก้ก่อนบันทึกลงปฏิทินเสมอ
หลักการเลือกวันที่: ให้คะแนนวันที่ที่อยู่ใกล้คำว่า "ในวัน...ที่" และ "เวลา" สูง
และตัดคะแนนวันที่ของตัวหนังสือเอง (ลงวันที่, วันที่ในหัวบันทึกข้อความ, วันที่ก่อน "เรื่อง")
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Bangkok")

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_THAI = "\u0e00-\u0e7f"

MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}
_MONTH_RE = "|".join(re.escape(m) for m in sorted(MONTHS, key=len, reverse=True))
# วัน เดือน ปี (ปีไม่บังคับ เช่น "30 พฤศจิกายน - 2 ธันวาคม 2569")
_DATE_RE = re.compile(
    rf"(?<!\d)(\d{{1,2}})\s*(?:(?:-|–|—|ถึง(?:วันที่?)?)\s*(\d{{1,2}})\s*)?({_MONTH_RE})\s*(?:(?:พ\.?\s*ศ\.?|ค\.?\s*ศ\.?)\s*)?(\d{{4}}|\d{{2}}(?!\d))?"
)
_TIME_RANGE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[.:]\s*(\d{2})\s*(?:น\.|นาฬิกา)?\s*(?:-|–|—|ถึง)\s*(\d{1,2})\s*[.:]\s*(\d{2})"
)
_TIME_RE = re.compile(r"เวลา\s*(?:ประมาณ\s*)?(\d{1,2})\s*[.:]\s*(\d{2})")
_WEEKDAY = "จันทร์|อังคาร|พุธ|พฤหัสบดี|พฤหัส|ศุกร์|เสาร์|อาทิตย์"
_EVENT_WORDS = re.compile(r"ประชุม|อบรม|สัมมนา|เข้าร่วม|พิธี|กิจกรรม|ตรวจ|ลงพื้นที่|ชี้แจง")
_SUBJECT_RE = re.compile(r"เรื?่?อง\s*[:：]?\s*(.+?)\s*(?=เรียน|อ้างถึง|สิ่งที่ส่งมาด้วย|ถึง\s|$)")
_LOCATION_RE = re.compile(
    rf"(?<![{_THAI}])ณ\s+(?!วันที่?)(.{{3,120}}?)\s*(?=โดย|ทั้งนี้|จึง|เพื่อ|ใน(?:วัน|เวลา)|ระหว่าง|เวลา|ตั้งแต่|[,;]|$)"
)


@dataclass
class Appointment:
    title: str = ""
    subject: str = ""
    start_date: date | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    location: str = ""
    snippet: str = ""  # ประโยคที่ใช้หาวันที่ ให้ผู้ใช้ตรวจ
    notes: list = field(default_factory=list)


def normalize(text):
    """เลขไทยเป็นเลขอารบิก ยุบช่องว่างและขึ้นบรรทัดเป็นช่องว่างเดียว ตัดช่องว่างที่ OCR แทรกระหว่างอักษรไทย"""
    text = (text or "").translate(_THAI_DIGITS).replace("\u200b", "")
    text = text.replace("\u0e4d\u0e32", "\u0e33")  # OCR มักแยก "ำ" เป็นนิคหิต + สระอา
    text = re.sub(r"\s+", " ", text).strip()
    # ไม้หันอากาศและสระหน้า (เ แ โ ใ ไ) ไม่มีทางอยู่ท้ายคำ ช่องว่างหลังตัวเหล่านี้จึงเป็นช่องว่างที่ตัวอ่าน PDF แทรกผิด
    text = re.sub(r"(?<=[\u0e31\u0e40-\u0e44]) (?=[\u0e01-\u0e2e])", "", text)
    return text


def _squeeze(text):
    # OCR ภาษาไทยมักแทรกช่องว่างกลางคำ เช่น "พฤศจิ กายน" จึงตัดช่องว่างที่อยู่ระหว่างอักษรไทยสองตัวออก
    return re.sub(rf"(?<=[{_THAI}]) (?=[{_THAI}])", "", text)


def _year(raw, fallback):
    if not raw:
        return fallback
    y = int(raw)
    if len(raw) == 2:
        y += 2500  # ปีย่อในหนังสือราชการเป็น พ.ศ.
    return y - 543 if y >= 2400 else y


def _safe_date(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


# OCR ภาษาไทยมักสับสนเลขไทยที่หน้าตาคล้ายกัน (๒/๖ และ ๕/๙)
_CONFUSABLE = {"2": "26", "6": "62", "5": "59", "9": "95"}
_WEEKDAY_NUM = {"จันทร์": 0, "อังคาร": 1, "พุธ": 2, "พฤหัสบดี": 3, "พฤหัส": 3, "ศุกร์": 4, "เสาร์": 5, "อาทิตย์": 6}


def _variants(digits):
    """ตัวเลขที่ OCR อาจอ่านผิดมา เช่น "2525" -> 2525, 2529, 2565, 2569, ... (ตัวที่อ่านได้มาก่อน)"""
    options = [""]
    for ch in digits:
        options = [o + alt for o in options for alt in _CONFUSABLE.get(ch, ch)]
    return options


def _fix_ocr_date(year_raw, day_raw, month, weekday, today):
    """
    แก้วันที่ที่ OCR อ่านเลขไทยผิด: ปีต้องอยู่ในช่วงใกล้ปัจจุบัน และถ้าหนังสือระบุวันในสัปดาห์ (เช่น "วันพุธที่")
    วันที่ต้องตรงกับวันนั้น คืน (date, แก้ไขหรือไม่) หรือ (None, False) ถ้าหาไม่ได้
    """
    years = []
    for raw in _variants(year_raw):
        y = _year(raw, today.year)
        if today.year - 1 <= y <= today.year + 3 and y not in years:
            years.append(y)
    years.sort(key=lambda y: abs(y - today.year))
    days = [int(d) for d in _variants(day_raw) if 1 <= int(d) <= 31]
    for y in years:
        for d in days:
            found = _safe_date(y, month, d)
            if found and (weekday is None or found.weekday() == weekday):
                return found, (str(d) != day_raw or y != _year(year_raw, today.year))
    return None, False


def _candidates(text, today, ocr=False):
    out = []
    matches = list(_DATE_RE.finditer(text))
    for i, m in enumerate(matches):
        day1, day2, month_name, year_raw = m.groups()
        year_next = matches[i + 1].group(4) if i + 1 < len(matches) else None
        y = _year(year_raw or year_next, today.year)
        month = MONTHS[month_name]
        start = _safe_date(y, month, int(day1))
        corrected = False
        wd = re.search(rf"วัน({_WEEKDAY})\s*ที่?\s*$", text[max(0, m.start() - 20):m.start()])
        weekday = _WEEKDAY_NUM[wd.group(1)] if wd else None
        plausible = start is not None and today.year - 1 <= start.year <= today.year + 3
        weekday_ok = start is not None and (weekday is None or start.weekday() == weekday)
        if ocr and (year_raw or year_next) and not day2 and not (plausible and weekday_ok):
            fixed, corrected = _fix_ocr_date(year_raw or year_next, day1, month, weekday, today)
            if fixed is not None:
                start = fixed
        if start is None:
            continue
        end = _safe_date(start.year, month, int(day2)) if day2 else None
        if end is not None and end < start:
            end = None
        out.append({"start": start, "end": end, "pos": m.start(), "endpos": m.end(), "has_year": bool(year_raw),
                    "corrected": corrected})
    # รวมช่วงข้ามเดือน "30 พฤศจิกายน - 2 ธันวาคม 2569"
    merged = []
    i = 0
    while i < len(out):
        c = out[i]
        if i + 1 < len(out) and c["end"] is None and re.fullmatch(
            r"\s*(?:-|–|—|ถึง(?:วันที่?)?)\s*(?:วัน(?:" + _WEEKDAY + r")?ที่?\s*)?", text[c["endpos"]:out[i + 1]["pos"]]
        ) and out[i + 1]["start"] > c["start"]:
            nxt = out[i + 1]
            c = {**c, "end": nxt["end"] or nxt["start"], "endpos": nxt["endpos"]}
            i += 1
        merged.append(c)
        i += 1
    return merged


def _score(c, text, subject_pos, today):
    if not (today.year - 1 <= c["start"].year <= today.year + 3):
        return -20  # ปีผิดปกติ มักเกิดจาก OCR อ่านเลขไทยผิด
    before = text[max(0, c["pos"] - 40):c["pos"]]
    after = text[c["endpos"]:c["endpos"] + 80]
    score = 0
    if re.search(r"ลงวันที่?\s*$", before):
        score -= 10  # วันที่ของหนังสือที่อ้างถึง
    if re.match(r"\s*เรื่อง", after):
        score -= 6  # วันที่ในหัวบันทึกข้อความ
    if subject_pos is not None and c["pos"] < subject_pos:
        score -= 3  # วันที่ของตัวหนังสือมักอยู่ก่อน "เรื่อง"
    if re.search(rf"(?:ใน|ระหว่าง|ตั้งแต่)\s*วัน\s*(?:{_WEEKDAY})?\s*(?:ที่?)?\s*$", before) or re.search(
        rf"วัน(?:{_WEEKDAY})\s*ที่?\s*$", before
    ):
        score += 3
    if re.search(r"ภายใน\s*วันที่?\s*$", before):
        score += 1  # กำหนดส่ง
    if re.match(r".{0,40}?(?:เวลา|\d{1,2}\s*[.:]\s*\d{2}\s*(?:น\.|นาฬิกา))", after):
        score += 4
    if _EVENT_WORDS.search(text[max(0, c["pos"] - 120):c["endpos"] + 120]):
        score += 1
    if c["end"]:
        score += 1
    return score


def _time(h, m):
    h, m = int(h), int(m)
    return time(h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None


def _find_times(text, start_at):
    """หาเวลาหลังวันที่ที่เลือก (ภายใน 120 ตัวอักษร) ก่อน ถ้าไม่พบใช้ "เวลา ..." แรกในหนังสือ"""
    for region in (text[start_at:start_at + 120], text):
        m = _TIME_RANGE_RE.search(region)
        if m:
            t1, t2 = _time(*m.group(1, 2)), _time(*m.group(3, 4))
            if t1:
                return t1, (t2 if t2 and t2 > t1 else None)
        m = _TIME_RE.search(region)
        if m and _time(*m.groups()):
            return _time(*m.groups()), None
    return None, None


def _subject_before_salutation(raw_text):
    """
    สำรองเมื่อหาคำว่า "เรื่อง" ไม่เจอ (OCR อ่านคำนี้ผิดบ่อย): ใช้บรรทัดก่อน "เรียน" ตามรูปแบบหนังสือราชการ
    ตัดคำนำหน้าบรรทัดที่ไม่ใช่ภาษาไทย (คำว่า "เรื่อง" ที่อ่านผิด) และเศษอักขระท้ายบรรทัดออก
    """
    lines = [normalize(line) for line in (raw_text or "").translate(_THAI_DIGITS).splitlines()]
    lines = [line for line in lines if line]
    for i, line in enumerate(lines):
        if line.startswith("เรียน") and i > 0:
            candidate = lines[i - 1]
            if re.match(r"(?:ที่|วันที่|ส่วนราชการ)\s", candidate):
                return ""
            candidate = re.sub(r"^(?:เร\S{0,5}ง|[^\u0e00-\u0e7f(\s]{1,6})\s+", "", candidate)
            candidate = re.sub(r"(?:\s+[^\u0e00-\u0e7f()\s]{1,10})+$", "", candidate)
            return candidate.strip() if len(re.findall(r"[\u0e00-\u0e7f]", candidate)) >= 4 else ""
    return ""


def clean_title(subject):
    title = re.sub(r"^ขอเชิญ\s*(?:เข้าร่วม|ร่วม)?\s*", "", subject).strip()
    return title or subject


def extract(raw_text, today=None, ocr=False):
    today = today or date.today()
    spaced = normalize(raw_text)
    text = _squeeze(spaced)
    result = Appointment()
    if not text:
        result.notes.append("ไม่พบข้อความในไฟล์")
        return result

    # ข้อความจาก OCR มีช่องว่างแทรกกลางคำ จึงตัดช่องว่างระหว่างอักษรไทยในเรื่องและสถานที่ออก
    tidy = _squeeze if ocr else (lambda value: value)
    m = _SUBJECT_RE.search(spaced) or _SUBJECT_RE.search(text)
    if m:
        result.subject = tidy(m.group(1).strip())[:300]
        result.title = clean_title(result.subject)[:200]
    m_flat = _SUBJECT_RE.search(text)
    subject_pos = m_flat.start() if m_flat else None

    if not result.subject:
        result.subject = tidy(_subject_before_salutation(raw_text))[:300]
        result.title = clean_title(result.subject)[:200]

    candidates = _candidates(text, today, ocr=ocr)
    if candidates:
        scores = [_score(c, text, subject_pos, today) for c in candidates]
        top = max(scores)
        best = candidates[scores.index(top)]  # คะแนนเท่ากันเลือกตัวที่อยู่ก่อน
        if top > -3:
            result.start_date, result.end_date = best["start"], best["end"]
            result.start_time, result.end_time = _find_times(text, best["endpos"])
            result.snippet = text[max(0, best["pos"] - 60):best["endpos"] + 90].strip()
            if not best["has_year"] and best["end"] is None:
                result.notes.append("ไม่พบปี พ.ศ. ในวันที่ที่เลือก ระบบใช้ปีปัจจุบัน")
            if best["corrected"]:
                result.notes.append("ตัวเลขวันที่ในภาพอ่านไม่ชัด ระบบเดาจากปีปัจจุบันและวันในสัปดาห์ กรุณาตรวจวันที่")
            if re.search(r"ภายใน\s*(?:วัน\S{0,10})?\s*$", text[max(0, best["pos"] - 25):best["pos"]]) and result.title:
                result.title = f"ครบกำหนด: {result.title}"[:200]  # วันที่ "ภายใน..." คือกำหนดส่ง
    if result.start_date is None:
        result.notes.append("ไม่พบวันนัดหมายในหนังสือ กรุณากรอกเอง")

    m = _LOCATION_RE.search(spaced)
    if m:
        result.location = tidy(m.group(1).strip(" ."))[:200]
    return result


# ---------------------------------------------------------------- ส่งออก
def _bounds(appt):
    """คืน (all_day, start, end) start/end เป็น datetime ในเวลาไทย หรือ date สำหรับทั้งวัน (end ไม่รวมวันนั้น)"""
    if appt.start_time is None:
        last = appt.end_date or appt.start_date
        return True, appt.start_date, last + timedelta(days=1)
    start = datetime.combine(appt.start_date, appt.start_time, TZ)
    end_day = appt.end_date or appt.start_date
    if appt.end_time is not None:
        end = datetime.combine(end_day, appt.end_time, TZ)
        if end <= start:
            end = start + timedelta(hours=1)
    else:
        end = start + timedelta(hours=1)
    return False, start, end


def _utc(dt):
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")


# อักษรไทยใน URL ใช้ 9 ตัวอักษรต่อ 1 ตัว และถ้าผู้ใช้ยังไม่ได้เข้าสู่ระบบ Google จะห่อ URL นี้ซ้ำอีก 2 ชั้น
# ลิงก์ยาวเกินทำให้ Google ตอบ "400 Bad Request" จึงจำกัดความยาวและตัดรายละเอียดก่อน แล้วจึงตัดสถานที่และชื่องาน
GOOGLE_URL_MAX = 900


def google_url(appt, details="", max_len=GOOGLE_URL_MAX):
    all_day, start, end = _bounds(appt)
    dates = f"{start:%Y%m%d}/{end:%Y%m%d}" if all_day else f"{_utc(start)}/{_utc(end)}"
    fields = {"text": appt.title, "details": details or "", "location": appt.location or ""}

    def build():
        params = {"action": "TEMPLATE", "text": fields["text"], "dates": dates, "ctz": "Asia/Bangkok"}
        for key in ("details", "location"):
            if fields[key]:
                params[key] = fields[key]
        return "https://calendar.google.com/calendar/render?" + urlencode(params, safe="/")

    url = build()
    for key, keep in (("details", 0), ("location", 20), ("text", 30)):
        if len(url) <= max_len:
            break
        original = fields[key]
        lo, hi = keep, len(original)  # หาความยาวมากที่สุดที่ยังไม่เกินกำหนด
        while lo < hi:
            mid = (lo + hi + 1) // 2
            fields[key] = original[:mid]
            if len(build()) <= max_len:
                lo = mid
            else:
                hi = mid - 1
        fields[key] = original[:lo]
        url = build()
    return url


def _ics_escape(value):
    return (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line):
    """ตัดบรรทัดยาวเกิน 75 ไบต์ตามมาตรฐาน iCalendar โดยไม่ตัดกลางอักขระ UTF-8"""
    out, current = [], ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > (75 if not out else 74):
            out.append(current)
            current = ch
        else:
            current += ch
    out.append(current)
    return "\r\n ".join(out)


def to_ics(appt, uid, details="", now=None):
    all_day, start, end = _bounds(appt)
    now = now or datetime.now(TZ)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//E-Saraban//TH", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{_utc(now)}",
    ]
    if all_day:
        lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}"]
    else:
        lines += [f"DTSTART:{_utc(start)}", f"DTEND:{_utc(end)}"]
    lines.append(f"SUMMARY:{_ics_escape(appt.title)}")
    if appt.location:
        lines.append(f"LOCATION:{_ics_escape(appt.location)}")
    if details:
        lines.append(f"DESCRIPTION:{_ics_escape(details)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8")
