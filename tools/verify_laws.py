"""法条库 ↔ 权威源全文逐条比对器（目标 1：真实完整）。

用法: python tools/verify_laws.py 源页.html law_id [law_id ...]
源页抓取自 gov.cn 系转载/最高法公报；比对时归一空白与全半角标点，只暴露真差异。
"""
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUNCT = str.maketrans({"（": "(", "）": ")", "：": ":", "；": ";", "，": ",", "。": ".", "、": ",",
                       "“": '"', "”": '"', "‘": "'", "’": "'", "！": "!", "？": "?", "　": " "})

def norm(s):
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"【[^】]*】", "", s)
    return s.translate(PUNCT)

def page_text(path):
    raw = open(path, encoding="utf-8", errors="ignore").read()
    raw = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", raw))
    body = re.sub(r"[ \t\u3000]+", "", text)
    return norm(re.sub(r"\s+", "", re.sub(r"【[^】]*】", "", body)))

def to_cn(n):
    d = "零一二三四五六七八九"
    if n <= 10: return {1:"一",2:"二",3:"三",4:"四",5:"五",6:"六",7:"七",8:"八",9:"九",10:"十"}[n]
    if n < 20: return "十" + d[n % 10]
    if n < 100:
        t, o = n // 10, n % 10
        return d[t] + "十" + (d[o] if o else "")
    h, r = n // 100, n % 100          # 100-999：一百零一 / 一百一十 / 一百二十三
    out = d[h] + "百"
    if r == 0: return out
    if r < 10: return out + "零" + d[r]
    t, o = r // 10, r % 10
    return out + ("一" if t == 1 else d[t]) + "十" + (d[o] if o else "")

def run(html_path, law_ids):
    pg = page_text(html_path)
    for lid in law_ids:
        core = json.load(open(f"{ROOT}/data/laws/{lid}.json", encoding="utf-8"))
        items = core if isinstance(core, list) else core.get("articles", [])
        misses = []
        for a in items:
            t = norm(a["text"])
            if t not in pg:      # 条文全文必须逐字出现在权威源页里
                misses.append(a["no"])
        ok = len(items) - len(misses)
        print(f"{lid:14s} {ok}/{len(items)} 逐字命中{'，未命中: ' + str(misses) if misses else ' ✓'}")
        return misses

def whitelist_ids():
    """从内核源码抽引用白名单（法条 id 集合）。"""
    import glob
    ids = set()
    for f in glob.glob(os.path.join(ROOT, "app", "**", "*.py"), recursive=True):
        src = open(f, encoding="utf-8").read()
        ids |= set(re.findall(r'"([a-z0-9]+:\d+)"', src))
    return ids


if __name__ == "__main__":
    args = sys.argv[1:]
    only_wl = "--whitelist" in args
    args = [a for a in args if a != "--whitelist"]
    pg = args[0] if args else None
    laws = args[1:]
    if only_wl and pg:
        wl = whitelist_ids()
        by_law = {}
        for cid in wl:
            law, no = cid.split(":")
            by_law.setdefault(law, set()).add(int(no))
        pg_text = page_text(pg)
        total_bad = []
        for law, nos in sorted(by_law.items()):
            core = json.load(open(f"{ROOT}/data/laws/{law}.json", encoding="utf-8"))
            items = core if isinstance(core, list) else core.get("articles", [])
            for a in items:
                if a["no"] in nos and norm(a["text"]) not in pg_text:
                    total_bad.append(f"{law}:{a['no']}")
        print(f"白名单 {sum(len(v) for v in by_law.values())} 条 → 未命中: {total_bad if total_bad else '无 ✓'}")
    else:
        run(pg, laws)
