"""Archive routing checks: offline title matching and path derivation."""
from vp_helper.models import Contest, Rules
from vp_helper.parsing import directory_name, is_provincial, provincial_archive, provincial_series
from vp_helper.srk import edition_in, _place_of, _same_place, _title_matches


def contest(title: str) -> Contest:
    name = directory_name([title])
    return Contest("qoj", "1", "https://qoj.ac/contest/1", name, name, {},
                   Rules(5 * 3600, 20), extra={"original_title": title})


def demo() -> None:
    # A provincial title never spells out its series.
    liaoning = contest("（2025）第六届辽宁省大学生程序设计竞赛 (沈阳)")
    assert liaoning.name == "2025 CCPC 辽宁 Pro", liaoning.name
    assert is_provincial(liaoning) and provincial_series(liaoning) == ("CCPC", "辽宁")
    assert provincial_archive(liaoning) == "data/provincial-contest/2025/liaoning"

    # Regional names keep their existing mapping.
    assert contest("The 2025 ICPC Asia Shenyang Regional Contest").name == "2025 ICPC Shenyang Reg"
    assert contest("2025 CCPC Harbin Reg").name == "2025 CCPC Harbin Reg"
    assert not is_provincial(contest("2025 CCPC Harbin Reg"))

    # An archive title may omit the year, so the ordinal has to carry it.
    assert edition_in("第六届辽宁省大学生程序设计竞赛") == 6
    assert edition_in("第 8 届 CCPC 河南省大学生程序设计竞赛") == 8
    assert _title_matches("第六届辽宁省大学生程序设计竞赛",
                          "（2025）第六届辽宁省大学生程序设计竞赛 (沈阳)")
    # The same invite hosts a province contest; the province and edition decide.
    assert _title_matches("2025 CCPC 全国邀请赛（南昌）暨第二届江西省赛 - 正式赛",
                          "2025 CCPC 全国邀请赛（南昌）暨第二届江西省赛 - 正式赛")
    # A different series or province must never match.
    assert not _title_matches("2025 ICPC 河南省大学生程序设计竞赛",
                              "2025CCPC全国邀请赛（郑州）暨第七届河南省赛")
    assert not _title_matches("2024 ICPC 河南省大学生程序设计竞赛",
                              "2025 ICPC 河南省大学生程序设计竞赛")

    # 东北 names a region, so a school called 东北林业大学 must not claim it.
    assert _place_of("2019年中国大学生程序设计竞赛 哈尔滨站-东北林业大学") == ""
    assert _place_of("第二十届东北地区大学生程序设计竞赛") == "东北"
    assert not _same_place("2019年中国大学生程序设计竞赛 哈尔滨站-东北林业大学",
                           "2019 东北地区大学生程序设计竞赛")
    # The archive states only the ordinal; the year comes from startAt instead.
    assert _same_place("第二十届东北地区大学生程序设计竞赛", "2026 东北地区大学生程序设计竞赛")

    # The bridge renames a judge verdict to the replay's submission result.
    from vp_helper.models import Submission
    from vp_helper.xcpc_bridge import _common, channel_payload
    liaoning = Contest("qoj", "2642", "https://qoj.ac/contest/2642", liaoning.name, liaoning.name,
                       {chr(65 + i): str(14742 + i) for i in range(13)}, Rules(5 * 3600, 20))
    payload = channel_payload(liaoning, "lncpc6th", [
        Submission("1", "me", "A", 600.0, "CORRECT"),
        Submission("2", "me", "B", 900.5, "WRONG-ANSWER"),
        Submission("3", "me", "C", 1200.0, "PENDING"),
    ], 0.0)
    assert [e["result"] for e in payload["events"]] == ["AC", "WA"], payload
    assert payload["events"][1]["timeMs"] == 900500
    # "AC,WA" is QOJ's offline-pass / hacked-later status: a wrong answer.
    from vp_helper.scoring import verdict
    assert verdict("AC,WA") == "WRONG-ANSWER"
    assert verdict("AC, WA") == "WRONG-ANSWER"
    assert verdict("AC") == "CORRECT"
    assert _common("abcd", "xbcdy") == 3
    # Both timers anchor on the native VP start, so a submission offset lands on
    # the same virtual second in the replay.
    from vp_helper.xcpc_bridge import _china_time
    start = 1793851906.0
    assert _china_time(start).endswith("+08:00")
    assert abs((start + 900 - start) * 1000 - 900000) < 1
    # The address is printed, never handed to an opener, and carries the team
    # plus the judge's own start so both clocks share one zero.
    from urllib.parse import parse_qs, urlsplit
    from vp_helper.xcpc_bridge import page_url
    url, _ = page_url(liaoning, "队 名", "某大学", start, 5174)
    parts = urlsplit(url)
    assert parts.hostname == "127.0.0.1" and parts.port == 5174, url
    query = parse_qs(parts.query)
    assert query["team"] == ["队 名"] and query["organization"] == ["某大学"], query
    assert query["play"] == ["1"] and query["at"] == [_china_time(start)], query


if __name__ == "__main__":
    demo()
    print("ok")
