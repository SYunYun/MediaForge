# Mediaforge

Agent 原生媒体栈工具箱（开源项目）。

## 模块一：hunt —— Cardigann 索引器引擎

`mediaforge.cardigann` 是 Jackett/Prowlarr Cardigann YAML 索引器定义的解释器子集：
加载社区 YAML 卡（500+ 站点），渲染 Go 模板子集，执行搜索，输出统一 Release。

```python
from mediaforge.cardigann import load_definition, search, Query

d = load_definition("tests/fixtures/yts.yml")
releases = search(d, Query(keywords="inside job"))
for r in releases:
    print(r["title"], r["seeders"], r["infohash"])
```

### 子模块

| 模块 | 职责 |
|---|---|
| `template.py` | Go 模板子集渲染器（变量 / if-else 嵌套 / eq/and/or/not），手写 tokenizer+递归解析 |
| `filters.py` | 滤镜管道：replace, re_replace, append, prepend, trim, tolower, toupper, split, join, case, querystring |
| `definition.py` | YAML 卡 → Definition dataclass；settings default 与用户配置合并 |
| `engine.py` | 搜索执行器：渲染 path/inputs → requests → json 点路径 / html CSS 选择器抽取 → Release dict |
| `loader.py` | 定义仓库：jsdelivr 拉 Jackett 卡，缓存 ~/.cache/mediaforge/indexers/ |

### 开发

```bash
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests pyyaml beautifulsoup4 pytest
.venv/bin/python -m pytest tests/
```

### 已知不支持的 Cardigann 特性

- 登录/session 流（login block、cookie 处理、验证码）
- download 段（种子文件下载与改写，仅输出 download URL）
- 模板函数全集（仅 if/eq/and/or/not；无 range/len/join 等管道函数）
- 滤镜：dateparse、regexp、validfilename、timeago 等未实现
- headers/cookies/ratelimit（requestDelay）、followredirect 等请求级配置
- rows 多 selector 数组、field selector 数组（fallback 链）
- caps 段仅解析不用于过滤；categorymappings 未参与搜索
- imdbid 之外的高级查询字段（tmdbid/season/ep 模板变量已解析但依赖定义支持）
