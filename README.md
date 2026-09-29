# Personal dotfiles

macOS 与 Arch Linux 共用的 Kitty / Neovim 配置。优先原生编辑习惯、少量依赖和可回滚部署。

- Kitty：沿用 Catppuccin Mocha 与 JetBrains Mono，不透明背景，少量留白，标准快捷键。
- Neovim ≥ 0.11.3：原生 LSP / 补全、文件与文本检索、Git、LaTeX；5 个功能插件加 lazy.nvim。
- Rust：rust-analyzer；Python：basedpyright + Ruff；LaTeX：texlab + VimTeX；Markdown：原生编辑，可选 Marksman。
- AI agent 在独立终端工作；Neovim 检查外部文件变化，保留有未保存修改时的冲突提示。
- 本地差异放在仓库外，旧配置和 Neovim 插件数据保留。暂不管理 shell、SSH、Git 身份或桌面会话。

## 新机器恢复

先安装 Git、Python 3、[rustup](https://rustup.rs/)；macOS 还需要 [Homebrew](https://brew.sh/)。
Arch 使用系统自带的 pacman。Rust 使用 rustup 管理，不另装一份 Homebrew Rust。

```sh
git clone https://github.com/singlelektron/Configs.git ~/GIT_repository/Configs
cd ~/GIT_repository/Configs

# 先查看软件安装计划，再执行；Arch 的 sudo / pacman 确认需要本人操作。
bash scripts/install-tools.sh
bash scripts/install-tools.sh --apply

# 先预览链接和备份计划，再部署。
python3 scripts/deploy.py
python3 scripts/deploy.py --apply

# 打开编辑器，执行 :DotfilesInstall，然后重启 Neovim。
nvim
python3 scripts/doctor.py
```

在功能分支尚未合并时，clone 命令加 `--branch codex/dotfiles-foundation`。

软件安装与配置部署分开：Homebrew 不主动升级已装工具；Arch 使用 `pacman -Syu --needed`，
会执行完整系统升级以避免部分升级。脚本不安装大型 TeX 发行版、Niri 或额外 AI 客户端。
软件安装无法通过配置回滚命令撤销。系统包随包管理器更新；插件提交和 Python CLI 版本固定。

Kitty 会为新窗口补充用户工具路径。其他终端和 SSH shell 中，按需把下面一行加入
自己的 `~/.zshrc` 或 `~/.bashrc`：

```sh
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
```

Neovim 也会为这两个标准目录补充 PATH，因此非交互 SSH 启动仍可发现语言服务。
项目的 Python / Rust 依赖仍由项目中的 `uv.lock`、`pyproject.toml`、`Cargo.lock` 等管理。

## 日常使用

打开文件、窗口、缓冲区、终端和寄存器都沿用 Neovim 的方式：`:edit`、`:split`、`:vsplit`、
`:buffer`、`:terminal`、`Ctrl-w`。不改写 Enter、Tab、`y/d/p`，不自动格式化或自动提交。

| 按键 / 命令 | 功能 |
| --- | --- |
| `Space ff` / `fg` / `fb` / `fh` | 找文件 / 搜索文本 / 缓冲区 / 帮助 |
| `gd`、`K` | 定义、悬浮信息 |
| `grn` / `gra` / `grr` / `gri` | 原生重命名 / 代码操作 / 引用 / 实现 |
| `Ctrl-x Ctrl-o` | 原生 LSP 补全；`Ctrl-n/p` 选择，`Ctrl-y` 接受 |
| `[d` / `]d`、`Space e` / `q` | 诊断跳转、详情 / location list |
| `Space cf` | 显式格式化（Python 使用 Ruff，Rust 使用 rust-analyzer） |
| `Space gs`、`:Git`、`:Gdiffsplit` | Git 状态、命令、diff |
| `[c` / `]c`、`Space hp` | Git 修改跳转、预览修改块 |
| `Space y` / `Space Y` | 复制选区 / 整行到系统剪贴板 |
| `Space us` | 英文拼写检查开关，默认关闭 |
| `\ll` / `\lv` / `\le` | VimTeX 单次编译 / 查看 PDF / 错误列表 |
| `:checkhealth dotfiles` | 配置和依赖诊断 |

Markdown、TeX 和 Git 提交消息只做视觉折行，不自动重新排版正文。
Python 优先采用项目根目录 `.venv/bin/python`，然后是已激活虚拟环境和系统 Python。
运行 `uv sync` 后重启对应 LSP / Neovim 即可识别新环境。
Rust 保留 rust-analyzer 的标准 Cargo 检查、构建脚本和过程宏分析。
文件和文本检索使用当前工作目录；从项目目录启动 `nvim`，或用 `:cd` 切换范围。

Kitty 保留 `Ctrl-Shift-C/V` 复制粘贴、`Ctrl-Shift-Enter` 新窗口、`Ctrl-Shift-T` 新标签，
后两者继承当前目录；macOS 的 Command 快捷键仍可用。配置更新后可用 `Ctrl-Shift-F5` 重载。

## 远端使用

从 Kitty 中连接远端，推荐使用其 [SSH kitten](https://sw.kovidgoyal.net/kitty/kittens/ssh/)，
它会处理终端能力信息；普通 SSH 仍然可用，不要全局把 `TERM` 强制改成 xterm。

```sh
kitten ssh user@arch-host
# 在远端 clone 同一仓库，运行上面的安装、部署和诊断命令。
```

SSH 下 `Space y` 通过 OSC 52 复制到本机；粘贴用 Kitty 的粘贴快捷键。
配置不主动请求读取本机剪贴板。无图形会话的 SSH 不能验证远端窗口外观或 PDF 查看器。
主机别名、用户、Tailscale 设置和密钥留在各自机器上；不用 dotfiles 同步 `~/.ssh`。

## 本机覆盖与恢复旧配置

共享配置 → 平台 Kitty 配置 → 本地覆盖。可创建以下文件；它们不在仓库中：

```text
~/.config/dotfiles-local/kitty.conf   # 如 font_size 15.0
~/.config/dotfiles-local/nvim.lua    # 如 vim.opt.number = false
```

设置了 `XDG_CONFIG_HOME` 时使用它替代 `~/.config`。
部署器只链接 Kitty 的三个受管文件和整个 Neovim 配置目录，保留 Kitty 其他文件。
若目标已存在，先整体移入 `${XDG_STATE_HOME:-~/.local/state}/dotfiles/backups/<id>/`，
权限为仅当前用户访问，并写入恢复清单。重复部署没有额外副作用。

```sh
# 使用部署完成时打印的真实绝对目录；先预览，再执行。
python3 scripts/deploy.py --restore /absolute/path/to/backup-id
python3 scripts/deploy.py --restore /absolute/path/to/backup-id --apply
```

恢复会移除本次创建的链接并放回原件；发现目标被换成新文件时会停止，不覆盖新修改。
部署中断也保留清单和原件，可用同一命令恢复。
链接指向本仓库：编辑受管文件就是编辑仓库文件，恢复旧配置不会撤销这些 Git 修改。
部署器拒绝符号链接父目录；若使用自定义 XDG 路径，请先提供真实绝对路径。
不要移动或删除正在使用的仓库目录；需要搬迁时保留旧目录、从新位置重新部署并检查链接。

旧 LazyVim 的 `~/.local/share/nvim/lazy` 不变，新插件在 `~/.local/share/nvim/dotfiles-lazy`。
普通启动不联网，首次未安装插件时基本编辑仍可用；`:DotfilesInstall` 才会下载并恢复锁定版本。
不要为同步配置复制整个 `~/.local/share/nvim` 或 `~/.local/state/nvim`。

## 可选写作工具

当前 macOS 已有 TeX Live；保留原安装。新 macOS 可安装
[`mactex-no-gui`](https://formulae.brew.sh/cask/mactex-no-gui)。需要在 Arch 本地编译时：

```sh
sudo pacman -Syu --needed texlive-binextra texlive-latexrecommended \
  texlive-latexextra texlive-xetex texlive-langchinese noto-fonts-cjk
```

`texlive-binextra` 提供 [TeX 辅助工具](https://archlinux.org/packages/extra/any/texlive-binextra/)，
包括 latexmk；大型 TeX 包按项目需求安装。编译引擎由项目指定，中文文稿例如首行
`% !TeX program = xelatex`，或在项目 `.latexmkrc` 中配置。VimTeX 不默认加 `-shell-escape`。
PDF 由系统默认查看器打开；反向搜索可在以后选定 Skim / Zathura 工作流时再配置。
没有 latexmk 时保留 LaTeX 编辑功能并关闭编译器；安装 TeX 工具后重启 Neovim 即可启用编译快捷键。

Markdown 跨文件链接补全可选安装 Marksman：`brew install marksman` 或
`sudo pacman -Syu --needed marksman`，随后重启 Neovim。
[Homebrew 当前给出的弃用日期是 2026-11-10](https://formulae.brew.sh/formula/marksman)，
因此它不进入必装清单。普通 Markdown 编辑、检索和拼写不依赖它。

## 维护

```text
config/kitty/         共享终端配置
config/nvim/          共享编辑器配置和插件锁
platforms/macos/      macOS 差异
platforms/linux/      Linux 差异，预留 Niri 扩展位置
packages/             平台软件清单、Python CLI 版本
scripts/              安装、可回滚部署、诊断、检查
tests/                部署回归测试、Neovim 冒烟测试
docs/                 初始环境审计与验证记录
```

更新：`git pull --ff-only` 后检查差异，重复部署，必要时执行 `:DotfilesInstall`。
主动升级插件时运行 `:Lazy update`，审查 `lazy-lock.json` 并在两台机器验证后提交。
Python 工具升级要修改版本清单并重跑安装；系统包仍由 Homebrew / pacman 管理。

本地检查：`bash scripts/check.sh`。基础检查不联网，完整插件安装验证另见验证记录。
提交前运行 `git diff --cached`。`.gitignore` 只是辅助，不能代替检查：不要加入 SSH/GPG 密钥、
Token、`.env`、AI 登录配置、会话历史、撤销文件、缓存、Git 身份和绝对本机路径。

初始选型见 [环境审计](docs/environment-audit.md)，实测范围与复测命令见 [验证记录](docs/validation.md)。
