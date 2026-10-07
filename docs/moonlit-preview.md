# Moonlit Bloom：预览与部署前工程交接

需求依据是 [TEMP-desktop-design.md](TEMP-desktop-design.md)。PR #4 的 Moonlit Bloom 视觉已获确认；本轮保持主题、Niri / Kitty / Neovim 工作流及三个壁纸场景，完成音乐后台与可恢复部署的工程收尾。分支仍为 `codex/desktop-nocturne-redesign`，PR 保持 Draft，未全面迁移主会话，旧 PR #3 保留。

## 实现范围

原生 Noctalia 外壳提供顶栏、启动器、控制中心及统一设备设置；本地插件补充轻量音乐、Music room、双网络概览和手动更新检查。`config/moonlit/runtime.json` 锁定运行时；`config/moonlit/palette.json` 是共用 palette，`scripts/moonlit-theme.py --check` 验证派生主题。三个场景手动选择，不自动切换或自动为每张图生成主题。

Music room 仍是浮动 popup，未接入远程封面、队列浏览和歌词；真实播放器不支持的操作保持禁用。现有壁纸是视觉参考，不作为原生 4K 成品交付。新壁纸与高级动画另行处理。

音乐服务改用 API32 `runStream` 启动常驻 Gio worker，订阅 Noctalia / MPRIS / DBus 事件，去重后发布状态。隐藏或暂停时没有周期进度查询；可见且播放时，每秒通过已有连接查询进度。用户主动控制仍使用一次性 CLI。播放器选择、网易云优先、显式来源、seek 与消失回退沿用原规则。

Noctalia 的部分属性缓存延迟更新，相关事件 burst 后有两次有限对账，随后停止。`runStream` 没有退出回调，休眠 wrapper 在 worker 退出时通知 UI：清空旧状态，并提供手动重连。插件重载 / 禁用清理进程组；worker 监听父进程和 owner 死亡；请求按 owner / 序号释放 pending，避免旧回调阻塞新入口。wrapper 自身遭外部 SIGKILL 的通知仍受上游 API 限制，需禁用 / 启用插件恢复。

时区跟随系统本地设置；外壳和本地插件使用简体中文，保留原始诊断信息。网络命令失败不再误报成功，面板关闭后忽略迟到回调；修复更新栏空错误字符串掩盖说明的问题。上游缺失翻译仍可能回退英文。

## 可恢复旧桌面基线

把正在使用的配置链接到可切换分支的 checkout，会让旧分支独有文件在切分支后失效。驻留外壳和 systemd 缓存可能暂时掩盖这个问题。

`scripts/desktop-baseline.py` 从指定 Git 提交生成仓库外只读版本目录，以旧版补缺失依赖、保留指定当前版本的有效桌面文件，只补兼容启动入口。共享编辑器 / 终端链接不在修复范围；缺失 GTK 设置继续继承系统设置。清单记录来源与逐文件哈希。

```bash
python3 scripts/desktop-baseline.py --help
# 使用已审阅的提交与新目录；变量须先按本机清单设置。
python3 scripts/desktop-baseline.py prepare --source-repo "$PWD" \
  --revision "$legacy_revision" --preserve-revision "$current_revision" \
  --baseline "$baseline_dir"
python3 scripts/desktop-baseline.py verify --baseline "$baseline_dir"
python3 scripts/desktop-baseline.py deploy --baseline "$baseline_dir" --home "$HOME"
```

`deploy` 默认仅预演，加 `--apply` 才写链接。脚本复用固定版本 `scripts/deploy.py` 的备份事务，拒绝未知个人文件、外部链接、未审阅源码修改及被篡改版本。它不重启服务、不注销、不更改默认会话。

恢复前用固定版本的 `scripts/deploy.py --restore <备份目录>` 预演。撤销修链会精确恢复原链接，也可能恢复原有失效链接；不要把它与未来 Moonlit 迁移的回退事务混淆。保留固定版本和备份，不当作缓存删除。

## 隔离预览与验证

```bash
python3 scripts/fetch-noctalia-preview.py --help
python3 scripts/fetch-noctalia-preview.py
python3 scripts/fetch-noctalia-preview.py --check
python3 scripts/desktop-preview.py --help
```

获取脚本校验锁定包的哈希和分离签名，只解包本地运行库，不安装或升级系统包。需要现有兼容的 Arch / Wayland 环境及 Niri、Kitty、Python GObject、DBus 工具；不会自动安装缺失依赖。

```bash
preview_root="/tmp/moonlit-preview-$(id -u)"
runtime_prefix="$PWD/local/noctalia-5.2.1/prefix"
python3 scripts/desktop-preview.py prepare --runtime "$preview_root" \
  --binary "$runtime_prefix/usr/bin/noctalia" --library-path "$runtime_prefix/usr/lib"
python3 scripts/desktop-preview.py start --runtime "$preview_root"
python3 scripts/desktop-preview.py status --runtime "$preview_root"
# 结束后仅停止本次预览所属进程：
python3 scripts/desktop-preview.py stop --runtime "$preview_root"
```

可给 prepare 加 `--wallpapers <本地目录>`；个人素材和路径不进入共享配置。预览使用独立配置、状态和私有 session DBus，系统设备写入由强制代理阻断，主题偏好仅写入内存。缺少代理或拒绝检查失败就不启动。PipeWire 仍是真实会话，音量和路由操作可能影响正在播放的声音；预览也不是任意启动应用的完整沙箱。

预览关闭通知守护、会话 / 电源操作、自动壁纸、天气、遥测、外部主题模板和插件来源同步。Noctalia 启动时可能尝试连接受信任蓝牙设备，预览代理会阻断；真实会话需单独验收。

嵌套窗口使用 Alt 作为 Mod，真实桌面快捷键不变：Alt+Return 打开 Kitty、Alt+N 打开 Neovim、Alt+D 打开启动器、Alt+Shift+Space 打开控制中心。截图通过 `desktop-preview.py capture --runtime "$preview_root" --output <文件>` 获取真实嵌套尺寸，不放大伪装为物理显示验收。

Linux 仓库检查、配置校验、原生插件 lint、真实 VLC 私有总线控制、反复开关音乐页、多来源合成回归、worker 故障恢复、插件禁用 / 启用及退出清理已执行。未验证 macOS；headless 测试不证明字体、中文输入、剪贴板或 GUI 工作流。

```bash
bash scripts/check.sh
# 已启动受保护预览后，使用专属无声 VLC（需 VLC / ffmpeg）：
python3 tests/moonlit_media_live.py --session "$preview_root/session.json" --keep-player
python3 tests/moonlit_media_benchmark.py --runtime "$preview_root" \
  --output "$preview_root/performance" --seconds 180 --include-room-playing
```

性能协议使用匹配配置、壁纸和播放器，先反复开关预热，再分别测关闭暂停、展开暂停、关闭播放及补充展开播放。CPU 按单个逻辑核归一化，包含外壳及存活 / 已回收子进程；RSS 求和不是 PSS。采样 PID 数不是完整启动次数；既有更新组件的本地状态读取也在统计内。原始性能、显示、部署、恢复路径和截图只保留在本机交接材料，不上传公开 PR。

## 真实会话验收

视觉已确认，接下来可安排受控验收。先保存工作，检查固定旧基线与恢复清单，验证旧基线重新登录；再以可恢复事务临时切换 Moonlit。明确顶栏、通知、idle / 锁屏各自唯一负责组件。失败时撤销当次 Moonlit 迁移，回到固定旧基线，不回滚修链事务。不自动更改默认会话或注销当前工作。

| 验收组 | 实际通过标准 |
| --- | --- |
| 显示与工作流 | 目标物理分辨率、缩放、刷新率下字体与弹层正确；原 Niri 按键和列宽、Kitty / 完整 Neovim / Codex / 浏览器多窗口工作流保留。 |
| 输入与焦点 | Fcitx5 中文输入、候选窗和切换；终端、编辑器、启动器、GTK / 浏览器剪贴板往返；启动 / 聚焦和关闭弹层后返回原焦点。 |
| 网络 | Wi-Fi 扫描、连接、错误密码、取消与重连；Ethernet 插拔；双网络和默认路由真实，保留可用连接和凭据。 |
| 蓝牙与音频 | 指定耳机连接 / 消失 / 重连；实际应用 stream→sink、音量及听感与界面一致，区分系统默认设备与已有流。 |
| 常亮与通知 | Caffeine 可逆，idle / 锁屏恢复；真实通知、操作、历史与免打扰；通知守护唯一。 |
| 会话 | 锁定 / 解锁、挂起恢复；保存工作后另验注销 / 重启 / 关机的确认和 inhibitor，不强制结束任务。 |
| 音乐与负载 | 用户真实网易云歌曲和账号、浏览器不抢源、显式选择、媒体键、seek 能力、关 / 开连续、热移除；长期资源增长和高负载帧时间另测。 |

上述真实会话项目尚未因隔离测试而自动通过；当前仍不作为全面迁移验收完成。

## 上游依据

- [Noctalia 插件运行时 API](https://docs.noctalia.dev/noctalia/plugins/development/runtime-api/)；具体接口按锁定版本源码和 API 清单验证。
- [MPRIS Player 接口](https://specifications.freedesktop.org/mpris/latest/Player_Interface.html)：Position 不发 PropertiesChanged，不能仅靠曲目信号更新可见进度。
