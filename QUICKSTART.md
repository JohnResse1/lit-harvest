# Quick Start / 快速开始

[English](#english) · [简体中文](#简体中文)

> **New here? Read only this file.** It assumes you have never used this project and do not write
> code. Follow it top to bottom.
>
> **第一次使用？只看这一个文件就够了。** 本文假设你从没用过这个项目、也不会写代码。照着从头到尾
> 做一遍即可。

---

# English

## What this is

**Literature Harvester** is a program that runs **on your own computer**. It searches academic
literature and downloads full-text articles that **you are entitled to access**, then saves them
locally in a tidy folder.

Four things to know before you start:

1. **It is not a website.** There is no cloud service. Everything lives in a folder on your machine.
2. **You need your own API key.** This tool talks to Elsevier (Scopus + ScienceDirect). You must use
   **your own** key. It will refuse to run without one.
3. **Nobody else can see your data.** Your papers, keys, and quota stay on your computer.
4. **There is a demo mode.** You can try the whole interface with built-in sample data, no key
   required. Do this first if you are unsure.

## Step 0 — Try it without a key (recommended first)

This creates three sample papers so you can click around safely. It needs no API key.

```bash
cd /path/to/lit-harvest
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/lit-harvest demo
.venv/bin/lit-harvest ui
```

Then open your browser at:

```text
http://127.0.0.1:8765
```

You will see three sample papers. Explore the pages freely:

| Page | What it shows |
| --- | --- |
| **总览 / Overview** | How many papers, jobs, quota, failures |
| **文献 / Papers** | Every paper and its processing stage |
| **提供商 / Providers** | Which credential is used and how much quota is left |
| **失败任务 / Failures** | Anything that failed and why |

When you are done exploring, clear the sample data:

```bash
.venv/bin/lit-harvest demo --clear
```

> The demo never contacts the internet and never asks for a key.

## Step 1 — Get your Elsevier API key

1. Go to **https://dev.elsevier.com/** and sign in (create a free account if needed).
2. Create an **API key** for your account.
3. Some access (for example Scopus) requires your institution to be entitled. If your key does not
   have access, the tool will tell you clearly instead of guessing.

You will paste this key once into the next step. Keep it private.

## Step 2 — Install (one time only)

If you already did Step 0, skip the install part and go to Step 3.

```bash
cd /path/to/lit-harvest

# Create an isolated Python environment
python3.11 -m venv .venv

# Install the tool and its dependencies
.venv/bin/python -m pip install -e '.[dev]'

# Create your local configuration file
cp config.example.yaml config.yaml
```

> Requires **Python 3.11 or newer**. On macOS you can check with `python3 --version`.

## Step 3 — Store your API key (one time only)

Run this and paste your key when asked. **The key is hidden as you type.**

```bash
.venv/bin/lit-harvest auth set elsevier university_primary
```

```text
API key for elsevier/university_primary:
```

Your key is saved to a private file inside the project:

```text
<project>/.lit-harvest/secrets.json   (permission 0600, ignored by Git)
```

It is **never** written into `config.yaml`, the database, logs, or the web page.

### Check that it works

```bash
.venv/bin/lit-harvest doctor --network
```

Expected result:

```text
Elsevier credential detected
Scopus Search STANDARD reachable
ScienceDirect Article Retrieval reachable
```

If something is wrong, the tool prints plain-language instructions and does not continue.

---

## Way A — Use the web dashboard (recommended for most people)

Start the dashboard:

```bash
.venv/bin/lit-harvest ui
```

Open:

```text
http://127.0.0.1:8765
```

The interface is bilingual — click **中文** or **EN** in the left sidebar. It follows your browser
language by default.

You will see four pages:

| Page | Use it to |
| --- | --- |
| **总览 Overview** | See totals, pipeline progress, quota runway |
| **文献 Papers** | Add DOIs, import a CSV, search, download files |
| **提供商 Providers** | Check credential health and remaining quota |
| **失败任务 Failures** | Retry or cancel failed jobs, pause/resume the queue |

### 1. Add a single DOI

On the **文献 / Papers** page, in the **Add a DOI** box:

1. Paste a DOI such as `10.1016/j.mtcomm.2026.115551`
2. Tick **Also download the publisher PDF** if you want the PDF too
3. Click **Fetch now**

The tool downloads the article and shows it in the list below.

### 2. Import a list of DOIs from a file (batch)

In the **Batch import from file** box:

1. Choose your file (`.csv`, `.tsv`, `.txt`, `.json`, `.jsonl`)
2. Set the **DOI column** — the default is `doi`
3. Leave **Run immediately** ticked to download right away
4. Tick **Also download the publisher PDF** if you want PDFs
5. Click **Upload and import**

A ready-made example is available with the **Download sample CSV** link.

**Minimum CSV requirement:** it must have a header row, and at least the DOI column.

```csv
doi
10.1016/j.mtcomm.2026.115551
```

Extra columns are allowed and ignored:

```csv
doi,title,notes
10.1016/j.mtcomm.2026.115551,Some paper,my note
```

You can also change the column name: if your file uses `identifier`, set **DOI column** to
`identifier`.

These DOI formats are all accepted automatically:

```text
10.1016/j.xxx
https://doi.org/10.1016/j.xxx
http://dx.doi.org/10.1016/j.xxx
doi:10.1016/j.xxx
DOI: 10.1016/j.xxx
```

### 3. Search by topic

In the **Search Scopus** box, enter a query and click **Run search**:

```text
TITLE-ABS-KEY("solid-state battery")
```

Set **Max results** to limit how many papers are retrieved (start with 10 while testing).

### 4. Download your articles

| Button | What you get |
| --- | --- |
| **Download XML** (paper page) | The publisher's structured full text |
| **Download PDF** (paper page) | The publisher PDF, if entitled |
| **Download JSON** (paper page) | The normalized, machine-readable document |
| **Download all data (ZIP)** (list page) | Everything, optionally including PDFs |
| **Export CSV** (list page) | A spreadsheet of your paper registry |

### 5. Where your files are stored

```text
data/
├── lit_harvest.db                       # your database
└── papers/
    └── 10.1016_j.mtcomm.2026.115551/
        ├── raw/elsevier_xml.xml         # original, untouched
        ├── raw/elsevier_pdf.pdf         # only if you asked for PDF
        ├── normalized/paper.json        # cleaned, structured version
        └── state.json                   # processing record
```

### 6. Choose where your files are stored (optional)

By default everything is saved in the `data/` folder inside the project. You can point it at any
folder you like — for example an external drive.

1. Open the **Storage / 存储** page in the sidebar.
2. Type or paste the folder you want, for example:

   ```text
   /Users/your-name/lit-harvest-data
   ```
3. The page checks the folder immediately and tells you if it is usable.
4. Click **Use this folder and copy data**.

Your existing papers and the database are **copied** to the new folder, and the original stays where
it was as a backup. Then restart the tool:

```bash
# stop with Ctrl+C, then
.venv/bin/lit-harvest ui
```

Click **Reset to default** on the same page to go back to `./data`.

> The setting is saved in `.lit-harvest/settings.json` (private, ignored by Git), so it survives
> restarts without editing any configuration file.

### 7. Stop the dashboard

Go to the terminal where you started it and press **Ctrl + C**.

---

## Way B — Use the command line

Every action is also available as a command. Run these from the project folder.

### Check your setup

```bash
.venv/bin/lit-harvest doctor --network
```

### Fetch one article

```bash
.venv/bin/lit-harvest fetch 10.1016/j.mtcomm.2026.115551
```

With the PDF as well:

```bash
.venv/bin/lit-harvest fetch 10.1016/j.mtcomm.2026.115551 --pdf
```

### Fetch many articles from a file

```bash
.venv/bin/lit-harvest fetch papers.csv --doi-column doi
```

Use your own file name. The same CSV rules as above apply.

### Search by topic

```bash
.venv/bin/lit-harvest search \
  --query 'TITLE-ABS-KEY("solid-state battery")' \
  --max-results 20
```

Save the results to a spreadsheet at the same time:

```bash
.venv/bin/lit-harvest search \
  --query 'TITLE-ABS-KEY("solid-state battery")' \
  --max-results 20 \
  --export results.csv
```

### Useful day-to-day commands

```bash
.venv/bin/lit-harvest jobs              # what is queued / running / done
.venv/bin/lit-harvest quota             # how much API quota is left
.venv/bin/lit-harvest parse             # re-process downloaded XML
.venv/bin/lit-harvest parse --force     # re-process everything
.venv/bin/lit-harvest export papers.csv # export your paper list

.venv/bin/lit-harvest storage show    # where files are stored
.venv/bin/lit-harvest storage set ~/papers-data   # move storage (copies data)
.venv/bin/lit-harvest storage reset   # back to ./data
.venv/bin/lit-harvest pause             # pause the queue
.venv/bin/lit-harvest resume            # resume the queue
.venv/bin/lit-harvest retry --transient # retry temporary failures
```

### Batch mode with a worker

The dashboard runs a background worker automatically. For the command line you can run one batch:

```bash
.venv/bin/lit-harvest worker --once
```

Or keep it running:

```bash
.venv/bin/lit-harvest worker
```

---

## Command cheat sheet

```text
lit-harvest demo                     create sample data (no key needed)
lit-harvest demo --clear             remove sample data
lit-harvest auth set elsevier university_primary    store your API key
lit-harvest doctor --network         check everything works
lit-harvest ui                       open the web dashboard

lit-harvest fetch DOI                download one article
lit-harvest fetch DOI --pdf          download one article + PDF
lit-harvest fetch file.csv           download many articles
lit-harvest search --query "..." --max-results 20
lit-harvest parse                    re-process downloaded files
lit-harvest export papers.csv        export your list

lit-harvest storage show             where files are stored
lit-harvest storage set PATH         change storage folder (copies data)
lit-harvest storage reset            back to ./data

lit-harvest jobs                     see job status
lit-harvest quota                    see remaining quota
```

---

## Troubleshooting

| Message | What it means | What to do |
| --- | --- | --- |
| `No Elsevier API key is configured yet.` | You have not stored a key | Run `lit-harvest auth set elsevier university_primary` |
| `Elsevier rejected your API key.` | The key is wrong or disabled | Re-run `auth set` with a correct key |
| `Your account is not entitled to this content.` | The key works, but no access to this article | Not a bug — try a DOI you have access to |
| `Elsevier could not find this DOI.` | The DOI is wrong or not in ScienceDirect | Check the DOI string |
| `Column 'doi' not found` | Your CSV has no header row | Add a `doi` header, or save as `.txt` with one DOI per line |
| Dashboard shows an error page | The server process is old | Stop it with Ctrl+C and run `lit-harvest ui` again |

## Important notes

- **Your key is personal.** Never share it or commit it to Git. The tool stores it in a private file
  and refuses to upload it anywhere.
- **Entitlement is yours.** This tool does not bypass paywalls and cannot download anything your
  institution or account cannot access.
- **Everything is local.** Closing the browser does not delete your data; deleting the `data/`
  folder does.
- **Only one instance per person.** If you share a computer, each user has their own project folder.

## Next steps

Once the basics work, see:

- [README.md](README.md) — full feature reference
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — credentials, quotas, resuming
- [docs/API.md](docs/API.md) — local HTTP API

---

# 简体中文

## 这是什么

**Literature Harvester（文献采集器）** 是一个**运行在你自己电脑上**的程序。它会检索学术文献，
下载**你有权访问**的全文，然后整齐地保存在本地文件夹里。

开始之前，先记住四件事：

1. **它不是网站。** 没有云端服务，一切都存在你电脑上的文件夹里。
2. **你需要自己的 API Key。** 这个工具要访问 Elsevier（Scopus + ScienceDirect），必须使用
   **你自己的**密钥。没有密钥它会拒绝运行。
3. **别人看不到你的数据。** 你的文献、密钥、配额都只在本机。
4. **有演示模式。** 不用密钥就能用内置示例数据体验完整界面。不确定的话，先做这一步。

## 第 0 步 —— 不用密钥先试一下（推荐先做）

这一步会创建三篇示例论文，让你安全地随便点。不需要任何 API Key。

```bash
cd /path/to/lit-harvest
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/lit-harvest demo
.venv/bin/lit-harvest ui
```

然后在浏览器打开：

```text
http://127.0.0.1:8765
```

你会看到三篇示例论文。可以随意浏览各个页面：

| 页面 | 展示内容 |
| --- | --- |
| **总览 Overview** | 文献数、任务数、配额、失败情况 |
| **文献 Papers** | 每篇论文及其处理阶段 |
| **提供商 Providers** | 使用了哪个凭证、还剩多少配额 |
| **失败任务 Failures** | 哪些失败了以及原因 |

体验完之后，清除示例数据：

```bash
.venv/bin/lit-harvest demo --clear
```

> 演示过程完全不联网，也不需要密钥。

## 第 1 步 —— 获取 Elsevier API Key

1. 打开 **https://dev.elsevier.com/** 并登录（没有账号就免费注册）。
2. 为你的账号创建一个 **API Key**。
3. 部分访问权限（例如 Scopus）需要你的机构有相应订阅。如果你的 Key 没有权限，工具会明确告诉
   你，而不会瞎猜。

下一步会把这个 Key 粘贴一次。请妥善保管。

## 第 2 步 —— 安装（只需一次）

如果你已经做过第 0 步，可以跳过安装，直接到第 3 步。

```bash
cd /path/to/lit-harvest

# 创建独立的 Python 环境
python3.11 -m venv .venv

# 安装工具及其依赖
.venv/bin/python -m pip install -e '.[dev]'

# 创建本地配置文件
cp config.example.yaml config.yaml
```

> 需要 **Python 3.11 或更高版本**。macOS 上可以用 `python3 --version` 查看。

## 第 3 步 —— 保存 API Key（只需一次）

执行下面的命令，按提示粘贴你的 Key。**输入过程中密钥是隐藏的。**

```bash
.venv/bin/lit-harvest auth set elsevier university_primary
```

```text
API key for elsevier/university_primary:
```

密钥会保存到项目内的私有文件：

```text
<项目目录>/.lit-harvest/secrets.json   （权限 0600，已被 Git 忽略）
```

它**绝不会**被写进 `config.yaml`、数据库、日志或网页。

### 检查是否可用

```bash
.venv/bin/lit-harvest doctor --network
```

期望输出：

```text
Elsevier credential detected
Scopus Search STANDARD reachable
ScienceDirect Article Retrieval reachable
```

如果哪里有问题，工具会打印通俗易懂的处理建议，并且不会继续执行。

---

## 方式 A —— 使用网页端（大多数人推荐）

启动面板：

```bash
.venv/bin/lit-harvest ui
```

打开：

```text
http://127.0.0.1:8765
```

界面是中英双语的，点击左侧边栏的 **中文** 或 **EN** 即可切换，默认跟随浏览器语言。

你会看到四个页面：

| 页面 | 用途 |
| --- | --- |
| **总览** | 查看总量、流水线进度、配额余量 |
| **文献** | 添加 DOI、导入 CSV、检索、下载文件 |
| **提供商** | 检查凭证健康状态和剩余配额 |
| **失败任务** | 重试或取消失败任务、暂停/恢复队列 |

### 1. 添加单个 DOI

在 **文献** 页面的「**添加 DOI**」框中：

1. 粘贴 DOI，例如 `10.1016/j.mtcomm.2026.115551`
2. 如果需要 PDF，勾选「**同时下载出版商 PDF**」
3. 点击「**立即获取**」

工具会下载这篇文章，并显示在下方的列表中。

### 2. 从文件批量导入 DOI

在「**从文件批量导入**」框中：

1. 选择文件（`.csv`、`.tsv`、`.txt`、`.json`、`.jsonl`）
2. 设置「**DOI 列名**」，默认是 `doi`
3. 保持勾选「**立即执行**」即可马上开始下载
4. 需要 PDF 就勾选「**同时下载出版商 PDF**」
5. 点击「**上传并导入**」

点「**下载示例 CSV**」可以拿到一个现成的例子。

**CSV 的最低要求：** 必须有表头行，并且至少包含 DOI 列。

```csv
doi
10.1016/j.mtcomm.2026.115551
```

可以有多余的列，会被忽略：

```csv
doi,title,notes
10.1016/j.mtcomm.2026.115551,某篇论文,我的备注
```

列名也可以不同：如果你的文件用的是 `identifier`，就把「**DOI 列名**」改成 `identifier`。

以下 DOI 写法都会被自动识别：

```text
10.1016/j.xxx
https://doi.org/10.1016/j.xxx
http://dx.doi.org/10.1016/j.xxx
doi:10.1016/j.xxx
DOI: 10.1016/j.xxx
```

### 3. 按主题检索

在「**检索 Scopus**」框中输入检索式，点击「**开始检索**」：

```text
TITLE-ABS-KEY("solid-state battery")
```

用「**最大结果数**」限制数量（测试时先设 10 比较稳妥）。

### 4. 下载你的文章

| 按钮 | 得到什么 |
| --- | --- |
| **下载 XML**（文献详情页） | 出版商结构化全文 |
| **下载 PDF**（文献详情页） | 出版商 PDF（前提是你有权限） |
| **下载 JSON**（文献详情页） | 规范化、机器可读的文档 |
| **打包下载全部数据（ZIP）**（列表页） | 全部数据，可选是否包含 PDF |
| **导出 CSV**（列表页） | 文献清单表格 |

### 5. 文件保存在哪里

```text
data/
├── lit_harvest.db                       # 你的数据库
└── papers/
    └── 10.1016_j.mtcomm.2026.115551/
        ├── raw/elsevier_xml.xml         # 原始文件，未经改动
        ├── raw/elsevier_pdf.pdf         # 只有你要求时才下载
        ├── normalized/paper.json        # 清洗后的结构化版本
        └── state.json                   # 处理记录
```

### 6. 选择文件保存位置（可选）

默认所有数据都保存在项目内的 `data/` 目录。你可以改成任意文件夹，例如移动硬盘。

1. 在左侧边栏打开「**存储 / Storage**」页面。
2. 输入或粘贴目标文件夹，例如：

   ```text
   /Users/你的用户名/lit-harvest-data
   ```
3. 页面会立即检查该目录并告知是否可用。
4. 点击「**使用此目录并复制数据**」。

已有的文献和数据库会被**复制**到新目录，原目录保留作为备份。然后重启工具：

```bash
# 先按 Ctrl+C 停止，然后
.venv/bin/lit-harvest ui
```

想改回 `./data`，在同一页面点击「**恢复默认**」即可。

> 设置保存在 `.lit-harvest/settings.json`（私有文件，已被 Git 忽略），重启后依然生效，无需手改
> 配置文件。

### 7. 停止面板

回到启动它的终端，按 **Ctrl + C**。

---

## 方式 B —— 使用命令行

每个操作都有对应命令。都在项目目录下执行。

### 检查环境

```bash
.venv/bin/lit-harvest doctor --network
```

### 获取单篇文章

```bash
.venv/bin/lit-harvest fetch 10.1016/j.mtcomm.2026.115551
```

同时要 PDF：

```bash
.venv/bin/lit-harvest fetch 10.1016/j.mtcomm.2026.115551 --pdf
```

### 从文件批量获取

```bash
.venv/bin/lit-harvest fetch papers.csv --doi-column doi
```

把文件名换成你自己的。CSV 规则与上面相同。

### 按主题检索

```bash
.venv/bin/lit-harvest search \
  --query 'TITLE-ABS-KEY("solid-state battery")' \
  --max-results 20
```

顺便导出表格：

```bash
.venv/bin/lit-harvest search \
  --query 'TITLE-ABS-KEY("solid-state battery")' \
  --max-results 20 \
  --export results.csv
```

### 日常常用命令

```bash
.venv/bin/lit-harvest jobs              # 排队 / 运行 / 完成情况
.venv/bin/lit-harvest quota             # 还剩多少 API 配额
.venv/bin/lit-harvest parse             # 重新处理已下载的 XML
.venv/bin/lit-harvest parse --force     # 全部重新处理
.venv/bin/lit-harvest export papers.csv # 导出文献清单
.venv/bin/lit-harvest pause             # 暂停队列
.venv/bin/lit-harvest resume            # 恢复队列
.venv/bin/lit-harvest retry --transient # 重试临时失败
```

### 用 worker 批量处理

网页端会自动运行后台 worker。命令行可以跑一批：

```bash
.venv/bin/lit-harvest worker --once
```

或者常驻运行：

```bash
.venv/bin/lit-harvest worker
```

---

## 常用命令速查

```text
lit-harvest demo                     创建示例数据（不需要 Key）
lit-harvest demo --clear             清除示例数据
lit-harvest auth set elsevier university_primary    保存你的 API Key
lit-harvest doctor --network         检查是否一切正常
lit-harvest ui                       打开网页面板

lit-harvest fetch DOI                下载一篇文章
lit-harvest fetch DOI --pdf          下载一篇文章 + PDF
lit-harvest fetch file.csv           批量下载
lit-harvest search --query "..." --max-results 20
lit-harvest parse                    重新处理已下载文件
lit-harvest export papers.csv        导出清单

lit-harvest storage show             查看当前存储位置
lit-harvest storage set PATH         更改存储目录（会复制数据）
lit-harvest storage reset            恢复默认 ./data

lit-harvest jobs                     查看任务状态
lit-harvest quota                    查看剩余配额
```

---

## 常见问题排查

| 提示 | 含义 | 怎么办 |
| --- | --- | --- |
| `No Elsevier API key is configured yet.` | 还没保存密钥 | 执行 `lit-harvest auth set elsevier university_primary` |
| `Elsevier rejected your API key.` | 密钥错误或未启用 | 用正确的 Key 重新执行 `auth set` |
| `Your account is not entitled to this content.` | 密钥没问题，但没有这篇文章的权限 | 不是程序 bug，换一篇你有权限的 DOI |
| `Elsevier could not find this DOI.` | DOI 写错或不在 ScienceDirect | 检查 DOI 字符串 |
| `Column 'doi' not found` | CSV 没有表头 | 加上 `doi` 表头，或改存为 `.txt`（每行一个 DOI） |
| 网页显示错误页 | 服务进程是旧的 | 按 Ctrl+C 停掉，重新执行 `lit-harvest ui` |

## 重要提醒

- **密钥是你个人的。** 不要分享，也不要提交到 Git。工具会把它存在私有文件里，不会上传到任何地方。
- **权限是你自己的。** 本工具不绕过付费墙，也无法下载你机构或账号无权访问的内容。
- **数据全在本地。** 关闭浏览器不会删除数据；删除 `data/` 目录才会。
- **每人一个实例。** 如果多人共用一台电脑，每个人使用各自的项目目录。

## 下一步

基础功能跑通后，可以看：

- [README-ZH.md](README-ZH.md) —— 完整功能说明
- [docs/OPERATIONS.md](docs/OPERATIONS.md) —— 凭证、配额、断点续跑
- [docs/API.md](docs/API.md) —— 本地 HTTP 接口
