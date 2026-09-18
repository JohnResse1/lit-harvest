# Quick Start / 快速开始

[English](#english) · [简体中文](#简体中文)

> **Never used this before? Only read this file.**
> It assumes you do not write code. Follow it step by step, top to bottom.
>
> **从没用过？只看这一个文件就够了。**
> 本文假设你不会写代码。请从上到下，一步一步照着做。

---

# English

## What you will end up with

A program running **on your own computer** that can:

- search academic literature
- download the full text you are entitled to
- save everything into a folder on your machine

**Three things to know first:**

1. **It is not a website.** Nothing is uploaded anywhere. Everything stays on your computer.
2. **You need your own Elsevier API key.** The program talks to Elsevier and refuses to run without
   a key. (Step 4 explains how to get one, for free.)
3. **Nobody else can see your data.** Your papers, your key, and your records are private to you.

## Which computer are you on?

The first two steps differ by system. After that, **every command is identical on all systems** —
because we activate the environment, which makes `lit-harvest` available everywhere.

Pick your system and follow along:

- [macOS](#macos--linux)
- [Linux](#macos--linux)
- [Windows](#windows)

## Step 1 — Check that Python is installed (all systems)

Open your terminal:

| System | How to open a terminal |
| --- | --- |
| macOS | Press `⌘ + Space`, type `Terminal`, press Enter |
| Windows | Press `Win`, type `PowerShell`, press Enter |
| Linux | Press `Ctrl + Alt + T` |

Now type this and press Enter:

```bash
python3 --version
```

**Windows users:** if that fails, try `py --version` instead.

### What you should see

```text
Python 3.11.0
```

Anything **3.11 or higher** is fine (3.12, 3.13, …).

### If you see something else

| What you see | What it means | What to do |
| --- | --- | --- |
| `Python 3.9.x` or `3.10.x` | Too old | Install a newer Python (below) |
| `command not found` | Python is not installed | Install Python (below) |
| `3.11` or higher | You are ready | **Skip to Step 2** |

### Installing Python

#### macOS

The simplest way is the official installer:

1. Go to **https://www.python.org/downloads/**
2. Click the big yellow **Download Python 3.x.x** button
3. Open the downloaded `.pkg` file and click through the installer
4. **Close your terminal and open a new one** (important!)
5. Run `python3 --version` again

<details>
<summary>Prefer Homebrew? (click to expand)</summary>

```bash
# Install Homebrew first if you do not have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12
```
</details>

#### Windows

1. Go to **https://www.python.org/downloads/**
2. Click **Download Python 3.x.x**
3. Run the installer
4. ⚠️ **On the first screen, tick "Add python.exe to PATH"** — this checkbox matters
5. Click **Install Now**
6. **Close PowerShell and open a new one**
7. Run `py --version` again

#### Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version
```

## Step 2 — Get the project (all systems)

You have two options. **Option A is easier** and does not require Git.

### Option A — Download as a ZIP (recommended if you are unsure)

1. Open this link in your browser:

   ```text
   https://github.com/JohnResse1/lit-harvest/archive/refs/heads/main.zip
   ```

2. The file downloads, usually into your **Downloads** folder.
3. **Unzip it** (double-click on macOS/Windows; right-click → Extract on Linux).
4. You now have a folder named something like `lit-harvest-main`.

### Option B — Use Git (if you already have it)

Check whether Git is installed:

```bash
git --version
```

If you see a version number, run:

```bash
cd ~
git clone https://github.com/JohnResse1/lit-harvest.git
```

If you see `command not found`, install Git:

| System | Command |
| --- | --- |
| macOS | Run `git --version` and accept the prompt to install developer tools |
| Windows | Download from **https://git-scm.com/download/win** |
| Linux | `sudo apt install -y git` |

### Now go into the project folder

**This is the part where beginners get stuck.** You must be *inside* the project folder before the
next steps work.

```bash
cd lit-harvest-main
```

> If you used Option B, the folder is named `lit-harvest` instead:
> ```bash
> cd lit-harvest
> ```

**Not sure where the folder is?** Type `ls` (macOS/Linux) or `dir` (Windows) to list what is around
you, and use `cd` to move.

To confirm you are in the right place:

```bash
ls
```

You should see files including `README.md`, `pyproject.toml`, and a folder named `src`.

If you see `No such file or directory`, you are in the wrong folder — use `cd` to navigate.

> **Tip:** You can drag a folder onto the terminal window after typing `cd ` and it will paste the
> path for you.

## Step 3 — Create the environment and install (all systems)

This downloads the libraries the program needs. It runs once, and takes 1–3 minutes.

### 3.1 Create the environment

```bash
python3 -m venv .venv
```

**Windows users:** use this instead:

```powershell
py -3.11 -m venv .venv
```

> If `py -3.11` is not found, use `py -3 -m venv .venv`.
> If that also fails, use `python -m venv .venv`.

### 3.2 Activate the environment

**macOS / Linux:**

```bash
source .venv/bin/activate
```

**Windows PowerShell:**

```powershell
.venv\Scripts\Activate.ps1
```

> If Windows blocks the script with an error about "execution policies", run this once and try again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

**You will know it worked** because your prompt now starts with `(.venv)`:

```text
(.venv) your-name@computer lit-harvest %
```

### 3.3 Install the program

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

> **Why `-e .`?** It installs the program from the current folder in editable mode, which points at
> the code you just downloaded. The dot means "this folder".

You should end with a line like:

```text
Successfully installed lit-harvest-0.1.0 ...
```

## Step 4 — Get your Elsevier API key (one time)

1. Open **https://dev.elsevier.com/** in your browser
2. Click **Sign in** (top right) → **Create account** if you do not have one
3. After signing in, go to **My API Key** (or **API Key Settings**)
4. Create a new key and **copy it** somewhere safe

> **Is it free?** Creating the key is free. Some data (like Scopus) only works if your school has a
> subscription. If yours does not, the program will tell you clearly instead of guessing.

## Step 5 — Give the program your key (one time)

Make sure you are still in the project folder **and** the `(.venv)` prefix is visible.

```bash
lit-harvest auth set elsevier university_primary
```

You will be asked:

```text
API key for elsevier/university_primary:
```

**Paste your key and press Enter.** The text stays hidden while you paste — that is normal.

### Where did my key go?

```text
.lit-harvest/secrets.json      (inside the project folder)
```

It is stored only on your computer, with restricted permissions, and it is **excluded from Git**, so
it can never be uploaded by accident.

## Step 6 — Check that everything works (all systems)

```bash
lit-harvest doctor --network
```

### What success looks like

```text
Elsevier credential detected
Scopus Search STANDARD reachable
ScienceDirect Article Retrieval reachable
```

### If something is wrong

| Message | What to do |
| --- | --- |
| `No Elsevier API key is configured yet.` | You skipped Step 5 — run the `auth set` command again |
| `Elsevier rejected your API key.` | The key was copied wrong — get a fresh one and repeat Step 5 |
| `Your account is not entitled to this content.` | Your school has no subscription — see the note in Step 4 |

## Step 7 — Try it without downloading anything (recommended)

This creates three sample papers so you can click around safely, with **no API key and no internet**:

```bash
lit-harvest demo
lit-harvest ui
```

Now open your browser and go to:

```text
http://127.0.0.1:8765
```

Explore the four pages:

| Page | What it shows |
| --- | --- |
| **Overview / 总览** | How many papers, jobs, and how much quota is left |
| **Papers / 文献** | Every paper and what stage it is at |
| **Providers / 提供商** | Which credential is used and how much quota remains |
| **Failures / 失败任务** | Anything that failed and why |

Switch the interface language with the **中文 / EN** buttons in the left sidebar.

When you are done, stop the program with `Ctrl + C` in the terminal, then remove the samples:

```bash
lit-harvest demo --clear
```

## Step 8 — Use it for real

Start the dashboard again:

```bash
lit-harvest ui
```

Then open `http://127.0.0.1:8765` and use the **Papers / 文献** page.

### Add one article

1. In the **Add a DOI** box, paste a DOI, for example `10.1016/j.mtcomm.2026.115551`
2. Tick **Also download the publisher PDF** if you want the PDF too
3. Click **Fetch now**

### Add many articles from a file

1. Prepare a `.csv` file with a header row. The smallest possible file is:

   ```csv
   doi
   10.1016/j.mtcomm.2026.115551
   ```

2. In the **Batch import from file** box, choose your file
3. Leave **DOI column** as `doi`
4. Keep **Run immediately** ticked
5. Click **Upload and import**

A ready-made example is available from the **Download sample CSV** link on that same page.

### Search, then choose what to download

1. Type a query in the **Search Scopus** box, for example:

   ```text
   TITLE-ABS-KEY("solid-state battery")
   ```

2. Click **Run search**
3. **Nothing is downloaded yet.** A table appears with a checkbox on every row.
4. Tick the papers you want (or use the header checkbox to select all)
5. Use **Choose which metadata columns to show** to add columns like authors, citations, or ISSN
6. Click **Download selected**

### Where do my files go?

```text
data/
├── lit_harvest.db                       your database
└── papers/
    └── 10.1016_j.mtcomm.2026.115551/
        ├── raw/elsevier_xml.xml         the original file, untouched
        ├── raw/elsevier_pdf.pdf         only if you asked for the PDF
        ├── normalized/paper.json        the cleaned-up, structured version
        └── state.json                   processing record
```

You can move this folder later from the **Storage / 存储** page in the dashboard.

### Stop the program

Press `Ctrl + C` in the terminal window where it is running.

## Every time you come back

You do **not** need to reinstall. Just:

```bash
# 1. open a terminal and go to the project folder
cd ~/lit-harvest-main          # use YOUR actual folder path

# 2. activate the environment
source .venv/bin/activate      # macOS/Linux
.venv\Scripts\Activate.ps1     # Windows

# 3. start the dashboard
lit-harvest ui
```

If you forget step 2, you will get `command not found: lit-harvest`. That is the most common
mistake — just run the activate command and try again.

## Command cheat sheet

After activating the environment, these work the same on macOS, Linux, and Windows:

```text
lit-harvest demo                 create sample data (no key needed)
lit-harvest demo --clear         remove sample data
lit-harvest auth set elsevier university_primary   store your API key
lit-harvest doctor --network     check that everything works
lit-harvest ui                   open the dashboard

lit-harvest fetch DOI            download one article
lit-harvest fetch DOI --pdf      download one article plus its PDF
lit-harvest fetch papers.csv     download many articles from a file
lit-harvest search --query "..." --max-results 20   preview search results
lit-harvest export papers.csv    export your list

lit-harvest storage show         see where files are stored
lit-harvest jobs                 see job status
lit-harvest quota                see remaining API quota
```

## Troubleshooting

| Problem | Cause | Fix |
| --- | --- | --- |
| `command not found: lit-harvest` | The environment is not active | Run the activate command from Step 3.2 |
| `command not found: python3.11` | You typed a version that is not installed | Use `python3` (macOS/Linux) or `py` (Windows) |
| `No such file or directory` | You are not in the project folder | Use `cd` to enter the folder from Step 2 |
| `No module named venv` (Linux) | Missing system package | `sudo apt install -y python3-venv` |
| Windows blocks `Activate.ps1` | PowerShell execution policy | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `pip install` is very slow | Network | Retry, or use a mirror: `python -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| Dashboard shows an old version | A stale process is running | Press `Ctrl + C`, then run `lit-harvest ui` again |
| Browser shows nothing at `127.0.0.1:8765` | The program stopped | Check the terminal for errors and restart |

## Important notes

- **Your key is personal.** Never share it, never paste it into a chat or commit it to Git.
- **This tool does not bypass paywalls.** It can only download what your school or account is
  entitled to.
- **Everything is local.** Closing the browser does not delete anything; only deleting the `data/`
  folder does.

## Next steps

- [README.md](README.md) — full feature reference
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — credentials, quotas, resuming
- [docs/API.md](docs/API.md) — the local HTTP API

---

# 简体中文

## 做完之后你会得到什么

一个**运行在你自己电脑上**的程序，它可以：

- 检索学术文献
- 下载你有权访问的全文
- 把所有内容保存到你电脑上的文件夹里

**先记住三件事：**

1. **它不是网站。** 不会上传到任何地方，一切都留在你自己的电脑上。
2. **你需要自己的 Elsevier API Key。** 程序要和 Elsevier 通信，没有 Key 会拒绝运行。
   （第 4 步会教你怎么免费申请。）
3. **别人看不到你的数据。** 你的文献、密钥、记录都只属于你。

## 你用的是什么系统？

前两步在不同系统上略有差别。从第 3 步开始，**所有系统命令完全一样**——因为我们激活了环境，
之后 `lit-harvest` 在任何系统上都能直接用。

选择你的系统，跟着做：

- [macOS](#macos--linux-中文)
- [Linux](#macos--linux-中文)
- [Windows](#windows-中文)

## 第 1 步 —— 确认装了 Python（所有系统）

先打开终端：

| 系统 | 怎么打开终端 |
| --- | --- |
| macOS | 按 `⌘ + 空格`，输入 `Terminal`，回车 |
| Windows | 按 `Win` 键，输入 `PowerShell`，回车 |
| Linux | 按 `Ctrl + Alt + T` |

输入下面这行，按回车：

```bash
python3 --version
```

**Windows 用户：** 如果上面这条报错，改用 `py --version`。

### 应该看到什么

```text
Python 3.11.0
```

**只要大于等于 3.11 就行**（3.12、3.13 都可以）。

### 如果看到的不是这个

| 你看到 | 含义 | 怎么办 |
| --- | --- | --- |
| `Python 3.9.x` 或 `3.10.x` | 版本太低 | 按下面的方法安装新版 |
| `command not found` | 没装 Python | 按下面的方法安装 |
| `3.11` 或更高 | 可以继续 | **直接跳到第 2 步** |

### 安装 Python

#### macOS

最简单是用官方安装包：

1. 打开 **https://www.python.org/downloads/**
2. 点击黄色的 **Download Python 3.x.x** 按钮
3. 打开下载的 `.pkg` 文件，一路点击安装
4. **关闭终端，重新打开一个**（这一步很重要！）
5. 再运行一次 `python3 --version`

<details>
<summary>想用 Homebrew？（点击展开）</summary>

```bash
# 如果还没装 Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12
```
</details>

#### Windows

1. 打开 **https://www.python.org/downloads/**
2. 点击 **Download Python 3.x.x**
3. 运行安装程序
4. ⚠️ **在第一个界面勾选 "Add python.exe to PATH"** —— 这个勾选框很关键
5. 点击 **Install Now**
6. **关闭 PowerShell，重新打开一个**
7. 再运行一次 `py --version`

#### Linux（Ubuntu / Debian）

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version
```

## 第 2 步 —— 把项目下载下来（所有系统）

有两种方式。**方式 A 更简单**，不需要 Git。

### 方式 A —— 下载 ZIP（不确定就用这个）

1. 在浏览器打开这个链接：

   ```text
   https://github.com/JohnResse1/lit-harvest/archive/refs/heads/main.zip
   ```

2. 文件会下载到你的**下载（Downloads）**文件夹
3. **解压它**（macOS/Windows 双击即可；Linux 右键 → 解压）
4. 你会得到一个类似 `lit-harvest-main` 的文件夹

### 方式 B —— 用 Git（如果你已经装了）

先检查 Git 是否已安装：

```bash
git --version
```

如果有版本号，运行：

```bash
cd ~
git clone https://github.com/JohnResse1/lit-harvest.git
```

如果提示 `command not found`，先安装 Git：

| 系统 | 做法 |
| --- | --- |
| macOS | 运行 `git --version`，按提示安装开发者工具 |
| Windows | 从 **https://git-scm.com/download/win** 下载安装 |
| Linux | `sudo apt install -y git` |

### 进入项目文件夹

**新手最容易卡在这里。** 你必须先**进入**项目文件夹，后面的命令才能生效。

```bash
cd lit-harvest-main
```

> 如果你用的是方式 B，文件夹名是 `lit-harvest`：
> ```bash
> cd lit-harvest
> ```

**不知道文件夹在哪？** 输入 `ls`（macOS/Linux）或 `dir`（Windows）看看周围有什么，
再用 `cd` 一层层进去。

确认位置是否正确：

```bash
ls
```

你应该能看到 `README.md`、`pyproject.toml`，以及一个叫 `src` 的文件夹。

如果提示 `No such file or directory`，说明你不在正确的文件夹里——用 `cd` 导航过去。

> **小技巧：** 先输入 `cd `（注意后面有个空格），然后把文件夹**拖到终端窗口上**，
> 路径会自动填进去。

## 第 3 步 —— 创建环境并安装（所有系统）

这一步会下载程序需要的库，只需做一次，大约 1–3 分钟。

### 3.1 创建环境

```bash
python3 -m venv .venv
```

**Windows 用户改用：**

```powershell
py -3.11 -m venv .venv
```

> 如果提示找不到 `py -3.11`，就换成 `py -3 -m venv .venv`。
> 如果还是不行，用 `python -m venv .venv`。

### 3.2 激活环境

**macOS / Linux：**

```bash
source .venv/bin/activate
```

**Windows PowerShell：**

```powershell
.venv\Scripts\Activate.ps1
```

> 如果 Windows 提示 "execution policies" 相关的错误，先运行下面这条，再重试：
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

**成功的标志**：命令提示符前面出现了 `(.venv)`：

```text
(.venv) your-name@computer lit-harvest %
```

### 3.3 安装程序

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

> **`-e .` 是什么意思？** 表示从当前文件夹以「可编辑」方式安装，指向你刚下载的代码。
> 那个点 `.` 代表「当前这个文件夹」。

最后应该看到类似：

```text
Successfully installed lit-harvest-0.1.0 ...
```

## 第 4 步 —— 申请 Elsevier API Key（一次）

1. 浏览器打开 **https://dev.elsevier.com/**
2. 点右上角 **Sign in** → 没有账号就点 **Create account**
3. 登录后进入 **My API Key**（或 **API Key Settings**）
4. 创建一个新 Key，**复制保存好**

> **免费吗？** 申请 Key 是免费的。但部分数据（如 Scopus）需要你学校有订阅才可用。
> 如果没有，程序会明确告诉你，而不是胡乱猜。

## 第 5 步 —— 把 Key 交给程序（一次）

确认你仍在项目文件夹里，**并且**命令提示符前有 `(.venv)`。

```bash
lit-harvest auth set elsevier university_primary
```

会提示你：

```text
API key for elsevier/university_primary:
```

**粘贴你的 Key，按回车。** 粘贴时文字不会显示，这是正常的。

### Key 存到哪里了？

```text
.lit-harvest/secrets.json      （在项目文件夹内）
```

只存在你的电脑上，权限受限，并且**已被 Git 排除**，所以不会误传上去。

## 第 6 步 —— 检查是否一切正常（所有系统）

```bash
lit-harvest doctor --network
```

### 成功的样子

```text
Elsevier credential detected
Scopus Search STANDARD reachable
ScienceDirect Article Retrieval reachable
```

### 如果出错了

| 提示 | 怎么办 |
| --- | --- |
| `No Elsevier API key is configured yet.` | 你跳过了第 5 步——重新运行 `auth set` |
| `Elsevier rejected your API key.` | Key 复制错了——重新申请一个，再重复第 5 步 |
| `Your account is not entitled to this content.` | 你学校没有订阅——见第 4 步的说明 |

## 第 7 步 —— 先空跑一遍（推荐）

这一步会创建三篇示例论文，让你安全地随便点，**不需要 API Key，也不联网**：

```bash
lit-harvest demo
lit-harvest ui
```

然后在浏览器打开：

```text
http://127.0.0.1:8765
```

熟悉这四个页面：

| 页面 | 展示内容 |
| --- | --- |
| **总览 Overview** | 文献数、任务数、剩余配额 |
| **文献 Papers** | 每篇论文及其所处阶段 |
| **提供商 Providers** | 使用了哪个凭证、还剩多少配额 |
| **失败任务 Failures** | 失败了什么、为什么 |

用左侧边栏的 **中文 / EN** 按钮切换语言。

体验完后，在终端按 `Ctrl + C` 停止程序，然后清除示例数据：

```bash
lit-harvest demo --clear
```

## 第 8 步 —— 正式开始使用

再次启动面板：

```bash
lit-harvest ui
```

然后打开 `http://127.0.0.1:8765`，使用「**文献 / Papers**」页面。

### 添加单篇文章

1. 在「**添加 DOI**」框里粘贴 DOI，例如 `10.1016/j.mtcomm.2026.115551`
2. 如果需要 PDF，勾选「**同时下载出版商 PDF**」
3. 点击「**立即获取**」

### 从文件批量添加

1. 准备一个带表头的 `.csv` 文件。最小的文件长这样：

   ```csv
   doi
   10.1016/j.mtcomm.2026.115551
   ```

2. 在「**从文件批量导入**」框里选择文件
3. 「**DOI 列名**」保持 `doi`
4. 保持勾选「**立即执行**」
5. 点击「**上传并导入**」

同一页面上的「**下载示例 CSV**」可以拿到现成的示例文件。

### 检索，然后自己挑选要下载哪些

1. 在「**检索 Scopus**」框输入检索式，例如：

   ```text
   TITLE-ABS-KEY("solid-state battery")
   ```

2. 点击「**开始检索**」
3. **此时还没有下载任何东西。** 下方会出现表格，每行都有勾选框
4. 勾选你想要的文献（也可以点表头全选）
5. 用「**选择要显示的元数据列**」增删要显示的列，比如作者、引用数、ISSN
6. 点击「**下载选中项**」

### 我的文件存在哪里？

```text
data/
├── lit_harvest.db                       你的数据库
└── papers/
    └── 10.1016_j.mtcomm.2026.115551/
        ├── raw/elsevier_xml.xml         原始文件，未被改动
        ├── raw/elsevier_pdf.pdf         只有你要求时才下载
        ├── normalized/paper.json        清洗后的结构化版本
        └── state.json                   处理记录
```

之后可以在面板的「**存储 / Storage**」页面里更改这个位置。

### 停止程序

在运行它的终端窗口按 `Ctrl + C`。

## 以后每次使用

**不需要重新安装**。只需要：

```bash
# 1. 打开终端，进入项目文件夹
cd ~/lit-harvest-main          # 换成你实际的文件夹路径

# 2. 激活环境
source .venv/bin/activate      # macOS/Linux
.venv\Scripts\Activate.ps1     # Windows

# 3. 启动面板
lit-harvest ui
```

如果忘了第 2 步，会提示 `command not found: lit-harvest`。这是最常见的错误，
运行激活命令后重试即可。

## 常用命令速查

激活环境后，以下命令在 macOS、Linux、Windows 上完全一致：

```text
lit-harvest demo                 创建示例数据（不需要 Key）
lit-harvest demo --clear         清除示例数据
lit-harvest auth set elsevier university_primary   保存 API Key
lit-harvest doctor --network     检查是否一切正常
lit-harvest ui                   打开网页面板

lit-harvest fetch DOI            下载一篇文章
lit-harvest fetch DOI --pdf      下载一篇文章 + PDF
lit-harvest fetch papers.csv     从文件批量下载
lit-harvest search --query "..." --max-results 20   先预览检索结果
lit-harvest export papers.csv    导出文献清单

lit-harvest storage show         查看文件保存位置
lit-harvest jobs                 查看任务状态
lit-harvest quota                查看剩余配额
```

## 常见问题排查

| 问题 | 原因 | 解决 |
| --- | --- | --- |
| `command not found: lit-harvest` | 环境没激活 | 运行第 3.2 步的激活命令 |
| `command not found: python3.11` | 输入的版本没装 | 改用 `python3`（macOS/Linux）或 `py`（Windows） |
| `No such file or directory` | 不在项目文件夹里 | 用 `cd` 进入第 2 步的文件夹 |
| `No module named venv`（Linux） | 缺系统包 | `sudo apt install -y python3-venv` |
| Windows 拦截 `Activate.ps1` | PowerShell 执行策略 | 运行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `pip install` 很慢 | 网络问题 | 重试，或换镜像：`python -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 面板显示旧版本 | 有旧进程在跑 | 按 `Ctrl + C`，重新运行 `lit-harvest ui` |
| 浏览器打不开 `127.0.0.1:8765` | 程序已退出 | 检查终端里的错误信息并重启 |

## 重要提醒

- **Key 是私人凭证。** 不要分享，不要粘到聊天里，也不要提交到 Git。
- **本工具不绕过付费墙。** 只能下载你学校或账号有权访问的内容。
- **一切都在本地。** 关闭浏览器不会删除数据；只有删掉 `data/` 文件夹才会。

## 下一步

- [README-ZH.md](README-ZH.md) —— 完整功能说明
- [docs/OPERATIONS.md](docs/OPERATIONS.md) —— 凭证、配额、断点续跑
- [docs/API.md](docs/API.md) —— 本地 HTTP 接口
