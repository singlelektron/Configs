# Markdown 数学笔记

本页就是可直接预览的示例：在 Neovim 打开本文件，点击顶部 **Preview**，将浏览器与编辑器并排放置。

## 开始写笔记

1. 将笔记保存为 `.md` 或 `.markdown`，例如新文件执行 `:w notes.md`。
2. 点击 **Preview**，或在普通模式依次按 `Space m p`，打开当前笔记的浏览器预览。
3. 在 Neovim 输入内容，浏览器随之更新；实时更新不会替你保存文件，仍用 `:w` 保存。

首次打开页面从磁盘读取，因此开启前已有的未保存修改应先 `:w`。手动刷新浏览器也会重新读取磁盘。
页面连接建立后，继续输入即可看到未保存内容的更新。

| 操作 | 鼠标 / 快捷键 | 命令 |
| --- | --- | --- |
| 开启当前文件 | 点击 Preview / `Space m p` | `:MarkdownPreview` |
| 关闭当前预览 | 再次点击 Preview / `Space m p` | `:MarkdownPreviewStop` |
| 随时停止服务 | `Space m s` | `:MarkdownPreviewStop` |

在另一份 Markdown 笔记中点击 Preview 或按 `Space m p`，会切换到该文件；在当前已预览的文件中则关闭。
浏览器负责阅读，笔记内容在 Neovim 中修改。

## 一页学习记录

今天关注二阶矩阵的行列式与积分。行内公式使用 `$...$`，例如 $\det(A)=ad-bc$；
独立公式使用 `$$...$$`，例如：

$$
A=\begin{pmatrix}1 & 2\\3 & 4\end{pmatrix},
\qquad \det(A)=1\cdot4-2\cdot3=-2.
$$

$$
\begin{aligned}
I &= \int_0^1 x^2\,\mathrm{d}x \\
  &= \left[\frac{x^3}{3}\right]_0^1 \\
  &= \frac{1}{3}.
\end{aligned}
$$

### 学习清单

- [x] 手算行列式。
- [ ] 用代码核对结果。
- [ ] 写下计算过程与疑问。

任务状态在源文件中用 `[ ]` / `[x]` 修改；当前预览保留这些标记，不提供点击勾选或回写功能。

| 对象 | 结果 | 后续问题 |
| --- | --- | --- |
| 矩阵 $A$ | 行列式为 $-2$ | 逆矩阵如何表示？ |
| 定积分 $I$ | $1/3$ | 数值积分误差如何变化？ |

### Python 与 Rust 计算片段

```python
a, b, c, d = 1, 2, 3, 4
determinant = a * d - b * c
print(determinant)  # -2
```

```rust
fn main() {
    let [[a, b], [c, d]] = [[1, 2], [3, 4]];
    println!("det(A) = {}", a * d - b * c);
}
```

公式由插件随附的 KaTeX 在本地渲染，安装插件后无需联网加载公式资源，也不需要额外的 TeX 或 Node 环境。
它支持 LaTeX 数学语法的一个子集，适合笔记中的矩阵、积分和对齐公式；完整 LaTeX 文档、宏包和 TikZ 仍需相应的编译流程。
支持范围见 [KaTeX 官方函数列表](https://katex.org/docs/supported.html)。

## 插图与目录

图片路径相对于当前笔记所在目录，例如以下写法引用同级 `images` 文件夹中的图片：

```markdown
![实验结果](images/figure.png)
```

当前预览根目录是笔记所在目录。使用 `../images/figure.png` 等跨上级目录引用时，需要将预览根目录调整到包含这些文件的共同目录；
可通过 `:checkhealth livepreview` 查看当前根目录。目录与 `dynamic_root` 设置见[插件官方说明](https://github.com/brianhuster/live-preview.nvim/blob/a6307fa340ed7c0d96f5c567afc8c991aad94ce0/doc/livepreview.txt)。

## 通过 SSH 预览 Arch 上的笔记

在本机终端建立隧道，将下面的 `user` 和 `arch-host` 换成自己的 SSH 用户名与主机名：

```sh
ssh -L 5500:127.0.0.1:5500 user@arch-host
```

保持此 SSH 连接，在远端 Neovim 打开笔记并启动预览。SSH 会话中不会自动启动远端浏览器；
在本机浏览器打开 Neovim 输出的 `http://127.0.0.1:5500/...` 地址即可。
预览服务只监听本机回环地址，默认端口为 `5500`。

若端口已被占用，先停止预览，在本机或远端对应的 `~/.config/dotfiles-local/nvim.lua` 中设置另一个端口：

```lua
require("livepreview.config").set({ port = 5501 })
```

重新启动 Neovim 后再开启预览；SSH 隧道也要对应改成 `-L 5501:127.0.0.1:5501`。
插件功能及实现见 [live-preview.nvim 官方仓库](https://github.com/brianhuster/live-preview.nvim)。
