# Niri 快捷键与窗口排列

本文对应仓库的 [Niri 配置](../platforms/linux/niri/config.kdl)。**Super 就是 Win 键**。
下文按从登录界面进入的真实 Niri 会话介绍；开发时在另一个桌面里嵌套运行 Niri，
配置中的 `Mod` 会变成 Alt，只有锁屏固定为 `Super+Alt+L`。
这些是桌面快捷键，Neovim 与 Kitty 原有按键保持不变。

## 先记住这几个

| 按键 | 功能 |
| --- | --- |
| `Super+D` | 暗玫瑰应用选择窗口：输入名称、↑↓ 选择、Enter 启动、Esc 关闭；也可直接点击 |
| `Super+Enter` | Kitty 终端；已有命令行程序在这里运行 |
| `Super+B` | 系统默认浏览器，例如 Chrome / Chromium |
| `Super+E` | Nautilus 文件管理器 |
| `Super+N` | 在学习工作区打开 Neovim 笔记终端 |
| `Super+O` | 总览窗口和工作区，再按一次退出 |
| `Super+Q` | 关闭当前窗口；未保存内容由应用决定是否询问 |
| `Super+Shift+Space` | Rose Observatory 桌面控制面板；Esc 关闭 |
| `Super+Shift+/` | Niri 快捷键提示层 |
| `Super+M`（可选） | 打开 CPU / GPU / RAM 参数图表，可用原有操作调整窗口大小 |
| `Super+Shift+M`（可选） | GPU 图表、显存与 GPU 进程监控 |

应用选择窗口与桌面控制面板共用配色、字体、卡片和边框样式。可按名称、类别或关键词搜索，
包含原生和 Flatpak 的可见应用入口；Neovim 等终端应用由 Kitty 打开。
再次按 `Super+D` 会聚焦已有窗口；启动出错时保留窗口并显示原因，不记录应用使用历史。

硬件监控快捷键通过独立的 `sysmon/niri.kdl` 启用，默认桌面部署不自动引入。
参数窗口打开为普通半屏宽的平铺列，沿用 Kitty 字体与外观，每 3 秒刷新，按 `Esc` 或 `q` 退出。
用下文的 `Super+[` / `Super+]` 合并或拆出窗口、调整高度，可排列到四分之一桌面大小；图表随尺寸调整。
命令行中可用 `sysmon`、`sysmon gpu`、`sysmon io` 和 `sysmon sensors`；
`sysmon proc` 或 `sysmon --filter python` 按需显示进程列表。构建、可恢复部署与个人 include 步骤见
[终端硬件监控](hardware-monitor.md)。

## 怎么把两个窗口上下排列

Niri 把窗口放在横向排列的「列」里，**同一列内可以有多个上下排列的窗口**。
左右切换的是列，上下切换的是同列窗口。新窗口默认新建一个半屏宽的列。

例如，浏览器在左，笔记终端在右，而且两者各占一列：

1. 点击**右侧笔记终端**，或用 `Super+→` 选中它。
2. 按 **`Super+[`**，把它并入左侧浏览器所在的列，放在浏览器下面。
3. 若想让这组上下窗口横向占满屏幕，按 `Super+F` 最大化这一列。
4. `Super+↑/↓` 在上下窗口间切换；`Super+Shift+↑/↓` 改变它们的上下顺序。
5. 想拆回左右排列，选中笔记终端，按 **`Super+]`**，它就会成为右侧的新列。

```text
开始：两个独立的列        选中 B，Super+[        选中 B，Super+]
┌────────┬────────┐       ┌────────┐           ┌────────┬────────┐
│        │        │       │   A    │           │        │        │
│   A    │   B    │  →    ├────────┤     →     │   A    │   B    │
│        │        │       │   B    │           │        │        │
└────────┴────────┘       └────────┘           └────────┴────────┘
```

`[` / `]` 的方向指左 / 右。**当前列只有一个窗口时**，把窗口并入相邻列；
**当前列已有多个窗口时**，把当前窗口拆成该方向的新列。相邻列不存在时无法合并。
这是 [Niri 26.04 的合并 / 拆分规则](https://github.com/niri-wm/niri/blob/v26.04/src/layout/scrolling.rs#L1627)。

高度调整用 `Super+Shift+-` 缩小、`Super+Shift+=` 增大，每次调整 5 个百分点；
应用的最小尺寸仍可能限制高度。也可按住 `Super` 用鼠标右键拖动边缘调整。

**如果合并后只能看到一个窗口**，当前列可能处于标签模式。按 `Super+W` 在
「上下平铺」和「标签显示」之间切换；标签模式仍用 `Super+↑/↓` 切换窗口。
它改变同列窗口的显示方式，不负责合并相邻列。[官方标签说明](https://niri-wm.github.io/niri/Tabs.html)

## 移动焦点与窗口

| 按键 | 功能 |
| --- | --- |
| `Super+H/L` 或 `Super+←/→` | 切换左 / 右列 |
| `Super+K/J` 或 `Super+↑/↓` | 切换同列上 / 下窗口 |
| `Super+Shift+H/L` 或 `Super+Shift+←/→` | 向左 / 右移动整列 |
| `Super+Shift+K/J` 或 `Super+Shift+↑/↓` | 在同列中向上 / 下移动当前窗口 |
| `Super+Home/End` | 切到第一 / 最后一列 |
| `Super+[` / `Super+]` | 向左 / 右合并或拆出当前窗口，规则见上文 |
| `Super+Alt+方向键` | 切到相应方向的显示器 |
| `Super+Ctrl+Alt+方向键` | 将整列移到相应方向的显示器 |

## 大小、全屏与浮动

| 按键 | 功能 |
| --- | --- |
| `Super+R` | 循环切换列宽：⅓、½、⅔、全宽 |
| `Super+Shift+R` | 按相反顺序切换列宽 |
| `Super+-` / `Super+=` | 列宽减少 / 增加 5 个百分点 |
| `Super+Shift+-` / `Super+Shift+=` | 当前窗口高度减少 / 增加 5 个百分点 |
| `Super+F` | 当前整列最大化 / 恢复宽度，适合上下两窗共同占满屏幕 |
| `Super+Shift+F` | 当前窗口全屏 / 退出全屏，适合视频和游戏 |
| `Super+C` | 当前列在屏幕中居中 |
| `Super+V` | 当前窗口在浮动和平铺之间切换 |
| `Super+Shift+V` | 在浮动区域和平铺区域之间切换焦点 |
| `Super+W` | 同列的上下平铺 / 标签显示 |

`-`、`=`、`[`、`]` 指键盘上的对应键；例如增大高度就是同时按住 Super、Shift 和 `=`。

## 工作区

| 按键 | 功能 |
| --- | --- |
| `Super+1` | Read：文档阅读 |
| `Super+2` | Code：代码项目 |
| `Super+3` | Study：网课与 Markdown 笔记 |
| `Super+4` | Play：游戏 |
| `Super+Shift+1/2/3/4` | 将当前**整列**移动到对应工作区 |
| `Super+PageUp/PageDown` | 上一个 / 下一个工作区 |
| `Super+Ctrl+PageUp/PageDown` | 将整列移到上一个 / 下一个工作区 |
| `Super+Tab` | 返回之前的工作区 |
| `Super+滚轮上/下` | 上一个 / 下一个工作区 |
| `Super+Shift+滚轮上/下` | 左列 / 右列 |

普通应用在当前工作区打开。`Super+N` 的专用笔记终端固定在 Study；项目代码可用普通终端
进入项目目录后运行 `nvim`。上下排列的一列移动工作区时会一起移动；只想移动一窗时先用
`Super+]` 把它拆出，再按工作区移动键。

## 桌面、截图与游戏

| 按键 | 功能 |
| --- | --- |
| `Super+T` | Kitty 终端，等同 `Super+Enter` |
| `Super+Alt+B` | Balanced / Focus / Performance 状态栏选择 |
| `Super+Alt+W` | 选择本地壁纸 |
| `Super+Alt+P` | Keep awake 网课常亮开关 |
| `Super+Alt+N` | 通知勿扰开关 |
| `Super+Alt+L` | 锁屏；应用抑制桌面快捷键时仍可用 |
| `Print` | 交互截图 |
| `Ctrl+Print` | 当前显示器截图 |
| `Alt+Print` | 当前窗口截图 |
| `Super+Esc` | 切换应用的快捷键抑制，游戏 / 远程桌面占用按键时可用 |
| `Ctrl+Alt+Delete` | 退出 Niri，会显示确认 |
| 音量增 / 减键 | 每次 ±5%，最高 100% |
| 静音 / 麦克风静音键 | 输出 / 输入静音切换 |
| 播放 / 下一首 / 上一首键 | 控制媒体 |
| 亮度增 / 减键 | 每次背光 ±5%，需要可用的背光设备 |

媒体、声音与亮度键在锁屏时也可用。截图默认写入 `~/Pictures/Screenshots/` 并放入剪贴板。
常亮只暂停空闲锁屏与熄屏，仍允许手动锁屏和休眠前锁屏；每次登录会重置为关闭。

## 鼠标操作与常用组合

- 按住 `Super` 加鼠标左键拖动窗口，可以调整排列位置。
- 按住 `Super` 加鼠标右键拖动，可以调整大小。
- 按住 `Super` 加鼠标中键拖动，横向滚动列、纵向切换工作区。
- 触控板三指横滑切换横向视野，三指竖滑切换工作区，四指竖滑打开 / 关闭总览。

这些是 Niri 的默认[鼠标与触控板手势](https://niri-wm.github.io/niri/Gestures.html)。

**网课 + 笔记并排：** `Super+3` → `Super+B` 打开课程 → `Super+N` 打开笔记。
默认各半屏；需要常亮时按 `Super+Alt+P`。Neovim 中打开 `.md` 文件后，`Space mp`
启动数学预览，`Space ms` 停止，详见 [Markdown 笔记指南](markdown-notes.md)。

**阅读 + 终端上下：** 打开文档，再打开终端 → 选中右侧终端 → `Super+[` → `Super+F`。
如果想让下方终端更矮，选中它后按几次 `Super+Shift+-`。

桌面安装、壁纸、常亮和机器迁移的完整说明见 [Niri 指南](niri.md)。
