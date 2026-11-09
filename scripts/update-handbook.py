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

# The timeline figures, shown on the web as real elements instead of the pictures in the Word file.
# Keyed by the sha256 prefix of the picture they replace, so a changed picture in a new Word file
# is shown as a picture (with a warning) rather than silently replaced by outdated dates here.
# Rows: (kind, date, title, detail, references). Kinds: n national, u HUST or the school, w unpublished.
# A plain string between groups is a "status as of" marker.
TIMELINES = {
    "df6040cb9306eff6": {
        "notes": ["仅收录教育部、研招网、华中科技大学研究生院及光电学院正式发布、可在官网查到的节点，按时间先后等距排列（不按真实时长）。",
                  "适用 2026 年硕士研究生招生考试（2025 年 12 月初试、2026 年秋季入学）。右侧编号对应图下来源表。"],
        "groups": [
            ("报名阶段（2025 年 6—11 月）", [
                ("u", "2025-06-05", "光电学院预告调整 839 初试大纲", "《波动光学与激光原理》（839）考试大纲调整，附件为新版大纲", "[1]"),
                ("n", "2025-09-24", "教育部印发 2026 年硕士招生工作管理规定", "报名、初试、复试、调剂、录取的全国统一规则均以此为准", "[2]"),
                ("u", "2025-10-09", "华科发布 2026 年硕士招生简章及专业目录", "同日发布考试科目调整汇总", "[3]"),
                ("n", "2025-10-10 — 10-13", "网上预报名", "每日 9:00—22:00，预报名信息有效，正式报名期间无需重复填报", "[4]"),
                ("n", "2025-10-16 — 10-27", "正式网上报名", "每日 9:00—22:00，登录研招网填报并网上缴费", "[4]"),
                ("u", "2025-10-31 — 11-05", "网上确认（华科报考点 4202）", "10-31 09:00 开始，首次上传截止 11-04 17:00，补充上传截止 11-05 17:00；其他报考点以当地公告为准", "[5]"),
            ]),
            ("初试（2025 年 12 月）", [
                ("u", "考前约 10 天", "研招网下载打印准考证", "A4 纸打印；12-22 网报系统关闭后无法再下载", "[5]"),
                ("n", "2025-12-20 — 12-21", "全国统一初试", "20 日上午政治/管综、下午外语；21 日上午业务课（一）、14:00 起业务课（二）", "[6]"),
            ]),
            ("成绩与复试（2026 年 2—3 月）", [
                ("u", "2026-02-28", "华科公布初试成绩", "09:00 起在华科研招系统查询；复查申请 03-01 9:00 — 03-03 17:00", "[7]"),
                ("n", "2026-02-28", "教育部公布国家线", "复试初试成绩基本要求；各招生单位在此基础上自定复试线", "[8]"),
                ("u", "2026-03-15", "光电学院公布复试理论测试范围", "光学工程、光电信息工程：《光电技术》《激光技术》各占 50%；通信工程：《通信原理》；其余专业见细则", "[9]"),
                ("u", "2026-03-16", "华科公布复试基本分数要求、院系复试线及复试细则", "复试报到系统 14:00 开放，网上报到并上传材料", "[10][11]"),
                ("u", "2026-03-20 — 03-21", "光电学院复试报到与复试", "全校一志愿集中复试为 03-21 — 03-22，线下现场复试；光电学院按院系安排为 03-20 — 03-21", "[10]"),
            ]),
            ("调剂与录取（2026 年 3—6 月）", [
                ("n", "2026-03-27", "调剂意向采集系统开通", "可查询、填报调剂意向，不等于正式调剂志愿", "[8]"),
                ("n", "2026-04-08", "调剂服务系统开通", "每次开放不少于 12 小时，志愿锁定不超过 36 小时；华科各院系调剂方案同日起陆续发布", "[8][12][13]"),
                ("n", "2026-04-30 前", "招生单位录取工作一般完成", "管理规定原文：录取工作一般应在录取当年 4 月底前完成", "[14]"),
                ("u", "2026-06-29", "华科发布 2026 年研究生新生入学须知", "凭录取通知书、身份证件按规定日期报到", "[15]"),
            ]),
        ],
        "foot": "核对日期 2026-11-02，具体以当年正式通知为准。2027 年考研见图1-2。",
    },
    "2d41724f9cb77cd6": {
        "notes": ["适用 2027 年硕士研究生招生考试（2026 年 12 月初试、2027 年秋季入学），截至 2026-11-02。",
                  "实心与空心节点均已由官方发布；灰色节点尚未公布，括号内为 2026 年同类节点的官方日期，仅供预估，出处见图1-1。"],
        "groups": [
            ("报名阶段（2026 年 9—10 月）", [
                ("n", "2026-09-24", "教育部印发 2027 年硕士招生工作管理规定", "预报名、正式报名、初试日期及调剂、录取规则均已明确", "[1]"),
                ("u", "2026-10-08", "华科发布 2027 年硕士招生简章及专业目录", "同日发布考试科目调整汇总，光电学院（182）不在调整之列", "[2][3]"),
                ("n", "2026-10-09 — 10-12", "网上预报名", "每日 9:00—22:00，具体安排由各省级教育招生考试机构公布", "[1]"),
                ("n", "2026-10-15 — 10-24", "正式网上报名", "每日 9:00—22:00，登录研招网填报并网上缴费", "[1]"),
                ("u", "2026-10-26 — 10-31", "报名材料审核（华科报考点 4202）", "10-26 09:00 开始审核；首次审核截止 10-30 12:00，补充上传截止 10-31 12:00；其他报考点以当地公告为准", "[4]"),
            ]),
            "截至 2026-11-02",
            ("初试（2026 年 12 月）", [
                ("u", "考前约 10 天", "研招网下载打印准考证", "A4 纸打印；12-20 网报系统关闭后无法再下载；华科报考点 12-18 下午前可查考场", "[4]"),
                ("n", "2026-12-19 — 12-20", "全国统一初试", "19 日上午政治/管综、下午外语；20 日上午业务课（一）、14:00 起业务课（二）", "[1]"),
            ]),
            ("成绩与复试（2027 年 2—3 月，日期待公布）", [
                ("w", "待公布", "公布初试成绩", "（2026 年：02-28 华科公布，03-01 — 03-03 复查）", ""),
                ("w", "待公布", "教育部公布国家线", "（2026 年：02-28）", ""),
                ("w", "待公布", "光电学院复试测试范围；华科复试线及复试细则", "（2026 年：03-15 测试范围，03-16 复试线、细则，14:00 开放报到）", ""),
                ("w", "待公布", "光电学院复试", "（2026 年：光电学院 03-20 — 03-21，全校集中 03-21 — 03-22）", ""),
            ]),
            ("调剂与录取（2027 年 3—4 月）", [
                ("w", "待公布", "调剂意向采集系统、调剂服务系统开通", "（2026 年：03-27、04-08）已定规则：每次开放不少于 12 小时，志愿锁定不超过 36 小时", "[1]"),
                ("n", "2027-04-30 前", "招生单位录取工作一般完成", "管理规定原文：录取工作一般应在录取当年 4 月底前完成", "[1]"),
            ]),
        ],
        "foot": "各节点以教育部、研招网及招生单位后续正式通知为准；新通知发布后应更新本图。",
    },
}
TIMELINE_KINDS = {"n": "全国统一节点（教育部 / 研招网）", "u": "华科 / 光电学院节点", "w": "尚未公布"}

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


def source_links(table):
    """Reference number to official URL, from the source table under a timeline."""
    found = (re.search(r'<td[^>]*>(?:<p>)?\[(\d+)\].*?<a href="([^"]+)"', row, re.S)
             for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table or "", re.S))
    return {m[1]: m[2] for m in found if m}


def timeline_html(data, caption, links):
    """One line of HTML for a timeline figure; the page styles it for light, dark and phone widths."""
    e = lambda s: html.escape(s, quote=False)

    def ref_links(refs):
        out = []
        for n in re.findall(r"\d+", refs):
            if n in links:
                out.append(f'<a href="{links[n]}" target="_blank" rel="noopener">[{n}]</a>')
            else:
                print(f"注意：「{plain(caption)}」的来源表里没有编号 [{n}] 的链接。")
                out.append(f"[{n}]")
        return "".join(out)

    parts, kinds = [f"<figcaption>{caption}</figcaption>"], []
    parts += [f'<p class="tl-note">{e(n)}</p>' for n in data["notes"]]
    for group in data["groups"]:
        if isinstance(group, str):
            parts.append(f'<p class="tl-now"><span>{e(group)}</span></p>')
            continue
        head, rows = group
        kinds += [r[0] for r in rows]
        pending = " tl-pending" if all(r[0] == "w" for r in rows) else ""
        parts.append(f'<div class="tl-head{pending}">{e(head)}</div><ol class="tl-list">')
        for kind, date, title, detail, refs in rows:
            parts.append(f'<li class="tl-{kind}"><span class="tl-date">{e(date)}</span><span class="tl-dot"></span>'
                         f'<div class="tl-body"><strong>{e(title)}</strong><span>{e(detail)}</span></div>'
                         f'<span class="tl-ref">{ref_links(refs)}</span></li>')
        parts.append("</ol>")
    legend = "".join(f'<li class="tl-{k}"><span class="tl-dot"></span>{e(v)}</li>'
                     for k, v in TIMELINE_KINDS.items() if k in kinds)
    parts.append(f'<ul class="tl-legend">{legend}</ul><p class="tl-foot">{e(data["foot"])}</p>')
    return f'<figure class="tl">{"".join(parts)}</figure>'


def native_timelines(article):
    """Swap the timeline pictures for real elements; a picture we have no data for stays a picture."""
    def swap(m):
        if m[1] in TIMELINES:
            return timeline_html(TIMELINES[m[1]], m[2], source_links(m[3])) + (m[3] or "")
        if "时间轴" in m[2]:
            print(f"注意：「{plain(m[2])}」的图片和脚本里的 TIMELINES 对不上，网页暂时显示图片。"
                  f"若时间轴有更新，请改 TIMELINES 并把键换成 {m[1]}。")
        return m[0]
    return re.sub(r'<figure><img src="[^"]*?([0-9a-f]{16})\.\w+"[^>]*><figcaption>(.*?)</figcaption></figure>'
                  r'(\s*<div class="tbl">.*?</table></div>)?', swap, article, flags=re.S)


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
        if l.startswith("<p>") and re.match(r"第[一二三四五六七八九十]+章：", t):  # author list: not indented in Word
            l = '<p class="flush">' + l[3:]
        out.append(l)
    close_ai()
    return native_timelines("\n".join(out))


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
            if n in article:  # pictures replaced by native elements are not published
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
