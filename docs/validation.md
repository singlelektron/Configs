# 验证记录与复测

## 状态栏交互与设置窗口修复：2026-10-06

- Linux 全量 `bash scripts/check.sh` 通过 **124 项 Python 回归、10 项 JavaScript 测试**，
  覆盖模式重启失败恢复、音频可用性、设备选择、滚轮边界和各模式差异；Qt Quick Test 使用实际
  音量面板组件和隔离音频替身，拖动滑块、点击设备、点击静音的 3 项鼠标交互回归通过。
  Qt6 QML、Neovim、Kitty、Niri、Fuzzel、GTK3/GTK4 CSS 和 systemd 检查通过。
- 本轮在真实 Niri 会话中检查：保存的布局、状态栏进程环境和 Quickshell 状态均为 Performance，
  原先模式差异过小；现 Focus 精简搜索、网络、日期和更新数字，Performance 增加秒数与音量百分比，
  控制中心同步显示模式说明。模式重启等待 systemd 作业返回，失败则恢复原偏好。
- 收起封面改为 26px，左内边距增加到 12px；时钟、日期与更新数字使用固定占位，避免胶囊随文字宽度移动。
- 新增声音展开面板及输出设备选择。初次 wpctl 验证证明音量读写有效，但用户实测指出听感不变；
  进一步检查发现网易云实际连接 MOMENTUM 4，默认输出却是 ALC897 数字输出。现已将本机默认输出
  对齐到正在使用的耳机，保留耳机原音量；**用户再次拖动后确认耳机音量会变化**。
  设备路径不写入 Git。验证音频不能仅检查默认输出数字。
- 测试时间 11:11:11→23:58:59、更新数0→999时，同一模式下右胶囊位置与宽度保持不变；
  真实 Niri 三模式轮换、模块可见性与稳定几何检查通过，最终恢复用户原先的 Performance。
- 控制中心改用与状态栏一致的深色；从控制中心打开声音、网络和蓝牙设置时加载专用 GTK3/GTK4 深色主题。
  启动器和其他应用仍保留原浅色偏好。GTK3/GTK4 控件及 Blueman 原始 UI 已隔离渲染检查；
  已经打开的设置窗口需关闭后从控制中心重开，才会加载局部主题。
- macOS：本轮未实机测试；本轮变更只影响 Linux 桌面组件。

## 粉紫桌面与网易云音乐岛：2026-10-06

- `bash scripts/check.sh` 通过 **123 项 Python 回归、5 项 JavaScript 状态测试**，以及
  Qt6 QML 静态分析、Neovim、Kitty、Niri、Fuzzel、GTK3/GTK4 CSS 和 systemd 静态检查。
  覆盖安装/外观恢复中断重试、更新超时进程组清理和媒体键选择一致性。
- Linux 当前主会话为 **GNOME Wayland**，保留其默认登录方式。Quickshell 0.3.1、GTKLock 4.0.0
  已安装；逐文件部署和重复部署通过，外观偏好有独立恢复备份，默认壁纸校验和真实 PNG 解码通过。
- GTK4 网易云 2.5.4 从固定上游源码原生构建。用户自行扫码登录后，真实会话验证了播放、暂停、恢复、
  下一首、上一首和封面；测试结束保持播放。账户和播放缓存没有进入 Git。
- Quickshell 在嵌套 Niri 中读取真实用户 MPRIS，真实歌曲封面及深色三组胶囊已截图检查。
  在另一组私有 D-Bus 和嵌套 Niri 中，验证了暂停的网易云优先于正在播放的浏览器、控制目标一致、
  seek 微秒单位、播放器热移除、含标记的元数据作为纯文本、工作区事件和开合层键盘焦点。
  目前该真实网易云客户端报告 `CanSeek=false`，界面显示进度而禁用拖动；支持 seek 的测试播放器已通过定位测试。
- 控制中心和启动器在隔离 GTK4 Broadway 中实际渲染，设置行、音量、静音、勿扰、布局选择、搜索和启动检查通过。
  CPU、内存和可用温度读取真实 `/proc`/`sysfs`，窗口不可见时停止采样。
- Arch `checkupdates` 真实检查成功，使用独立数据库；失败不会显示假零更新，也不会自动升级系统。
- Kitty 实际用户配置解析为 `#1b1722`、不透明度 `0.86`；GTKLock CSS 原生解析通过。
- GTKLock 在独立嵌套 Niri 中启动；发现继承 X11 后端会失败，启动器已局部指定 Wayland。
  锁定后 Niri 不执行截图请求，因此**锁屏时钟画面与实际 PAM 解锁未完成验收**。
- 当前检查不能替代完整 Niri 会话的 4K 缩放、物理键鼠、Esc/外部点击收起、鼠标穿透、中文输入、门户、
  PAM 解锁、休眠恢复和游戏验收。保存工作后手动登录 Niri 进行这些操作；本次没有自动切换会话。
- macOS：共享 Kitty / Neovim / LazyGit 配色已更新，**本次未在 macOS 实机验证**字体、透明度、剪贴板或 GUI。

## 统一应用选择与桌面菜单：2026-09-29

- Linux：`bash scripts/check.sh` 通过 84 项 Python 回归及 Neovim、Kitty、Niri、GTK CSS、
  systemd 配置检查。新增搜索回归覆盖 Unicode、名称优先、多关键词、空结果与稳定排序。
- 原生 GIO 用隔离的临时 `.desktop` 文件验证参数引号、字段码、中文和空格路径、工作目录、
  Kitty 终端入口、PATH 恢复、隐藏/缺失应用拒绝、启动错误回调，以及启动器退出后子进程继续运行。
  这些用例不启动用户的真实应用。
- GTK4 应用选择窗口在私有 D-Bus 的嵌套 Niri 中实际渲染，680×720 截图检查通过；
  搜索、Enter、空结果、↑↓ 选择与滚动、鼠标行激活、长错误提示与恢复、单实例和 Esc 关闭通过。
  界面与桌面控制面板共用样式；本机 GIO 发现 87 个可见应用，包含 Chrome Flatpak、Steam、Kitty 和 Neovim。
- 四个新增文件通过部署器逐文件安装，重复部署无改动，实际部署的 Niri 配置解析通过。
  最后尝试打开真实会话窗口时，当前会话已自动锁屏，Niri 忽略窗口启动请求；没有解除或绕过锁屏。
  解锁后通过 `Super+D` 验收真实应用启动、焦点和中文输入；隔离测试不替代这些实际操作。
- macOS：本次未实机测试；新的应用选择窗口只随 Linux 的 `--desktop niri` 选项部署。

## Steam 菜单焦点修复：2026-09-29

用户确认是下拉菜单一闪即消失、Steam 主进程仍在；本机为 Niri 26.04、
Xwayland Satellite 0.8.2，与上游 #489/#468 描述吻合。
构建并安装上游正式版 0.8.3，固定提交 `b83eab900644e4c7c77982ce3d44cb490f0c5e1d`，
使用 `cargo build --release --locked`；缺失的 libclang 及头文件仅从校验过的稳定仓库包
提取到临时构建目录，没有替换系统包或启用 testing。

- Linux：`cargo test --release --locked popup_` 通过 9 项单元测试和 1 项集成测试，
  包含 override-redirect 弹窗焦点回归；可执行文件报告 `v0.8.3`，运行库均可解析。
- 版本化二进制、构建记录与私有路径覆盖保存在仓库外；真实部署配置 `niri validate` 通过。
  `bash scripts/check.sh` 的 73 项回归及原生配置检查通过。
- 当前 Steam 和 Niri 会话没有被中止。集成的 Satellite 需重新登录后才更新；
  Steam 实际菜单、全屏和游戏鼠标仍待用户重新登录后验收。
- macOS：不适用。构建、启用和回退步骤见 [Steam 菜单排查](niri.md#steam-顶部菜单一闪就关闭)。

## 英文界面与控制面板：2026-09-29

- Linux：`bash scripts/check.sh` 通过 73 项 Python 回归、Neovim/Kitty 检查、
  Niri 部署及本机覆盖解析、GTK3/GTK4 CSS 和 systemd 静态检查。
- GTK4 控制面板在私有 D-Bus 的嵌套 Niri 中实际渲染；680×700 截图确认分区、图标和文字无截断。
  预览后端验证模式切换、常亮状态同步、外部快捷键修改状态后的幂等操作、壁纸名称更新和恢复、
  错误内联显示及恢复、再次启动复用单窗口。预览不操作真实壁纸、锁屏、注销或服务。
- 真实 Niri 会话成功打开单个 680×720 浮动面板，用户可直接查看；确认受管 Waybar 运行。
  本机账号 Language 和用户服务环境均为英语；没有退出会话或关闭其他应用。
  新增文件可回滚部署及重复部署通过；新增启动回归确保面板通过 Niri 启动，
  从 Waybar 打开后不会随状态栏模式切换一起结束。
- 这些结果不代表实际设备设置、锁屏解锁、游戏和全部应用翻译均已验收。
  已运行应用需重开，完整语言环境在重新登录后统一；中文输入法及区域格式保留。
- macOS：本次未实机复测；GTK4 桌面面板和语言配置仅属于 Linux 桌面选项。

## 暗玫瑰 Niri 增补：2026-09-29

本次实施环境为 Arch 衍生版 x86_64，原桌面为 GNOME Wayland；没有退出、更换或启用默认桌面会话。
软件版本：Niri 26.04、Waybar 0.15.0、Fuzzel 1.15.0、Mako 1.11.0、
Swaybg 1.2.2、Swayidle 1.9.0、Swaylock 1.8.6、Xwayland Satellite 0.8.2。

| 检查 | Linux 本次结果 | macOS 本次结果 |
| --- | --- | --- |
| `bash scripts/check.sh`：70 项 Python 回归、Neovim smoke、真实 Kitty 解析 | 通过 | 未实机复测 |
| 已安装插件的 Neovim UI 集成测试 | 通过 | 未实机复测 |
| Niri 真实解析器：部署链接、缺失/有效/无效本机覆盖、自定义 XDG 路径含空格 | 通过 | 不适用 |
| Fuzzel 配置、Waybar GTK CSS、7 个用户服务静态校验 | 通过 | 不适用 |
| Mako 原生配置读取与私有 D-Bus 服务响应 | 通过 | 不适用 |
| Swaylock 原生配置读取，指定不存在的显示器后退出 | 通过；未实际锁屏 | 不适用 |
| 三档 Waybar 在独立嵌套 Niri 中运行 | 通过；无模块/格式错误 | 不适用 |
| 本机桌面部署、重复部署、恢复预览 | 通过 | 不适用 |
| `doctor.py --desktop niri` | 补充用户工具 PATH 后通过 | 桌面选项拒绝，单元测试通过 |
| C 图实际 JPEG 解码、3840×2160 尺寸、SHA-256、本机缓存 | 通过 | 未实测 |
| 物理显示器、输入法、实际复制粘贴、屏幕共享、锁屏唤醒、游戏/VRR | 待真实 Niri 登录验收 | 不适用 |

桌面辅助测试覆盖三档偏好持久化、只重启受管 Waybar、常亮跨布局切换、服务失败时不伪报成功、
独立睡前锁屏、嵌套会话隔离、损坏/截断图片拒绝、中文与特殊字符路径、取消选图、默认图哈希不符时保留旧缓存、
自选图→默认图→纯色回退，以及无 GPU/电池/背光时的处理。部署测试另覆盖 Linux 显式选用、
macOS 拒绝、旧清单兼容、恢复冲突和保留同目录私有文件。

嵌套测试使用临时配置和私有 D-Bus，移除真实会话启动入口与本机 include，不使用 `--session`，
不启动锁屏、空闲、输入法或 systemd 用户服务。三档状态栏实际运行后退出所有自有测试进程。
这只证明组件能在嵌套 Wayland 环境运行；不代表 4K 物理输出、NVIDIA 帧时间或游戏体验已经验证。
系统服务静态校验与 GPU 设备访问在受限沙箱之外完成；没有启用服务。

本机显示覆盖依据当前 GNOME 的 4K/160Hz/125% 设置写在仓库外，首次登录仍需用 `niri msg outputs`
核对实际输出名与精确刷新率。共享主题改动同步影响 Kitty、Neovim 和 LazyGit；macOS 原有平台配置保留，
以下较早的双平台记录属于之前的基础配置验证，不能替代本次 macOS 外观复测。

## 基础配置历史记录：2026-09-29

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
