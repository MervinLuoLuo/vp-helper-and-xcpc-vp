from __future__ import annotations

from datetime import datetime
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .models import Medals, VPError


def contest_id_url(platform: str, ident: str) -> str:
    if platform != "qoj" or not re.fullmatch(r"[0-9]+", ident) or int(ident) <= 0:
        raise VPError("Use vp qoj ID with a positive numeric contest ID.")
    return "https://qoj.ac/contest/" + str(int(ident))


def contest_url(url: str) -> tuple[str, str, str]:
    p = urlsplit(url)
    try:
        port = p.port
    except ValueError:
        raise VPError("Invalid contest URL port.") from None
    if p.scheme not in ("http", "https") or p.username or p.password or port:
        raise VPError("Use a QOJ contest URL.")
    match = re.fullmatch(r"/contest/(\d+)/?", p.path) if p.hostname in ("qoj.ac", "contest.ucup.ac") else None
    if not match:
        raise VPError("Only QOJ contest links are supported.")
    return "qoj", match[1], f"https://{p.hostname}{p.path.rstrip('/')}"


def seconds(value: str) -> int:
    parts = [int(x) for x in value.strip().split(":")]
    if len(parts) == 2:
        return parts[0] * 3600 + parts[1] * 60
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise VPError(f"Invalid contest time: {value!r}")


def timestamp(value: str, timezone: str = "Asia/Shanghai") -> float:
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(timezone))
        return dt.timestamp()
    except ValueError as exc:
        raise VPError(f"Invalid platform timestamp: {value!r}") from exc


def js_value(html: str, key: str, default=None):
    # Decode JSON literals only. Never execute platform JavaScript.
    match = re.search(r"(?<![\w.])(?:var\s+)?" + re.escape(key) + r"\s*=\s*", html)
    if not match:
        return default
    try:
        return json.JSONDecoder().raw_decode(html[match.end():])[0]
    except ValueError:
        return default


# Chinese contest titles never spell out ICPC/CCPC and separate the province from
# the word 省赛 ("provincial contest"). Both are mapped to the same vocabulary the
# archives use, so a provincial site keeps the archive path it is published under.
# A provincial title names its own province, so 大学生程序设计竞赛 alone means CCPC.
# An English provincial title writes "Collegiate Programming Contest" and omits
# the series entirely; among those, a provincial contest is CCPC by convention.
_SERIES_WORDS = (("中国大学生程序设计竞赛", "CCPC"), ("大学生程序设计竞赛", "CCPC"), ("CCPC", "CCPC"),
                 ("国际大学生程序设计竞赛", "ICPC"), ("ICPC", "ICPC"),
                 ("Collegiate Programming Contest", "CCPC"))
_PROVINCES = ("东北", "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
              "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
              "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏",
              "新疆", "香港", "澳门", "台湾")
# XCPCIO spells a provincial directory as full pinyin, not the two-letter form
# the SRK repository uses, so every province needs its own entry.
_PROVINCE_SLUGS = {"北京": "beijing", "天津": "tianjin", "河北": "hebei", "山西": "shanxi",
                   "内蒙古": "neimenggu", "辽宁": "liaoning", "吉林": "jilin",
                   "黑龙江": "heilongjiang", "上海": "shanghai", "江苏": "jiangsu",
                   "浙江": "zhejiang", "安徽": "anhui", "福建": "fujian", "江西": "jiangxi",
                   "山东": "shandong", "河南": "henan", "湖北": "hubei", "湖南": "hunan",
                   "广东": "guangdong", "广西": "guangxi", "海南": "hainan", "重庆": "chongqing",
                   "四川": "sichuan", "贵州": "guizhou", "云南": "yunnan", "西藏": "xizang",
                   "陕西": "shaanxi", "甘肃": "gansu", "青海": "qinghai", "宁夏": "ningxia",
                   "新疆": "xinjiang", "香港": "hongkong", "澳门": "macao", "台湾": "taiwan",
                   "东北": "northeast"}
# srk-collection names provincial directories by two-letter pinyin initials,
# except the North-East combined contest. Where initials collide the repository
# assigns them by documented convention rather than pinyin order, so these
# follow the directories themselves rather than the provinces' spelling.
# English titles name the province instead of using 省赛, so an English spelling
# has to resolve to the same province the archives key on.
_PROVINCE_ENGLISH = {
    "Anhui": "安徽", "Beijing": "北京", "Chongqing": "重庆", "Fujian": "福建",
    "Gansu": "甘肃", "Guangdong": "广东", "Guangxi": "广西", "Guizhou": "贵州",
    "Hainan": "海南", "Hebei": "河北", "Heilongjiang": "黑龙江", "Henan": "河南",
    "Hubei": "湖北", "Hunan": "湖南", "Inner Mongolia": "内蒙古", "Jiangsu": "江苏",
    "Jiangxi": "江西", "Jilin": "吉林", "Liaoning": "辽宁", "Ningxia": "宁夏",
    "Qinghai": "青海", "Shaanxi": "陕西", "Shandong": "山东", "Shanghai": "上海",
    "Shanxi": "山西", "Sichuan": "四川", "Tianjin": "天津", "Tibet": "西藏",
    "Xinjiang": "新疆", "Yunnan": "云南", "Zhejiang": "浙江",
    "Hong Kong": "香港", "Macau": "澳门", "Macao": "澳门", "Taiwan": "台湾",
}
_PROVINCE_ABBREVIATIONS = {"安徽": "ah", "北京": "bj", "重庆": "cq", "福建": "fj", "广东": "gd",
                           "广西": "gx", "贵州": "gz", "河南": "ha", "河北": "he", "湖北": "hb",
                           "湖南": "hn", "黑龙江": "hl", "吉林": "jl", "江苏": "js", "江西": "jx",
                           "辽宁": "ln", "内蒙古": "nm", "四川": "sc", "山东": "sd", "上海": "sh",
                           "陕西": "sn", "山西": "sx", "新疆": "xj", "浙江": "zj", "东北": "northeast"}


def directory_name(titles: list[str]) -> str:
    for title in titles:
        # Recent CCPC titles pair a Chinese name with a complete English name.
        paired = [part for part in re.findall(r"[（(]([^（）()]+)[）)]", title)
                  if re.search(r"\b(?:ICPC|CCPC)\b", part, re.I) and re.search(r"\b20\d{2}\b", part)]
        if paired:
            # The paired English name carries the searchable series and site, but
            # the Chinese half still holds 省赛 / 邀请, so keep both.
            title = paired[-1] + " " + title
        year = re.search(r"(?<![0-9])(20\d{2})(?![0-9])", title)
        if not year:
            continue
        series = next((code for word, code in _SERIES_WORDS if re.search(r"(?<![A-Za-z])" + word + r"(?![A-Za-z])", title, re.I)), None)
        if not series:
            continue
        province = _province_of(title)
        # A provincial title states its province instead of writing 省赛.
        provincial = re.search(r"省赛|省级|Provincial", title, re.I) or (
            province and re.search(r"大学生程序设计竞赛|Collegiate Programming Contest", title, re.I))
        kind = ("Reg" if re.search(r"Regional|区域|\bSite\b", title, re.I)
                else "Inv" if re.search(r"Invitational|邀请", title, re.I)
                else "Pro" if provincial else None)
        # Titles that already carry the archive's trailing suffix need no mapping.
        if not kind:
            kind = re.search(r"(?<![A-Za-z])(Reg|Inv|Pro)(?![A-Za-z])", title).group(1) if re.search(
                r"(?<![A-Za-z])(Reg|Inv|Pro)(?![A-Za-z])", title) else None
        if not kind:
            continue
        if kind == "Pro" and province:
            # The province alone names a provincial site; the ordinal and the
            # paired Latin name would only add noise to the directory.
            return f"{year[1]} {series} {province} Pro"
        site = title
        patterns = [r"(?<![0-9])20\d{2}(?![0-9])", r"(?<![A-Za-z])ICPC(?![A-Za-z])", r"(?<![A-Za-z])CCPC(?![A-Za-z])",
                    r"(?<![A-Za-z])Collegiate(?![A-Za-z])",
                    r"(?<![A-Za-z])Asia(?:\s+East)?(?![A-Za-z])",
                    r"(?<![A-Za-z])(?:The|Contest|Regional|Invitational|Provincial|Programming|Collegiate|China|International|Chinese|University|Finals?|Championship|Site)(?![A-Za-z])",
                    r"\b\d+(?:st|nd|rd|th)\b", r"(?<![A-Za-z])(?:Reg|Inv|Pro)(?![A-Za-z])",
                    r"第[一二三四五六七八九十百零〇\d]+届", "大学生程序设计竞赛", "程序设计竞赛", "省赛"]
        for pattern in patterns:
            site = re.sub(pattern, " ", site, flags=re.I)
        site = re.sub(r"[()\[\]:,/\\\-–—]+", " ", site)
        site = " ".join(site.split()).strip(" .")
        if site:
            return f"{year[1]} {series} {site} {kind}"
    raise VPError("The platform does not identify an ICPC/CCPC year, site and Reg/Inv/Pro contest name.")


def _province_of(title: str) -> str | None:
    # 东北 must name the region, not a school such as 东北林业大学.
    if re.search(r"东北(?:地区|赛区|三省)", title):
        return "东北"
    # An English title spells the province out (Jiangsu, Inner Mongolia).
    for english, chinese in _PROVINCE_ENGLISH.items():
        if re.search(r"(?<![A-Za-z])" + re.escape(english) + r"(?![A-Za-z])", title, re.I):
            return chinese
    return next((name for name in _PROVINCES if name != "东北" and name in title), None)


def provincial_archive(contest) -> str | None:
    """XCPCIO publishes provincial contests apart from the regional series."""
    match = re.fullmatch(r"(20\d\d) (ICPC|CCPC) (\S+) Pro", contest.name)
    if not match:
        return None
    return f"data/provincial-contest/{match[1]}/{_PROVINCE_SLUGS.get(match[3], match[3].lower())}"


def is_provincial(contest) -> bool:
    return re.fullmatch(r"(20\d\d) (ICPC|CCPC) (\S+) Pro", contest.name) is not None


def provincial_series(contest) -> tuple[str, str] | None:
    """The series and province a provincial contest name declares."""
    match = re.fullmatch(r"(20\d\d) (ICPC|CCPC) (\S+) Pro", contest.name)
    return (match[2], match[3]) if match else None


def ccpc_reveal_count(name: str) -> int | None:
    match = re.fullmatch(r"(20\d{2}) CCPC .+ Reg", name)
    return 50 if match and int(match[1]) >= 2026 else None


def medals_from_html(html: str, source: str) -> Medals | None:
    cutoffs = js_value(html, "medals_cutoff")
    if cutoffs and len(cutoffs) == 3 and all(isinstance(x, int) for x in cutoffs):
        if 0 <= cutoffs[0] <= cutoffs[1] <= cutoffs[2]:
            return Medals(cutoffs[0], cutoffs[1]-cutoffs[0], cutoffs[2]-cutoffs[1], source)
    return None
