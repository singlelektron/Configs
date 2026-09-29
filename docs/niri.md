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

## 四个工作区与三种信息布局

| 工作区 | 使用方式 |
| --- | --- |
| `read` | PDF、资料和网页阅读 |
| `code` | 项目 Neovim、终端和参考文档；从项目目录启动 `nvim` |
| `study` | 网课 Firefox + 半屏 Markdown 笔记；`Super+N` 打开专用笔记终端 |
| `play` | Steam 与游戏；匹配的 Steam 游戏和 Gamescope 窗口全屏打开 |

普通应用在当前工作区打开，不按应用类别自动搬走；只有专用笔记终端固定在 `study`。
在 `study` 中打开 Firefox 和 `Super+N`，用 `Super+R` 调成两个半宽列；
笔记保存为 `.md` 后用 `Space mp` 打开数学预览，`Space ms` 停止。
宽屏可使用三分之一列宽放置资料、编辑器、预览；第三列也可保留在横向滚动区域。
Firefox 画中画窗口默认浮动在右下角，适合边看课边调整笔记。
公式、预览和保存行为见 [Markdown 笔记指南](markdown-notes.md)。

| Waybar 布局 | 常驻信息 |
| --- | --- |
| `balanced`（默认） | 工作区、窗口、日期时间、常亮、媒体、声音、网络、CPU、内存、托盘 |
| `focus` | 工作区、时间、常亮、声音、网络、托盘 |
| `performance` | 工作区、窗口、时间、常亮、声音、网络、CPU、内存、GPU、温度、托盘 |

三种布局共用字号、间距和配色。点击右侧 `BAL` / `FOCUS` / `PERF` 或按 `Super+Alt+B` 切换；
左侧 `∑` 或 `Super+Shift+Space` 打开桌面菜单。声音左键静音、右键控制面板，滚轮调整音量；
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
按 `Super+Alt+P` 或点击栏中的“常亮 OFF”进入网课常亮：暂停这两个空闲计时，立即点亮显示器，
栏中显示“常亮 ON”；再次点击恢复默认策略。它不控制系统的挂起策略，手动锁屏与休眠前锁屏仍有效。
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

## 快捷键

真实会话中 `Mod` 为 **Super**；嵌套测试中为 **Alt**。下表使用 `Mod`，锁屏固定为 `Super+Alt+L`。
原有 Vim、Kitty 的 Ctrl/Alt 操作保持不变。`Mod+Shift+/` 显示配置的帮助。

| 按键 | 功能 |
| --- | --- |
| `Mod+Enter` / `Mod+T` | 打开 Kitty |
| `Mod+D` / `Mod+B` / `Mod+E` | 应用启动器 / Firefox / Nautilus |
| `Mod+N` | 在 `study` 打开 Neovim 笔记终端 |
| `Mod+Shift+Space` | 桌面控制菜单 |
| `Mod+Alt+B` / `Mod+Alt+W` | 状态栏布局 / 选择壁纸 |
| `Mod+Alt+P` / `Mod+Alt+N` | 网课常亮 / 通知勿扰 |
| `Super+Alt+L` | 锁屏，快捷键被游戏抑制时仍可用 |
| `Mod+Q` / `Mod+O` | 关闭当前窗口 / 总览 |
| `Mod+H/J/K/L` 或 `Mod+方向键` | 左右切换列，上下切换同列窗口 |
| `Mod+Shift+H/J/K/L` 或 `Mod+Shift+方向键` | 左右移动整列，上下移动窗口 |
| `Mod+Home` / `Mod+End` | 第一列 / 最后一列 |
| `Mod+Alt+方向键` | 切换相应方向的显示器 |
| `Mod+Ctrl+Alt+方向键` | 将整列移至相应方向的显示器 |
| `Mod+1/2/3/4` | `read` / `code` / `study` / `play` |
| `Mod+Shift+1/2/3/4` | 将整列移到对应工作区 |
| `Mod+PageUp/PageDown` | 上一个 / 下一个工作区 |
| `Mod+Ctrl+PageUp/PageDown` | 将整列移到上一个 / 下一个工作区 |
| `Mod+Tab` | 返回此前工作区 |
| `Mod+滚轮上/下` | 上一个 / 下一个工作区 |
| `Mod+Shift+滚轮上/下` | 左列 / 右列 |
| `Mod+[` / `Mod+]` | 向左 / 右合并窗口到列，或从列中拆出 |
| `Mod+R` / `Mod+Shift+R` | 正向 / 反向切换 ⅓、½、⅔、全宽列 |
| `Mod+-` / `Mod+=` | 列宽减少 / 增加 5% |
| `Mod+Shift+-` / `Mod+Shift+=` | 窗口高度减少 / 增加 5% |
| `Mod+F` / `Mod+Shift+F` | 最大化列 / 当前窗口全屏 |
| `Mod+C` | 将当前列居中 |
| `Mod+V` / `Mod+Shift+V` | 切换当前窗口浮动 / 切换平铺与浮动焦点 |
| `Mod+W` | 同列窗口切换标签显示 |
| `Print` / `Ctrl+Print` / `Alt+Print` | 交互截图 / 当前显示器 / 当前窗口 |
| `Mod+Escape` | 切换应用对桌面快捷键的抑制，始终可触发 |
| `Ctrl+Alt+Delete` | 退出 Niri，显示确认 |
| 音量增减 / 静音 / 麦克风静音键 | 调整声音，音量最高 100%，锁屏时也可用 |
| 播放 / 下一首 / 上一首键 | 控制媒体，锁屏时也可用 |
| 亮度增减键 | 调整背光 ±5%，需要可用的背光设备 |

截图保存到 `~/Pictures/Screenshots/`。字体、透明度、实际剪贴板、输入法、显示缩放、锁屏、
门户和游戏兼容性均需要在真实图形会话验证；静态解析或 headless 测试通过不代表这些已验证。
Linux 和 macOS 的实际结果分别记录在 [验证记录](validation.md)。
