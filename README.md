```markdown
# bilim4s2mp4

> 一键批量转化 B站缓存视频为 MP4 的本地工具。

Termux 部署

1. 环境与权限准备
打开 Termux，依次执行以下命令：
apt update && apt install python3 ffmpeg -y
termux-setup-storage
termux-wake-lock
```
*(注：申请存储权限时请点击允许)*

2. 获取源码
进入手机内部存储并克隆项目：
```bash
cd ~/storage/shared
git clone https://github.com/a17437/bilim4s2mp4.git
cd bilim4s2mp4
```

3. 开始转换
准备文件： 找到你的 B站缓存目录（通常位于 Android/data/tv.danmaku.bili/download）。
移动缓存： 将里面纯数字命名的缓存文件夹，复制或移动到本项目的 from 目录下（即 内部存储/bilim4s2mp4/from/）。
运行脚本： 在 Termux 中输入以下命令开始合并：
```bash
python3 main.py
```

💡 注意事项
* **防杀后台：** 转换期间请保持 Termux 在前台运行，并保持屏幕常亮。
* **成功标识：** 看到“结束啦!恭喜!!!”即代表完成，文件保存在 `out` 目录。
* **目录冲突：** 如果提示 `out` 目录已存在，请确认无误后执行 `rm -rf out` 删除旧目录再重试。
