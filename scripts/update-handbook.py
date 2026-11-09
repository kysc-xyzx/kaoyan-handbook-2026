#!/usr/bin/env python3
"""Publish a new handbook to the password-protected online reader (Tencent COS).

Converts the Word file to article HTML with pandoc, uploads its images and the
PDF to an unguessable folder, encrypts the article with the access password and
uploads it as manifest.js. The web page at
https://kysc-xyzx.github.io/kaoyan-handbook-2026/ decrypts it in the browser,
so neither GitHub nor the public manifest ever holds readable content, the
password, or the image and PDF addresses.

Runs on the Mac: needs pandoc, node, rclone (brew install pandoc node rclone)
and the Tencent COS config saved in PicList. The password and the folder name
live in the login keychain; the first run creates them. Show the password with:

    security find-generic-password -a kaoyan-handbook -s kysc-handbook-password -w

Usage:
    python3 更新手册.py "/path/新版手册.docx" "/path/新版手册.pdf"
    python3 更新手册.py --new-password "/path/新版手册.docx" "/path/新版手册.pdf"
"""
import datetime
import hashlib
import html
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.parse

PREFIX = "public/kaoyan-handbook-2026"
PICLIST = "~/Library/Application Support/PicList/data.json"
KEYCHAIN_ACCOUNT = "kaoyan-handbook"
PASSWORD_SERVICE = "kysc-handbook-password"
TOKEN_SERVICE = "kysc-handbook-token"
PBKDF2_ITERATIONS = 1_000_000
# Letters and digits without the look-alikes i, l, o, 0, 1. The page lowercases input.
PASSWORD_LETTERS = "abcdefghjkmnpqrstuvwxyz"
PASSWORD_DIGITS = "23456789"
PASSWORD_LENGTH = 8

FRONT_TITLES = {"版权声明", "作者名单", "序", "免责声明"}
TITLE = "华中科技大学光学与电子信息学院考研手册（2026年版）·经验分享篇"

ENCRYPT_JS = r"""
const c = require('crypto');
let s = '';
process.stdin.on('data', d => s += d).on('end', () => {
  const {password, text, iter} = JSON.parse(s);
  const salt = c.randomBytes(16), iv = c.randomBytes(12);
  const key = c.pbkdf2Sync(password, salt, iter, 32, 'sha256');
  const h = c.createCipheriv('aes-256-gcm', key, iv);
  const ct = Buffer.concat([h.update(text, 'utf8'), h.final(), h.getAuthTag()]);
  process.stdout.write(JSON.stringify({iter, salt: salt.toString('base64'),
                                       iv: iv.toString('base64'), ct: ct.toString('base64')}));
});
"""


def keychain_get(service):
    r = subprocess.run(["security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", service, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def keychain_set(service, value):
    subprocess.run(["security", "add-generic-password", "-U", "-a", KEYCHAIN_ACCOUNT, "-s", service, "-w", value],
                   check=True)


def new_password():
    """Eight characters, at least one letter and one digit."""
    while True:
        p = "".join(secrets.choice(PASSWORD_LETTERS + PASSWORD_DIGITS) for _ in range(PASSWORD_LENGTH))
        if set(p) & set(PASSWORD_LETTERS) and set(p) & set(PASSWORD_DIGITS):
            return p


def encrypt(password, text):
    payload = json.dumps({"password": password.strip().lower(), "text": text, "iter": PBKDF2_ITERATIONS})
    out = subprocess.run(["node", "-e", ENCRYPT_JS], input=payload, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def plain(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def board_list(table):
    """The editorial-board tables are layout grids: role in column 1, names after it."""
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        cells = [plain(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if not cells:
            continue
        names = [c for c in cells[1:] if c]
        if cells[0]:
            rows.append((cells[0], names))
        elif rows:
            rows[-1][1].extend(names)
    body = "".join(f"<dt>{html.escape(r)}</dt><dd>{''.join(f'<span>{html.escape(n)}</span>' for n in ns)}</dd>"
                   for r, ns in rows)
    return f'<dl class="board">{body}</dl>'


def clean_table(table):
    table = table.replace(' style="text-align: left;"', "")
    return f'<div class="tbl">{table}</div>'


def image_tag(tag, urls):
    src = re.search(r'src="([^"]+)"', tag)[1]
    size = re.search(r'width:([\d.]+)in;height:([\d.]+)in', tag)
    alt = re.search(r'alt="([^"]*)"', tag)
    dims = f' width="{round(float(size[1]) * 150)}" height="{round(float(size[2]) * 150)}"' if size else ""
    return (f'<img src="{urls[os.path.basename(src)]}"{dims} alt="{alt[1] if alt else ""}" '
            'loading="lazy" decoding="async">')


def slug(text, seen):
    base = re.sub(r"[^\w一-鿿]+", "", text) or "section"
    sid, n = base, 1
    while sid in seen:
        n += 1
        sid = f"{base}-{n}"
    seen.add(sid)
    return sid


def is_numbered_heading(text, next_text):
    m = re.match(r"^(\d+(?:\.\d+)?)\.?\s*[一-鿿]", text)
    if not m or len(text) > 16 or re.search(r"[，。！；、]", text):
        return False
    if len(next_text) >= 28 and not re.match(r"\d+\.\D", next_text):
        return True
    return bool(re.match(re.escape(m[1]) + r"\.\d", next_text))


def build_article(pandoc_html, urls):
    """Turn pandoc's flat HTML into the blog article: cover, sections, summaries, sub-headings."""
    src = re.sub(r"<table.*?</table>",
                 lambda m: (clean_table(m[0]) if "<thead>" in m[0] or "<caption>" in m[0] else board_list(m[0])),
                 pandoc_html, flags=re.S)
    src = re.sub(r"<img\b[^>]*>", lambda m: image_tag(m[0], urls), src)
    src = re.sub(r"</?u>", "", src)
    src = re.sub(r'<a href="(https?:[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', src)
    src = re.sub(r"<figure>\s*(<img[^>]*>)\s*<figcaption[^>]*><p>(.*?)</p></figcaption>\s*</figure>",
                 r"<figure>\1<figcaption>\2</figcaption></figure>", src, flags=re.S)
    # Keep a table or figure on one logical line so the walk below sees whole blocks.
    src = re.sub(r"<(div class=\"tbl\"|figure)>.*?</(div|figure)>",
                 lambda m: m[0].replace("\n", ""), src, flags=re.S)
    lines = [l for l in src.split("\n") if l.strip() and l.strip() != "<p></p>"]

    # Cover: leading logo and photo, then bold title lines, up to the editorial-board heading.
    cover_imgs, cover_text, i = [], [], 0
    while i < len(lines):
        l = lines[i]
        if "<img" in l:
            cover_imgs.append(re.search(r"<img[^>]*>", l)[0].replace(' loading="lazy"', ""))
        else:
            t = plain(l)
            if "考研手册（" in t and "年版" in t and "经验" not in t:
                break
            cover_text.append(t)
        i += 1
    while len(cover_text) < 4:
        cover_text.append("")
    logo = cover_imgs[0] if cover_imgs else ""
    photo = cover_imgs[1] if len(cover_imgs) > 1 else ""
    out = [f'<header class="cover"><div class="logo">{logo}</div><h1>{cover_text[0]}</h1>'
           f'<p class="sub">{cover_text[1]}</p>{photo}'
           f'<p class="org">{cover_text[2]}<span>{cover_text[3]}</span></p></header>',
           '<nav id="toc" aria-label="目录"></nav>']

    seen = set()
    def heading(level, text):
        out.append(f'<h{level} id="{slug(text, seen)}">{html.escape(text)}</h{level}>')

    heading(2, "编委会")
    i += 1  # the long book-title line the board heading replaces
    in_ai = in_article = False

    def close_ai():
        nonlocal in_ai
        if in_ai:
            out.append("</aside>")
            in_ai = False

    while i < len(lines):
        l = lines[i].strip()
        t = plain(l)
        next_t = plain(lines[i + 1]) if i + 1 < len(lines) else ""
        i += 1
        if re.match(r'^<p><a href="#[^"]+">.*<span>\d+</span></a></p>$', l) or t == "目录":
            continue
        m = re.match(r"^<h([12])\b[^>]*>(.*)</h\1>$", l)
        if m:
            close_ai()
            in_article = m[1] == "2"
            heading(int(m[1]) + 1, plain(m[2]))
            continue
        if l.startswith("<p>") and t in FRONT_TITLES:
            heading(2, t)
            continue
        bold_only = re.match(r"^<p><strong>([^<]*)</strong></p>$", l)
        if bold_only and t == "【AI总结】":
            close_ai()
            out.append('<aside class="ai"><div class="label">AI 总结</div>')
            in_ai = True
            continue
        if bold_only and t == "【作者正文】":
            close_ai()
            out.append('<p class="part">作者正文</p>')
            continue
        if in_ai:
            out.append(f"<p>{bold_only[1]}</p>" if bold_only and len(t) > 30 else l)
            continue
        if bold_only and t.startswith("【") and t.endswith("】"):
            out.append(f'<p class="byline">{html.escape(t[1:-1])}</p>')
            continue
        if bold_only and len(t) <= 20 and t != "" and in_article:
            heading(4, t.rstrip("：:"))
            continue
        if bold_only and len(t) > 40:
            out.append(f'<p class="note">{bold_only[1]}</p>')
            continue
        if in_article and l.startswith("<p>") and "<" not in l[3:-4] and is_numbered_heading(t, next_t):
            heading(4, t)
            continue
        out.append(l)
    close_ai()
    return "\n".join(out)


def convert(docx, workdir):
    media = os.path.join(workdir, "media_root")
    page = subprocess.run(["pandoc", docx, "-f", "docx", "-t", "html5", "--wrap=none", f"--extract-media={media}"],
                          capture_output=True, text=True, check=True).stdout
    return page, os.path.join(media, "media")


def hashed_names(media_dir):
    names = {}
    for f in sorted(os.listdir(media_dir)):
        digest = hashlib.sha256(open(os.path.join(media_dir, f), "rb").read()).hexdigest()[:16]
        names[f] = digest + os.path.splitext(f)[1].lower()
    return names


def main():
    args = sys.argv[1:]
    rotate = "--new-password" in args
    args = [a for a in args if a != "--new-password"]
    if len(args) != 2 or not args[0].lower().endswith(".docx") or not args[1].lower().endswith(".pdf"):
        sys.exit(__doc__)
    docx, pdf = map(os.path.abspath, args)
    for f in (docx, pdf):
        if not os.path.isfile(f):
            sys.exit(f"找不到文件：{f}")

    cfg = json.load(open(os.path.expanduser(PICLIST)))["picBed"]["tcyun"]
    bucket, area = cfg["bucket"], cfg["area"]
    env = dict(os.environ,
               RCLONE_CONFIG_COS_TYPE="s3",
               RCLONE_CONFIG_COS_PROVIDER="TencentCOS",
               RCLONE_CONFIG_COS_ACCESS_KEY_ID=cfg["secretId"],
               RCLONE_CONFIG_COS_SECRET_ACCESS_KEY=cfg["secretKey"],
               RCLONE_CONFIG_COS_ENDPOINT=f"cos.{area}.myqcloud.com")

    def rclone(*a):
        subprocess.run(["rclone", *a, "--s3-acl", "public-read"], env=env, check=True)

    password = keychain_get(PASSWORD_SERVICE)
    if rotate or not password:
        password = new_password()
        keychain_set(PASSWORD_SERVICE, password)
        print(f"新访问密码：{password}")
    token = keychain_get(TOKEN_SERVICE)
    if not token:
        token = secrets.token_urlsafe(18).replace("-", "x").replace("_", "y")
        keychain_set(TOKEN_SERVICE, token)

    base = f"https://{bucket}.cos.{area}.myqcloud.com/{PREFIX}/{token}"
    pdf_key = f"{PREFIX}/{token}/kaoyan-handbook-2026.pdf"
    filename = os.path.basename(pdf)

    with tempfile.TemporaryDirectory() as tmp:
        print("转换 Word…")
        page, media_dir = convert(docx, tmp)
        names = hashed_names(media_dir)
        urls = {f: f"{base}/img/{n}" for f, n in names.items()}
        article = build_article(page, urls)

        print("上传图片…")
        up = os.path.join(tmp, "img")
        os.mkdir(up)
        for f, n in names.items():
            os.rename(os.path.join(media_dir, f), os.path.join(up, n))
        rclone("copy", up, f"cos:{bucket}/{PREFIX}/{token}/img", "--transfers", "8",
               "--header-upload", "Cache-Control: public, max-age=31536000")

        print("上传 PDF…")
        rclone("copyto", pdf, f"cos:{bucket}/{pdf_key}",
               "--header-upload", "Content-Type: application/pdf",
               "--header-upload", "Content-Disposition: attachment; filename*=UTF-8''"
               + urllib.parse.quote(filename),
               "--header-upload", "Cache-Control: no-cache")

        updated = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
                   .strftime("%Y-%m-%d %H:%M"))  # Beijing time; the Mac's own zone may differ
        content = {"title": TITLE, "file": filename, "size": os.path.getsize(pdf), "updated": updated,
                   "pdf": f"{base}/kaoyan-handbook-2026.pdf", "html": article}
        print("加密并上传正文…")
        sealed = encrypt(password, json.dumps(content, ensure_ascii=False))
        mpath = os.path.join(tmp, "manifest.js")
        with open(mpath, "w", encoding="utf-8") as f:
            f.write("window.HANDBOOK = " + json.dumps(sealed) + ";\n")
        rclone("copyto", mpath, f"cos:{bucket}/{PREFIX}/manifest.js",
               "--header-upload", "Content-Type: application/javascript; charset=utf-8",
               "--header-upload", "Cache-Control: no-cache")

    print(f"\n完成：更新于 {updated}")
    print("在线阅读：https://kysc-xyzx.github.io/kaoyan-handbook-2026/")


if __name__ == "__main__":
    main()
