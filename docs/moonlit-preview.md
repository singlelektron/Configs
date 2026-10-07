# Moonlit Bloom：预览与受控会话交接

需求依据是 [TEMP-desktop-design.md](TEMP-desktop-design.md)。视觉方向已确认；分支为 `codex/desktop-nocturne-redesign`，PR 保持 Draft，旧 PR #3 保留。本文说明使用与恢复流程，不表示主会话迁移或人工 GUI 验收已经完成。

## 实现与边界

Noctalia 提供顶栏、启动器和控制中心，本地插件补充音乐、网络概览及手动更新。`config/moonlit/runtime.json` 锁定运行时，`palette.json` 是共用 palette；`scripts/moonlit-theme.py --check` 检查派生主题。Cozy Night、Quiet Street、Blue Hour 手动切换，不自动换图或分别生成主题。

Music room 仍是 popup，仅支持本地封面；没有虚构队列或歌词。音乐 worker 订阅媒体事件并去重，隐藏或暂停时没有周期进度查询，可见且播放时每秒查询进度；相关属性事件后有两次有限缓存对账。插件退出清理所属进程，异常提供重连；外部强杀 wrapper 的恢复仍受上游 API 限制。

`shell.lang="en"` 使外壳和插件默认英文，不改全局 locale。日期 `%x` 跟随会话 `LC_TIME`，空 `timezone` 跟随本地时区；时钟保留紧凑的 24 小时分钟格式，避免 `%X` 增加秒和文字单位。中文字体、Fcitx 与输入环境保留，原始诊断不翻译。区域日期、歌曲名或个人文件名含中文不属于界面漏译。

现有壁纸是视觉参考，不作为原生 4K 成品交付；新壁纸和高级动画另行处理。隔离测试不等于物理显示器、中文输入或真实账号验收。

## 固定旧桌面基线

配置直接链接可切换分支的 checkout，可能在切分支后丢失旧版依赖。`desktop-baseline.py` 从指定提交生成仓库外只读版本，补缺失依赖并保留已审阅的当前文件；共享编辑器 / 终端与个人覆盖不在修链范围。

```bash
python3 scripts/desktop-baseline.py --help
# 以下变量须先按本机审阅清单设置。
python3 scripts/desktop-baseline.py prepare --source-repo "$PWD" \
  --revision "$legacy_revision" --preserve-revision "$current_revision" --baseline "$baseline_dir"
python3 scripts/desktop-baseline.py verify --baseline "$baseline_dir"
python3 scripts/desktop-baseline.py deploy --baseline "$baseline_dir" --home "$HOME"
```

`deploy` 默认预演，加 `--apply` 才写链接；拒绝未知个人文件、外部链接和未审阅修改，不重启服务或切换会话。修链备份只用于撤销这次修复，恢复它可能重新引入原有失效链接。保留固定基线与备份。

## 受控主会话：基础阶段

先准备并验证固定旧基线、已锁定校验且可长期保留的运行时及三个本地壁纸样片。源码必须是干净、已提交的 checkout；`prepare` 按指定提交归档，不从未提交文件制作发布物。下列变量均是本机占位，`release_dir` 和 `live_dir` 必须是仓库外两个独立的新目录。

```bash
python3 scripts/desktop-session.py --help
python3 scripts/desktop-session.py prepare --source-repo "$PWD" --commit "$reviewed_commit" \
  --baseline "$baseline_dir" --release "$release_dir" --live-root "$live_dir" \
  --binary "$runtime_prefix/usr/bin/noctalia" --library-path "$runtime_prefix/usr/lib" \
  --wallpapers "$wallpaper_dir"
```

`prepare` 只生成固定发布归档与私有运行状态，不改现有链接或服务。部署仅管理配置目录下七个目标：`niri/config.kdl`、`niri/desktopctl.py`、`niri/moonlit-session.json`、`niri/moonlit-theme.kdl`、`systemd/user/dotfiles-niri-waybar.service`、`kitty/theme.conf`、`moonlit/nvim-theme.lua`。个人 overrides 保持原位。

```bash
session_tool="$release_dir/source/scripts/desktop-session.py"
transaction="$live_dir/transaction.json"
python3 "$session_tool" deploy --transaction "$transaction"          # 只预演
python3 "$session_tool" deploy --transaction "$transaction" --apply  # 实际切换并启动
python3 "$session_tool" status --transaction "$transaction"
# 仅对已部署事务显式启动；start 本身会操作服务，不是预演。
python3 "$session_tool" start --transaction "$transaction"
python3 "$session_tool" restore --transaction "$transaction"         # 先检查冲突
python3 "$session_tool" restore --transaction "$transaction" --apply
```

执行实际切换前保存工作并核对预演；脚本要求真实主 Niri 会话，拒绝嵌套会话和正在过渡的服务状态。基础切换只管理旧 bar / wallpaper 服务；旧 mako、idle、锁屏与 polkit 保持负责，不更改默认会话、不自动注销。启动失败会尝试恢复该事务，冲突时保留备份供检查。

回滚必须使用**这次新 release 内归档的 `scripts/desktop-session.py` 和对应 transaction**，恢复本次七个目标及原有服务状态。不要使用旧 baseline 修链备份代替迁移回滚；保留新 release、transaction、部署备份及旧 baseline，直到确认无需恢复。

基础阶段的系统总线仅允许设备状态读取；蓝牙自动连接等写入被阻断，Noctalia 使用不可用的 PipeWire remote，音频面板及相关入口隐藏。会话总线允许必要音乐控制，拒绝抢占通知、ScreenSaver 与托盘 watcher。拒绝屏保注册是预期限制，不代表旧锁屏失效。受限外壳不是任意插件或应用的完整沙箱。

先人工验收英语界面、区域日期、真实分辨率 / 缩放、弹层焦点、启动器普通应用与 Terminal=true 应用、Kitty / Neovim、中文候选与剪贴板、媒体键和来源选择，以及恢复路径。**这些 GUI 项目未通过前，不进入设备控制阶段或放宽代理。** Wi-Fi、蓝牙、真实 stream→sink、通知和会话操作需要之后分别验收；状态命令返回 ready 不能替代它们。

## 隔离预览

获取脚本只校验锁定包的哈希与分离签名并解包，不安装或升级系统包。依赖现有兼容的 Arch / Wayland、Niri、Kitty、Python GObject 和 DBus 工具。

```bash
python3 scripts/fetch-noctalia-preview.py --help
python3 scripts/fetch-noctalia-preview.py
python3 scripts/fetch-noctalia-preview.py --check
preview_root="/tmp/moonlit-preview-$(id -u)"
runtime_prefix="$PWD/local/noctalia-5.2.1/prefix"
python3 scripts/desktop-preview.py prepare --runtime "$preview_root" \
  --binary "$runtime_prefix/usr/bin/noctalia" --library-path "$runtime_prefix/usr/lib"
python3 scripts/desktop-preview.py start --runtime "$preview_root"
python3 scripts/desktop-preview.py status --runtime "$preview_root"
python3 scripts/desktop-preview.py stop --runtime "$preview_root"
```

`prepare` 可加 `--wallpapers "$wallpaper_dir"`；素材与个人路径不进入共享配置。嵌套预览使用私有 session DBus、独立配置 / 状态及系统设备写入代理，主题偏好写入内存；缺少代理或拒绝检查失败就不启动。它与基础主会话不同：预览仍连接真实 PipeWire，音量和路由操作可能影响当前声音。

预览禁用通知守护、电源操作、自动壁纸、天气、遥测、外部模板和插件来源同步。嵌套窗口以 Alt 为 Mod：Alt+Return 打开 Kitty，Alt+N 打开 Neovim，Alt+D 打开启动器，Alt+Shift+Space 打开控制中心；真实桌面按键不变。

截图使用 `desktop-preview.py capture --runtime "$preview_root" --output "$capture_file"`，记录实际嵌套尺寸，不放大冒充物理显示验收。退出仅停止本次预览所属进程。

## 验证记录的含义

配置或部署改动后运行 `bash scripts/check.sh`，并验证固定运行时的合并配置和插件 lint。已执行的 Linux 隔离测试覆盖本地无声 VLC 控制、合成多来源、音乐页生命周期、worker 恢复和退出清理；它们不等于网易云账号或真实声音验收。macOS 未验证，headless 也不证明字体、输入、剪贴板或 GUI 工作流。

本使用流程不启动性能采样。既有性能结果只能在匹配配置、播放器和测量方法下解释，不能外推长期负载；原始性能、部署恢复路径、截图与运行身份只保留本机，不上传公开 PR。

## 上游依据

- [Noctalia 插件运行时 API](https://docs.noctalia.dev/noctalia/plugins/development/runtime-api/)；接口以锁定版本源码为准。
- [MPRIS Player 接口](https://specifications.freedesktop.org/mpris/latest/Player_Interface.html)：Position 不发 PropertiesChanged，可见进度不能仅靠曲目信号。
