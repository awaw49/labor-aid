'use strict';

const LABELS = {
  employer_name: '公司全称', employer_city: '上班城市', start_date: '入职日期', end_date: '离职日期',
  termination_by: '谁提出解除', termination_reason: '解除理由', contract_state: '合同情况',
  avg_wage: '月平均工资', dispute_types: '争议类型', prior_proceeding: '是否走过程序',
  still_employed: '是否在职', claims: '诉求', last_claim_date: '最近一次主张权利',
};
const OPTION_LABELS = {
  termination_by: { employer: '公司提出', employee: '自己辞职', mutual: '协商一致', unknown: '不确定' },
  contract_state: { none: '没签过', one: '签过 1 次', two_plus: '签过 2 次及以上', unknown: '不确定' },
  prior_proceeding: { none: '都没有', arbitration_done: '仲裁过', court_done: '起诉过', settled: '签过协议' },
  still_employed: { yes: '还在职', no: '已离职', unknown: '不确定' },
  dispute_types: { unpaid_wage: '欠薪', termination: '解除', no_contract: '未签合同', overtime: '加班费',
    annual_leave: '年休假', social_insurance: '社保', noncompete: '竞业限制', other: '其他' },
  claims: { compensation_2n: '2N 赔偿', compensation_n: 'N 补偿', double_wage: '二倍工资',
    wage: '补发工资', annual_leave_pay: '年假工资', confirm_relation: '确认劳动关系', unsure: '不确定' },
};
const STATUS = {
  pass: '通过', warn: '需注意', fail: '不满足', out_of_scope: '不适用',
};

const state = {
  sid: null, data: null, report: null, view: 'home',
  multi: new Set(), font: 16, recording: null, audioChunks: [], timer: null, startedAt: 0,
  busy: false,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html !== undefined) n.innerHTML = html; return n; };
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (n) => '¥' + Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 });

async function api(path, body, method = 'POST') {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const res = await fetch(path, opt);
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : data;
    const msg = typeof detail === 'object' ? (detail.message || JSON.stringify(detail)) : String(detail || '请求失败');
    const err = new Error(msg);
    err.payload = detail;
    err.retryable = res.status >= 500 || res.status === 429;
    throw err;
  }
  return data;
}

function toast(msg, ms = 2400) {
  const t = $('#toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

/* ---------------- 路由 ---------------- */
const VIEWS = { home: 'view-home', chat: 'view-chat', report: 'view-report', laws: 'view-laws', settings: 'view-settings' };
const TITLES = { home: '劳动仲裁初步咨询', chat: '咨询', report: '律师意见', laws: '法条库', settings: '设置' };

const historyStack = [];

function go(view, push = true) {
  if (push && state.view !== view) historyStack.push(state.view);
  state.view = view;
  $$('.view').forEach(v => v.classList.toggle('active', v.id === VIEWS[view]));
  $('#composer').hidden = view !== 'chat';
  $('#navBack').hidden = view === 'home';
  $('#navTitle').textContent = TITLES[view];
  window.scrollTo({ top: 0 });
  if (view === 'laws' && !$('#lawList').dataset.loaded) loadLaws();
  if (view === 'settings') loadSettings();
  $('#navBook').style.visibility = view === 'laws' ? 'hidden' : 'visible';
}

window.addEventListener('scroll', () => {
  $('#topbar').classList.toggle('scrolled', window.scrollY > 4);
}, { passive: true });

/* ---------------- 会话 ---------------- */
async function ensureSession() {
  if (state.sid) return;
  const data = await api('/api/session', {});
  state.sid = data.session_id;
  state.data = data;
  renderMessages(data.messages || []);
  updateChrome();
}

async function startChat() {
  go('chat');
  await ensureSession();
}

function updateChrome() {
  const c = state.data?.completeness;
  if (!c) return;

}

/* ---------------- 消息渲染 ---------------- */
function renderMessages(msgs) {
  for (const m of msgs) appendMessage(m);
  scrollBottom();
}

function appendMessage(m) {
  const list = $('#chatList');
  if (m.kind === 'questions') {
    const wrap = el('div', 'msg');
    wrap.dataset.kind = 'questions';
    (m.questions || []).forEach(q => wrap.appendChild(questionCard(q)));
    list.appendChild(wrap);
    return;
  }
  if (m.kind === 'conflict') {
    const c = (state.data?.conflicts || []).find(x => x.slot === m.slot);
    list.appendChild(conflictCard(m, c));
    return;
  }
  if (m.kind === 'offer') {
    const card = el('div', 'offer-card');
    card.innerHTML = `<div class="offer-text">${esc(m.text)}</div>
      <button class="btn btn-primary btn-sm">${esc(m.action || '查看律师意见')}</button>`;
    card.querySelector('button').addEventListener('click', buildReport);
    list.appendChild(card);
    return;
  }
  const node = el('div', 'msg ' + (m.role === 'user' ? 'user' : 'assistant'));
  const bubble = el('div', 'bubble');
  bubble.textContent = m.text || '';
  node.appendChild(bubble);
  list.appendChild(node);
}

function questionCard(q) {
  const card = el('div', 'qcard');
  card.dataset.slot = q.slot;
  const isMulti = !!q.multi || q.type === 'multi';
  card.appendChild(el('div', 'q-title', esc(q.text)));
  if (q.why && q.kind !== 'confirm') card.appendChild(el('div', 'q-why', esc(q.why)));

  const chips = el('div', 'q-chips');
  const options = (q.options || []).slice();
  if (isMulti) options.push({ value: '__done__', label: '选好了' });
  options.forEach(o => {
    const b = el('button', 'chip' + (o.value.startsWith('__') ? ' subtle' : ''), esc(o.label));
    b.dataset.value = o.value;
    chips.appendChild(b);
  });
  if (q.kind === 'confirm') {
    const manual = el('button', 'chip subtle', '不对，我来改');
    manual.dataset.value = '__manual__';
    chips.appendChild(manual);
  }
  card.appendChild(chips);

  const needsInput = q.kind === 'ask' && ['text', 'money', 'date', 'city'].includes(q.type);
  if (needsInput) {
    const row = el('div', 'q-input');
    const input = el('input');
    input.placeholder = q.placeholder || '直接输入';
    if (q.type === 'date') input.inputMode = 'numeric';
    if (q.type === 'money') input.inputMode = 'decimal';
    const btn = el('button', '', '提交');
    row.append(input, btn);
    card.appendChild(row);
    const submit = () => {
      const v = input.value.trim();
      if (!v) return;
      if (q.kind === 'confirm') submitConfirm(q.slot, v); else submitAnswer(q.slot, v);
      card.remove();
    };
    btn.addEventListener('click', submit);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
  }

  chips.addEventListener('click', async (ev) => {
    const b = ev.target.closest('.chip');
    if (!b) return;
    const v = b.dataset.value;
    if (isMulti && !v.startsWith('__')) {
      b.classList.toggle('selected');
      if (state.multi.has(v)) state.multi.delete(v); else state.multi.add(v);
      return;
    }
    if (v === '__done__') {
      const values = [...state.multi];
      state.multi.clear();
      if (!values.length) { toast('至少选一项'); return; }
      card.remove();
      await submitAnswer(q.slot, values);
      return;
    }
    if (v === '__unsure__') { showHelp(card, q); return; }
    if (v === '__skip__') { card.remove(); await submitAnswer(q.slot, '__skip__'); return; }
    if (v === '__manual__') {
      const row = el('div', 'q-input');
      const input = el('input');
      input.placeholder = '填正确的值';
      const btn = el('button', '', '确定');
      row.append(input, btn);
      card.appendChild(row);
      input.focus();
      btn.addEventListener('click', () => { const val = input.value.trim(); if (val) { submitConfirm(q.slot, val); card.remove(); } });
      return;
    }
    if (q.kind === 'confirm') { card.remove(); await submitConfirm(q.slot, v === 'yes' ? null : v); }
    else { card.remove(); await submitAnswer(q.slot, v); }
  });

  card.appendChild(el('div', 'q-skip'));
  return card;
}

function showHelp(card, q) {
  const old = $('.q-help', card);
  if (old) return;
  const box = el('div', 'q-help');
  box.innerHTML = `<b>可以这样查：</b>${esc(q.help || '先空着也行，意见里我会写明这项没问到。')}`;
  const skip = el('button', 'chip subtle', '先空着');
  skip.style.marginTop = '8px';
  skip.addEventListener('click', async () => { card.remove(); await submitAnswer(q.slot, '__skip__'); });
  box.appendChild(skip);
  card.appendChild(box);
}

function conflictCard(m, c) {
  const wrap = el('div', 'msg');
  const box = el('div', 'conflict');
  box.appendChild(el('div', 'c-title', '这里对不上'));
  box.appendChild(el('div', 'c-body', esc(m.text)));
  const actions = el('div', 'c-actions');
  const oldVal = (c && c.old) || '先前的说法';
  const newVal = (c && c.new) || '这次的说法';
  const b1 = el('button', '', '以先前为准'); b1.dataset.value = oldVal;
  const b2 = el('button', '', '以这次为准'); b2.dataset.value = newVal;
  actions.append(b1, b2);
  box.appendChild(actions);
  wrap.appendChild(box);
  actions.addEventListener('click', async (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    box.remove();
    await submitAnswer(m.slot, b.dataset.value);
  });
  return wrap;
}

function scrollBottom() {
  const list = $('#chatList');
  requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }));
  if (list) list.scrollTop = list.scrollHeight;
}

/* ---------------- 提交 ---------------- */
async function submitAnswer(slot, value) {
  if (state.busy) return;
  state.busy = true;
  try {
    const r = await api(`/api/session/${state.sid}/answer`, { slot, value });
    mergeState(r);
    if (r.help) showHelpSheet(r.help);
    renderMessages(r.messages || []);
  } catch (e) { toast(e.message); }
  finally { state.busy = false; }
}

async function submitConfirm(slot, value) {
  if (state.busy) return;
  state.busy = true;
  try {
    const body = value === null || value === undefined || value === '' ? { slot } : { slot, value };
    const r = await api(`/api/session/${state.sid}/confirm`, body);
    mergeState(r);
    renderMessages(r.messages || []);
  } catch (e) { toast(e.message); }
  finally { state.busy = false; }
}

async function sendText(text, source = 'text') {
  if (!text.trim()) return;
  await ensureSession();
  appendMessage({ role: 'user', kind: 'text', text });
  scrollBottom();
  try {
    const r = await apiWithRetry(`/api/session/${state.sid}/text`, { text, source });
    mergeState(r);
    renderMessages(r.messages || []);
  } catch (e) { toast(e.message, 4200); }
}

function mergeState(r) {
  state.data = { ...(state.data || {}), ...r };
  if (r.slots) state.data.slots = r.slots;
  if (r.suspect) state.data.suspect = r.suspect;
  if (r.conflicts) state.data.conflicts = r.conflicts;
  if (r.completeness) state.data.completeness = r.completeness;
  updateChrome();
}

async function apiWithRetry(path, body, tries = 3) {
  let last;
  for (let i = 0; i < tries; i++) {
    try {
      return await api(path, body);
    } catch (e) {
      last = e;
      if (!e.retryable) throw e;
      toast(i === 0 ? '网络抖了一下，正在重试…' : '再试一次…', 1800);
      await new Promise(r => setTimeout(r, 900 * (i + 1)));
    }
  }
  throw last;
}

/* ---------------- 输入栏 ---------------- */
function autoGrow() {
  const t = $('#textInput');
  t.style.height = 'auto';
  t.style.height = Math.min(120, t.scrollHeight) + 'px';
  $('#sendBtn').disabled = !t.value.trim();
}

async function onSend() {
  const t = $('#textInput');
  const v = t.value.trim();
  if (!v) return;
  t.value = ''; autoGrow();
  if (!$('#view-chat').classList.contains('active')) go('chat');   // 从首页直接开口：切到对话视图再发
  await sendText(v);
}

/* 图片 */
async function compressImage(file, maxSide = 1600) {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bmp.width * scale);
  canvas.height = Math.round(bmp.height * scale);
  canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', 0.86));
  return new File([blob], 'photo.jpg', { type: 'image/jpeg' });
}

async function uploadImages(files) {
  if (!files.length) return;
  await ensureSession();
  for (const file of files) {
    appendMessage({ role: 'user', kind: 'image', text: '已发送 1 张照片' });
    const note = el('div', 'msg assistant');
    note.innerHTML = '<div class="bubble plain" style="color:var(--ink-3)">正在看这张材料…</div>';
    $('#chatList').appendChild(note); scrollBottom();
    try {
      const fd = new FormData();
      fd.append('file', await compressImage(file));
      const r = await apiWithRetry(`/api/session/${state.sid}/image`, fd);
      note.remove();
      mergeState(r);
      renderMessages(r.messages || []);
    } catch (e) { note.remove(); toast(e.message); }
  }
}

/* 语音 */
async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
    const rec = new MediaRecorder(stream, { mimeType: mime });
    state.audioChunks = [];
    rec.ondataavailable = e => { if (e.data.size) state.audioChunks.push(e.data); };
    rec.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(state.audioChunks, { type: 'audio/webm' });
      state.audioBlob = blob;
    };
    rec.start();
    state.recording = rec;
    state.startedAt = Date.now();
    $('#voiceOverlay').hidden = false;
    state.timer = setInterval(() => {
      const s = Math.floor((Date.now() - state.startedAt) / 1000);
      $('#voiceTime').textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
      if (s >= 60) finishRecording();
    }, 250);
  } catch (e) { toast('无法使用麦克风，请检查权限'); }
}

function finishRecording() {
  if (!state.recording) return;
  clearInterval(state.timer);
  state.recording.stop();
  state.recording = null;
  $('#voiceOverlay').hidden = true;
  const blob = state.audioBlob;
  if (!blob || blob.size < 1200) { toast('太短了，再多说几句'); return; }
  transcribe(blob);
}

function cancelRecording() {
  if (state.recording) { clearInterval(state.timer); state.recording.stop(); state.recording = null; }
  $('#voiceOverlay').hidden = true;
}

async function transcribe(blob) {
  const toastEl = $('#toast');
  toast('正在转写…', 8000);
  try {
    const fd = new FormData();
    fd.append('file', blob, 'voice.webm');
    const r = await apiWithRetry(`/api/session/${state.sid}/asr`, fd);
    if (!r.transcript) { toast('没听清，再说一次'); return; }
    $('#transcript').value = r.transcript;
    $('#transcriptSheet').hidden = false;
  } catch (e) { toast(e.message, 4000); }
}

/* ---------------- 律师意见 ---------------- */
async function buildReport() {
  if (state.busy) return;
  state.busy = true;
  toast('正在整理意见…', 8000);
  try {
    const rep = await apiWithRetry(`/api/session/${state.sid}/report`, {});
    state.report = rep;
    renderReport(rep);
    go('report');
  } catch (e) {
    const detail = e.payload;
    let hint = '';
    if (detail && detail.missing) hint = detail.message || '还差一点信息，先把下面这些确认一下';
    else if (typeof detail === 'string') hint = detail;
    else if (detail && detail.message) hint = detail.message;
    else hint = e.message;
    toast(hint, 3600);
    const card = el('div', 'offer-card');
    card.innerHTML = `<div class="offer-text">意见没生成出来：${esc(hint)}</div>
      <button class="btn btn-primary btn-sm">再试一次</button>`;
    card.querySelector('button').addEventListener('click', () => { card.remove(); buildReport(); });
    $('#chatList').appendChild(card);
    scrollBottom();
  } finally { state.busy = false; }
}

function statusOf(decision) {
  if (decision === 'cannot' || decision === 'not_recommended') return 'bad';
  if (decision === 'better_alternative') return 'warn';
  return 'ok';
}

function verdictText(label) {
  return String(label || '').replace(/[✅⚠️❌]/g, '').replace(/^\s+/, '').trim();
}

function renderReport(r) {
  const c = r.conclusion;
  const days = c.deadline?.days_left;
  const status = statusOf(c.decision);
  const gateRows = (c.gates || []).map(g => `
    <div class="gate-row">
      <div class="gate-dot ${g.status}">${g.status === 'pass' ? '✓' : '!'}</div>
      <div><b>${esc(g.name.replace('第一层 · ', '').replace('第二层 · ', ''))}</b><span>${esc(g.message)}</span></div>
    </div>`).join('');

  const worthRow = `
    <div class="gate-row">
      <div class="gate-dot ${c.score >= 62 ? 'pass' : c.score >= 45 ? 'warn' : 'fail'}">${c.score >= 62 ? '✓' : '!'}</div>
      <div><b>值不值得去</b><span>综合评分 ${c.score}/100${c.score >= 62 ? '，投入产出比合适' : c.score >= 45 ? '，可以先补材料再决定' : '，目前性价比不高'}</span></div>
    </div>`;

  const reasons = (c.reasons || []).map((x, i) => `
    <div class="reason">
      <div class="reason-n">${i + 1}</div>
      <div><div class="reason-t">${esc(x.text)}</div><div class="cites">${citeChips(x.citations)}</div></div>
    </div>`).join('');

  const calc = (c.calc_items || []).filter(i => i.primary);
  const calcHtml = calc.length ? `
    <div class="section">
      <div class="section-head"><div class="section-title">金额构成</div><div class="section-hint">参考值，非承诺</div></div>
      <div class="card">
        ${calc.map(i => `<div class="mat"><div class="mat-top"><div class="mat-name">${esc(i.label)}</div><div class="mat-name">${money(i.amount)}</div></div><div class="mat-meta"><span>${esc(i.detail)}</span></div></div>`).join('')}
        ${(c.calc_notes || []).map(n => `<div class="mat"><div class="mat-meta"><span>${esc(n)}</span></div></div>`).join('')}
      </div>
    </div>` : '';

  const matList = r.materials || [];
  const materials = matList.map(m => `
    <div class="mat">
      <div class="mat-top">
        <div class="mat-name">${esc(m.name)}</div>
        <div class="mat-state ${m.have ? 'done' : ''}">${m.have ? '已有' : (m.required ? '需准备' : '建议')}</div>
      </div>
      <div class="mat-meta">
        <span><b>用途</b>${esc(m.purpose)}</span>
        <span><b>谁举证</b>${esc(m.burden)}</span>
        <span><b>怎么拿</b>${esc(m.how)}</span>
      </div>
    </div>`).join('');

  const venues = (r.venue || []).map(v => `
    <div class="venue">
      <div class="venue-stage">${esc(v.stage)}</div>
      <div class="venue-name">${esc(v.name)}</div>
      <div class="venue-where">${esc(v.where)}${v.tel ? ` · ${esc(v.tel)}` : ''}</div>
      ${v.note ? `<div class="venue-where" style="color:var(--ink-3)">${esc(v.note)}</div>` : ''}
      <div class="venue-acts">${(v.actions || []).map(actionBtn).join('')}</div>
    </div>`).join('');

  const articles = (r.citations?.articles || []).map(a => `
    <details class="article">
      <summary><span class="a-name">${esc(a.law.replace('中华人民共和国', ''))} ${esc(a.no_cn)}</span><span class="section-hint">展开</span></summary>
      <div class="a-body">${esc(a.text)}<div class="a-src">施行 ${esc(a.effective || '')} · ${esc(a.chapter || '')}</div></div>
    </details>`).join('');

  const cases = (r.citations?.cases || []).map(x => `
    <div class="case">
      <div class="case-t">${esc(x.title)}</div>
      <div class="case-src">${esc(x.source)}</div>
      <div class="case-p"><b>争议焦点</b> ${esc(x.focus)}</div>
      <div class="case-p"><b>裁判要旨</b> ${esc(x.holding)}</div>
      <div class="case-p"><b>可比之处</b> ${esc(x.comparable)}</div>
      <div class="case-p"><b>不能类比</b> ${esc(x.limit)}</div>
      ${x.source_url ? `<div class="cites"><a class="cite" href="${esc(x.source_url)}" target="_blank" rel="noopener">查看官方原文</a></div>` : ''}
    </div>`).join('');

  const confidence = c.confidence || {};
  const confCount = (confidence.from_image || []).length;
  const oralCount = (confidence.from_oral || []).length;

  const openQs = (r.open_questions || []);
  $('#reportBody').innerHTML = `
    <div class="opinion-head">
      <div class="opinion-kicker">初步咨询意见</div>
      <div class="opinion-date">${esc(r.generated_at || '')}${r.preliminary ? ' · 待补充材料后再确认' : ''}</div>
    </div>
    <div class="report-hero ${status === 'warn' ? 'is-warn' : status === 'bad' ? 'is-bad' : ''}">
      <div class="verdict">${esc(verdictText(c.label))}</div>
      <div class="verdict-desc">${esc(c.one_liner)}</div>
      <div class="metrics">
        <div class="metric"><div class="m-v">${c.claim_amount ? money(c.claim_amount) : '待确认'}</div><div class="m-l">可主张金额（参考）</div></div>
        <div class="metric"><div class="m-v ${days !== null && days !== undefined && days <= 60 ? 'hot' : ''}">${days === null || days === undefined ? '未起算' : Math.max(0, days) + ' 天'}</div><div class="m-l">仲裁时效剩余</div></div>
      </div>
      ${(c.decision === 'not_recommended' && r.evidence) ? `<div class="evidence-hint">当前材料证据强度 ${r.evidence.score}/100，补齐后再评估一次更准。</div>` : ''}
      <div class="gate-strip">${gateRows}${worthRow}</div>
    </div>

    <div class="section">
      <div class="section-head"><div class="section-title">为什么是这个结论</div><div class="section-hint">${confCount ? `其中 ${confCount} 项经材料核对` : '依据你确认的口述事实'}</div></div>
      <div class="card">${reasons}</div>
    </div>

    ${openQs.length ? `<div class="section">
      <div class="section-head"><div class="section-title">还需要你补一句的</div><div class="section-hint">影响个别结论</div></div>
      <div class="card card-pad">
        <div class="hint" style="padding:0">${openQs.map(q => esc(q.label)).join('、')}——这几项我还没问到，上面的意见先按已知情况给。</div>
      </div>
    </div>` : ''}

    ${calcHtml}

    <div class="section">
      <div class="section-head"><div class="section-title">要带什么</div><div class="section-hint">${matList.length} 项</div></div>
      <div class="card">
        <div class="card-pad" style="padding-bottom:0"><div class="hint" style="padding:0 0 12px">这是你带去仲裁委交的材料，照着准备就行，不用发给我。</div></div>
        ${materials}
      </div>
    </div>

    <div class="section">
      <div class="section-head"><div class="section-title">去哪儿提交</div><div class="section-hint">按杭州</div></div>
      <div class="card">${venues}</div>
    </div>

    <div class="section">
      <div class="section-head"><div class="section-title">依据的法条</div><div class="section-hint">${(r.citations?.articles || []).length} 条</div></div>
      <div class="card">${articles}</div>
    </div>

    ${cases ? `<div class="section"><div class="section-head"><div class="section-title">类似案件</div><div class="section-hint">仅供参考</div></div><div class="card">${cases}</div></div>` : ''}

    <div class="notice">
      ${esc(r.disclaimer)}
      <div style="margin-top:10px"><button class="link-btn" id="backToChat">情况有变化？回去接着补</button></div>
      <div style="margin-top:8px">${(r.hotlines || []).map(h => `<a href="tel:${esc(h.tel)}" class="cite">${esc(h.label)} ${esc(h.tel)}</a>`).join(' ')}</div>
    </div>`;

  $('#backToChat')?.addEventListener('click', () => go('chat'));
  $$('#reportBody [data-copy]').forEach(b => b.addEventListener('click', () => copy(b.dataset.copy)));
  $$('#reportBody .cite[data-law]').forEach(b => b.addEventListener('click', () => showArticle(b.dataset.law)));
}

function citeChips(ids) {
  return (ids || []).map(id => {
    const [law, no] = id.split(':');
    const name = (state.report?.citations?.articles || []).find(a => a.id === id)?.law || '';
    const short = name ? name.replace('中华人民共和国', '').replace('最高人民法院关于审理劳动争议案件适用法律问题的解释', '司法解释') : lawShort(law);
    return `<button class="cite" data-law="${esc(id)}">${esc(short)} 第 ${esc(no)} 条</button>`;
  }).join('');
}

function lawShort(id) {
  return ({ laodonghetongfa: '劳动合同法', tiaojiezhongcai: '调解仲裁法', laodongfa: '劳动法',
    nianxiujia: '年休假条例', shebaofa: '社会保险法', jiancha: '监察条例',
    sfjs1: '司法解释（一）', sfjs2: '司法解释（二）' })[id] || id;
}

function actionBtn(a) {
  if (a.kind === 'tel') return `<a class="act primary" href="tel:${esc(a.value)}"><svg class="ic-sm"><use href="#i-phone"/></svg>${esc(a.label)}</a>`;
  if (a.kind === 'url' || a.kind === 'map') return `<a class="act" href="${esc(a.value)}" target="_blank" rel="noopener"><svg class="ic-sm"><use href="#i-external"/></svg>${esc(a.label)}</a>`;
  if (a.kind === 'copy') return `<button class="act" data-copy="${esc(a.value)}">${esc(a.label)}</button>`;
  return `<span class="act">${esc(a.label)}</span>`;
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast('已复制'); }
  catch { toast('复制失败，请长按选择'); }
}

/* 导出 */
async function exportImage() {
  if (!state.report) return;
  toast('正在生成长图…', 5000);
  const canvas = await html2canvas($('#reportBody'), { backgroundColor: '#F6F5F1', scale: 2, useCORS: true });
  const a = document.createElement('a');
  a.href = canvas.toDataURL('image/png');
  a.download = '劳动仲裁咨询意见.png';
  a.click();
  toast('已保存到相册/下载');
}

async function exportPdf() {
  if (!state.report) return;
  toast('正在生成 PDF…', 6000);
  const canvas = await html2canvas($('#reportBody'), { backgroundColor: '#ffffff', scale: 2, useCORS: true });
  const img = canvas.toDataURL('image/jpeg', 0.94);
  const { jsPDF } = window.jspdf;
  const pdf = new jsPDF({ unit: 'mm', format: 'a4' });
  const pw = 210, ph = 297, margin = 8;
  const iw = pw - margin * 2;
  const ih = canvas.height * iw / canvas.width;
  let left = ih, pos = margin;
  pdf.addImage(img, 'JPEG', margin, pos, iw, ih);
  left -= (ph - margin * 2);
  while (left > 0) {
    pos = margin - (ih - left);
    pdf.addPage();
    pdf.addImage(img, 'JPEG', margin, pos, iw, ih);
    left -= (ph - margin * 2);
  }
  pdf.save('劳动仲裁咨询意见.pdf');
  toast('PDF 已保存');
}

function speak() {
  if (!state.report) return;
  const c = state.report.conclusion;
  const text = [verdictText(c.label), c.one_liner, ...(c.reasons || []).map((x, i) => `第${i + 1}，${x.text}`)].join('。');
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'zh-CN'; u.rate = 1;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
  toast('正在朗读');
}

async function rebuttal() {
  openSheet('公司会怎么反驳你', '<div class="hint">正在准备…</div>');
  try {
    const r = await api(`/api/session/${state.sid}/rebuttal`, {});
    $('#sheetBody').innerHTML = (r.items || []).map((x, i) => `
      <div class="case">
        <div class="case-t">${i + 1}. ${esc(x.attack)}</div>
        <div class="case-p"><b>对方会拿</b> ${esc(x.evidence)}</div>
        <div class="case-p"><b>你可以说</b> ${esc(x.reply)}</div>
        <div class="cites">${(x.citations || []).map(id => `<button class="cite" data-law="${esc(id)}">${esc(lawShort(id.split(':')[0]))} 第 ${esc(id.split(':')[1])} 条</button>`).join('')}</div>
      </div>`).join('') || '<div class="hint">暂无内容</div>';
    $$('#sheetBody .cite[data-law]').forEach(b => b.addEventListener('click', () => showArticle(b.dataset.law)));
  } catch (e) { $('#sheetBody').innerHTML = `<div class="hint">${esc(e.message)}</div>`; }
}

/* ---------------- 法条 ---------------- */
async function loadLaws() {
  try {
    const r = await api('/api/laws', undefined, 'GET');
    const groups = {};
    (r.laws || []).forEach(l => {
      const k = l.category || '法律';
      (groups[k] = groups[k] || []).push(l);
    });
    $('#lawList').innerHTML = Object.entries(groups).map(([cat, laws]) => `
      <div class="law-group-title">${esc(cat)}</div>
      ${laws.map(l => `<button class="law-item" data-lawid="${esc(l.id)}">
        <div><div class="l-n">${esc(l.title)}</div><div class="l-c">施行 ${esc(l.effective || '')}</div></div>
        <div class="l-r">${l.count} 条</div></button>`).join('')}`).join('');
    $$('#lawList [data-lawid]').forEach(b => b.addEventListener('click', () => openLaw(b.dataset.lawid)));
    $('#lawList').dataset.loaded = '1';
  } catch (e) { toast(e.message); }
}

async function openLaw(id) {
  openSheet('', '<div class="hint">加载中…</div>');
  const law = await api(`/api/laws/${id}`, undefined, 'GET');
  $('#sheetTitle').textContent = law.title;
  $('#sheetBody').innerHTML = `
    <div class="hint" style="padding:0 0 10px">${esc(law.flavor)}<br>施行 ${esc(law.effective || '')} · ${esc(law.issuer)}</div>
    ${law.articles.map(a => `<div class="article-item"><div class="a-no">${esc(a.no_cn)}</div><div class="a-txt" style="-webkit-line-clamp:6">${esc(a.text)}</div></div>`).join('')}`;
}

async function searchLaws() {
  const q = $('#lawSearch').value.trim();
  if (!q) { loadLaws(); return; }
  const r = await api(`/api/search?q=${encodeURIComponent(q)}&limit=15`, undefined, 'GET');
  $('#lawList').innerHTML = (r.results || []).length ? r.results.map(a => `
    <button class="article-item" data-law="${esc(a.id)}" style="text-align:left;width:100%">
      <div class="a-no">${esc(a.law)} ${esc(a.no_cn)}</div>
      <div class="a-txt">${esc(a.text)}</div>
    </button>`).join('') : '<div class="law-empty">没找到相关条文，换个说法试试</div>';
  $$('#lawList [data-law]').forEach(b => b.addEventListener('click', () => showArticle(b.dataset.law)));
}

async function showArticle(id) {
  openSheet('', '<div class="hint">加载中…</div>');
  try {
    const a = await api(`/api/law/${encodeURIComponent(id)}`, undefined, 'GET');
    $('#sheetTitle').textContent = `${a.law} ${a.no_cn}`;
    $('#sheetBody').innerHTML = `
      <div style="font-size:.92em;line-height:1.75;white-space:pre-wrap">${esc(a.text)}</div>
      <div class="hint" style="padding:12px 0 0">施行 ${esc(a.effective || '')} · ${esc(a.chapter || '')}<br>
        在官方数据库搜索《${esc(a.law)}》即可核对原文与版本。</div>
      <div class="sheet-actions">
        <button class="btn btn-ghost" id="copyArticle">复制原文</button>
        <a class="btn btn-primary" href="https://flk.npc.gov.cn/" target="_blank" rel="noopener">打开官方数据库</a>
      </div>`;
    $('#copyArticle').addEventListener('click', () => copy(a.text));
  } catch (e) { $('#sheetBody').innerHTML = `<div class="hint">${esc(e.message)}</div>`; }
}

/* ---------------- 设置 ---------------- */
async function loadSettings() {
  const s = await api('/api/settings', undefined, 'GET');
  $('#setBase').value = s.base_url || '';
  $('#setKey').value = '';
  $('#setKey').placeholder = s.api_key || '未设置';
  $('#setTextModel').value = s.text_model || '';
  $('#setVisionModel').value = s.vision_model || '';
  $('#connResult').textContent = '';
}

async function saveSettings() {
  const key = $('#setKey').value.trim();
  const body = {
    base_url: $('#setBase').value.trim(),
    text_model: $('#setTextModel').value.trim(),
    vision_model: $('#setVisionModel').value.trim(),
  };
  if (key) body.api_key = key;
  try {
    const s = await api('/api/settings', body);
    $('#setKey').value = '';
    $('#setKey').placeholder = s.api_key;
    $('#connResult').textContent = '已保存';
    toast('设置已保存');
  } catch (e) { $('#connResult').textContent = e.message; }
}

async function testConn() {
  $('#connResult').textContent = '正在测试…';
  try {
    const r = await api('/api/settings/test', {
      base_url: $('#setBase').value.trim(),
      api_key: $('#setKey').value.trim() || undefined,
      model: $('#setTextModel').value.trim(),
    });
    $('#connResult').textContent = r.ok
      ? `连接正常，模型回复：${r.reply || ''}`
      : `连接失败：${r.chat_error || r.models_error || '未知原因'}`;
  } catch (e) { $('#connResult').textContent = '测试失败：' + e.message; }
}

async function resetSettings() {
  await api('/api/settings/reset', {});
  await loadSettings();
  toast('已恢复默认');
}

/* ---------------- 弹层 ---------------- */
function openSheet(title, html) {
  $('#sheetTitle').textContent = title;
  $('#sheetBody').innerHTML = html;
  $('#sheet').hidden = false;
}

function closeSheets() {
  $$('.sheet').forEach(s => { s.hidden = true; });
}

function showHelpSheet(help) {
  openSheet('可以这样查', `
    <div style="font-size:.9em;line-height:1.7">${esc(help.help || '先空着也可以，意见里我会写明这项没问到。')}</div>
    <div class="sheet-actions"><button class="btn btn-primary" data-close>知道了</button></div>`);
}

/* ---------------- 初始化 ---------------- */
function bind() {
  $('#startBtn').addEventListener('click', startChat);
  $('#navBack').addEventListener('click', () => {
    const prev = historyStack.pop();
    go(prev || 'home', false);
  });
  $('#navBook').addEventListener('click', () => go('laws'));
  $('#homeBook').addEventListener('click', (e) => { e.preventDefault(); go('laws'); });
  $('#navSettings').addEventListener('click', () => go('settings'));
  $('#homeSettings').addEventListener('click', (e) => { e.preventDefault(); go('settings'); });

  $('#sendBtn').addEventListener('click', onSend);
  $('#textInput').addEventListener('input', autoGrow);
  $('#textInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && window.innerWidth > 720) { e.preventDefault(); onSend(); }
  });

  $('#attachBtn').addEventListener('click', () => { $('#attachSheet').hidden = false; });
  $('#pickCamera').addEventListener('click', () => { closeSheets(); $('#cameraInput').click(); });
  $('#pickAlbum').addEventListener('click', () => { closeSheets(); $('#albumInput').click(); });
  $('#cameraInput').addEventListener('change', e => { uploadImages([...e.target.files]); e.target.value = ''; });
  $('#albumInput').addEventListener('change', e => { uploadImages([...e.target.files]); e.target.value = ''; });

  $('#micBtn').addEventListener('click', startRecording);
  $('#voiceDone').addEventListener('click', finishRecording);
  $('#voiceCancel').addEventListener('click', cancelRecording);
  $('#transcriptSend').addEventListener('click', async () => {
    const text = $('#transcript').value.trim();
    $('#transcriptSheet').hidden = true;
    if (text) await sendText(text, 'speech');
  });
  $('#transcriptRetry').addEventListener('click', () => { $('#transcriptSheet').hidden = true; startRecording(); });

  $('#exportImg').addEventListener('click', exportImage);
  $('#exportPdf').addEventListener('click', exportPdf);
  $('#speakBtn').addEventListener('click', speak);
  $('#rebutBtn').addEventListener('click', rebuttal);

  $('#lawSearch').addEventListener('keydown', e => { if (e.key === 'Enter') searchLaws(); });
  $('#lawSearch').addEventListener('input', e => { if (!e.target.value.trim()) loadLaws(); });

  $('#saveSettings').addEventListener('click', saveSettings);
  $('#testConn').addEventListener('click', testConn);
  $('#resetSettings').addEventListener('click', resetSettings);

  $$('#fontSeg .seg').forEach(b => b.addEventListener('click', () => {
    $$('#fontSeg .seg').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    document.documentElement.style.setProperty('--fs', b.dataset.size + 'px');
    state.font = Number(b.dataset.size);
    localStorage.setItem('font', b.dataset.size);
  }));

  $$('[data-close]').forEach(b => b.addEventListener('click', closeSheets));
  $$('.sheet').forEach(s => s.addEventListener('click', e => { if (e.target === s) closeSheets(); }));

  window.addEventListener('popstate', () => {
    const prev = historyStack.pop();
    go(prev || 'home', false);
    history.pushState({}, '');
  });
}

function restorePrefs() {
  const f = localStorage.getItem('font');
  if (f) {
    document.documentElement.style.setProperty('--fs', f + 'px');
    $$('#fontSeg .seg').forEach(x => x.classList.toggle('active', x.dataset.size === f));
  }
}

async function init() {
  bind();
  restorePrefs();
  history.pushState({}, '');
  $('#navBack').hidden = true;
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
}

document.addEventListener('DOMContentLoaded', init);
