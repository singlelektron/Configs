# Moonlit Bloom 第一阶段预览交接

日期：2026-10-07。需求依据是 [TEMP-desktop-design.md](TEMP-desktop-design.md)。本阶段提供可交互的原生 Noctalia 5.2.1 外壳、统一主题和嵌套 Niri 预览；视觉确认后才安排主会话迁移与高级动画。工作分支仍为 `codex/desktop-nocturne-redesign`，旧 draft PR #3 保留。

**这里展示的是在本机运行、以 3840 × 2160 截取的嵌套 Niri 桌面。嵌套输出为 60 Hz，不代表主会话已迁移，也不代表已经完成实体 4K 屏幕原刷新率下的日常使用验收。** 截图来自真实程序，不是静态网页 mockup；壁纸和音乐测试数据的边界见下文。

## 安全基线

主会话实测 Niri 26.04、Quickshell 0.3.1、Kitty 0.49.2、Neovim 0.12.5；物理输出 3840 × 2160 / 160 Hz，缩放 1.25，嵌套预览保持该缩放。开始时工作分支干净，基线 head 为 `479f353`，main 为 `cc7a185`，旧 PR #3 为 `7fc7f15`。

50 条部署链接已逐条记录；开始前就有 21 条指向旧 PR 文件的失效链接，现用 Quickshell 仍驻留运行，其重启入口与当前 checkout 不一致。已保存选择性的受管文件和旧 PR 恢复材料，没有复制整个 home。收尾复核确认链接、存在状态与可读文件哈希均未改变；未重启旧外壳。这个既有重启风险仍需后续独立处理，不能因当前画面仍能显示而忽略。

本次变更只有新增预览目录、脚本、测试与文档，以及扩展检查脚本；现用 `config/nvim`、`config/kitty`、Niri、服务及部署清单均不改动。实现先在独立副本 / worktree 中完成，不对已部署配置切换分支。

## 设计判断

- 使用深莓色阅读底、柔粉强调、薰衣草紫辅助和少量暖色语义色。少女主体、暗环境与局部光源共同决定氛围；常用面板延续粉紫玻璃、柔和边缘与留白，不加入 HUD 刻度或满屏装饰。
- 三个场景 **Cozy Night / Quiet Street / Blue Hour** 共用 `config/moonlit/palette.json`。壁纸手动选择，不随时间、工作区或 Codex 状态切换，也没有额外的“工作 / 娱乐”主题模式。
- 38 逻辑像素的顶栏保留工作区、当前应用、音乐、启动器、更新、音量和日期时间。音乐有独立播放按钮；点歌名展开轻量控制，再进入 Music room。控制中心放在左上方，避免覆盖右侧人物面部。花朵是本阶段唯一的小型装饰母题，设备图标仍表达真实功能。
- 选择上游原生 Noctalia v5 的配置、JSON palette 和受支持 Luau 插件，未 fork 外壳，也没有继续叠加旧 PR 的视觉实现。网络、蓝牙、声音和启动器使用同一套组件；音乐、更新和双网络概览是小型本地扩展。
- Kitty 保留原有 13 pt 等宽字体与按键，在预览中使用 0.86 背景不透明度。Neovim 只加载颜色覆盖，保留正常 Vim 操作；错误、警告、增删和终端 ANSI 色各有语义。Niri 窗口仍按原来的横向工作流组织，预览使用静态壁纸的 xray 模糊。

`scripts/moonlit-theme.py` 从唯一 palette 派生 Noctalia、Kitty、Neovim 和 Niri 主题。`--check` 检查派生文件是否漂移及基本对比度。纯色文字对比度检查不能替代半透明窗口叠在实际壁纸上的阅读验收。

## 复现预览

在独立工作目录中运行以下命令。**不要在当前已被主目录符号链接引用的 checkout 中切换分支，也不要为这次预览运行面向真实 home 的部署命令。** 原配置仍使用仓库既有的 `scripts/deploy.py` 备份与恢复机制；预览脚本只对专属临时 home 调用它。

运行环境要求：Arch x86_64、正在运行的 Wayland 会话、可用的 Niri、Kitty、Python、`python-gobject`、`dbus-run-session`、`xdg-dbus-proxy`、`busctl`、`nmcli`、`ip`。截图还需 Pillow；获取运行时需 `bsdtar`、`pacman-key` 和支持 zstd tar 的 Python（本机为 Python 3.14）。这些脚本不会安装缺失的系统软件。

先核对 CLI，再获取锁定的本地运行时：

```bash
python3 scripts/fetch-noctalia-preview.py --help
python3 scripts/desktop-preview.py --help
python3 scripts/fetch-noctalia-preview.py
python3 scripts/fetch-noctalia-preview.py --check
```

默认运行时目录是仓库内被 Git 忽略的 `local/noctalia-5.2.1`。下载清单、官方 Arch Archive URL、精确版本和 SHA-256 位于 `config/moonlit/runtime.json`；下载包及签名会保留。脚本先核对哈希和 `pacman-key` 分离签名，检查归档路径，再只解包 `usr`，不执行安装脚本、不调用 `sudo`、不安装或更新系统包。已有无关目录会被拒绝，已有 prefix 不会被覆盖。需要另存时使用 `--destination /absolute/path/to/fresh-directory`；已有签名包可通过 `--package-dir /absolute/path/to/packages` 复用。

该清单是本机 Arch 快照所需的四包补充，不是完整发行版或通用依赖解析器。其他机器仍需要兼容的系统库与可用 Arch 签名密钥环。已用本次下载且验证通过的包完成重新解包和 `--check`；官方归档下载入口尚未单独做一次全量重下载测试。

在同一个终端继续：

```bash
preview_root="/tmp/moonlit-preview-$(id -u)"
runtime_prefix="$PWD/local/noctalia-5.2.1/prefix"

python3 scripts/moonlit-theme.py --check
python3 scripts/desktop-preview.py prepare \
  --runtime "$preview_root" \
  --binary "$runtime_prefix/usr/bin/noctalia" \
  --library-path "$runtime_prefix/usr/lib"
python3 scripts/desktop-preview.py start --runtime "$preview_root"
python3 scripts/desktop-preview.py status --runtime "$preview_root"
```

如果要使用本地壁纸目录，在 `prepare` 后附加 `--wallpapers /absolute/path/to/private-wallpapers`，该目录必须已经存在。路径只写入预览状态，不提交个人图片或绝对路径到共享配置。未传此参数时，不保证复现截图中的个人壁纸。不要把三联概念图裁切放大后标成原生 4K 成品。

`prepare` 会复制受管配置到专属目录，生成预览安全覆盖，并执行 Niri 配置校验。重复准备前必须 `stop`；重复准备会重置该预览的 Noctalia 设置状态。`start` 打开嵌套窗口，不改变登录管理器、默认会话或现有桌面服务。

预览内部常用操作：

| 操作 | 入口 |
| --- | --- |
| 应用启动器 | 顶栏启动器，或嵌套窗口内 `Alt+D` |
| Kitty / Neovim | `Alt+Return` / `Alt+N` |
| 控制中心 | 左侧花朵，或 `Alt+Shift+Space` |
| 网络概览 | 控制中心网络快捷入口；其中 `Wi-Fi settings` 返回原生网络页 |
| 轻量音乐 / Music room | 点顶栏歌名，再点 `Open music room` |
| 手动壁纸选择 | 控制中心壁纸入口 |
| 更新 | 点顶栏 `Updates` 手动检查，右键查看结果 |

嵌套 Niri 的 `Mod` 使用 Alt，避免与外层 Super 习惯冲突；真实桌面的既有 Super 快捷键未被替换。网络、蓝牙和会话按键的能力受下文安全边界限制。

按需要调整嵌套窗口尺寸，再查看 `status` 的输出尺寸和缩放；脚本不把小窗口截图自动放大成 4K。分别打开工作布局、控制中心、Music room 后截图：

```bash
python3 scripts/desktop-preview.py capture --runtime "$preview_root" \
  --output "$preview_root/screenshots/work.png"
# 切换到控制中心后执行：
python3 scripts/desktop-preview.py capture --runtime "$preview_root" \
  --output "$preview_root/screenshots/control-center.png"
# 切换到 Music room 后执行：
python3 scripts/desktop-preview.py capture --runtime "$preview_root" \
  --output "$preview_root/screenshots/music-room.png"

python3 scripts/desktop-preview.py stop --runtime "$preview_root"
python3 scripts/desktop-preview.py status --runtime "$preview_root"
```

`capture` 使用记录在预览目录中的嵌套 Niri socket，返回实际像素尺寸，并明确标记 `physical_4k_acceptance: false`。`stop` 通过 PID、进程启动时间和 pidfd 只结束本次预览拥有的进程，不按全局进程名清理。退出后保留日志、截图和配置，方便复查；临时目录不是长期保存交付物的位置。

## 已实现与未完成的边界

| 部分 | 当前真实能力 | 当前限制 |
| --- | --- | --- |
| 外壳与工作布局 | 原生顶栏、工作区、窗口标题、启动器、控制中心、统一子页、Kitty / Neovim 颜色 | 仅嵌套预览；中文输入法、剪贴板、完整编辑器插件与日常多窗口焦点链尚待主会话验收。预览禁用 Neovim 插件加载以避免额外安装和状态写入。 |
| Wi-Fi / 有线 | 显示真实设备和已有接入点；补充概览读取各 Ethernet / Wi-Fi 状态及 IPv4 / IPv6 默认路由、metric、路由表 | 系统总线写操作被阻断；连接、断开、密码错误、配对等不能据此宣布验收通过。概览不是新连接管理器，默认路由列表也不等于完整策略路由判定。 |
| 蓝牙 | 真实适配器与设备状态，同一控制中心视觉 | 配对、连接、断开和属性写入被代理拒绝；未通过修改 Trusted 或 Powered 规避上游自动行为。 |
| 声音 | 原生 PipeWire 音量、设备和逐应用输出路由界面；区分系统默认输出与应用已有路由 | **连接真实音频会话，音量和路由操作会影响当前声音。** 本阶段未把界面展示当作耳机热插拔、真实听感或网易云实际路由验收。 |
| 常亮、通知、会话 | 保留统一界面结构，通知守护与关机等动作在预览中关闭 | 不替换现有通知服务；锁屏、挂起、重启、关机、退出登录不能在本阶段视为已完成。预览常亮不能证明真实会话的电源管理行为。 |
| 音乐轻量控制 | 真实 MPRIS 元数据、能力判断、独立播放按钮、来源选择、支持时的前后曲和 seek；关闭展示页不拥有或停止播放器 | 私有会话总线与主会话隔离，不会直接接管主会话网易云。已测 VLC 本地无声播放，不是网易云登录、账号、在线曲库和持续后台播放验收。 |
| Music room | 与轻量控制共享同一个真实来源；专辑盒视觉、真实曲目信息、进度、来源选择和错误状态 | 当前是 1120 × 700 的浮动 popup，尚非可最大化独立窗口。仅接收本地 `file://` 封面；远程封面未下载。队列浏览未接入，歌词未提供，界面直说不可用，不填入虚构内容。 |
| 更新 | 用户主动触发 `checkupdates`，使用独立数据库；未知、失败、旧结果有区别 | 仅官方 Arch 仓库；不覆盖 AUR，不自动升级。不检查时 `?` 表示未知，不能解读为零更新。 |
| 壁纸 | 三个同主题候选与手动入口，统一 UI palette | 本轮三个独立生成的场景均为 1672 × 941，并非从三联图裁出；旧三联参考图另行保留。当前截图中的缩放不改变素材分辨率，独立原生 3840 × 2160 壁纸仍待制作。 |

音乐没有另造播放引擎。对网易云的偏好、浏览器不无提示抢源、显式改选和来源消失后的回退已有逻辑及测试，但仍须用用户实际播放后端验证。当前共享媒体服务在面板可见时每秒读取一次、隐藏时每两秒读取一次；关闭 Music room 会清空大封面节点并停止该页帧 / 秒回调。每次读取会启动一个 Python / Gio 桥进程，原生 API 的插件接口没有媒体事件订阅；后续应复用 Gio 连接并按事件刷新，同时对重复状态去重。它尚不是完全事件驱动实现，不能把“关闭动画”写成“后台零开销”。

## 隔离措施及首次探测发现

预览采用独立 XDG 配置 / 状态 / 缓存、独立 Noctalia 数据根和私有 session D-Bus；私有总线没有服务激活目录，不启动主会话的通知、密钥环或门户。`GSETTINGS_BACKEND=memory` 阻止 Noctalia 的主题偏好写回真实 GNOME 设置。会话、电源、锁屏、自动壁纸、天气、遥测和外部主题模板关闭。

系统设备通过强制 `xdg-dbus-proxy --filter` 读取，**缺少代理或拒绝验证失败就不启动外壳**。允许的对象限于 NetworkManager、BlueZ、UPower、login1：共同允许 Properties.Get / GetAll、ObjectManager.GetManagedObjects、Introspect，以及各服务必要的设备、接入点、已有连接设置、会话或电源状态读取与状态信号。NetworkManager GetSecrets、BlueZ Connect / Disconnect、Properties.Set、配对、网络激活和电源动作均不在允许列表中。准确列表见 `scripts/desktop-preview.py` 的 `SYSTEM_READ_METHODS` 与 `COMMON_READ_METHODS`。

启动前向一个不存在的 BlueZ 路径发送 Connect 拒绝探针，必须得到 AccessDenied；这个路径即使错误放行也不存在真实设备。结果保存在 `proxy-verification.json`，代理日志在 `system-proxy.log`。这层隔离不涵盖 PipeWire，也不是对任意从启动器打开的应用做完整沙箱；启动实际应用仍会执行其真实行为。

首次未加系统总线代理的探测暴露了两个上游默认行为，不能省略：

1. Noctalia 5.2.1 初始化蓝牙时会自动尝试连接已配对、受信任而未连接的设备。首次日志记录到 **两次 `Device.Connect` 请求超时**，没有观察到成功连接；不是必须点击设备才会发生。目前没有对应的安全禁用配置，最终预览由方法白名单阻断此请求，未修改用户设备的 Trusted 状态。
2. `shell.offline_mode=true` 并不能禁止插件管理器初始化 Git 来源；首次启动曾拉取 official / community 仓库到预览自己的状态目录。现已显式设置 `[plugins] source=[]`、`auto_update="none"`，只启用仓库中的三个本地插件。不能仅凭 offline_mode 宣称此前没有联网。

这些措施保护本阶段的比较和截图，不表示完整桌面迁移也应永久禁止设备操作。后续需要在视觉确认后，为真实设备写入与错误恢复设计独立的受控验收。

## 验证记录

以下为本阶段 Linux 快照，不沿用旧 PR 的测试结果充数：

- `bash scripts/check.sh`：144 项通过；覆盖既有部署恢复与本次主题、媒体、更新、网络和预览隔离等行为。
- 三个本地插件使用实际 Noctalia 5.2.1 lint：0 error / 0 warning；原生配置校验及 Niri 配置校验通过。
- 使用真实 VLC、私有 MPRIS 总线和本地无声测试媒体：8 项断言通过；反复打开 / 关闭展示界面 20 次，未重启或重播后端，该轮外壳 RSS 增量约 40 KiB。一次小幅 RSS 增量不构成长期无泄漏证明。
- 合成 MPRIS 场景：10 项断言通过，用于验证多源、显式选择、热移除等边界。合成后端不是网易云功能验收。
- 锁定运行时包的哈希、分离签名、重新解包后的二进制及 `--version` 已验证。运行时获取脚本的错误哈希、错误签名、目标目录保护与不安全归档路径有测试。

**未做 macOS 验证。** Linux 中的 headless / 解析测试也不能证明实体屏幕字体、中文输入法、剪贴板、声音听感或完整 GUI 工作流已经通过。

### 性能与交付证据

每种状态观察约 180 秒，每 2 秒采样。CPU 为**单个逻辑核 100%**，不是整机百分比；“含子进程”把 `/proc` 已回收子进程 CPU 计入，避免漏报短命 Python 媒体桥。Noctalia 数字不含额外的嵌套 Niri 与 VLC。

| 状态 | Noctalia 自身 CPU | 含桥接子进程 CPU | Noctalia RSS | 嵌套 Niri CPU / RSS | VLC CPU / RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| 展示关闭、VLC 暂停 | 0.87% | 8.27% | 443.14 MiB | 0.68% / 415.84 MiB | 0.00% / 25.77 MiB |
| Music room 打开、VLC 暂停 | 1.45% | 16.15% | 449.75 MiB | 0.77% / 513.22 MiB | 0.00% / 25.77 MiB |
| 关闭后、VLC 后台播放 | 0.93% | 8.58% | 451.79 MiB | 0.51% / 551.59 MiB | 0.70% / 28.29 MiB |

整机 NVIDIA 采样均值依次为 GPU 利用率 3.10% / 3.67% / 7.10%，显存 2201 / 2029 / 1883 MiB，功耗 33.02 / 25.20 / 33.09 W。**这些是包括现用桌面与其他应用的整机数字，不是新 shell 独占 GPU 成本，不能用功耗高低宣称两状态谁更省电。** 旧 Quickshell 的先前约 178 秒观察为 CPU 0.25%、RSS 337.94 MiB；期间存在开发活动且短暂与预览重叠，不是相同负载的公平性能对照。

结论：本轮能评价视觉和基础交互，**尚未通过后台低开销验收**。媒体桥在隐藏 / 展开时分别每分钟启动约 30 / 60 次 Python；应在下一阶段改为连接复用与事件驱动，并去掉未变化状态导致的重绘。关闭后的 RSS 没有立即回落，不能宣称缓存 / 纹理已经释放。静态日志显示没有装饰 frameTick / animation 循环，但仍有状态刷新引起的重绘。

20 次开关验证中的 IPC 接收确认时间：打开中位数 35.02 ms / p95 40.81 ms，关闭中位数 34.80 ms / p95 37.65 ms。它只测命令确认，**不等于可见内容延迟、帧时间或掉帧率**。嵌套输出 60 Hz 不是测得动画 60 fps。尚未获得 p95 帧耗时；实体 160 Hz、模型推理、全屏游戏压力测试和长时间资源增长仍未验收。

本机交付目录为仓库 Git 忽略的 `local/moonlit-preview/review/`：

- `01-work-4k.png`、`02-launcher-4k.png`、`03-controls-4k.png`：两列工作、启动器、展开控制中心。
- `04-audio-4k.png`、`05-network-4k.png`、`06-bluetooth-4k.png`、`07-links-4k.png`：统一设备设置与双网络概览。
- `08-music-light-4k.png`、`09-music-room-4k.png`：真实 VLC 元数据与测试媒体；无封面时显示缺失状态。
- `10-wallpaper-picker-4k.png`、`scene-*-4k.png`、`11-neutral-palette-4k.png`：手动壁纸选择、三个场景与去壁纸配色复查。
- `interaction-4k.mp4`：约 14.93 秒，3840 × 2160、30 fps、无音轨；录屏帧率不是桌面渲染性能测量。
- `performance-*.csv`、`performance-summary.json`、`media-lifecycle.json`、`media-selection-live.json`、`baseline-verification.json`、`linux-check.log`：本机证据。

这些文件保留在本机，没有上传到公开 PR。网络 / 蓝牙截图可能包含本机名称、SSID 与地址；壁纸、账户和运行状态也不进入共享配置。原始三张壁纸位于同级 `wallpapers/`，每张实际为 1672 × 941；截图为原生 3840 × 2160，不将两者混为一谈。

## 上游依据

- [Noctalia v5.2.1 发布](https://github.com/noctalia-dev/noctalia/releases/tag/v5.2.1) 与 [配置说明](https://docs.noctalia.dev/noctalia/configuration/)；本轮使用原生运行时，不照搬旧 Quickshell 安装方法。
- [声明式插件 UI](https://docs.noctalia.dev/noctalia/plugins/development/declarative-ui/)；三个扩展只使用当前受支持接口。
- [Niri Window Effects](https://niri-wm.github.io/niri/Window-Effects.html)；本机 26.04 的 xray 模糊已在嵌套窗口使用，缓存不能替代负载实测。

## 下一阶段

先根据工作布局、展开控制中心和 Music room 的实际画面确认整体方向，集中评价玻璃强度、甜美程度、人物与文字的关系。确认前停在本阶段，不全面部署，不合并 PR，也不删除旧 draft。

确认后优先制作三个独立原生 4K 壁纸；在保留可恢复部署的前提下完成真实主会话的启动器 / 焦点 / 中文输入 / 剪贴板验收，再验证 Wi-Fi、双网络、蓝牙、逐应用音频路由、通知、常亮与会话操作。音乐先用实际网易云后端证明账号、播放连续性和来源锁定，再决定独立 Music room 窗口、远程封面缓存和高级动画。模型推理与游戏负载下的帧时间、功耗和关闭展示后的回落需要单独测量。
