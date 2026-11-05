// 从国家法律法规数据库（flk.npc.gov.cn）抓取法律法规官方文本的元数据与文件地址
import { chromium } from '/Users/curing/.npm-global/lib/node_modules/@playwright/cli/node_modules/playwright-core/index.mjs';
import fs from 'fs';

const CHROME = '/Users/curing/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing';
const titles = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const outFile = process.argv[3];
let out = fs.existsSync(outFile) ? JSON.parse(fs.readFileSync(outFile, 'utf8')) : {};

const b = await chromium.launch({headless: true, executablePath: CHROME});
const p = await b.newPage();

async function ready() {
  await p.goto('https://flk.npc.gov.cn/search', {waitUntil: 'domcontentloaded', timeout: 60000});
  await p.waitForTimeout(2500);
}
async function jget(path, retries = 4) {
  for (let i = 0; i < retries; i++) {
    let txt = '';
    try {
      txt = await p.evaluate(async (path) => (await fetch(path)).text(), path);
    } catch (e) { txt = ''; }
    if (txt.trim().startsWith('{')) return JSON.parse(txt);
    await ready();
  }
  throw new Error('blocked: ' + path);
}
const search = (q) => jget('/law-search/search/list?' + '');
async function searchTitle(q) {
  const body = JSON.stringify({searchRange:1,sxrq:[],gbrq:[],searchType:2,sxx:[],gbrqYear:[],flfgCodeId:[],zdjgCodeId:[],searchContent:q,xgzlSearch:false,orderByParam:{order:"-1",sort:""},pageNum:1,pageSize:20});
  return await jgetSpecial('/law-search/search/list', body);
}
async function jgetSpecial(path, body, retries = 4) {
  for (let i = 0; i < retries; i++) {
    let txt = '';
    try {
      txt = await p.evaluate(async ({path, body}) => {
        const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body});
        return await r.text();
      }, {path, body});
    } catch (e) { txt = ''; }
    if (txt.trim().startsWith('{')) return JSON.parse(txt);
    await ready();
  }
  throw new Error('blocked: ' + path);
}

await ready();
for (const t of titles) {
  if (out[t.id] && out[t.id].ossUrl) { console.log('SKIP', t.id); continue; }
  try {
    const res = await searchTitle(t.title);
    const clean = s => s.replace(/<[^>]+>/g, '');
    const rows = (res.rows || []).map(r => ({...r, clean: clean(r.title)}));
    const pick = rows.find(r => r.clean === t.title && r.sxx === 3)
              || rows.find(r => r.clean === t.title)
              || rows.find(r => r.clean.startsWith(t.title))
              || rows[0];
    if (!pick) { console.log('MISS', t.title); continue; }
    const d = await jget('/law-search/search/flfgDetails?bbbs=' + pick.bbbs);
    const data = d.data || {};
    const word = data.ossFile?.ossWordPath;
    let signed = null, dl = null;
    if (word) {
      const l = await jget('/law-search/amazonFile/previewLink?filePath=' + encodeURIComponent(word));
      signed = l.data?.url || null;
      var gen = signed && new URL(signed).searchParams.get('file');
      dl = null;
      if (gen) {
        const genUrl = gen.replace(/^http:\/\/172\.16\.220\.27:38080/, 'https://flk.npc.gov.cn');
        const j = await jget(genUrl);
        dl = j.file?.download_url || null;
      }
    }
    out[t.id] = {query: t.title, hit: pick.clean, bbbs: pick.bbbs, flxz: data.flxz, zdjg: data.zdjgName,
                 gbrq: data.gbrq, sxrq: data.sxrq, sxx: data.sxx, wordPath: word, signedUrl: signed, ossUrl: dl, downloadUrl: gen ? gen.replace(/^http:\/\/172\.16\.220\.27:38080/, 'https://flk.npc.gov.cn') : null};
    fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
    console.log(t.id, '->', pick.clean, data.gbrq, data.sxrq, 'docx:', !!dl);
  } catch (e) {
    console.log('FAIL', t.id, e.message.slice(0, 80));
    await ready();
  }
  await p.waitForTimeout(600);
}
await b.close();
console.log('WROTE', outFile);
