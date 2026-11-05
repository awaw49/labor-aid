import json
import os
import subprocess
import time
import urllib.parse

meta = json.load(open('data/raw/flk_meta.json', encoding='utf-8'))
os.makedirs('data/raw/docx', exist_ok=True)
for k, v in meta.items():
    dst = f'data/raw/docx/{k}.docx'
    if os.path.exists(dst) and os.path.getsize(dst) > 2000:
        print('skip', k); continue
    signed = v.get('signedUrl')
    if not signed:
        print('no signed', k); continue
    gen = urllib.parse.parse_qs(urllib.parse.urlparse(signed).query).get('file', [None])[0]
    gen = gen.replace('http://172.16.220.27:38080', 'https://flk.npc.gov.cn')
    j = None
    for attempt in range(5):
        out = subprocess.run(['curl','-s','-m','30',gen,'-H','User-Agent: Mozilla/5.0'], capture_output=True, text=True).stdout
        try:
            j = json.loads(out); break
        except Exception:
            time.sleep(2)
    if not j:
        print('gen failed', k, out[:120]); continue
    dl = j['file']['download_url']
    r = subprocess.run(['curl','-s','-m','60','--resolve','flkoss.obs-bj2-internal.cucloud.cn:80:111.202.93.152','-o',dst,'-w','%{http_code}',dl], capture_output=True, text=True)
    print(k, r.stdout, os.path.getsize(dst) if os.path.exists(dst) else 0)
