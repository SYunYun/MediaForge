"""score.py 单测：seeders 曲线 / 体积带 / 动画带 / 组偏好 / breakdown。"""

from mediaforge.hunt.score import (
    BAND_FULL,
    BAND_OUT,
    BAND_TOLERANCE,
    SEED_CAP,
    detect_animation,
    detect_resolution,
    group_score,
    rank_releases,
    score_release,
    seeders_score,
    size_band_score,
)

GB = 1024 ** 3

DEFAULT_BANDS = {
    "720p": {"lo": 1, "hi": 4},
    "1080p": {"lo": 10, "hi": 20},
    "2160p": {"lo": 30, "hi": 60},
}

CFG = {
    "hunt": {
        "prefer_groups": ["edge2020", "Tigole", "QxR", "NAN0", "SAMPA"],
        "animation_keywords": ["Ani-", "anime"],
        "group_bonus": 15,
        "animation_band_factor": 0.6,
        "size_bands": DEFAULT_BANDS,
    }
}


def _rel(title="Movie 2024 1080p", size=15 * GB, seeders=50, **kw):
    r = {"title": title, "size": size, "seeders": seeders, "infohash": "a" * 40,
         "indexer": "yts"}
    r.update(kw)
    return r


class TestSeedersCurve:
    def test_zero_seeders_zero_points(self):
        assert seeders_score(0) == 0.0
        assert seeders_score(None) == 0.0

    def test_monotonic_increasing(self):
        prev = 0.0
        for s in (0, 1, 2, 5, 15, 50, 100, 500, 1000):
            cur = seeders_score(s)
            assert cur >= prev, (s, prev, cur)
            prev = cur

    def test_capped_at_50(self):
        assert seeders_score(10000) == SEED_CAP
        assert seeders_score(100000) == SEED_CAP

    def test_log_scaling_exact_points(self):
        # 对数缩放：2^k - 1 个种子正好 10k 分（log2 特性）
        assert seeders_score(1) == 10.0
        assert seeders_score(3) == 20.0
        assert seeders_score(7) == 30.0
        assert seeders_score(15) == 40.0
        assert seeders_score(31) == 50.0  # 恰好在封顶线上

    def test_capped_plateau_is_the_diminishing(self):
        # log2(1+s) 曲线在未封顶区间等边际；封顶后收益归零 = 实际递减
        assert seeders_score(31) == seeders_score(60) == seeders_score(200) == SEED_CAP


class TestSizeBand:
    def test_1080p_live_in_band(self):
        assert size_band_score(15 * GB, "1080p", False, DEFAULT_BANDS) == BAND_FULL

    def test_1080p_live_inside_tolerance(self):
        # 10-20GB 带宽外但 0.5x~2x 内（5-40GB）：+8
        assert size_band_score(8 * GB, "1080p", False, DEFAULT_BANDS) == BAND_TOLERANCE
        assert size_band_score(25 * GB, "1080p", False, DEFAULT_BANDS) == BAND_TOLERANCE

    def test_1080p_live_far_outside_penalty(self):
        assert size_band_score(2 * GB, "1080p", False, DEFAULT_BANDS) == BAND_OUT
        assert size_band_score(80 * GB, "1080p", False, DEFAULT_BANDS) == BAND_OUT

    def test_720p_band(self):
        assert size_band_score(2 * GB, "720p", False, DEFAULT_BANDS) == BAND_FULL
        assert size_band_score(20 * GB, "720p", False, DEFAULT_BANDS) == BAND_OUT

    def test_2160p_band(self):
        assert size_band_score(45 * GB, "2160p", False, DEFAULT_BANDS) == BAND_FULL

    def test_animation_narrower_band(self):
        # 动画 1080p 最优带 = 10-20GB × 0.6 = 6-12GB
        assert size_band_score(8 * GB, "1080p", True, DEFAULT_BANDS, 0.6) == BAND_FULL
        # 15GB 对动画已经出带（>12GB）但还在容差内
        assert size_band_score(15 * GB, "1080p", True, DEFAULT_BANDS, 0.6) == BAND_TOLERANCE
        # 真人 15GB 在带内 → 动画判定改变结果，证明分支生效
        assert size_band_score(15 * GB, "1080p", False, DEFAULT_BANDS, 0.6) == BAND_FULL

    def test_missing_size_or_resolution(self):
        assert size_band_score(None, "1080p", False, DEFAULT_BANDS) == 0.0
        assert size_band_score(15 * GB, None, False, DEFAULT_BANDS) == 0.0
        assert size_band_score(15 * GB, "480p", False, DEFAULT_BANDS) == 0.0


class TestResolutionAndAnimation:
    def test_detect_resolution(self):
        assert detect_resolution("Inception 2010 1080p BluRay") == "1080p"
        assert detect_resolution("Dune 2160p HDR") == "2160p"
        assert detect_resolution("Old Movie 720p x264") == "720p"
        assert detect_resolution("No res here") is None
        # 高分辨率优先
        assert detect_resolution("Dune 1080p 2160p UHD") == "2160p"

    def test_detect_animation(self):
        assert detect_animation("[Ani-] Movie 1080p", ["Ani-", "anime"]) is True
        assert detect_animation("Movie 1080p Anime", ["Ani-", "anime"]) is True
        assert detect_animation("Movie 1080p", ["Ani-", "anime"]) is False


class TestGroupPreference:
    def test_hit_adds_bonus(self):
        assert group_score("Movie 2024 1080p WEBRip x264-Tigole", ["Tigole"], 15) == 15.0

    def test_multiple_groups_stack(self):
        title = "Movie 1080p Tigole QxR REMUX"
        assert group_score(title, ["Tigole", "QxR"], 15) == 30.0

    def test_no_hit_zero(self):
        assert group_score("Movie 1080p x264", ["Tigole"], 15) == 0.0
        assert group_score("", ["Tigole"], 15) == 0.0

    def test_case_insensitive(self):
        assert group_score("movie tigole 1080p", ["TIGOLE"], 15) == 15.0


class TestScoreRelease:
    def test_adds_score_and_breakdown_keys(self):
        out = score_release(_rel(), CFG)
        assert "score" in out and "score_breakdown" in out
        bd = out["score_breakdown"]
        assert set(bd) >= {"seeders", "size_band", "group", "resolution", "is_animation"}

    def test_total_is_sum_of_factors(self):
        out = score_release(_rel(title="Movie 2024 1080p Tigole",
                                 size=15 * GB, seeders=100), CFG)
        bd = out["score_breakdown"]
        assert out["score"] == round(bd["seeders"] + bd["size_band"] + bd["group"], 1)
        # 1080p 15GB 在带内、Tigole 命中、100 种子封顶
        assert bd["size_band"] == BAND_FULL
        assert bd["group"] == 15.0
        assert bd["seeders"] == SEED_CAP

    def test_animation_release_gets_animation_band(self):
        out = score_release(_rel(title="[Ani-] Movie 2024 1080p", size=8 * GB), CFG)
        assert out["score_breakdown"]["is_animation"] is True
        assert out["score_breakdown"]["size_band"] == BAND_FULL

    def test_does_not_mutate_input(self):
        r = _rel()
        score_release(r, CFG)
        assert "score" not in r


class TestRankReleases:
    def test_sorts_by_score_desc(self):
        releases = [
            _rel(title="Bad 1080p Tiny", size=1 * GB, seeders=1, infohash="a" * 40),
            _rel(title="Good 1080p Tigole", size=15 * GB, seeders=100, infohash="b" * 40),
        ]
        ranked = rank_releases(releases, CFG)
        assert [r["title"] for r in ranked] == ["Good 1080p Tigole", "Bad 1080p Tiny"]
        assert ranked[0]["score"] > ranked[1]["score"]

    def test_dedup_by_infohash_keeps_highest(self):
        releases = [
            _rel(title="Low 1080p", size=1 * GB, seeders=1, infohash="c" * 40),
            _rel(title="High 1080p", size=15 * GB, seeders=200, infohash="c" * 40),
            _rel(title="Other", size=15 * GB, seeders=200, infohash="d" * 40),
        ]
        ranked = rank_releases(releases, CFG)
        assert len(ranked) == 2
        assert ranked[0]["title"] == "High 1080p"
