# 初始环境审计

日期：2026-09-29。通过本机命令和成功认证后的 SSH 只读检查获得；以下是当日快照。
只记录与配置决策有关的工具和行为，不保存主机地址、用户名、登录配置或使用历史。

| 项目 | macOS | Arch 主机 |
| --- | --- | --- |
| 系统 | macOS 26.6.2，arm64 | Nyarch / Arch 衍生版，x86_64 |
| Shell / 桌面 | Zsh | Bash、GNOME 50 |
| Kitty | 0.47.2 | 0.49.1 |
| Neovim | 0.12.4 | 0.12.5 |
| 原 Neovim | 未定制 LazyVim starter | 未定制 LazyVim starter |
| Rust | 1.96.0，rustup | 1.96.0，rustup |
| Python | 3.14.2，已有 uv | 3.14.7，未装 uv |
| TeX | TeX Live 2025、latexmk、XeLaTeX | 未安装编译工具 |
| AI CLI | 已有 Codex | 已有 Codex |

两边都没有 LazyVim language extras 或自定义快捷键，未发现需要迁移的 Neovim 特殊工作流。
因此用原生 LSP 和小型插件组合替换发行版配置，旧目录整体备份，插件另存新目录。

macOS Kitty 的实际定制只有 Catppuccin Mocha 与 JetBrains Mono NL Nerd Font，保留它们。
Arch Kitty 使用 0.82 透明度、强制 X11，指定的 SF Mono Ligaturized 没有安装并回退到了
Noto Sans Mono。共享配置采用不透明背景、可安装的字体、自动显示后端；未来切换 Niri 不需重写终端配置。

两台主机的 rust-analyzer 路径都是 rustup shim，初始并未安装对应组件；不能用 `command -v`
判断语言服务器已可用。Arch 非交互 SSH 找不到 Cargo 路径，交互 Bash 也缺少 `~/.local/bin`。
安装/诊断脚本显式处理这些差异，不接管整个 shell 配置。

选择简单链接部署器而非引入 chezmoi / Nix / Ansible：目前只有两个应用、少量平台差异，
无需模板系统或额外常驻管理工具。Python 标准库负责预览、备份与恢复，并测试真实文件操作。
系统软件交给已有的 Homebrew / pacman，Python CLI 交给 uv tool，Rust 组件交给 rustup。

Niri 尚未安装或配置，保持现有 GNOME；`platforms/linux` 只提供将来扩展位置。
texlab 可以先服务 LaTeX 编辑，完整 TeX 发行版等实际需要本机编译时再装。

参考：[Neovim LSP](https://neovim.io/doc/user/lsp/)、
[Kitty 配置](https://sw.kovidgoyal.net/kitty/conf/)、
[uv 独立工具](https://docs.astral.sh/uv/guides/tools/)、
[Ruff Neovim 配置](https://docs.astral.sh/ruff/editors/setup/#neovim)。
