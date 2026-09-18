# Literature Harvester 文献采集器

[English](README.md) | [简体中文](README-ZH.md)

一个本地优先的学术文献发现、获取、原始数据保存和确定性规范化工具。v0.1 重点完成文献获取与
结构化语料库的基础设施，明确不包含 LLM 科学信息抽取和知识图谱。

## 它能做什么

Literature Harvester 面向个人研究者，支持：

1. 通过 Elsevier Scopus Search STANDARD 检索文献。
2. 从 CSV、TSV、TXT、JSON、JSONL 导入 DOI。
3. 解析并获取用户有权访问的出版商全文。
4. 无损保存出版商返回的原始数据。
5. 将 Elsevier ScienceDirect FULL XML 规范化为与提供商无关的 `PaperDocument`。
6. 跟踪凭证、配额、重试、失败和可恢复任务。
7. 通过命令行和本地 Web 面板查看文献库与运行状态。

系统内部感知不同提供商，但对用户保持接口一致。获取/规范化层与后续科学理解层刻意解耦。

## 功能

- Scopus Search STANDARD 检索和游标分页
- ScienceDirect FULL XML 全文获取
- 可选下载出版商 PDF，并作为独立原始附件保存
- 提供商抽象、凭证元数据、健康检查和配额监控
- 支持配额感知、重试和恢复的 SQLite 任务队列
- 支持 CSV、TSV、TXT、JSON、JSONL 的 DOI 导入
- 确定性的 Elsevier FULL XML 到 `PaperDocument` 规范化
- Typer CLI 和 React/FastAPI 本地面板
- 支持运行时切换的中英文双语面板
- 使用 Server-Sent Events（SSE）实时更新面板
- 显示 提供商 → 服务 → 凭证 的配额状态
- 失败中心，支持暂停、恢复、重试和取消
- 项目内凭证存储，不需要导出 API Key 环境变量
- 仓库 API 泄漏扫描，并在 CI 中强制执行
- 运行时路径由当前配置文件解析，可移植

v0.1 不对 PDF 做 OCR；PDF 仅作为原始附件保存，并按访问权限使用。

v0.1 明确不包含：LLM 抽取、材料领域 NER、关系抽取、知识图谱、Neo4j、向量数据库、研究空白
发现、假设生成、PDF OCR、浏览器抓取、云部署、用户登录和 UI 内凭证编辑。

## 环境要求

- Python 3.11+
- 与你账号/机构权限匹配的 Elsevier API Key
- 只有从源码重新构建前端时才需要 Node.js

发布包和本地 wheel 已经包含构建好的双语前端，正常使用不需要安装 Node.js。

## 快速开始

### 1. 进入项目目录

```bash
cd /path/to/lit-harvest
```

### 2. 安装

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp config.example.yaml config.yaml
```

### 3. 保存 Elsevier 凭证

推荐把密钥保存在项目内部：

```bash
.venv/bin/lit-harvest auth set elsevier university_primary
```

命令会使用隐藏输入：

```text
API key for elsevier/university_primary:
```

密钥保存位置：

```text
<项目目录>/.lit-harvest/secrets.json
```

文件权限为 `0600`，并且 `.lit-harvest/` 已加入 `.gitignore`。

密钥不会写入：

- `config.yaml`
- SQLite
- 日志
- API 响应
- 浏览器状态

`config.yaml` 只保存引用：

```yaml
providers:
  elsevier:
    credentials:
      - name: university_primary
        secret_ref: file:elsevier:university_primary
```

### 4. 检查环境和凭证

```bash
.venv/bin/lit-harvest auth list
.venv/bin/lit-harvest doctor
.venv/bin/lit-harvest doctor --network
```

如果没有配置凭证，`doctor` 会按设计返回非零退出码。

## 常用流程

### 按主题检索

```bash
.venv/bin/lit-harvest search \
  --query 'TITLE-ABS-KEY("solid-state battery")' \
  --max-results 100
```

限制年份并导出：

```bash
.venv/bin/lit-harvest search \
  --query 'TITLE-ABS-KEY("solid-state electrolyte")' \
  --max-results 500 \
  --start-year 2020 \
  --end-year 2026 \
  --export papers.jsonl
```

### 获取单个 DOI

```bash
.venv/bin/lit-harvest fetch 10.1016/j.mtcomm.2026.115551
```

### 同时下载出版商 PDF

```bash
.venv/bin/lit-harvest fetch 10.1016/j.mtcomm.2026.115551 --pdf
```

PDF 是补充性原始附件，FULL XML 仍然是规范化内容的权威来源。如果没有 PDF 权限或下载失败，
XML 获取仍会成功，并在 JSON 结果中返回 `pdf_error` 字段。

如果希望每次 fetch 都尝试下载 PDF：

```yaml
providers:
  elsevier:
    download_pdf: true
```

### 导入 DOI 文件

```bash
.venv/bin/lit-harvest fetch papers.csv --doi-column doi
```

支持格式：

```text
.csv
.tsv
.txt
.json
.jsonl
```

以下 DOI 写法都会自动规范化并去重：

```text
10.1016/j.xxx
https://doi.org/10.1016/j.xxx
http://dx.doi.org/10.1016/j.xxx
doi:10.1016/j.xxx
DOI: 10.1016/j.xxx
```

无效 DOI 会记录在结果中，不会中断整批处理。

### 重新解析已下载的原始 XML

```bash
.venv/bin/lit-harvest parse
```

该命令只重新规范化本地原始文件，不会重新下载文章。

### 启动本地 Web 面板

```bash
.venv/bin/lit-harvest ui
```

默认地址：

```text
http://127.0.0.1:8765
```

API 文档：

```text
http://127.0.0.1:8765/docs
```

## CLI 命令

```text
lit-harvest version
lit-harvest auth set [provider] [name] [--secret-ref REF] [--config PATH]
lit-harvest auth list [--config PATH]
lit-harvest auth test [provider] [name] [--config PATH]
lit-harvest auth remove [provider] [name] [--secret-ref REF] [--config PATH]
lit-harvest doctor [--network] [--json] [--config PATH]

lit-harvest search --query QUERY --max-results N [--start-year N] [--end-year N]
                   [--export PATH] [--config PATH]

lit-harvest fetch DOI|FILE [--doi-column COLUMN] [--pdf|--no-pdf] [--config PATH]
lit-harvest parse [--limit N] [--config PATH]
lit-harvest export PATH [--format csv|json|jsonl] [--config PATH]
lit-harvest jobs [--status STATUS] [--limit N] [--config PATH]
lit-harvest quota [--config PATH]
lit-harvest pause [--reason TEXT] [--config PATH]
lit-harvest resume [--config PATH]
lit-harvest retry --job-id ID | --transient [--config PATH]
lit-harvest ui [--host HOST] [--port PORT] [--config PATH]
```

## 配置

从 [`config.example.yaml`](config.example.yaml) 开始。

示例：

```yaml
storage:
  root: ./data

database:
  url: sqlite:///./data/lit_harvest.db

scheduler:
  retry:
    max_attempts: 4
    base_delay_seconds: 2

  rate_limit:
    respect_retry_after: true

  quota:
    warning_ratio: 0.30
    low_ratio: 0.10

server:
  host: 127.0.0.1
  port: 8765

providers:
  elsevier:
    enabled: true

    services:
      scopus_search:
        enabled: true

      article_retrieval:
        enabled: true

    credentials:
      - name: university_primary
        secret_ref: file:elsevier:university_primary
        institution: HIT
        quota_scope: institution
```

### 凭证引用格式

```text
file:provider:name         推荐的 0600 项目内密钥文件
keychain:service:account   可选的 macOS Keychain / 系统 Keyring
env:NAME                   兼容 CI/容器的旧模式
```

旧的 `api_key_env` 字段仍然兼容已有部署，但不再是推荐的本地工作流。

### 可选 Keychain 模式

如果希望使用系统 Keychain 而不是项目内文件：

```bash
export LIT_HARVEST_SECRET_BACKEND=keychain
.venv/bin/lit-harvest auth set elsevier university_primary \
  --secret-ref keychain:lit-harvest.elsevier:university_primary
```

## 凭证和配额策略

凭证故障转移采用保守策略。

- 机构级配额耗尽时，同一机构下的其他凭证会被阻止继续轮换。
- 账号级、提供商级和未知范围配额同样阻止凭证轮换。
- 只有相互独立授权的凭证才能进行合法的故障转移。
- HTTP 429、超时、500、502、503、504 会使用有上限的指数退避重试。
- HTTP 400、401、403、404 不会被无限重试。
- 系统不会通过轮换凭证绕过提供商或机构配额。

## 路径与可移植性

所有运行时路径都相对于当前配置文件或当前工作目录解析：

```text
./data
./data/lit_harvest.db
./.lit-harvest/secrets.json
```

项目不依赖任何固定的绝对路径。如果希望把数据放到其他位置，可以在 `config.yaml` 中使用绝对
路径或 `~`：

```yaml
storage:
  root: ~/lit-harvest-data

database:
  url: sqlite:///~/lit-harvest-data/lit_harvest.db
```

也可以通过 `LIT_HARVEST_CONFIG` 指向仓库外的配置文件；此时项目内密钥文件会跟随该配置文件
所在目录解析。

## 存储结构

```text
data/
├── lit_harvest.db
├── exports/
└── papers/
    └── 10.1016_j.example/
        ├── raw/
        │   ├── elsevier_xml.xml
        │   └── elsevier_pdf.pdf        # 可选
        ├── normalized/
        │   └── paper.json
        └── state.json
```

项目内凭证单独保存：

```text
.lit-harvest/
└── secrets.json
```

当解析规则升级时，原始出版商数据不会被丢弃。

## 本地 API

```text
GET  /api/health
GET  /api/overview
GET  /api/doctor

GET  /api/papers
POST /api/papers/import
POST /api/papers/doi
GET  /api/papers/export
GET  /api/papers/{paper_id}

GET  /api/providers
GET  /api/providers/quotas

GET  /api/jobs
POST /api/jobs/{job_id}/retry
POST /api/jobs/{job_id}/cancel
GET  /api/failures
POST /api/failures/retry-transient

POST /api/queue/pause
POST /api/queue/resume

GET  /api/events
```

## Web 页面

```text
/             Overview 总览
/papers       Papers 文献列表与生命周期
/papers/:id   Paper detail 文献详情
/providers    Provider / service / credential / quota
/failures     Failure center 和队列控制
```

## 安全与路径

提交或公开发布前执行：

```bash
lit-harvest security scan
```

扫描器会检查可见文件和 Git 跟踪文件中的疑似 API Key、私钥块；如果 `.lit-harvest/`、
`config.yaml`、`data/` 或 `.env` 被 Git 跟踪，会直接失败。

运行时路径相对于当前配置文件或当前工作目录解析，不依赖固定绝对路径。也可以通过
`LIT_HARVEST_CONFIG` 指向仓库外的配置文件。

## 开发

运行测试和静态检查：

```bash
.venv/bin/pytest
.venv/bin/ruff check src/lit_harvest tests
.venv/bin/mypy src/lit_harvest
.venv/bin/lit-harvest security scan
```

修改 React/TypeScript 后重新构建前端：

```bash
./scripts/build_frontend.sh
```

如果 `node` 不在 `PATH`，脚本会尝试使用 Codex 自带的 Node 运行时。

## 开源与 GitHub

仓库已经准备好推送到私密 GitHub 仓库。首次推送前执行：

```bash
lit-harvest security scan
git check-ignore -v .lit-harvest/secrets.json config.yaml data/lit_harvest.db .env
git status --short
```

随后按照 [docs/PUBLISHING.md](docs/PUBLISHING.md) 操作。仓库已包含 CI、`SECURITY.md`、
`CONTRIBUTING.md` 和 `CODE_OF_CONDUCT.md`。

## 文档

- [架构](docs/ARCHITECTURE.md)
- [数据模型](docs/DATA_MODEL.md)
- [本地 API](docs/API.md)
- [运维说明](docs/OPERATIONS.md)
- [English README](README.md)

## v0.1 范围

已实现：

- 提供商抽象
- 凭证元数据和项目内密钥存储
- 配额模型和管理器
- 调度器和可恢复任务队列
- SQLite 运行状态
- 原始文档存储
- DOI 导入
- Scopus Search STANDARD
- ScienceDirect FULL XML 获取
- 可选保存出版商 PDF 附件
- Elsevier FULL XML 确定性规范化
- CLI
- FastAPI 后端
- React 面板
- SSE 实时更新
- 暂停、恢复、重试和取消操作

明确不包含：

- LLM 抽取
- 材料领域 NER
- 实验关系抽取
- 知识图谱
- Neo4j
- 向量数据库
- 研究空白引擎
- 假设生成
- PDF OCR
- 浏览器抓取
- 云部署
- SaaS
- 用户登录
- UI 内凭证编辑
- 无限制凭证轮换
- 大量出版商集成

## 许可证

[MIT](LICENSE)
