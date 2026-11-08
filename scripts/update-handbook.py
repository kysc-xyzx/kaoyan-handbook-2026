#!/usr/bin/env python3
"""Publish a new handbook PDF to the online reader (Tencent COS).

Renders every page of the PDF to JPEG and uploads, under
public/kaoyan-handbook-2026/ in the PicList bucket (object ACL public-read;
the bucket itself stays private):

    kaoyan-handbook-2026.pdf   the download file (download name = local file name)
    pages/p-001.jpg ...        page images shown by the web page
    manifest.js                title / page count / update time, uploaded last

The web page at https://kysc-xyzx.github.io/kaoyan-handbook-2026/ reads
everything from COS, so nothing on GitHub has to change.

Runs on the Mac: needs poppler (brew install poppler), rclone
(brew install rclone) and the Tencent COS config saved in PicList.
Credentials reach rclone through environment variables only.

Usage: python3 更新手册.py "/path/to/新版手册.pdf"
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

PREFIX = "public/kaoyan-handbook-2026"
PDF_KEY = f"{PREFIX}/kaoyan-handbook-2026.pdf"
PICLIST = "~/Library/Application Support/PicList/data.json"
DPI = "200"  # page images ~1654 px wide: sharp on high-DPI screens

if len(sys.argv) != 2 or not sys.argv[1].lower().endswith(".pdf"):
    sys.exit(__doc__)
src = os.path.abspath(sys.argv[1])
if not os.path.isfile(src):
    sys.exit(f"找不到文件：{src}")

cfg = json.load(open(os.path.expanduser(PICLIST)))["picBed"]["tcyun"]
bucket, area = cfg["bucket"], cfg["area"]
base_url = f"https://{bucket}.cos.{area}.myqcloud.com/{PREFIX}"
env = dict(os.environ,
           RCLONE_CONFIG_COS_TYPE="s3",
           RCLONE_CONFIG_COS_PROVIDER="TencentCOS",
           RCLONE_CONFIG_COS_ACCESS_KEY_ID=cfg["secretId"],
           RCLONE_CONFIG_COS_SECRET_ACCESS_KEY=cfg["secretKey"],
           RCLONE_CONFIG_COS_ENDPOINT=f"cos.{area}.myqcloud.com")


def rclone(*args):
    subprocess.run(["rclone", *args, "--s3-acl", "public-read"], env=env, check=True)


info = subprocess.run(["pdfinfo", src], capture_output=True, text=True, check=True).stdout
field = lambda name: (re.search(rf"^{name}:\s*(.*)$", info, re.M) or [None, ""])[1].strip()
pages = int(field("Pages"))
m = re.match(r"([\d.]+) x ([\d.]+)", field("Page size"))
width, height = (round(float(m[1])), round(float(m[2]))) if m else (595, 842)
filename = os.path.basename(src)

with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "pages")
    os.mkdir(out)
    print(f"渲染 {pages} 页…")
    subprocess.run(["pdftoppm", "-r", DPI, "-jpeg", "-jpegopt", "quality=80,progressive=y",
                    src, os.path.join(out, "p")], check=True)
    for f in os.listdir(out):  # pdftoppm pads by page count; normalize to p-001.jpg
        n = int(re.search(r"(\d+)\.jpg$", f)[1])
        os.rename(os.path.join(out, f), os.path.join(out, f"p-{n:03d}.jpg"))

    print("上传页面图片…")
    rclone("copy", out, f"cos:{bucket}/{PREFIX}/pages", "--transfers", "8",
           "--header-upload", "Content-Type: image/jpeg",
           "--header-upload", "Cache-Control: public, max-age=31536000", "--progress")

    print("上传 PDF…")
    rclone("copyto", src, f"cos:{bucket}/{PDF_KEY}",
           "--header-upload", "Content-Type: application/pdf",
           "--header-upload", "Content-Disposition: attachment; filename*=UTF-8''"
           + urllib.parse.quote(filename),
           "--header-upload", "Cache-Control: no-cache")

    manifest = {
        "title": field("Title") or os.path.splitext(filename)[0],
        "file": filename,
        "pages": pages,
        "width": width,
        "height": height,
        "size": os.path.getsize(src),
        "updated": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
                   .strftime("%Y-%m-%d %H:%M"),  # Beijing time; the Mac's own zone may differ
        "base": base_url,
        "pdf": f"{base_url}/kaoyan-handbook-2026.pdf",
    }
    mpath = os.path.join(tmp, "manifest.js")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("window.HANDBOOK = " + json.dumps(manifest, ensure_ascii=False) + ";\n")
    rclone("copyto", mpath, f"cos:{bucket}/{PREFIX}/manifest.js",
           "--header-upload", "Content-Type: application/javascript; charset=utf-8",
           "--header-upload", "Cache-Control: no-cache")

print(f"\n完成：{manifest['title']}，共 {pages} 页，更新于 {manifest['updated']}")
print("在线阅读：https://kysc-xyzx.github.io/kaoyan-handbook-2026/")
print(f"下载链接：{manifest['pdf']}")
