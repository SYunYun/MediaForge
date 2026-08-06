# MediaForge 完全体架构（2026-08-06 定稿）

## 终局

**一个常驻 daemon 取代 arr 全家桶**：`hunt → get → organize → subs` 四个模块全部 Agent 原生。
最终栈 = **MediaForge + Jellyfin**，没了。Prowlarr/Radarr/Sonarr/Bazarr/qBittorrent 全部退役。

```
mediaforged   常驻 daemon（systemd user，localhost 出 JSON API）
├── hunt      找：Cardigann 解释器 + search/pick/add + 健康打分（已上线，116 tests）
├── subs      字幕：SubHD 管线 + 双语合成 + 轴对齐 + QA（拆 Bazarr 位）
├── get       下：内嵌 libtorrent 会话（踢掉 qbit 壳）
└── organize  整理：硬链入库 + 命名 + Sxx 解析 + Jellyfin 刷新（拆 Sonarr/Radarr 位）

mediaforge    CLI = 瘦客户端，跟 daemon 走 localhost 说话
```

## 语言与 runtime：Python，不折腾

三个硬约束钉死的选择：

1. **libtorrent 只认 Python**：官方一等公民绑定是 `python3-libtorrent`（apt）；Go 无成熟绑定，Rust 引擎太嫩。
2. **PT 白名单指纹**：私有站校验客户端指纹，自研/小众引擎直接封号；libtorrent 指纹通行。这扇门只有 libtorrent 能开。
3. **存量即成本**：hunt 与字幕管线全是 Python；依赖纪律保持最小（现仅 requests/pyyaml/beautifulsoup4/pytest）。

Runtime 形态：

- **FastAPI + uvicorn**（localhost）——选它因为 OpenAPI 自动出 schema，"capabilities 自描述"这条铁律白送。这是唯一新增的重依赖。
- **libtorrent alert-pump 线程**灌状态；协议的硬骨头全在 C++ 侧。
- **SQLite（stdlib）**记队列/状态/账本，不引外部数据库。
- 打包坑备案：`python3-libtorrent` 是系统包，venv 用 `--system-site-packages` 只借这一个，或 `python-libtorrent-bin` 预编译轮——get 期实测再定。

## 设计不变量（铁律，全期适用）

1. **写操作全幂等**：重复执行无副作用；出错响亮，不静默。
2. **配置推导不记忆**：路径/状态从系统推导，人肉记忆永远不是真相源。
3. **全 JSON 自描述**：Agent 能 capabilities 发现一切。
4. **品味留人**：选种、命名、收藏级字幕裁决 = 人类决策；机器提议不代拍。
5. **绝不移动/删除 Downloads 源文件**：库目录是硬链视图（link=2）。

## 模块边界

| 模块 | 职责 | 拆谁的位 | 核心从哪来 |
|---|---|---|---|
| hunt ✅ | 索引站搜索/打分/投喂 | Prowlarr | 已上线（Cardigann 解释器子集） |
| subs | 字幕拉取/合成/对齐/QA | Bazarr | ~/cinema 实战脚本群（SubHD 管线） |
| get | BT 会话/队列/做种比例/断点续传 | qBittorrent 壳 | libtorrent 引擎内嵌（肌肉不碰） |
| organize | 硬链/命名/入库/刷新 | Sonarr/Radarr | media-ctl intake/hook 通用化 |

## 排序与理由

```
subs → get → organize
```

- **subs 先行**：核心代码打过仗（纯搬运），最快见效，CLI 形态先进，不依赖 daemon。
- **get 最重**：daemon 骨架随它落地；且迁移要等 174G 做种债清偿（自然窗口 ~2-3 周）。
- **organize 收尾**：半成品已在 media-ctl 实战，抽通用化即可；media-ctl 此后退化为纯配置层（path_maps + 凭据）。

## get 模块专章（最重的一期）

- **形态**：mediaforged 内的 libtorrent 会话；alert-pump → SQLite；systemd user 常驻。
- **双后端**：`--engine libtorrent`（内嵌，自用终态）/ `--engine qbit`（外挂，喂别人的现有栈）。开源不对用户做"先卸载 qbit"的硬要求。
- **隐形家务清单**（踢 qbit 必须自接的账）：常驻会话、断点续传（resume data）、做种比例/队列策略、端口映射（NAT-PMP/UPnP）、磁盘水位守卫。
- **迁移账**：174G 做种债记在 qbit 账本——重添加+重校验+比例清零，**债清再切**。

## 体验目标（验收叙事）

```
用户: "我想看《夜班经理》"
MF:   6 个源，最优 [1080p x265 · 34 做种 · 8.2G]，下吗？   ← 选种归人
用户: "下"
MF:   …下载→硬链入库→字幕→对齐→双语合成→QA→刷新…
MF:   "S01 已入库，双语字幕配好，可以看了。"
```
