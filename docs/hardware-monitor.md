# 终端硬件监控

`sysmon` 默认只显示 CPU、GPU、RAM、磁盘与网络的关键参数和曲线。Niri 下用 `Super+M`
或 `sysmon --window` 打开约四分之一桌面大小的浮动窗口，方便同时观察本地程序。
窗口沿用现有字体家族与暗玫瑰 / Moonlit Bloom 配色，使用 11 号字号，隐藏单窗口标签栏并关闭背景模糊。

数据采集与绘图使用第三方 [btop 1.4.7](https://github.com/aristocratos/btop/tree/v1.4.7)，本仓库提供
Python 启动器、主题和一份小型 C++ 补丁：移除菜单、帮助、设置及进程控制入口，按 `Esc` 直接退出。
不需要重写 Rust；默认关闭进程采集、PCIe 速率轮询和重复 GPU 信息，并降低刷新频率。

## 日常打开

| 命令 / 按键 | 用途 |
| --- | --- |
| `sysmon` | 紧凑参数视图，不扫描进程列表 |
| `sysmon proc` | CPU、GPU、RAM 与进程列表 |
| `sysmon all` | CPU、GPU、RAM、磁盘、网络与进程总览；适合放大窗口 |
| `sysmon gpu` | nvtop：GPU 曲线、显存与使用 GPU 的进程；Arch 可选工具 |
| `sysmon io` | btop：启动时展开磁盘读写曲线，观察加载数据、编译和缓存 |
| `sysmon sensors` | 定时刷新传感器读数，查看温度、风扇和电压；Arch 可选工具 |
| `sysmon --filter python` | 自动打开进程视图并筛选 Python；可换成自己的程序名称 |
| `sysmon --window` | 在独立 Kitty 窗口打开紧凑参数视图 |
| `sysmon gpu --window` | 在独立 Kitty 窗口打开 GPU 视图 |
| `Super+M` | 打开紧凑参数窗口，需先启用下面的可选 Niri include |
| `Super+Shift+M` | 打开 GPU 窗口，同上 |

默认每 **3000 ms** 刷新；`sysmon --interval 1000` 改为每秒，单位是毫秒，最小为 100 ms。
参数也可组合，例如 `sysmon --filter python --window --interval 1000`。
进程筛选只作用于列表；CPU / GPU / RAM 图表仍是整机数值。
GPU 模式刷新间隔按 100 ms 步长取整。更高刷新率会增加监控程序自己的开销。

在参数视图中按 `Esc` 或 `q` 退出；正在输入进程筛选时，`Esc` 先取消输入。
nvtop 使用自己的按键与界面，按 `q` 退出；`Ctrl+C` 也可结束监控。
传感器视图使用 `watch sensors`，按 `Ctrl+C` 退出。该视图提供读数列表，曲线看总览或 GPU 视图。
已运行程序不会随监控窗口退出。

## 观察自己的程序

先在普通终端启动本地程序，再按 `Super+M`，或在另一终端运行：

```sh
sysmon --filter python
```

在进程列表中选择目标并按 `Enter` 查看 CPU / 内存详情；多进程程序可用树形视图观察子进程。
GPU 任务另开 `sysmon gpu`，按进程名或 PID 对照 GPU 利用率与显存。
进程筛选不启动目标程序，也不自动收集或保存整个运行过程。

| 图表 / 参数 | 观察内容 |
| --- | --- |
| CPU | 总利用率、各逻辑核、频率；温度和功率按硬件及读取权限显示 |
| GPU | 设备利用率、VRAM、温度、功率、频率；nvtop 补充 GPU 进程与驱动提供的编解码指标 |
| RAM / Swap | 内存使用、可用内存、缓存及交换空间；进程列表提供各进程占用 |
| Disk I/O | 各磁盘读写吞吐与容量，适合排查数据加载或写入瓶颈 |
| Network | 当前网卡的上传 / 下载曲线与累计流量 |
| Sensors | 系统已经暴露的温度、风扇转速及电压；不同设备会提供不同项目 |

### 参数视图常用按键

保留以下 [btop 操作](https://github.com/aristocratos/btop/blob/v1.4.7/src/btop_menu.cpp#L163-L205)。
进程相关按键只在 `proc` / `all` 视图中使用，`j/k` 与上下方向键都可选择进程。

| 按键 | 功能 |
| --- | --- |
| `f` 或 `/` | 输入进程筛选，`Enter` 确认，`Delete` 清空已确认的筛选 |
| `Enter` | 查看 / 关闭所选进程详情 |
| `e` | 切换进程树；树内按 `Space` 展开 / 折叠所选进程 |
| `i` | 切换磁盘 I/O 大图 |
| `n` / `b` | 下一张 / 上一张网卡 |
| `1` / `2` / `3` / `4` | 显示 / 隐藏 CPU、内存、网络、进程区域 |
| `5` | 显示 / 隐藏第一张可检测 GPU 的区域 |
| `Esc` / `q` / `Ctrl+C` | 退出；筛选输入中的 `Esc` 取消输入 |

每次打开都会恢复仓库的起始布局，临时调整不写回配置。菜单、帮助与进程发信号 / 调整优先级的按键不启用。
`sysmon --theme moonlit` 或 `sysmon --theme rose` 可显式选择 btop 配色；默认根据当前 Kitty 主题选择。
nvtop 使用终端颜色，其个人偏好保存到 `${XDG_STATE_HOME:-$HOME/.local/state}/sysmon/nvtop.ini`。

## 安装与独立部署

默认入口需要本仓库构建的 `btop-view`，单独安装系统 `btop` 不包含精简界面补丁。
构建需要 Python 3、`make`、`patch` 及 GCC 14+ 或 Clang 19+；macOS 的编译器设置见
[上游构建说明](https://github.com/aristocratos/btop/tree/v1.4.7#compilation-macos-osx)。Arch 可安装构建工具与可选视图：

```sh
sudo pacman -Syu --needed gcc make patch nvtop lm_sensors
```

传感器视图还需要系统的 `watch` 命令。软件清单中的 `btop` 仍可单独使用；Arch 另含 `nvtop` 与 `lm_sensors`。
在仓库中构建一次，再部署入口：

```sh
python3 scripts/build-monitor.py
python3 scripts/deploy.py --monitor
python3 scripts/deploy.py --monitor --apply
```

构建脚本下载固定版本源码、校验哈希并应用补丁，将结果安装到用户工具目录；运行 `sysmon` 时不会下载或编译。
补丁更新后重新运行构建命令，可用 `python3 scripts/build-monitor.py --check` 验证安装。
构建与软件安装不能通过配置恢复撤销。`--monitor` 部署只管理监控入口与主题，不替换当前桌面会话。

命令链接位于 `~/.local/bin/sysmon`，配置位于 `${XDG_CONFIG_HOME:-$HOME/.config}/sysmon/`。
`--monitor` 与 `--desktop` 互斥。自定义 XDG_CONFIG_HOME 不会改变命令链接所在的 HOME；
测试时可用 `--home /tmp/your-disposable-home` 同时隔离 config、state 和 bin。
已有 Kitty 的新窗口会包含 `~/.local/bin`；其他终端若找不到 `sysmon`，可先用
`~/.local/bin/sysmon`，或按 [README 的 PATH 说明](../README.md#新机器恢复) 补充路径。

部署输出会给出仓库外备份目录。恢复时使用对应的目录，先看计划，再实际恢复：

```sh
python3 scripts/deploy.py --restore "$monitor_backup_dir"
python3 scripts/deploy.py --restore "$monitor_backup_dir" --apply
```

### 启用 Niri 快捷键

Linux 的监控部署额外安装 `sysmon/niri.kdl`。先把现有的
`${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles-local/niri.kdl` 备份到仓库外，再在该**个人文件**中追加一次：

```kdl
include "../sysmon/niri.kdl"
```

不要将个人屏幕设置复制进仓库。检查配置通过后显式重载：

```sh
niri validate --config "${XDG_CONFIG_HOME:-$HOME/.config}/niri/config.kdl"
niri msg action load-config-file --path "${XDG_CONFIG_HOME:-$HOME/.config}/niri/config.kdl"
```

这条 include 从已有的本地覆盖引入独立入口，也适用于 Niri 配置链接到固定 Moonlit release 的会话；
无需改写该 release 或会话 transaction。真实会话的 `Mod` 是 Super，嵌套 Niri 通常是 Alt。
监控窗口默认浮动在右下角，宽、高各为可用桌面的二分之一；可以用 Niri 常规操作移动或调整大小。
恢复监控部署前，先从个人文件移除这条 include 并验证 / 重载 Niri，再恢复部署备份，避免留下失效 include。
个人文件的追加内容不在 `deploy.py` 的监控备份范围内。

## 设备与平台边界

GPU 图表取决于驱动和设备库；缺少可检测 GPU 时紧凑视图仍可查看 CPU、RAM、磁盘和网络。
NVIDIA 通常通过驱动自带的 NVML 提供数据；AMD / Intel 的项目随驱动与权限而异。
部分 CPU 功率、Intel GPU 信息需要额外读取权限；入口不自动使用 sudo、不设置 capability，也不加载驱动。
空值表示该项暂不可读，不等于使用量为零。[btop GPU 说明](https://github.com/aristocratos/btop/tree/v1.4.7#optional-dependencies-needed-for-gpu-monitoring)、
[nvtop 设备支持说明](https://github.com/Syllo/nvtop#gpu-support)

`sensors` 仅显示内核已提供的传感器，不自动运行 `sensors-detect`、加载模块或更改风扇控制。
温度名称与核编号需要结合机器实际传感器确认。运行监控本身无需修改功耗策略、超频或桌面会话。

macOS 构建后可用 `sysmon` / `sysmon io` 及 Kitty 新窗口入口；本仓库的 nvtop 和 lm_sensors 安装项仅在 Arch 提供。
btop 的 macOS GPU 支持针对 Apple Silicon，仍取决于构建和机器；温度、功率、磁盘及进程数据与 Linux
不保证一致。Niri 快捷键仅限 Linux。Linux 实机图表、快捷键与 macOS 验证应分别报告，配置解析不代表 GUI 或硬件验收。
