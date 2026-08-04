# Mediaforge 踩坑实录（docs/pitfalls.md）

每个设计决策背后都是真实事故。给面试官讲"我怎么发现的"，比讲"我写了什么"值钱。

## 1. 四套路径体系（本项目缘起）

同一文件四个名字：宿主机 `/media/Media/Shows/X`、Jellyfin `/media/Shows/X`
（挂载 `/media/Media:/media`）、qbit `/downloads/X`（挂载 Downloads 子目录）、
MoviePilot `/media/Media/X`（整棵穿透）。三次历史事故（皮克斯 26 任务团灭、
savepath 静默回退、deleteFiles 险删收藏）全是"路径靠人脑记忆"造成的。

**教训**：路径映射必须是配置（最好从 docker-compose 推导），不是任何人的记忆。
错误要响亮拒绝（"这是容器路径，请给宿主机形式"），不要静默乱猜。

## 2. qBittorrent 5.x 四坑

- login 成功返回 **HTTP 204 空 body**，不是 "Ok."
- `torrents/add` 返回 JSON `{"pending_count": 1}` = 异步受理，不是失败；别按字符串判
- `resume` 改名 `start`
- 删任务永远 `deleteFiles=false`——收藏是硬链接视图，deleteFiles=true 会团灭收藏

## 3. Cardigann 解释器兼容墙（真实遇到，逐个修）

- **相对路径**：eztv 等定义的 path 是相对路径（`search/...`），无 scheme →
  拼 `definition.links[0]` 的 sitelink
- **URL 编码**：requests 只编码 query 不编码 path，关键词含空格直接炸 →
  只对 path 段逐段 quote，query 原样交给 requests
- **Go 模板函数**：`{{ join .Categories "," }}` 是函数调用语法 → 补了最小函数集
  （join/lower/upper/trim/split/replace/append/prepend）
- **Go 正则 `\p{...}`**：Python `re` 不认 unicode property（TPB 的中文归一化
  滤镜 `[\p{IsCJKUnifiedIdeographs}\W]+`）→ 捕获 `re.error` 跳过该滤镜并告警，
  不整条失败（fail-loud, non-fatal）
- **rows 选择器是模板**：TPB 的 `${{ if .Config.uploader }}:has(...){{ end }}`
  渲染后是 `$`（=JSON 根数组自身）→ 先渲染选择器再解析；`$` 语义 = 根节点

## 4. GFW 索引器画像（2026-08 实测）

| 索引器 | 状态 | 备注 |
|---|---|---|
| YTS（JSON API） | ✅ 直连可用 | movies-api.accel.li，无需代理 |
| TPB（apibay JSON API） | ✅ 直连可用 | `q.php?q=...`，注意 infohash 字段名 |
| LimeTorrents | ⚠️ 代理 SSL 抖、直连返回 bot 页 | 镜像轮换解决 |
| EZTV | ❌ 403（Turnstile） | 已知墙 |
| 1337x / KAT | ❌ Turnstile | 已知墙，别浪费轮次 |

## 5. 幂等投喂（agent 重试安全）

add 前先查 `torrents/info` 的 hash 字段判重：已存在 → `already_present`，
不存在 → add + 回查确认落队。**这是"给人用的工具"和"给 agent 用的工具"
的本质区别**：人会小心，agent 会重试、会超时、会从头再来。
