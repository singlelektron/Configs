# 验证记录与复测

2026-09-29，真实 macOS arm64 和 Arch 衍生版 x86_64。版本和初始状态见环境审计。

| 检查 | macOS | Arch |
| --- | --- | --- |
| 部署 / 恢复回归测试（16 项） | 通过 | 通过 |
| Neovim 基础、外部修改和未保存冲突测试 | 通过 | 通过 |
| Kitty 配置、主题、本地覆盖解析 | 通过 | 通过 |
| JetBrains Mono NL Nerd Font Mono 匹配 | Kitty CoreText 确认 | Fontconfig 确认 |
| 新配置部署、重复部署、恢复预览 | 通过 | 通过 |
| 6 个插件仓库与提交锁一致 | 通过 | 通过 |
| 核心工具、配置链接诊断 | 通过 | 通过（SSH 显式补充用户 PATH） |
| Rust LSP、类型 hover、格式化 | 通过 | 通过 |
| Python LSP、项目 .venv、类型错误 + F401、格式化 | 通过 | 通过 |
| texlab 连接、VimTeX 初始化 | 通过 | 通过 |
| 显式 VimTeX PDF 编译、编译后停止 | 通过 | 未安装完整 TeX，跳过 |

macOS 用临时项目完成了实际 TeX PDF 编译；这不证明任意科研文稿及字体依赖均可复现。
Arch 保留编辑与语言服务，完整 TeX 发行版是可选步骤。Marksman 未安装，两端没有验证
Markdown LSP。两端均未做图形会话截图、实际跨 SSH 剪贴板传输和 PDF 反向搜索验证。

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
