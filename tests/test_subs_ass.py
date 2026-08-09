"""ass.py 工具函数测试 —— 重点防 SRT 毫秒/1000 与 ASS 厘秒/100 混淆回归。"""
from mediaforge.subs.ass import (
    ts2sec, sec2ts, parse_srt, parse_ass, norm_tokens, _EN_INLINE,
)


def test_ts2sec_ass_centisecond():
    # ASS 厘秒（2位小数）
    assert ts2sec("0:00:07.50") == 7.5
    assert ts2sec("0:02:15.10") == 135.1
    assert ts2sec("1:00:00.00") == 3600.0


def test_sec2ts_roundtrip():
    for t in (0.0, 1.5, 135.1, 3600.0, 3661.25):
        assert abs(ts2sec(sec2ts(t)) - t) < 0.011


def test_parse_srt_millisecond():
    """SRT 毫秒是 3 位小数，必须 /1000 不是 /100（回归坑）。"""
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False, encoding="utf-8") as f:
        f.write("1\n00:00:07,758 --> 00:00:11,388\nhey you kids\n\n")
        p = f.name
    try:
        cues = parse_srt(p)
        assert len(cues) == 1
        st, en, txt = cues[0]
        assert abs(st - 7.758) < 0.001, f"start={st} 应为 7.758"
        assert abs(en - 11.388) < 0.001, f"end={en} 应为 11.388"
    finally:
        os.unlink(p)


def test_parse_srt_strips_sdh_brackets():
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False, encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:02,500\n[alarm blaring] come on\n\n")
        p = f.name
    try:
        cues = parse_srt(p)
        assert "alarm" not in cues[0][2]
        assert "come on" in cues[0][2]
    finally:
        os.unlink(p)


def test_parse_ass_extracts_english():
    import tempfile, os
    content = (
        "[Script Info]\nPlayResX: 1920\nPlayResY: 1080\n\n"
        "[V4+ Styles]\nFormat: Name\nStyle: Default,Arial,62,...,2,36,0,0,0,1,3,1.5\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,中文主行\\N{\\fs38\\c&H00D7D7D7&\\b0}English line here\n"
        "Dialogue: 0,0:00:05.00,0:00:06.00,片头1,,0,0,0,,片头特效\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".ass", delete=False, encoding="utf-8") as f:
        f.write(content)
        p = f.name
    try:
        cues = parse_ass(p)
        dlg = [c for c in cues if c.is_dialogue]
        assert len(dlg) == 1
        assert "english line here" in dlg[0].eng
        assert abs(dlg[0].start - 1.0) < 0.001
        assert abs(dlg[0].end - 4.0) < 0.001
        # 片头署名样式不算对白
        assert not any(c.is_credit and c.is_dialogue for c in cues)
    finally:
        os.unlink(p)


def test_norm_tokens():
    # 撇号被当分隔符拆成 i+m（ASS/SDH 两边同样处理，匹配不受影响）
    assert norm_tokens("I'm 中文 hello") == {"i", "m", "hello"}
    assert norm_tokens("") == set()