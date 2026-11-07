# 考研手册 2026 · 经验分享篇（在线阅读）

在线地址：https://kysc-xyzx.github.io/kaoyan-handbook-2026/

这个仓库只放网页（`index.html`）。手册内容都在腾讯云 COS 上：

```
https://hysinoss-1334037784.cos.ap-shanghai.myqcloud.com/public/kaoyan-handbook-2026/
├── kaoyan-handbook-2026.pdf   「下载 PDF」的文件
├── pages/p-001.jpg …          在线阅读的页面图片
└── manifest.js                标题、页数、更新时间
```

存储桶本身是私有的，只有上面这些文件单独设为公共读。

## 更换 PDF

在 Mac 上运行一条命令，网页和下载链接一起更新，GitHub 上不用改任何东西：

```bash
python3 scripts/update-handbook.py "/path/to/新版手册.pdf"
```

需要 `poppler`、`rclone`（`brew install poppler rclone`）和 PicList 里的腾讯云 COS 配置。新内容刷新网页即可看到。

网页标题取自 PDF 的「标题」属性（WPS：文件 → 属性），没有时用文件名。

浏览量和下载量不在网页上显示，由私有后台从 COS 访问日志统计。
