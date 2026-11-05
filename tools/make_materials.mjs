import { chromium } from '/Users/curing/.npm-global/lib/node_modules/@playwright/cli/node_modules/playwright-core/index.mjs';
import fs from 'fs';
const CHROME = '/Users/curing/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing';
const b = await chromium.launch({headless:true, executablePath: CHROME});
const p = await b.newPage({viewport:{width:900,height:1180}, deviceScaleFactor:2});
const base = `font-family:'PingFang SC','Songti SC',serif;color:#1b1b1b;`;
const docs = {
 'offer_letter': `<div style="padding:56px 64px;background:#fff;min-height:1180px;${base}">
   <h1 style="text-align:center;letter-spacing:6px;font-size:30px;margin:0 0 6px">录用通知书</h1>
   <div style="text-align:center;color:#666;font-size:14px;margin-bottom:34px">杭州云帆科技有限公司</div>
   <p style="font-size:18px;line-height:2">张三先生：</p>
   <p style="font-size:18px;line-height:2;text-indent:2em">经面试与综合评估，我公司决定录用您担任<b>运营专员</b>岗位。现将有关事项通知如下：</p>
   <table style="width:100%;border-collapse:collapse;font-size:17px;margin:18px 0">
     <tr><td style="border:1px solid #ddd;padding:11px 14px;width:34%;background:#fafafa">入职日期</td><td style="border:1px solid #ddd;padding:11px 14px">2025 年 6 月 1 日</td></tr>
     <tr><td style="border:1px solid #ddd;padding:11px 14px;background:#fafafa">岗位</td><td style="border:1px solid #ddd;padding:11px 14px">运营专员</td></tr>
     <tr><td style="border:1px solid #ddd;padding:11px 14px;background:#fafafa">工作地点</td><td style="border:1px solid #ddd;padding:11px 14px">杭州市滨江区</td></tr>
     <tr><td style="border:1px solid #ddd;padding:11px 14px;background:#fafafa">月工资</td><td style="border:1px solid #ddd;padding:11px 14px">应发 8,600 元（基本工资 5,000 元 + 绩效 2,600 元 + 补贴 1,000 元）</td></tr>
     <tr><td style="border:1px solid #ddd;padding:11px 14px;background:#fafafa">试用期</td><td style="border:1px solid #ddd;padding:11px 14px">2 个月</td></tr>
   </table>
   <p style="font-size:17px;line-height:2;text-indent:2em">请您于入职当日携带身份证原件及复印件办理入职手续。</p>
   <div style="margin-top:70px;text-align:right;font-size:18px;line-height:2">杭州云帆科技有限公司（盖章）<br>2025 年 5 月 20 日</div>
 </div>`,
 'payslip': `<div style="padding:40px 40px;background:#fff;min-height:1180px;${base}">
   <div style="border:1px solid #ccc;padding:22px">
     <div style="text-align:center;font-size:26px;letter-spacing:4px;margin-bottom:6px">工资条</div>
     <div style="text-align:center;color:#666;font-size:14px;margin-bottom:18px">杭州云帆科技有限公司 · 2026 年 2 月</div>
     <div style="font-size:16px;line-height:1.9;display:flex;justify-content:space-between"><span>姓名：张三</span><span>部门：运营部</span><span>工号：YF-0231</span></div>
     <table style="width:100%;border-collapse:collapse;font-size:16px;margin-top:14px">
       <tr><td style="border:1px solid #ccc;padding:9px 12px;background:#f7f7f7">项目</td><td style="border:1px solid #ccc;padding:9px 12px;background:#f7f7f7;text-align:right">金额（元）</td></tr>
       <tr><td style="border:1px solid #ccc;padding:9px 12px">基本工资</td><td style="border:1px solid #ccc;padding:9px 12px;text-align:right">5,000.00</td></tr>
       <tr><td style="border:1px solid #ccc;padding:9px 12px">绩效工资</td><td style="border:1px solid #ccc;padding:9px 12px;text-align:right">2,600.00</td></tr>
       <tr><td style="border:1px solid #ccc;padding:9px 12px">交通餐补</td><td style="border:1px solid #ccc;padding:9px 12px;text-align:right">1,000.00</td></tr>
       <tr><td style="border:1px solid #ccc;padding:9px 12px">应发合计</td><td style="border:1px solid #ccc;padding:9px 12px;text-align:right"><b>8,600.00</b></td></tr>
       <tr><td style="border:1px solid #ccc;padding:9px 12px">养老/医疗/失业（个人）</td><td style="border:1px solid #ccc;padding:9px 12px;text-align:right">-512.20</td></tr>
       <tr><td style="border:1px solid #ccc;padding:9px 12px">个人所得税</td><td style="border:1px solid #ccc;padding:9px 12px;text-align:right">-96.00</td></tr>
       <tr><td style="border:1px solid #ccc;padding:9px 12px">实发合计</td><td style="border:1px solid #ccc;padding:9px 12px;text-align:right"><b>7,991.80</b></td></tr>
     </table>
     <div style="font-size:14px;color:#666;margin-top:14px">发放日期：2026-03-10　制表：财务部</div>
   </div>
 </div>`,
 'wechat': `<div style="background:#ededed;min-height:1180px;padding:0;${base}">
   <div style="background:#f7f7f7;padding:16px;text-align:center;font-size:18px;border-bottom:1px solid #ddd">王经理（HR）</div>
   <div style="padding:20px 16px">
     <div style="text-align:center;color:#999;font-size:13px;margin-bottom:18px">2026年3月14日 18:42</div>
     <div style="display:flex;gap:10px;margin-bottom:16px"><div style="width:40px;height:40px;border-radius:6px;background:#4b6cb7;color:#fff;display:grid;place-items:center;font-size:14px">王</div>
       <div style="background:#fff;padding:12px 14px;border-radius:8px;max-width:70%;font-size:17px;line-height:1.6">张三，公司业务调整，你这个岗位取消了，明天不用来了。</div></div>
     <div style="display:flex;gap:10px;margin-bottom:16px;justify-content:flex-end">
       <div style="background:#95ec69;padding:12px 14px;border-radius:8px;max-width:70%;font-size:17px;line-height:1.6">那工资和赔偿怎么算？我合同也一直没签。</div></div>
     <div style="display:flex;gap:10px;margin-bottom:16px"><div style="width:40px;height:40px;border-radius:6px;background:#4b6cb7;color:#fff;display:grid;place-items:center;font-size:14px">王</div>
       <div style="background:#fff;padding:12px 14px;border-radius:8px;max-width:70%;font-size:17px;line-height:1.6">工资结到 3 月 15 号，其他的按公司规定来。</div></div>
     <div style="display:flex;gap:10px"><div style="width:40px;height:40px;border-radius:6px;background:#4b6cb7;color:#fff;display:grid;place-items:center;font-size:14px">王</div>
       <div style="background:#fff;padding:12px 14px;border-radius:8px;max-width:70%;font-size:17px;line-height:1.6">明天来办下交接，把工牌交了。</div></div>
   </div>
 </div>`,
 'bank_flow': `<div style="padding:34px 30px;background:#fff;min-height:1180px;${base}">
   <div style="font-size:22px;font-weight:600;margin-bottom:4px">个人账户交易明细</div>
   <div style="color:#666;font-size:14px;margin-bottom:18px">查询期间：2025-12-01 至 2026-03-31　户名：张三</div>
   <table style="width:100%;border-collapse:collapse;font-size:15px">
     <tr style="background:#f4f4f4"><td style="border:1px solid #ddd;padding:8px">交易日期</td><td style="border:1px solid #ddd;padding:8px">对方户名</td><td style="border:1px solid #ddd;padding:8px">摘要</td><td style="border:1px solid #ddd;padding:8px;text-align:right">金额</td></tr>
     <tr><td style="border:1px solid #ddd;padding:8px">2025-12-10</td><td style="border:1px solid #ddd;padding:8px">陈某某</td><td style="border:1px solid #ddd;padding:8px">转账 工资</td><td style="border:1px solid #ddd;padding:8px;text-align:right">8,600.00</td></tr>
     <tr><td style="border:1px solid #ddd;padding:8px">2026-01-09</td><td style="border:1px solid #ddd;padding:8px">陈某某</td><td style="border:1px solid #ddd;padding:8px">转账 工资</td><td style="border:1px solid #ddd;padding:8px;text-align:right">8,600.00</td></tr>
     <tr><td style="border:1px solid #ddd;padding:8px">2026-02-10</td><td style="border:1px solid #ddd;padding:8px">陈某某</td><td style="border:1px solid #ddd;padding:8px">转账 工资</td><td style="border:1px solid #ddd;padding:8px;text-align:right">8,600.00</td></tr>
     <tr><td style="border:1px solid #ddd;padding:8px">2026-03-10</td><td style="border:1px solid #ddd;padding:8px">陈某某</td><td style="border:1px solid #ddd;padding:8px">转账 工资</td><td style="border:1px solid #ddd;padding:8px;text-align:right">7,991.80</td></tr>
   </table>
   <div style="color:#888;font-size:13px;margin-top:16px">注：对方为个人账户，非公司对公账户。</div>
 </div>`
};
for (const [name, html] of Object.entries(docs)) {
  await p.setContent(`<html><body style="margin:0;background:#fff">${html}</body></html>`);
  await p.screenshot({path:`data/materials/${name}.png`, fullPage:true});
  console.log('made', name);
}
await b.close();
