# 验证记录与复测

2026-09-29，真实 macOS arm64 和 Arch 衍生版 x86_64。版本和初始状态见环境审计。

| 检查 | macOS | Arch |
| --- | --- | --- |
| 部署 / 恢复回归测试（29 项） | 通过 | 通过 |
| Neovim 基础、外部修改和未保存冲突测试 | 通过 | 通过 |
| Kitty 配置、透明度、主题、本地覆盖和 Git 快捷键解析 | 通过 | 通过 |
| JetBrains Mono NL Nerd Font Mono 匹配 | Kitty CoreText 确认 | Fontconfig 确认 |
| 新配置部署、重复部署、恢复预览 | 通过 | 通过 |
| 9 个插件仓库与提交锁一致（含 lazy.nvim） | 通过 | 通过 |
| 核心工具、配置链接诊断 | 通过 | 通过（SSH 显式补充用户 PATH） |
| 文件树真实 Git 标记、点文件 / 忽略文件、定位和打开回调 | 通过 | 通过 |
| 可点击标签、文件树 / Fugitive / Diff 回调、特殊文件名转义 | 通过 | 通过 |
| Git 终端切换文件后继续运行、退出清理、未保存编辑保留、不抢焦点 | 通过 | 通过 |
| LazyGit 真实 PTY：加载共享配置、呈现面板、`q` 正常退出 | 通过 | 通过 |
| Markdown：真实 HTTP / WebSocket、未保存修改、中文路径、端口冲突、Preview 回调 | 通过 | 通过 |
| Markdown 浏览器：行内公式、矩阵、aligned、实时更新 | 本机 Chrome 通过 | SSH 隧道到 macOS Chrome 通过 |
| 真实 PTY 启动：空目录 / 文件显示侧栏，Git 提交 / diff 不自动打开 | 通过 | 未复测 |
| Rust LSP、类型 hover、格式化 | 通过 | 通过 |
| Python LSP、项目 .venv、类型错误 + F401、格式化 | 通过 | 通过 |
| texlab 连接、VimTeX 初始化 | 通过 | 通过 |
| 显式 VimTeX PDF 编译、编译后停止 | 通过 | 未安装完整 TeX，跳过 |

部署 / 恢复测试包含跨文件系统 `EXDEV` 故障注入，覆盖文件、目录、相对与悬空符号链接，
以及复制失败、源件清理失败、清单写入失败后重试和复制期间源文件变化。
目录校验回归覆盖多层子文件改写、同长度且恢复修改时间的改写、深层新增文件、
副本发布后源件变化、递归读取失败，以及恢复时备份内容变化后重试。
新增用例在修复前能复现遗漏检测，修复后会停止操作并保留新内容。
Arch 另在实际位于不同文件系统的 `/tmp` 与 `/dev/shm` 中验证了备份和恢复，
确认内容、权限、修改时间、链接文本及中断恢复后重试；也实际验证了备份复制后、
副本发布后和恢复复制后三个阶段的嵌套内容修改被检出且新内容可恢复。
所有操作均使用临时配置目录；这些校验不提供活跃写入期间的原子文件系统快照。

macOS 用临时项目完成了实际 TeX PDF 编译；这不证明任意科研文稿及字体依赖均可复现。
Arch 保留编辑与语言服务，完整 TeX 发行版是可选步骤。Marksman 未安装，两端没有验证
Markdown LSP。两端均未做 Kitty / Neovim 图形会话截图、实际跨 SSH 剪贴板传输和 PDF 反向搜索验证。

Markdown 预览使用锁定的 `live-preview.nvim`。两端均验证初始 HTTP 页面、本地公式资源、
未保存内容通过 WebSocket 推送而磁盘保持原样、切换文件时工作目录不变、停止后端口释放，
以及端口占用时不开错页面。macOS Chrome 中检查了中文数学笔记的实际排版；经 SSH 隧道
也确认 Arch 临时缓冲区的未保存标题变化到达本机浏览器，7 个公式节点没有 KaTeX 错误。
未验证 Arch 桌面浏览器；初始加载 / 手动刷新读取磁盘的限制见笔记指南。

鼠标与 Git 增补已在两端部署，LazyGit 均为 0.65.1。文件树和标签测试调用真实插件的
点击动作；Git 终端生命周期测试使用临时替身进程检查退出处理，不在用户项目中提交、
暂存或推送。另在临时空 Git 仓库和隔离状态目录中启动真实 LazyGit，确认终端面板呈现
和正常退出。这些验证不等同于在图形窗口中实际点击，或完整操作 LazyGit。
本次 Kitty 图形自动化入口受到工具限制，未验证实际透明效果与窗口模糊。

已安装锁定插件后，可在仓库根目录运行界面与 Git 集成测试：

```sh
dotfiles_ui_tmp="$(mktemp -d)"
for dotfiles_case in nvim tree ui git markdown; do
  XDG_STATE_HOME="$dotfiles_ui_tmp/$dotfiles_case/state" \
  XDG_CACHE_HOME="$dotfiles_ui_tmp/$dotfiles_case/cache" \
    nvim --headless -i NONE -u config/nvim/init.lua \
      "+lua dofile('tests/$dotfiles_case.lua')" || exit 1
done
```

基础测试不联网：

```sh
bash scripts/check.sh
```

在已部署配置、已执行 `:DotfilesInstall`、已安装语言工具的机器运行真实集成测试：

```sh
dotfiles_integration_tmp="$(mktemp -d)"
XDG_STATE_HOME="$dotfiles_integration_tmp/state" \
XDG_CACHE_HOME="$dotfiles_integration_tmp/cache" \
DOTFILES_INTEGRATION_ROOT="$dotfiles_integration_tmp/fixtures" \
nvim --headless -u "${XDG_CONFIG_HOME:-$HOME/.config}/nvim/init.lua" \
  -i NONE -l "$PWD/tests/lsp.lua"
```

若只有编辑工具、没有 TeX 发行版，在 `nvim` 前增加环境赋值
`DOTFILES_SKIP_TEX_BUILD=1`。仍验证 texlab，明确跳过 PDF 编译。
测试只创建新的临时项目，保留日志、诊断和 PDF 便于检查；不修改用户项目。
macOS 文件监听在受限执行沙盒中可能出现 `EMFILE`：用无配置 Neovim 监听单个空目录
已能复现，而正常本机进程没有该错误。真实集成结果来自正常权限环境，没有因此关闭 LSP 文件监听。

自动安装锁定插件可用以下命令，失败时会返回非零退出码：

```sh
nvim --headless -i NONE \
  '+lua local ok, err = pcall(vim.cmd, "DotfilesInstall"); if not ok then print(err); vim.cmd("cquit 1") end' \
  +qa
```

迁移保存了两端原 Kitty 入口配置与整个 Neovim 目录，备份位于各自
`~/.local/state/dotfiles/backups/`。恢复预览已验证，实际恢复操作在临时 home 测试中验证。
原 LazyVim 插件目录、系统 shell 启动文件、SSH 和 AI 认证数据没有纳入版本控制。

源码经过独立复查和常见凭据 / 主机路径字面量检查；检查不等同于对未来提交的秘密扫描保证。
