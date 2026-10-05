# Linux 桌面

可选的 Niri 桌面使用暗玫瑰主题，与共享 Kitty、Neovim 和 LazyGit 一致。
`niri/config.kdl` 管理布局、按键与窗口规则；`systemd/` 管理仅随 Niri 会话运行的桌面组件。
共用组件的主题和行为放在 `config/`，硬件和个人壁纸留在本机。

安装和部署均需显式指定 `--desktop niri`；默认命令仍只处理原有编辑工具。
脚本不替换 GNOME、不启用显示管理器或改变默认登录会话，服务也不执行 `enable`。
先完成静态检查，再自行在登录界面选择 Niri。

完整安装、工作流、按键、125% 缩放、网课常亮和游戏说明见 [Niri 使用指南](../../docs/niri.md)。
配色约定见 [统一风格](../../docs/style.md)，实际验证范围见 [验证记录](../../docs/validation.md)。
