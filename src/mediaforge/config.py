"""Mediaforge 配置：模板生成 + 加载 + 凭据回退。

优先顺序（凭据）：
1. ~/.config/mediaforge/config.yaml 里显式写的值
2. 环境变量 MEDIAFORGE_QBIT_URL / MEDIAFORGE_QBIT_USERNAME / MEDIAFORGE_QBIT_PASSWORD
3. 上一项目 ~/media-ctl/config.yaml 的 services.qbit（同机沿用）

铁律：仓库里绝不硬编码真实凭据。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

CONFIG_DIR_ENV = "MEDIAFORGE_CONFIG_DIR"
CONFIG_DIR = Path(os.environ.get(CONFIG_DIR_ENV, str(Path.home() / ".config" / "mediaforge")))
CONFIG_PATH = CONFIG_DIR / "config.yaml"

DEFAULT_INDEXERS = ["yts"]

# 默认体积带（GB，真人）：带宽外按档位递减
DEFAULT_SIZE_BANDS = {
    "720p": {"lo": 1, "hi": 4},
    "1080p": {"lo": 10, "hi": 20},
    "2160p": {"lo": 30, "hi": 60},
}

TEMPLATE = """\
# Mediaforge 配置 —— 首次运行自动生成，改完即生效（无 daemon，无需重启）
# 凭据优先级：本文件显式值 > 环境变量 MEDIAFORGE_QBIT_* > ~/media-ctl/config.yaml

qbit:
  url: http://localhost:8080
  username: admin
  password: ""            # 留空自动回落到 env / media-ctl；别把真密码写进仓库
  paused: false           # add 默认是否暂停（true=只入队不下载，安全验证用）
  savepath: ""            # 可选：宿主机下载目录；按下方 path_map 翻译成容器路径
  path_map:               # 宿主路径 -> qbit 容器路径（qbit 5.x 只认容器内路径）
    - host: /media/Media/Downloads
      container: /downloads

hunt:
  prefer_groups: [edge2020, Tigole, QxR, NAN0, SAMPA]
  animation_keywords: [Ani-, anime]   # title 命中任一即按动画体积带算
  group_bonus: 15                     # 命中一个偏好组加的分
  animation_band_factor: 0.6          # 动画最优带 = 真人带 × 该系数（1080p 动画≈6-12GB）
  # 体积带（GB）: 带宽内 +25，带宽外 0.5x~2x 内 +8，更远 -10
  size_bands:
    720p:  {lo: 1,  hi: 4}
    1080p: {lo: 10, hi: 20}
    2160p: {lo: 30, hi: 60}

proxy: ""                 # 如 http://127.0.0.1:7892；空 = 直连
timeout: 12               # 所有 requests 超时（项目铁律 ≤15）
indexers: [yts]           # search/pick 默认索引器（loader 缓存里要有对应定义卡）
"""


class ConfigError(Exception):
    """配置缺失或格式错误。"""


def config_dir() -> Path:
    return CONFIG_DIR


def ensure_config(force: bool = False) -> Path:
    """首次运行生成配置模板；force=True 时覆盖（保留原文件为 .bak）。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists() and not force:
        return CONFIG_PATH
    if CONFIG_PATH.exists() and force:
        bak = CONFIG_PATH.with_suffix(".yaml.bak")
        CONFIG_PATH.rename(bak)
    CONFIG_PATH.write_text(TEMPLATE, encoding="utf-8")
    return CONFIG_PATH


def _media_ctl_qbit() -> dict:
    """从 ~/media-ctl/config.yaml 继承 qbit 端点（若存在）。"""
    candidates = [
        Path.home() / "media-ctl" / "config.yaml",
        Path.home() / "media-ctl" / "config.yml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            services = data.get("services") or {}
            qbit = services.get("qbit") or {}
            return {"url": qbit.get("url"), "username": qbit.get("username"),
                    "password": qbit.get("password")}
        except yaml.YAMLError:
            continue
    return {}


def load_config(env: Optional[dict] = None) -> dict:
    """加载配置：默认值 <- 模板文件 <- 环境变量覆盖。

    env 参数供测试注入；默认读 os.environ。
    """
    env = dict(os.environ) if env is None else env
    cfg = {
        "qbit": {
            "url": "http://localhost:8080",
            "username": "admin",
            "password": "",
            "paused": False,
            "savepath": "",
            "path_map": [{"host": "/media/Media/Downloads", "container": "/downloads"}],
        },
        "hunt": {
            "prefer_groups": ["edge2020", "Tigole", "QxR", "NAN0", "SAMPA"],
            "animation_keywords": ["Ani-", "anime"],
            "group_bonus": 15,
            "animation_band_factor": 0.6,
            "size_bands": DEFAULT_SIZE_BANDS,
        },
        "proxy": "",
        "timeout": 12,
        "indexers": list(DEFAULT_INDEXERS),
        "subs": {
            "media": {
                "backend": "filesystem",
                "root": "/media/Media",
                "library": "Shows",
            },
            "naming": {
                "ass_suffix": ".default.chi.zh-cn.ass",
            },
        },
    }
    if CONFIG_PATH.exists():
        try:
            file_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{CONFIG_PATH} 解析失败: {exc}") from exc
        for section in ("qbit", "hunt", "subs"):
            if isinstance(file_cfg.get(section), dict):
                cfg[section].update(file_cfg[section])
        for key in ("proxy", "timeout", "indexers"):
            if key in file_cfg:
                cfg[key] = file_cfg[key]

    # 环境变量覆盖（测试/容器场景）
    if env.get("MEDIAFORGE_QBIT_URL"):
        cfg["qbit"]["url"] = env["MEDIAFORGE_QBIT_URL"]
    if env.get("MEDIAFORGE_QBIT_USERNAME"):
        cfg["qbit"]["username"] = env["MEDIAFORGE_QBIT_USERNAME"]
    if env.get("MEDIAFORGE_QBIT_PASSWORD"):
        cfg["qbit"]["password"] = env["MEDIAFORGE_QBIT_PASSWORD"]
    if env.get("MEDIAFORGE_PROXY"):
        cfg["proxy"] = env["MEDIAFORGE_PROXY"]

    # 凭据回退：media-ctl（同机上一项目）
    if not cfg["qbit"]["password"] or not cfg["qbit"]["url"]:
        inherited = _media_ctl_qbit()
        for key in ("url", "username", "password"):
            if not cfg["qbit"][key] and inherited.get(key):
                cfg["qbit"][key] = inherited[key]
    return cfg


def redact(cfg: dict) -> dict:
    """展示用脱敏配置。"""
    out = json_clone(cfg)
    if out.get("qbit", {}).get("password"):
        out["qbit"]["password"] = "***"
    return out


def json_clone(obj: Any) -> Any:
    import json

    return json.loads(json.dumps(obj, ensure_ascii=False))
