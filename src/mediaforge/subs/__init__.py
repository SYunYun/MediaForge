"""Mediaforge subs 模块 —— 字幕管理的 Agent 原生自愈闭环。

设计原则（2026-08-10 阿喆拍板）：
- 无感服务优于有感服务：入库自检 → 自主发现问题 → 自修复 → 复检门禁 → 静默
- 除 Jellyfin 外全部合一：subs 是 MediaForge 四模块之一，不是独立服务
- 品味留人、脏活归机器：选源/收藏级字幕/审美判断留人，格式/对齐/结构归机器

模块组成：
- ass.py       ASS/SRT 解析 + 时间工具
- inspect.py   体检器（Start/End 双检 + 断裂/End偏短判定）
- ledger.py    台账（每季每集状态持久化）
- media.py     媒体库接口抽象层（先 filesystem，留 jellyfin 位）
"""
from __future__ import annotations

SUBS_VERSION = "0.1.0"