# 将 flk 官方 docx 解析为"条"级结构化法条库
import json
import os
import re

from docx import Document

CN = '零一二三四五六七八九十百'
ART = re.compile(r'^第([' + CN + r']+)条[\s　]*(.*)$')
CHAP = re.compile(r'^第([' + CN + r']+)章[\s　]*(.*)$')
SECT = re.compile(r'^第([' + CN + r']+)节[\s　]*(.*)$')
def cn2int(s):
    d = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if s == '十': return 10
    if '十' in s:
        a, _, b = s.partition('十')
        return (d[a] if a else 1) * 10 + (d[b] if b else 0)
    if '百' in s:
        a, _, b = s.partition('百')
        return (d[a] if a else 1) * 100 + (cn2int(b) if b else 0)
    v = 0
    for ch in s: v = v * 10 + d[ch]
    return v

meta = json.load(open('data/raw/flk_meta.json', encoding='utf-8'))
outdir = 'data/laws'; os.makedirs(outdir, exist_ok=True)
index = []
for key, m in meta.items():
    doc = Document(f'data/raw/docx/{key}.docx')
    paras = [p.text.replace('\u3000', ' ').strip() for p in doc.paragraphs]
    paras = [p for p in paras if p]
    title = paras[0]
    flavor = next((p for p in paras[:6] if '通过' in p or '修正' in p or '公布' in p), '')
    articles, chapter, section, i = [], '', '', 0
    while i < len(paras):
        t = paras[i]
        c = CHAP.match(t)
        s = SECT.match(t)
        if c: chapter = t; section = ''; i += 1; continue
        if s: section = t; i += 1; continue
        a = ART.match(t)
        if a:
            num = cn2int(a.group(1))
            body = [a.group(2).strip()] if a.group(2).strip() else []
            j = i + 1
            while j < len(paras) and not ART.match(paras[j]) and not CHAP.match(paras[j]) and not SECT.match(paras[j]):
                body.append(paras[j]); j += 1
            text = '\n'.join(body).strip()
            if text:
                articles.append({
                    'no': num, 'no_cn': '第' + a.group(1) + '条',
                    'text': text, 'chapter': chapter, 'section': section,
                })
            i = j; continue
        i += 1
    seen, uniq = set(), []
    for a in articles:
        if a['no'] in seen: continue
        seen.add(a['no']); uniq.append(a)
    uniq.sort(key=lambda a: a['no'])
    law = {
        'id': key, 'title': m['hit'], 'title_full': title, 'flavor': flavor,
        'category': m['flxz'], 'issuer': m['zdjg'],
        'promulgated': m['gbrq'], 'effective': m['sxrq'],
        'source': f"https://flk.npc.gov.cn/detail?id={m['bbbs']}",
        'source_name': '国家法律法规数据库（全国人大常委会办公厅）',
        'fetched_at': '2026-11-03',
        'articles': uniq,
    }
    json.dump(law, open(f'{outdir}/{key}.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    index.append({'id': key, 'title': law['title'], 'count': len(uniq), 'effective': m['sxrq'] or m['gbrq']})
    print(f"{key:16s} {len(uniq):3d} 条  {law['title']}")
json.dump(index, open(f'{outdir}/index.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('TOTAL articles', sum(x['count'] for x in index))
