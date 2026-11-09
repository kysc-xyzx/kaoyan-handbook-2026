# 考研手册 2026 · 经验分享篇（在线阅读）

在线地址：https://kysc-xyzx.github.io/kaoyan-handbook-2026/ （需要访问密码）

这个仓库只放阅读页（`index.html`）和发布脚本，不含手册内容。正文、图片地址和 PDF 地址都用访问密码加密后放在腾讯云 COS 的 `manifest.js` 里，由浏览器输入密码后解密。

## 更新手册

在 Mac 上运行，GitHub 上不用改任何东西：

```bash
python3 scripts/update-handbook.py "/path/新版手册.docx" "/path/新版手册.pdf"
```

需要 `pandoc`、`node`、`rclone` 和 PicList 里的腾讯云 COS 配置。访问密码保存在 Mac 钥匙串，加 `--new-password` 可以换一个新密码。

浏览量和下载量不在网页上显示，由私有后台从 COS 访问日志统计。
