"""inspect 判定逻辑测试 —— 各 verdict 分支。"""
from mediaforge.subs.inspect import judge


def test_verdict_ok():
    assert judge(-0.2, -0.3, -0.2, -0.25) == "ok"


def test_verdict_uniform():
    # 整体早超阈值
    assert judge(-1.0, -1.2, -1.0, -1.0) == "uniform"


def test_verdict_break():
    # 前段对齐、后段差出缺口 => 片中断裂（优先于 uniform）
    assert judge(-0.2, -0.4, -0.2, -1.4) == "break"


def test_verdict_end_short():
    # Start 对齐但 End 偏早
    assert judge(-0.2, -0.9, -0.2, -0.2) == "end_short"


def test_verdict_slight():
    # Start 略超 OK 区间但未到统一错轴
    assert judge(0.4, 0.0, 0.4, 0.4) == "slight"


def test_verdict_no_match():
    assert judge(None, None, None, None) == "no_match"