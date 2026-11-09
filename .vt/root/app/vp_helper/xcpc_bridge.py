"""Bridge one native QOJ VP into the xcpc-vp browser replay.

The web app replays a RankLand ranklist and keeps its own submissions in
browser storage. This module serves the page, picks the matching contest, and
publishes every judge-verified submission to a small file the page polls, so
the replay records results without manual entry.
"""
from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from . import webui

_RANKLAND_V2 = "https://rl.algoux.cn/api/v2/public/contests"
_BASE_PORT = 5174


def enabled() -> bool:
    return os.environ.get("VP_XCPC", "1") not in ("0", "false", "no")


def _title(contest) -> str:
    return (contest.extra.get("original_title") or contest.name or "").strip()


def _normalize(text: str) -> str:
    return re.sub(r"[\s\u3000（）()【】\[\]、，,·:：\-—–的“”]", "", text or "").lower()


def _rankland_contests() -> list[dict]:
    """Every publicly listed contest, without an account."""
    try:
        with urlopen(_RANKLAND_V2, timeout=20) as response:
            return json.load(response)["data"]["contests"]
    except Exception:
        return []


# The judge writes the seat in English (Nanjing), the archive in Chinese (南京),
# so both spellings have to resolve to one place. XCPC venues only.
_SEATS = {
    "nanjing": "南京", "beijing": "北京", "shanghai": "上海", "guangzhou": "广州",
    "shenzhen": "深圳", "hangzhou": "杭州", "chengdu": "成都", "wuhan": "武汉",
    "xian": "西安", "xi\'an": "西安", "tianjin": "天津", "chongqing": "重庆",
    "shenyang": "沈阳", "harbin": "哈尔滨", "changchun": "长春", "dalian": "大连",
    "jinan": "济南", "qingdao": "青岛", "zhengzhou": "郑州", "changsha": "长沙",
    "nanchang": "南昌", "fuzhou": "福州", "xiamen": "厦门", "kunming": "昆明",
    "guiyang": "贵阳", "lanzhou": "兰州", "taiyuan": "太原", "hefei": "合肥",
    "yinchuan": "银川", "huhehaote": "呼和浩特", "hohhot": "呼和浩特",
    "guilin": "桂林", "haikou": "海口", "shijiazhuang": "石家庄", "ningbo": "宁波",
    "suzhou": "苏州", "wuxi": "无锡", "harbin": "哈尔滨", "hongkong": "香港",
    "hong kong": "香港", "macau": "澳门", "macao": "澳门", "taibei": "台北",
}


def _site_words(title: str) -> set[str]:
    """The place a title names: a province, a seat city, or the North-East region."""
    from .parsing import _PROVINCES
    words = {name for name in _PROVINCES if name in title}
    # A seat is what distinguishes one station of a series from another. The
    # Chinese anchor must be a suffix (区域赛南京站), not a word boundary inside
    # the title, so seat names are matched directly instead of by regex.
    for chinese in set(_SEATS.values()):
        if chinese in title:
            words.add(chinese)
    lowered = title.lower()
    for english, chinese in _SEATS.items():
        if english in lowered:
            words.add(chinese)
    return words


def find_contest(title: str) -> str | None:
    """The single RankLand contest key whose declared title names this one.

    The judge and the archive write the same edition differently (第十届 vs
    第 10 届, a year vs no year at all), so the comparison keeps the series,
    requires a shared place, and then takes the candidate sharing the longest
    run of characters. A tie stays unresolved and the page opens on its finder.
    """
    from .srk import _series_conflict, edition_in
    wanted = _site_words(title)
    flat = _normalize(title)
    if not wanted or not flat:
        return None
    years = set(re.findall(r"\d{4}", title))
    scored = []
    for item in _rankland_contests():
        declared = (item.get("title") or {}).get("zh-CN") or item.get("name") or ""
        if not declared or _series_conflict(declared, title):
            continue
        if not (wanted & _site_words(declared)):
            continue
        # The archive often states the ordinal only; its own start date still
        # carries the year the judge names.
        declared_years = set(re.findall(r"\d{4}", declared))
        started = str(item.get("startAt") or "")[:4]
        if started.isdigit():
            declared_years.add(started)
        left, right = edition_in(title), edition_in(declared)
        if not ((years & declared_years) or (left is not None and left == right)):
            continue
        other = _normalize(declared)
        scored.append((_common(flat, other), item["uk"], other))
    if not scored:
        return None
    best = max(size for size, _, _ in scored)
    top = [(uk, other) for size, uk, other in scored if size == best]
    if len(top) == 1:
        return top[0][0]
    # One contest is published twice, once under its series key and once under
    # its provincial key; both open the same ranklist, so prefer the series one.
    series = [uk for uk, _ in top if re.match(r"^(?:icpc|ccpc)\d{4}", uk)]
    return series[0] if len(series) == 1 else None


def _common(left: str, right: str) -> int:
    """Length of the longest run of characters two titles share."""
    best = 0
    previous = [0] * (len(right) + 1)
    for i in range(1, len(left) + 1):
        current = [0] * (len(right) + 1)
        for j in range(1, len(right) + 1):
            if left[i - 1] == right[j - 1]:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def _china_time(timestamp: float) -> str:
    """A China-time ISO string; the page reads bare times in that zone."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp + 8 * 3600)) + "+08:00"


def page_url(contest, team: str, organization: str, start_time: float, port: int) -> tuple[str, str | None]:
    """The address to open by hand, plus the contest key it selected.

    The page derives its clock from ``at``, so anchoring it on the native VP's
    own start keeps both timers on the same zero and the mirrored submission
    times line up with the replay.
    """
    key = find_contest(_title(contest))
    query = {"play": "1", "at": _china_time(start_time), "rule": "auto"}
    if key:
        query["contest"] = key
    if team.strip():
        query["team"] = team.strip()
    if organization.strip():
        query["organization"] = organization.strip()
    return f"http://127.0.0.1:{port}/?" + urlencode(query), key


def port() -> int:
    return int(os.environ.get("VP_XCPC_PORT", _BASE_PORT))


def prepare(contest, team: str, organization: str, start_time: float) -> tuple[str, str | None]:
    """Serve the page and build its address; opening it stays the user's job.

    Launching a browser from a terminal is unreliable across distributions and
    desktop sessions, so the URL is printed instead of passed to an opener.
    """
    number = port()
    webui.ensure_served(number)
    return page_url(contest, team, organization, start_time, number)


# The judge names a verdict, the replay names a submission result.
_RESULTS = {
    "CORRECT": "AC", "WRONG-ANSWER": "WA", "TIMELIMIT": "TLE", "MEMORY-LIMIT": "MLE",
    "RUN-ERROR": "RTE", "COMPILER-ERROR": "CE", "OUTPUT-LIMIT": "OLE", "NO-OUTPUT": "NOUT",
}


def channel_payload(contest, key: str | None, submissions: list, start_time: float) -> dict:
    """Submissions shaped for the page's manual-submission records."""
    order = list(contest.problems)
    events = []
    for item in submissions:
        result = _RESULTS.get(item.verdict)
        if result is None or item.problem not in order:
            continue
        events.append({"problemIndex": order.index(item.problem),
                       "timeMs": int(round(item.time * 1000)), "result": result})
    return {"type": "sync", "contest": key, "events": events}


def write_channel(payload: dict) -> None:
    """Hand the payload to the open page through a small file the page polls.

    A terminal has no BroadcastChannel, so the page watches this file instead;
    it is the same message the page would have received through the channel.
    """
    path = webui.state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf8")
    os.replace(temporary, path)
