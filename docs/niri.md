# Niri：Rose Observatory

这套 Arch Linux 桌面把阅读、代码、网课笔记和游戏分成四个命名工作区。
暗玫瑰主题、细边框和规整信息布局提供简约科幻感；壁纸使用二次元人物与城市风景。
默认列宽为一半屏幕，保留 Kitty、Neovim 的原有操作。组件可用鼠标点击，也有键盘入口。

## 安装与迁移

需要 Niri **26.04 或更新版本**。从仓库根目录运行；与基础编辑工具共用安装器和可回滚部署器：

```sh
# 预览软件清单；实际安装执行完整 Arch 系统升级，需要本人完成 sudo/pacman 确认。
bash scripts/install-tools.sh --desktop niri
bash scripts/install-tools.sh --desktop niri --apply

# 预览受管文件和备份，再建立链接。
python3 scripts/deploy.py --desktop niri
python3 scripts/deploy.py --desktop niri --apply

# 默认壁纸只下载到本机，不放进仓库。
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" wallpaper fetch

python3 scripts/doctor.py --desktop niri
bash scripts/check.sh
```

不加 `--desktop niri` 时仍只处理原有编辑工具；macOS 拒绝此桌面选项。
安装清单采用官方 Arch 包，包含 Waybar、Fuzzel、Mako、Swaybg、Swayidle、Swaylock、
Xwayland Satellite、桌面门户、音频控制、Firefox、文件管理和 Fcitx5 中文输入组件。
显卡驱动、Steam、Proton、Gamescope、PDF 查看器和完整 TeX 环境按需要单独管理。

部署只链接明确列出的配置文件，不接管整个 `~/.config`，也不覆盖其他配置文件、输入法词库或个人状态。
原件保存在部署命令打印的备份目录，恢复方法见 [README](../README.md#本机覆盖与恢复旧配置)。
安装软件与恢复配置是两件事；恢复配置不卸载软件。更新仓库后重复部署并运行检查即可。

## 第一次进入桌面

部署过程不退出当前 GNOME，不启用服务，也不更改显示管理器或默认会话。
保存工作后自行注销，在登录界面的会话菜单选择 **Niri**；保留 GNOME 作为可随时返回的会话。
应使用完整的 `niri-session` 登录流程。GNOME 内直接运行 `niri` 只能检查嵌套布局，
不会自动启动本配置的状态栏、通知、锁屏等服务，不能代替真实会话验收。

首次登录按以下顺序检查：

1. 打开 Kitty，确认鼠标、键盘、中文字体、显示器和 125% 缩放；检查 Waybar 及默认壁纸。
2. 在 Kitty、Firefox、Neovim 中分别输入中文，复制一段中文和公式；确认音量控制、网络和文件选择器。
3. 用 `Super+Alt+L` 锁屏并成功解锁，再测试休眠与恢复；常亮关闭时确认 5 分钟锁屏、10 分钟熄屏。
4. 打开网页网课与 Markdown 笔记，测试浏览器画中画、实时预览和常亮开关。
5. 在浏览器实际发起屏幕共享，检查门户选择界面；最后测试一款游戏的全屏、鼠标和退出行为。

可用以下命令检查服务；它们只随 Niri 会话启动和停止，没有 `enable` 步骤：

```sh
systemctl --user status 'dotfiles-niri-*.service'
journalctl --user -b -u dotfiles-niri-waybar.service
journalctl --user -b -u dotfiles-niri-session-events.service
```

Fcitx5 通过 XDG 自动启动入口运行，已有的输入法列表、快捷键和词库留在本机。
新机器用 `fcitx5-configtool` 选择中文输入法，并实际检查 GTK、Qt 和终端输入；
不要把现有机器的整个输入法状态目录复制进仓库。

## 界面语言

桌面控件、菜单和应用界面以英语为主。Niri 启动的应用与用户服务使用
`LANG=en_US.UTF-8`、`LC_MESSAGES=en_US.UTF-8` 和 `LANGUAGE=en_US:en`；
新机器需先确认 `locale -a` 包含 `en_US.utf8`；缺失时在 `/etc/locale.gen` 启用
`en_US.UTF-8 UTF-8` 并运行 `sudo locale-gen`。
用户服务的语言文件由部署器逐文件安装到 `${XDG_CONFIG_HOME:-~/.config}/environment.d/`，
原有同名文件会备份，恢复仍使用部署器。
本机已有的日期、数字等区域格式设置保留，中文字体、Fcitx5 和中文输入不受界面语言影响。
应用自己单独指定的语言优先级可能不同，需要在该应用内设置。

已运行的程序会保留启动时的语言环境；保存工作后注销并重新登录，随后打开应用，
才能让整个会话一致使用新设置。本机登录账号的语言选择属于机器设置，不进入 Git。

## 四个工作区与三种信息布局

| 工作区 | 使用方式 |
| --- | --- |
| `read` | PDF、资料和网页阅读 |
| `code` | 项目 Neovim、终端和参考文档；从项目目录启动 `nvim` |
| `study` | 网课浏览器 + 半屏 Markdown 笔记；`Super+N` 打开专用笔记终端 |
| `play` | Steam 与游戏；匹配的 Steam 游戏和 Gamescope 窗口全屏打开 |

普通应用在当前工作区打开，不按应用类别自动搬走；只有专用笔记终端固定在 `study`。
在 `study` 中用 `Super+B` 打开默认浏览器，再用 `Super+N` 打开笔记，用 `Super+R` 调成两个半宽列；
笔记保存为 `.md` 后用 `Space mp` 打开数学预览，`Space ms` 停止。
宽屏可使用三分之一列宽放置资料、编辑器、预览；第三列也可保留在横向滚动区域。
Firefox 画中画窗口默认浮动在右下角，适合边看课边调整笔记。
`Super+B` 通过系统默认浏览器的桌面入口启动，支持原生和 Flatpak 应用，不固定为 Firefox。
已安装 Chrome/Chromium 时，可在浏览器设置中设为默认浏览器；用
`xdg-settings get default-web-browser` 查看当前选择。个人默认应用关联留在本机，不进入 Git。
公式、预览和保存行为见 [Markdown 笔记指南](markdown-notes.md)。

| Waybar 布局 | 常驻信息 |
| --- | --- |
| `balanced`（默认） | 工作区、窗口、日期时间、常亮、媒体、声音、网络、CPU、内存、托盘 |
| `focus` | 工作区、时间、常亮、声音、网络、托盘 |
| `performance` | 工作区、窗口、时间、常亮、声音、网络、CPU、内存、GPU、温度、托盘 |

三种布局共用字号、间距和配色。点击右侧 `BAL` / `FOCUS` / `PERF` 或按 `Super+Alt+B` 切换；
左侧 `∑` 或 `Super+Shift+Space` 打开 GTK4 桌面控制面板，按 Esc 关闭。
面板使用暗玫瑰卡片、英文标签与明确的状态开关，提供声音、网络、蓝牙、壁纸、信息栏和会话入口。声音左键静音、右键控制面板，滚轮调整音量；
媒体左键播放/暂停、右键下一首。网络悬停查看接口、地址与流量，时钟悬停查看日历。
GPU 信息目前读取 `nvidia-smi`，温度只显示受支持的 CPU 传感器；缺失或读取失败时隐藏对应数据。
“性能”只是信息布局，不改变 GPU 时钟、电源配置或游戏性能。

```sh
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" bar balanced
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" bar focus
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" bar performance
```

布局选择和个人壁纸路径保存在 `${XDG_STATE_HOME:-~/.local/state}/dotfiles/niri/settings.json`，
不进入 Git。切换只重启已经运行的对应服务；在 GNOME 中修改偏好不会启动 Niri 桌面组件。

## 网课常亮、锁屏与通知

默认空闲 **300 秒锁屏、600 秒熄屏**，恢复输入后点亮显示器。
按 `Super+Alt+P` 或点击栏中的“AWAKE OFF”进入网课常亮：暂停这两个空闲计时，立即点亮显示器，
栏中显示“AWAKE ON”；再次点击恢复默认策略。它不控制系统的挂起策略，手动锁屏与休眠前锁屏仍有效。
退出后再次进入 Niri 时常亮默认关闭，不持久化。

锁屏/休眠事件与空闲计时由两个独立服务监听，因此网课常亮不会关闭手动锁屏或休眠前锁屏。
`Super+Alt+L` 在游戏抑制桌面快捷键时仍可用。
`Super+Alt+N` 切换 Mako 勿扰，与常亮独立；退出常亮不会自动改变通知偏好。

```sh
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" presentation toggle
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" presentation status
```

## 壁纸

默认图为 [Anime Girl On Rooftop Dancing With Cat City Skyline](https://hdqwalls.com/wallpaper/3840x2400/anime-girl-on-rooftop-dancing-with-cat-city-skyline)。
仓库只记录来源、下载地址、解码尺寸与 SHA-256，第三方原图不随仓库分发。
`wallpaper fetch` 显式下载到 `${XDG_DATA_HOME:-~/.local/share}/dotfiles/wallpapers/default.jpg`；
已有文件哈希正确时直接复用。下载限制 64 MiB，并校验哈希、格式与尺寸后原子替换。
失败会保留已有文件；会话启动不联网下载。

`Super+Alt+W` 打开文件选择器，也可使用以下命令。选图只保存路径，不搬走或复制原图：

```sh
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" wallpaper choose
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" wallpaper set "$HOME/Pictures/wallpaper.jpg"
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/niri/desktopctl.py" wallpaper reset
```

支持静态 JPEG、PNG、WebP、BMP、TIFF，不支持动画。个人选图丢失或无效时回退到本机默认图；
默认图也不可用时显示暗玫瑰纯色 `#19151c`，不影响登录和工作。
默认按 `fill` 铺满屏幕，比例不同时会裁剪。较亮的壁纸可在本机 Kitty 覆盖中提高不透明度，
例如 `background_opacity 1.0`；共享默认值为 `0.94`。

## 显示器、本机覆盖与游戏

在真实 Niri 会话运行 `niri msg outputs` 查看输出名称、支持的模式和缩放。
创建 `${XDG_CONFIG_HOME:-~/.config}/dotfiles-local/niri.kdl`，将示例输出名换为实际值：

```kdl
output "DISPLAY-NAME" {
    scale 1.25
    // 验证显示器和游戏支持后，才按需打开：
    // variable-refresh-rate on-demand=true
}
```

`1.25` 为 125% 缩放；原生分辨率和刷新率先使用 Niri 的自动选择。
如需固定模式，使用 `niri msg outputs` 报告的模式，不把输出名称、设备名称和机器专属设置提交到 Git。
主配置通过可选相对 include 读取本机文件，支持自定义 `XDG_CONFIG_HOME`。文件缺失正常，
文件存在但语法错误则校验失败；每次修改后运行：

```sh
niri validate --config "${XDG_CONFIG_HOME:-$HOME/.config}/niri/config.kdl"
```

游戏优先使用现有驱动和 Steam/Proton 配置。X11 程序由 Xwayland Satellite 提供兼容，
无需在仓库加入驱动参数或全局游戏环境变量。Gamescope 可按游戏单独尝试，不预设为所有游戏的启动参数。
游戏窗口规则只请求按需 VRR，显示器输出默认不强制启用；打开上面的可选配置后逐个游戏检查闪烁、
帧时间、切回桌面、鼠标捕获和休眠恢复，出现问题就移除本机 VRR 配置。
游戏 app-id 可能不同，可用 `niri msg windows` 确认后在本机增加规则。

### Steam 顶部菜单一闪就关闭

如果 Steam 主窗口仍在，只是顶部菜单或右键菜单刚打开就消失，这是
Xwayland Satellite 0.8.2 的已知弹窗焦点问题，见 [上游报告 #489](https://github.com/Supreeeme/xwayland-satellite/issues/489)。
[正式版 0.8.3](https://github.com/Supreeeme/xwayland-satellite/releases/tag/v0.8.3)
已包含 [修复 #494](https://github.com/Supreeeme/xwayland-satellite/pull/494)。
整个 Steam 进程退出属于另一种症状，应先查日志，不能直接套用此判断。

2026-09-29 核查时，[Arch extra](https://archlinux.org/packages/extra/x86_64/xwayland-satellite/)
仍提供 0.8.2，0.8.3 只在 extra-testing。先检查当前仓库版本；若 extra 已有 0.8.3 或更新版本，
正常执行 `sudo pacman -Syu --needed xwayland-satellite`，随后重新登录即可。
无需为这个修复全局启用 testing 仓库。

稳定仓库尚未更新时，可临时构建固定的上游正式版，保留系统包并仅在本机指定替代路径。
[上游构建依赖](https://github.com/Supreeeme/xwayland-satellite#building)包括 Rust/Cargo、Clang（含 libclang）、
Git、xcb、xcb-util-cursor 和 Xwayland；本机还需 pkg-config（Arch 包 `pkgconf`）。
缺少工具时用 `pacman -Syu --needed` 安装相应包；已有 rustup 工具链时使用其 Cargo，
不必再安装与 rustup 冲突的 Arch `rust` 包。

```sh
(
    set -eu
    satellite_build="$(mktemp -d -t dotfiles-satellite-0.8.3.XXXXXX)"
    git clone --depth 1 --branch v0.8.3 \
        https://github.com/Supreeeme/xwayland-satellite.git "$satellite_build/src"
    test "$(git -C "$satellite_build/src" rev-parse HEAD)" = \
        b83eab900644e4c7c77982ce3d44cb490f0c5e1d
    cd "$satellite_build/src"
    cargo build --release --locked
    satellite_dest="${XDG_DATA_HOME:-$HOME/.local/share}/dotfiles/tools/xwayland-satellite/0.8.3/xwayland-satellite"
    install -Dm755 target/release/xwayland-satellite "$satellite_dest"
    "$satellite_dest" -version
    printf 'Niri binary path: %s\n' "$satellite_dest"
)
```

创建 `${XDG_CONFIG_HOME:-~/.config}/dotfiles-local/xwayland-satellite.kdl`；若已存在先备份，
将下面占位符换为上面打印的**绝对路径**。源码、二进制与此本机文件都不进入 Git。

```kdl
xwayland-satellite {
    path "/absolute/path/to/dotfiles/tools/xwayland-satellite/0.8.3/xwayland-satellite"
}
```

主配置可选读取这个文件，再读取硬件设置 `dotfiles-local/niri.kdl`。
运行 `niri validate --config "${XDG_CONFIG_HOME:-$HOME/.config}/niri/config.kdl"`，
保存工作并**注销、重新登录 Niri**，然后检查 Steam 菜单和游戏。
[上游说明](https://github.com/Supreeeme/xwayland-satellite#compositor-integration)要求集成模式更换二进制后重启 compositor；
仅重开 Steam 不会替换已经运行的 Satellite。不要 `pkill xwayland-satellite`，这会中断其他 X11 应用。

回滚时只删除或改名备份 `dotfiles-local/xwayland-satellite.kdl`，重新登录便恢复系统包；
保留显示器设置 `dotfiles-local/niri.kdl`。以后官方 extra 更新至 0.8.3 或更新版本时，
完整升级后同样移除此临时覆盖并重新登录，恢复由 pacman 管理更新。

## 快捷键与窗口排列

完整表格与上下排列的操作示例单独保存在 [Niri 快捷键与窗口排列](niri-keybindings.md)。
真实会话使用 Super（Win 键），`Super+Shift+/` 打开提示层。
两个各自独占一列的窗口，选中右侧窗口后按 `Super+[` 即可上下排列；
再按 `Super+F` 可让整列占满屏宽。拆回左右排列时，选中要拆出的窗口后按 `Super+]`。

截图保存到 `~/Pictures/Screenshots/`。字体、透明度、实际剪贴板、输入法、显示缩放、锁屏、
门户和游戏兼容性均需要在真实图形会话验证；静态解析或 headless 测试通过不代表这些已验证。
Linux 和 macOS 的实际结果分别记录在 [验证记录](validation.md)。
