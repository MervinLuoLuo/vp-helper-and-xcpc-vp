"""Read original CCPC eligibility and timelines from public SRK archives."""
from __future__ import annotations

import math
import json
import re
from urllib.parse import urlsplit

import requests

from .models import Cell, Contest, Submission, TeamScore, VPError
from .parsing import (_PROVINCE_ABBREVIATIONS, is_provincial, provincial_series, timestamp)
from .scoring import score_submissions, verdict


def source_url(contest: Contest) -> str | None:
    if is_provincial(contest):
        return provincial_source(contest)
    match = re.fullmatch(r"(20\d{2}) CCPC ([A-Za-z][A-Za-z .-]*) Reg", contest.name)
    if not match:
        return None
    year, site = match.groups()
    slug = re.sub(r"[ .-]+", "", site.lower())
    return ("https://raw.githubusercontent.com/algoux/srk-collection/master/official/ccpc/ccpc"
            + year + "/ccpc" + year + slug + ".srk.json")


_RAW = "https://raw.githubusercontent.com/algoux/srk-collection/master/{}"
_INDEX = "https://github.com/algoux/srk-collection/tree/master/{}"


def _index(directory: str) -> list[str]:
    """File names of one repository directory; raw endpoints cannot list them."""
    try:
        with requests.Session() as public:
            response = public.get(_INDEX.format(directory), timeout=(10, 30),
                                  headers={"Accept": "text/html"})
            response.raise_for_status()
    except requests.RequestException:
        return []
    return sorted(set(re.findall(r"[A-Za-z0-9_.-]+\.srk\.json", response.text)))


def _title_of(data) -> tuple[str, str]:
    """The Chinese title an SRK archive declares, plus its start year.

    Several editions state only the ordinal (第二十届...), so the year is read
    from startAt instead of being guessed from the file name.
    """
    if not isinstance(data, dict):
        return "", ""
    contest = data.get("contest") or {}
    title = contest.get("title") or {}
    found = ""
    if isinstance(title, str):
        found = title
    elif isinstance(title, dict):
        for key in ("zh-CN", "fallback"):
            if isinstance(title.get(key), str):
                found = title[key]
                break
    start = contest.get("startAt")
    return found, start[:4] if isinstance(start, str) else ""


def _series_conflict(left: str, right: str) -> bool:
    """Whether two titles name different series. A title may omit its series."""
    stated = {word for word in ("icpc", "ccpc") if word in right.lower()}
    return bool(stated) and not any(word in left.lower() for word in stated)


def _title_matches(title: str, expected: str) -> bool:
    """Whether an archive title names the same contest as the platform title."""
    def normalize(text: str) -> str:
        return re.sub(r"[\s（）()【】\[\]、，,·:：\-—–的“”]", "", text or "").lower()

    left, right = normalize(title), normalize(expected)
    if not left or not right:
        return False
    if left == right:
        return True
    # An invitation also hosts its province's contest, so the archive may name
    # either. Require the province to agree and a shared edition or year, and
    # never accept a title that contradicts the requested series.
    if _series_conflict(left, right):
        return False
    province = _province_in(right)
    if province is None or province not in _place_of(left):
        return False
    numbers = set(re.findall(r"\d+", left)) & set(re.findall(r"\d+", right))
    # The ordinal alone identifies an edition whose year the archive omits.
    left_edition, right_edition = edition_in(left), edition_in(right)
    return bool(numbers) or (left_edition is not None and left_edition == right_edition)


def edition_in(text: str) -> int | None:
    """The 第N届 ordinal a title states in Chinese or Arabic numerals."""
    match = re.search(r"第\s*([一二三四五六七八九十百零〇\d]+)\s*届", text)
    if not match:
        return None
    digits = match[1]
    if digits.isdigit():
        return int(digits)
    values = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    total = current = 0
    for char in digits:
        if char in values:
            current = values[char]
        elif char == "十":
            total, current = total + (current or 1) * 10, 0
        elif char == "百":
            total, current = total + (current or 1) * 100, 0
        else:
            return None
    return total + current if total or current else None


_PROVINCE_WORDS = {name: name for name in _PROVINCE_ABBREVIATIONS}


def _place_of(text: str) -> str:
    """The regions a title can name, with 东北 resolved as a region or absent."""
    places = [name for name in _PROVINCE_WORDS if name != "东北" and name in text]
    if re.search(r"东北(?:地区|赛区|三省)", text):
        places.append("东北")
    return " ".join(places)


def _province_in(text: str) -> str | None:
    # 东北 must name the region, not a school such as 东北林业大学.
    if re.search(r"东北(?:地区|赛区|三省)", text):
        return "东北"
    return next((name for name in _PROVINCE_WORDS if name != "东北" and name in text), None)


def provincial_source(contest: Contest) -> str | None:
    """Find the provincial archive whose declared title names this contest.

    Series directories are searched first because a provincial contest that is
    also a national invitational is published there under the invitation name.
    """
    series = provincial_series(contest)
    if series is None:
        return None
    kind, province = series
    year = re.match(r"(20\d\d)", contest.name).group(1)
    title = contest.extra.get("original_title") or contest.name
    directories = [f"official/{kind.lower()}/{kind.lower()}{year}"]
    abbreviation = _PROVINCE_ABBREVIATIONS.get(province)
    if abbreviation:
        directories.append(f"official/provincial/{abbreviation}")
    for directory in directories:
        fallback = []
        for name in _index(directory):
            url = _RAW.format(directory + "/" + name)
            found = _archive_title(url)
            if not found:
                continue
            archived, started = found
            if _title_matches(archived, title):
                return url
            # A title may state only the edition (第二十届...) while the platform
            # states only the year. The archive's own start date decides then.
            if _same_place(archived, title) and started and started == year:
                fallback.append(url)
        if len(fallback) == 1:
            return fallback[0]
    return None


def _same_place(title: str, expected: str) -> bool:
    """Same series and province, ignoring any edition or year spelling."""
    if _series_conflict(title, expected):
        return False
    province = _province_in(expected)
    return province is not None and province in _place_of(title)


def _archive_title(url: str):
    try:
        from .originals import archive_json
        with requests.Session() as public:
            return _title_of(archive_json(public, url))
    except (requests.RequestException, VPError, ValueError):
        return None


def _seconds(value) -> float:
    units = {"ms": 0.001, "s": 1, "min": 60, "h": 3600}
    if (not isinstance(value, list) or len(value) != 2 or type(value[0]) not in (int, float)
            or value[1] not in units or not math.isfinite(value[0]) or value[0] < 0):
        raise ValueError("invalid SRK duration")
    return value[0] * units[value[1]]


def _names(value) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, dict):
        values = [value.get(k) for k in ("fallback", "zh-CN", "en-US")]
        names = list(dict.fromkeys(v for v in values if isinstance(v, str) and v.strip()))
        if names:
            return names
    raise ValueError("missing SRK identity")


def metadata(data: dict, contest: Contest, source: str) -> dict:
    try:
        config = data["sorter"]["config"]
        # Provincial exports name this field timePrecision; the series exports
        # name it rankingTimePrecision. Both carry the same minute-based rule.
        precision = config.get("rankingTimePrecision") or config.get("timePrecision")
        if data["sorter"]["algorithm"] != "ICPC" or precision != "min":
            raise ValueError("unsupported SRK scoring")
        duration = _seconds(data["contest"]["duration"])
        penalty = _seconds(data["sorter"]["config"]["penalty"])
        labels = [p["alias"] for p in data["problems"]]
        if (int(duration) != duration or penalty % 60 or labels != list(contest.problems)
                or duration < contest.rules.duration):
            raise ValueError("SRK rules do not match")
        # The archive must identify the exact judge problems, not just a city.
        # Provincial exports link the site-wide problem page, while series exports
        # link the contest-scoped one; both name the same judge problem ID.
        for problem in data["problems"]:
            link = urlsplit(problem["link"])
            base = urlsplit(contest.url)
            identity = contest.problems[problem["alias"]]
            expected = (base.path + "/problem/" + identity, "/problem/" + identity)
            if link.hostname != base.hostname or link.path not in expected:
                raise ValueError("SRK problems do not match this contest")
        teams = []
        groups = {}
        for row in data["rows"]:
            user = {k: v for k, v in row["user"].items() if k != "id"}
            groups.setdefault(json.dumps(user, sort_keys=True), []).append(row)
        ignored, empty_names = [], []
        for group in groups.values():
            if len(group) < 2:
                continue
            if not group[0]["user"].get("teamMembers"):
                raise ValueError("duplicate team without member identity")
            active = [r for r in group if r["score"]["value"] or any(
                s.get("solutions") or s.get("tries") or s.get("result") for s in r["statuses"])]
            if len(active) > 1:
                raise ValueError("duplicate active team histories")
            keep = active[0] if active else group[0]
            for duplicate in group:
                if duplicate is keep:
                    continue
                if _seconds(duplicate["score"]["time"]) != 0:
                    raise ValueError("duplicate team has a nonempty score")
                ignored.append(str(duplicate["user"]["id"]))
                empty_names.append(_names(keep["user"]["name"])[0] + " (" + _names(keep["user"]["organization"])[0] + ")")
        identities = set()
        for row in data["rows"]:
            user = row["user"]
            ident = str(user["id"])
            if ident in ignored:
                continue
            if not ident or ident == "me" or ident in identities or type(user.get("official")) is not bool:
                raise ValueError("ambiguous SRK team")
            identities.add(ident)
            names, organizations = _names(user["name"]), _names(user["organization"])
            aliases = [name + " (" + organization + ")" for name in names for organization in organizations]
            # QOJ's comma-delimited ghost import can retain only the last part
            # of a comma-containing name. School, eligibility and every final
            # problem cell must still match; ambiguous aliases are rejected.
            aliases += [name.rsplit(",", 1)[-1].strip() + " (" + organization + ")"
                        for name in names if "," in name and name.rsplit(",", 1)[-1].strip()
                        for organization in organizations]
            aliases = list(dict.fromkeys(aliases))
            teams.append({"id": ident, "name": aliases[0], "aliases": aliases,
                          "official": user["official"]})
        medals = None
        for series in data.get("series", []):
            rule = series.get("rule", {})
            counts = rule.get("options", {}).get("count", {}).get("value")
            styles = [s.get("style") for s in series.get("segments", [])]
            if (rule.get("preset") == "ICPC" and styles == ["gold", "silver", "bronze"]
                    and isinstance(counts, list) and len(counts) == 3
                    and all(type(n) is int and n >= 0 for n in counts)):
                medals = dict(zip(("gold", "silver", "bronze"), counts))
                break
        return {"version": 1, "contest_name": contest.name, "duration": int(duration),
                "penalty_minutes": int(penalty // 60), "problems": labels,
                "problem_ids": {str(i): p for i, p in enumerate(labels)},
                "source": source, "source_format": "srk", "teams": teams, "medals": medals,
                "ignored_empty_team_ids": ignored, "ignored_empty_team_names": empty_names,
                "original_start": timestamp(data["contest"]["startAt"])}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise VPError("The SRK archive does not match the contest, judge problem IDs, or explicit team eligibility.") from None


def _floors_solve_times(data: dict, metadata: dict, contest: Contest) -> bool:
    """Whether the declared totals truncate each solve time to whole minutes.

    Provincial exports do; series exports keep the exact second. Deciding from
    the archive itself avoids pinning the choice to a file path.
    """
    ignored = set(metadata.get("ignored_empty_team_ids", []))
    found = False
    for row in data["rows"]:
        if str(row["user"]["id"]) in ignored:
            continue
        declared = _seconds(row["score"]["time"])
        exact = floored = 0.0
        for status in row["statuses"]:
            if status.get("result") not in ("AC", "FB"):
                continue
            at = _seconds(status["time"])
            penalty = contest.rules.penalty_minutes * 60 * (status["tries"] - 1)
            exact += at + penalty
            floored += int(at // 60) * 60 + penalty
        if abs(declared - exact) > 0.001:
            found = True
            if abs(declared - floored) > 0.001:
                return False
    return found


def submissions(data: dict, metadata: dict, contest: Contest) -> list[Submission]:
    events, expected = [], []
    teams = {team["id"]: team for team in metadata["teams"]}
    floored = _floors_solve_times(data, metadata, contest)
    try:
        for row in data["rows"]:
            if str(row["user"]["id"]) in metadata.get("ignored_empty_team_ids", []):
                continue
            team = teams[str(row["user"]["id"])]
            if len(row["statuses"]) != len(contest.problems):
                raise ValueError("incomplete SRK statuses")
            cells, raw_time = {}, 0.0
            for label, status in zip(contest.problems, row["statuses"]):
                accepted = status.get("result") in ("AC", "FB")
                tries = status.get("tries", 0)
                if type(tries) is not int or tries < 0 or status.get("result") == "?":
                    raise ValueError("incomplete SRK result")
                at = _seconds(status["time"]) if accepted else None
                cells[label] = Cell(tries, 0, accepted, int(at // 60) if at is not None else None)
                if accepted:
                    if not tries:
                        raise ValueError("accepted SRK problem without attempt")
                    # Provincial exports declare a minted solve time floored per
                    # problem; series exports keep the exact second. Follow the
                    # declared total so the archive stays self-consistent.
                    minute = int(at // 60) * 60 if floored else at
                    raw_time += minute + contest.rules.penalty_minutes * 60 * (tries - 1)
                for solution in status.get("solutions", []):
                    code = solution["result"]
                    if code in ("NOUT", "UKE") and code in data["sorter"]["config"].get("noPenaltyResults", []):
                        continue
                    result = verdict({"FB": "AC", "RTE": "RE", "PE": "WA"}.get(code, code))
                    event_time = _seconds(solution["time"])
                    if result in ("PENDING", "TOO-LATE") or not 0 <= event_time < contest.rules.duration:
                        raise ValueError("nonfinal or out-of-window SRK event")
                    events.append(Submission(str(len(events) + 1), team["id"], label, event_time, result))
            final = TeamScore(team["id"], team["name"], cells, eligible=team["official"],
                              penalty_minutes=contest.rules.penalty_minutes)
            if final.solved != row["score"]["value"] or not math.isclose(raw_time, _seconds(row["score"]["time"]), abs_tol=0.001):
                raise ValueError("SRK declared score is inconsistent")
            expected.append(final)
        grouped = {team: [] for team in teams}
        for event in events:
            grouped[event.team].append(event)
        for final in expected:
            actual = score_submissions(grouped[final.id], list(contest.problems), contest.rules,
                                       contest.rules.duration, team_id=final.id)
            if actual.cells != final.cells:
                raise ValueError("SRK histories do not reproduce every final cell")
        return events
    except (KeyError, TypeError, ValueError, AttributeError, VPError):
        raise VPError("The SRK submission histories do not reproduce the original final scores.") from None
