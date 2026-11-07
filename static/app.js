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

function sessionGone(e) { return !!(e && e.sessionGone); }

async function api(path, body, method = 'POST') {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 200000);   // 桥路上限 180s + 余量
  let res;
  try { res = await fetch(path, { ...opt, signal: ctrl.signal }); }
  catch (e) { if (e.name === 'AbortError') throw Object.assign(new Error('等太久没有回应——服务可能没起来'), { payload: { message: '等太久没有回应——服务可能没起来', retryable: true } }); throw e; }
  finally { clearTimeout(timer); }
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : data;
    const msg = typeof detail === 'object' ? (detail.message || JSON.stringify(detail)) : String(detail || '请求失败');
    const err = new Error(msg);
    err.payload = detail;
    err.retryable = res.status >= 500 || res.status === 429;
    // 服务端内存会话被清（重启/过期）：标记后由调用方自愈开新会话
    if (res.status === 404 && /session not found/.test(msg) && state.sid) {
      err.sessionGone = true;
      state.sid = null;
      try { sessionStorage.removeItem('sid'); } catch (_) {}
    }
    throw err;
  }
  return data;
}

window.addEventListener('error', (e) => { try { toast('页面出了点小状况：' + (e.message || '').slice(0, 60)); } catch (_) {} });
window.addEventListener('unhandledrejection', () => { /* 网络类 rejection 已在各调用点 toast，这里兜底防白屏 */ });

function applyTheme() {
  const t = localStorage.getItem('theme') || 'auto';
  document.documentElement.dataset.theme = t === 'auto' ? '' : t;
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
  try { if (push) location.hash = '#/' + view; } catch (_) {}
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
  let prev = null;
  try { prev = sessionStorage.getItem('sid'); } catch (_) {}
  if (prev) {
    // 刷新后先续旧会话：对话还在，用户不丢上下文；服务端已清就照常新建
    try {
      const data = await api(`/api/session/${prev}`, undefined, 'GET');
      state.sid = data.session_id;
      state.data = data;
      renderMessages(data.messages || []);
      updateChrome();
      return;
    } catch (_) {}
  }
  const data = await api('/api/session', {});
  state.sid = data.session_id;
  try { sessionStorage.setItem('sid', state.sid); } catch (_) {}
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
  const remain = Math.max(0, c.total - c.done);
  document.title = remain > 0 ? `咨询 · 还差 ${remain} 项 — 劳动仲裁初步咨询` : '劳动仲裁初步咨询';

}

/* ---------------- 消息渲染 ---------------- */
function renderMessages(msgs) {
  for (const m of msgs) appendMessage(m);
  scrollBottom();
}

function appendMessage(m) {
  const list = $('#chatList');
  if (m.kind === 'questions') {
    const qs = (m.questions || []).filter(q => (q.text || '').trim());
    if (!qs.length) return;                       // 空 questions 消息一律不渲染
    const wrap = el('div', 'msg');
    wrap.dataset.kind = 'questions';
    if (m.bundle && qs.length > 1) wrap.appendChild(bundleCard(qs));
    else qs.forEach(q => wrap.appendChild(questionCard(q)));
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
  const bubble = el('div', 'bubble' + (m.kind === 'image_read' ? ' quote-bubble' : ''));
  bubble.textContent = m.text || '';
  if (m.thumb) {
    const img = el('img', 'thumb');
    img.src = m.thumb; img.alt = '刚发送的材料';
    bubble.appendChild(img);
  }
  node.appendChild(bubble);
  const list0 = $('#chatList');
  if (list0 && list0.children.length > 80) list0.removeChild(list0.firstElementChild);   // 超长对话 DOM 修剪
  list.appendChild(node);
}

function questionCard(q) {
  const comp = state.data?.completeness;
  const remain = comp ? Math.max(0, comp.total - comp.done) : null;
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
    b.setAttribute('aria-label', o.label);
    chips.appendChild(b);
  });
  if (q.kind === 'confirm') {
    const manual = el('button', 'chip subtle', '不对，我来改');
    manual.dataset.value = '__manual__';
    chips.appendChild(manual);
    const pending = Object.keys(state.data?.suspect || {}).length;
    if (pending > 1) {
      const all = el('button', 'chip', '都对，就这些');
      all.dataset.value = '__confirm_all__';
      all.addEventListener('click', async () => {
        card.remove();
        try {
          const r = await api(`/api/session/${state.sid}/confirm_all`, {});
          mergeState(r);
          renderMessages(r.messages || []);
        } catch (e) { if (sessionGone(e)) { await ensureSession(); } toast(e.message); }
      });
      chips.appendChild(all);
    }
  }
  if (remain !== null && q.kind === 'ask') {
    const prog = el('div', 'q-help');
    prog.style.cssText = 'border:0;padding:0 0 6px;color:var(--ink-3,#8A968F);font-size:.78rem';
    prog.textContent = `还差 ${remain} 项关键信息就能出完整意见`;
    card.appendChild(prog);
  }
  card.appendChild(chips);

  const needsInput = q.kind === 'ask' && ['text', 'money', 'date', 'city'].includes(q.type);
  if (needsInput) {
    const row = el('div', 'q-input');
    const input = el('input');
    input.placeholder = q.placeholder || '直接输入';
    if (q.type === 'date') { input.inputMode = 'numeric'; input.placeholder = (input.placeholder || '例：2026-03-15').replace(/20\d{2}/, String(new Date().getFullYear())); }
    if (q.type === 'money') input.inputMode = 'decimal';
    const btn = el('button', '', '提交');
    btn.disabled = true;
    setTimeout(() => input.focus(), 80);
    if (q.type === 'money') input.addEventListener('input', () => {   // 金额只留数字与小数点
      const cleanedParts = input.value.replace(/[^0-9.]/g, '').split('.');
      const cleaned = cleanedParts.length > 1 ? cleanedParts[0] + '.' + cleanedParts.slice(1).join('') : cleanedParts[0] || '';
      if (cleaned !== input.value) input.value = cleaned;
      btn.disabled = !cleaned.trim();
    });
    input.addEventListener('input', () => { btn.disabled = !input.value.trim(); });
    row.append(input, btn);
    card.appendChild(row);
    const submit = () => {
      const v = input.value.trim();
      if (!v || btn.disabled) return;
      btn.disabled = true;                    // 提交中防重复
      if (q.kind === 'confirm') submitConfirm(q.slot, v); else submitAnswer(q.slot, v);
      card.remove();
    };
    btn.addEventListener('click', submit);
    input.addEventListener('keydown', e => {
      if (e.isComposing || e.keyCode === 229) return;   // 输入法组词回车不提交
      if (e.key === 'Enter') { e.preventDefault(); if (!btn.disabled) submit(); }
    });
  }

  chips.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return;
    const btns = [...chips.querySelectorAll('button')];
    const i = btns.indexOf(document.activeElement);
    if (i < 0) return;
    ev.preventDefault();
    btns[(i + (ev.key === 'ArrowDown' ? 1 : btns.length - 1)) % btns.length].focus();
  });
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

/* ---------------- 打包卡：两件小事一张卡，一次提交 ---------------- */
function bundleCard(qs) {
  const card = el('div', 'qcard');
  const parts = qs.map(q => ({ q, value: null }));

  parts.forEach(p => {
    const sec = el('div', 'b-sec');
    sec.appendChild(el('div', 'q-title', esc(p.q.text)));
    if (p.q.why) sec.appendChild(el('div', 'q-why', esc(p.q.why)));
    const chips = el('div', 'q-chips');
    const inputTypes = ['text', 'money', 'date', 'city'];
    (p.q.options || []).forEach(o => {
      const b = el('button', 'chip' + (o.value.startsWith('__') ? ' subtle' : ''), esc(o.label));
      b.dataset.value = o.value;
      b.addEventListener('click', () => {
        if (o.value === '__unsure__') { showPartHelp(sec, p, refresh); return; }
        p.value = o.value;
        chips.querySelectorAll('.chip').forEach(x => x.classList.remove('selected'));
        b.classList.add('selected');
        refresh();
      });
      chips.appendChild(b);
    });
    sec.appendChild(chips);
    if (p.q.kind === 'ask' && inputTypes.includes(p.q.type)) {
      const row = el('div', 'q-input');
      const input = el('input');
      input.placeholder = p.q.placeholder || '直接输入';
      if (p.q.type === 'date') { input.inputMode = 'numeric'; input.placeholder = (input.placeholder || '例：2026-03-15').replace(/20\d{2}/, String(new Date().getFullYear())); }
      if (p.q.type === 'money') input.inputMode = 'decimal';
      if (p.q.type === 'money') input.addEventListener('input', () => {   // 金额只留数字与小数点
        const ps = input.value.replace(/[^0-9.]/g, '').split('.');
        const cleaned = ps.length > 1 ? ps[0] + '.' + ps.slice(1).join('') : ps[0] || '';
        if (cleaned !== input.value) input.value = cleaned;
        p.value = cleaned.trim() || null; refresh();
      });
      else input.addEventListener('input', () => { p.value = input.value.trim() || null; refresh(); });
      row.append(input);
      sec.appendChild(row);
    }
    card.appendChild(sec);
  });

  const submit = el('button', 'btn btn-primary b-submit', '提交');
  submit.disabled = true;
  function refresh() {
    submit.disabled = parts.some(p => !p.value);
  }
  submit.addEventListener('click', async () => {
    if (submit.disabled || state.busy) return;
    submit.disabled = true;
    const answers = parts.map(p => ({ slot: p.q.slot, value: p.value }));
    const ok = await submitBundle(answers, card);
    if (!ok) submit.disabled = false;
  });
  card.appendChild(submit);
  return card;
}

function showPartHelp(sec, p, refresh) {
  const old = $('.q-help', sec);
  if (old) return;
  const box = el('div', 'q-help');
  box.innerHTML = `<b>可以这样查：</b>${esc(p.q.help || '先空着也行，意见里我会写明这项没问到。')}`;
  const skip = el('button', 'chip subtle', '先空着');
  skip.style.marginTop = '8px';
  skip.addEventListener('click', () => {
    p.value = '__skip__';
    box.remove();
    refresh();
  });
  box.appendChild(skip);
  sec.appendChild(box);
}

async function submitBundle(answers, card) {
  if (state.busy) return false;
  state.busy = true;
  const thinking = waitBubble();
  try {
    const r = await api(`/api/session/${state.sid}/answer_batch`, { answers });
    clearWait(thinking);
    card && card.remove();
    mergeState(r);
    if (r.help) showHelpSheet(r.help);
    renderMessages(r.messages || []);
    if (state.report) { state.factsUpdated = true; toast('情况有更新——书面意见还是旧的，点「查看律师意见」重新出', 4200); }
    return true;
  } catch (e) {
    clearWait(thinking);
    if (sessionGone(e)) { await ensureSession(); state.busy = false; return submitBundle(answers, card); }
    toast(e.message);
    return false;
  } finally { state.busy = false; }
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

function scrollBottom(force = true) {
  const list = $('#chatList');
  const nearBottom = () => !list || (list.scrollHeight - list.scrollTop - list.clientHeight) < 240;
  const wasNear = nearBottom();
  requestAnimationFrame(() => {
    if (!force && !wasNear) return;           // 用户正在上翻看历史，不硬拉
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    if (list) list.scrollTop = list.scrollHeight;
  });
}

/* ---------------- 提交 ---------------- */
function waitBubble(text) {
  const t = el('div', 'msg assistant');
  t.innerHTML = `<div class="bubble plain" style="color:var(--ink-3)">${esc(text || '律师在记录…')}</div>`;
  $('#chatList').appendChild(t); scrollBottom(false);
  t._hintTimer = setTimeout(async () => {          // 等太久时告诉用户卡在哪，不干瞪
    try {
      const st = await api('/api/bridge/status', undefined, 'GET');
      if (st.mode === 'manual') {
        const b = t.querySelector('.bubble');
        if (b) b.textContent = (st.responder_online === false || st.pending > 0)
          ? '还在等应答方写回复——演示桥路没接上时这里会一直等，设置里能看到桥路状态'
          : '应答方在写回复，一般几秒内好';
      }
    } catch {}
  }, 5000);
  return t;
}

function clearWait(t) {
  if (t && t._hintTimer) clearTimeout(t._hintTimer);
  if (t) t.remove();
}

async function submitAnswer(slot, value) {
  if (state.busy) return;
  state.busy = true;
  const thinking = waitBubble();
  try {
    const r = await api(`/api/session/${state.sid}/answer`, { slot, value });
    clearWait(thinking);
    mergeState(r);
    if (r.help) showHelpSheet(r.help);
    renderMessages(r.messages || []);
    if (state.report) { state.factsUpdated = true; toast('情况有更新——书面意见还是旧的，点「查看律师意见」重新出', 4200); }
  } catch (e) {
    clearWait(thinking);
    if (sessionGone(e)) { await ensureSession(); state.busy = false; return submitAnswer(slot, value); }
    toast(e.message);
  }
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
  } catch (e) {
    if (sessionGone(e)) { await ensureSession(); state.busy = false; return submitConfirm(slot, value); }
    toast(e.message); }
  finally { state.busy = false; }
}

async function sendText(text, source = 'text', retried = false) {
  if (!text.trim() || state.busy) return;
  state.busy = true;
  try { return await _sendTextInner(text, source, retried); }
  finally { state.busy = false; }
}

async function _sendTextInner(text, source = 'text', retried = false) {
  await ensureSession();
  if (!retried) { appendMessage({ role: 'user', kind: 'text', text }); scrollBottom(); }
  const thinking = waitBubble();
  try {
    const r = await apiWithRetry(`/api/session/${state.sid}/text`, { text, source });
    clearWait(thinking);
    mergeState(r);
    renderMessages(r.messages || []);
  } catch (e) {
    clearWait(thinking);
    if (sessionGone(e) && !retried) { toast('刚才服务重启了一下，接着说就行', 2600); return sendText(text, source, true); }
    const sorry = el('div', 'msg assistant');
    sorry.innerHTML = '<div class="bubble">这会儿网络不太稳，你刚才说的话我没能记下来——再发一次就好，内容不会丢。</div>';
    $('#chatList').appendChild(sorry); scrollBottom(false);
    toast(e.message, 4200);
  }
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
  if (state.busy) return;                     // 应答中防连点：一条一条来
  const t = $('#textInput');
  const v = t.value.trim();
  if (!v) return;
  t.value = ''; autoGrow();
  if (!$('#view-chat').classList.contains('active')) go('chat');   // 从首页直接开口：切到对话视图再发
  await sendText(v);
}

/* 图片 */
async function compressImage(file, maxSide = 1600) {
  // createImageBitmap 按图片内嵌方向解码，避免 iPhone 照片横竖颠倒
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
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
  let picIdx = 0;
  for (const file of files) {
    picIdx++;
    if (files.length > 1) toast(`正在读第 ${picIdx}/${files.length} 张…`, 4000);
    const shotUrl = state.lastShots?.[state.lastShots.length - 1];
    appendMessage({ role: 'user', kind: 'image', text: '已发送 1 张照片', thumb: shotUrl });
    if (!/^image\//.test(file.type || '')) { toast('这个不是图片——支持照片或截图（jpg/png 等）'); continue; }
    const note = waitBubble('正在看这张材料…');
    try {
      const fd = new FormData();
      const shot = await compressImage(file);
      fd.append('file', shot);
      state.lastShots = state.lastShots || [];
      state.lastShots.push(URL.createObjectURL(shot));
      const r = await apiWithRetry(`/api/session/${state.sid}/image`, fd);
      clearWait(note);
      mergeState(r);
      renderMessages(r.messages || []);
    } catch (e) {
      clearWait(note);
      if (sessionGone(e)) { await ensureSession(); return uploadImages([file]); }
      toast(e.message);
    }
  }
}

/* 语音 */
async function startRecording() {
  if (state.recording) return;                // 录音中再点麦克风：忽略，不重复起流
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(m => MediaRecorder.isTypeSupported(m)) || '';
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
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const an = ac.createAnalyser();
      an.fftSize = 256;
      ac.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.frequencyBinCount);
      state.meter = setInterval(() => {
        an.getByteFrequencyData(buf);
        const v = Math.min(100, Math.round(buf.reduce((a, b) => a + b, 0) / buf.length * 2));
        const bar = $('#voiceMeter');
        if (bar) bar.style.width = v + '%';
      }, 120);
    } catch (_) {}
    state.timer = setInterval(() => {
      const s = Math.floor((Date.now() - state.startedAt) / 1000);
      $('#voiceTime').textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0') + (s >= 45 ? `（还剩 ${60 - s} 秒）` : '');
      if (s >= 60) finishRecording();
    }, 250);
  } catch (e) { toast('无法使用麦克风，请检查权限'); }
}

function finishRecording() {
  if (!state.recording) return;
  clearInterval(state.timer); clearInterval(state.meter);
  state.recording.stop();
  state.recording = null;
  $('#voiceOverlay').hidden = true;
  const blob = state.audioBlob;
  if (!blob || blob.size < 1200) { toast('太短了，再多说几句'); return; }
  transcribe(blob);
}

function cancelRecording() {
  if (state.recording) { clearInterval(state.timer); state.recording.stop(); state.recording = null; }
  state.audioChunks = []; state.audioBlob = null;   // 取消就作废，别让上次录音串场
  $('#voiceOverlay').hidden = true;
}

async function transcribe(blob) {
  const toastEl = $('#toast');
  toast('正在转写…', 8000);
  try {
    const fd = new FormData();
    fd.append('file', blob, 'voice.webm');
    let r;
    try {
      r = await apiWithRetry(`/api/session/${state.sid}/asr`, fd);
    } catch (e) {
      if (sessionGone(e)) { await ensureSession(); return transcribe(blob); }
      throw e;
    }
    try { const au = $('#transcriptAudio'); au.src = URL.createObjectURL(blob); au.style.display = 'block'; } catch (_) {}
    if (!r.transcript) { toast('没听清，再说一次'); return; }
    $('#transcript').value = r.transcript;
    $('#transcriptSheet').hidden = false;
  } catch (e) { toast(e.message, 4000); }
}

/* ---------------- 律师意见 ---------------- */
async function buildReport(force = false) {
  if (state.busy) return;
  if (!force && state.report) { renderReport(state.report); go('report'); return; }   // 回看秒开
  state.busy = true;
  $('#reportBody').innerHTML = ['58%', '80%', '70%', '64%'].map(w =>
    `<div class="skel" style="width:${w}%"></div>`).join('') +
    '<div class="hint" style="text-align:center;padding:20px 0">正在整理意见…</div>';
  go('report');
  toast('正在整理意见…', 8000);
  try {
    const rep = await apiWithRetry(`/api/session/${state.sid}/report`, {});
    state.report = rep; state.factsUpdated = false;
    renderReport(rep);
    go('report');
  } catch (e) {
    if (sessionGone(e)) { await ensureSession(); return buildReport(); }
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
    card.querySelector('button').addEventListener('click', () => { card.remove(); buildReport(true); });
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
      <div><b>${esc(g.name.replace('第一层 · ', '').replace('第二层 · ', ''))}</b><span>${esc(g.message)}</span>
        ${(g.detail || []).length ? `<details class="gate-detail"><summary>细项</summary>${g.detail.map(d => `<div class="dim-note">· ${esc(d)}</div>`).join('')}</details>` : ''}
      </div>
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
    <div class="section" id="sec-calc">
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

  const hi = (t) => esc(String(t)).replace(/&lt;mark&gt;/g,'<mark>').replace(/&lt;\/mark&gt;/g,'</mark>');
  const cases = (r.citations?.cases || []).map(x => `
    <details class="case">
      <summary><div class="case-t">${esc(x.title)}</div><div class="case-src">${esc(x.source)}</div></summary>
      <div class="case-p"><b>争议焦点</b> ${esc(x.focus)}</div>
      <div class="case-p"><b>裁判要旨</b> ${esc(x.holding)}</div>
      <div class="case-p"><b>可比之处</b> ${esc(x.comparable)}</div>
      <div class="case-p"><b>不能类比</b> ${esc(x.limit)}</div>
      ${x.source_url ? `<div class="cites"><a class="cite" href="${esc(x.source_url)}" target="_blank" rel="noopener">查看官方原文</a></div>` : ''}
    </details>`).join('');

  const confidence = c.confidence || {};
  const confCount = (confidence.from_image || []).length;
  const oralCount = (confidence.from_oral || []).length;

  const openQs = (r.open_questions || []);
  $('#reportBody').innerHTML = `
    <div class="print-head" style="display:none">
      <b>劳动仲裁初步咨询意见（${esc(r.city || '')}口径）</b> · 生成于 ${esc(r.generated_at || '')} · 仅供参考，不构成律师意见
    </div>
    <div class="opinion-head">
      <div class="opinion-kicker">${r.preliminary ? '初步咨询意见' : '咨询意见'}${state.factsUpdated ? ' · <span style="color:#B42318">事实已更新，建议重新生成</span>' : ''}</div>
      <div class="opinion-date">${esc(r.generated_at || '')}${r.preliminary ? ' · 待补充材料后再确认' : ''}${r.facts_snapshot ? ` · 基于 ${Object.keys(r.facts_snapshot).length} 项确认事实` : ''}</div>
      <div class="toc">
        ${[['结论', 'sec-conclusion'], ['金额', 'sec-calc'], ['材料', 'sec-materials'], ['提交', 'sec-venue'], ['法条', 'sec-cites']].filter(([_, id]) => document.getElementById(id) || true).map(([t, id]) => `<button class="cite" data-jump="${id}">${t}</button>`).join(' ')}
      </div>
    </div>
    <div class="report-hero ${status === 'warn' ? 'is-warn' : status === 'bad' ? 'is-bad' : ''}">
      <div class="verdict">${esc(verdictText(c.label))}</div>
      <div class="verdict-desc">${esc(c.one_liner)}</div>
      <div class="metrics">
        <div class="metric"><div class="m-v">${c.claim_amount ? money(c.claim_amount) : '待确认'}</div><div class="m-l">可主张金额（参考）</div>
          ${r.claim_amount_rmb ? `<div class="m-rmb">${esc(r.claim_amount_rmb)}</div>` : ''}</div>
        <div class="metric"><div class="m-v ${days !== null && days !== undefined && days <= 60 ? 'hot' : ''}">${days === null || days === undefined ? '未起算' : Math.max(0, days) + ' 天'}</div><div class="m-l">仲裁时效剩余${c.deadline?.start_date ? `（自 ${esc(c.deadline.start_date)} 起算）` : ''}</div></div>
      </div>
      ${(c.decision === 'not_recommended' && r.evidence) ? `<div class="evidence-hint">当前材料证据强度 ${r.evidence.score}/100，补齐后再评估一次更准。</div>` : ''}
      <div class="gate-strip">${gateRows}${worthRow}</div>
      ${(c.deadline?.exceptions || []).length ? `<div class="dim-note" style="margin-top:8px">${c.deadline.exceptions.map(x => '· ' + esc(x)).join('<br>')}</div>` : ''}
      ${(c.dimensions || []).length ? `<div class="dims">${(c.dimensions || []).map(d => `
        <div class="dim"><div class="dim-top"><span>${esc(d.label || d.key || '')}</span><span>${d.score}</span></div>
        <div class="dim-bar"><i style="width:${Math.max(0, Math.min(100, d.score))}%"></i></div>
        <div class="dim-note">${esc(d.note || '')}</div></div>`).join('')}</div>` : ''}
    </div>

    <div class="section" id="sec-conclusion">
      <div class="section-head"><div class="section-title">为什么是这个结论</div><div class="section-hint">${confCount ? `其中 ${confCount} 项经材料核对` : '依据你确认的口述事实'}</div></div>
      <div class="card">${reasons}</div>
    </div>

    ${c.alternative && c.decision === 'better_alternative' ? `<div class="section">
      <div class="section-head"><div class="section-title">更快的路</div><div class="section-hint">先试这个</div></div>
      <div class="card card-pad"><div class="hint" style="padding:0"><b>${esc(c.alternative.title || '')}</b>——${esc(c.alternative.why || '')}</div></div>
    </div>` : ''}

    ${openQs.length ? `<div class="section">
      <div class="section-head"><div class="section-title">还需要你补一句的</div><div class="section-hint">影响个别结论</div></div>
      <div class="card card-pad">
        <div class="hint" style="padding:0">这几项我还没问到，上面的意见先按已知情况给：
          <button class="cite" id="gotoFill" style="margin:6px 8px 0 0">回去补这几句</button></div>
      </div>
    </div>` : ''}

    ${calcHtml}

    <div class="section" id="sec-materials">
      <div class="section-head"><div class="section-title">要带什么</div><div class="section-hint">${matList.length} 项</div></div>
      <div class="card">
        <div class="card-pad" style="padding-bottom:0"><div class="hint" style="padding:0 0 12px">这是你带去仲裁委交的材料，照着准备就行，不用发给我。${r.evidence?.gaps?.length ? '<br><b>目前最短板：</b>' + esc(r.evidence.gaps.join('；')) : ''}</div>
          ${(r.evidence?.dimensions || []).length ? `<div class="dims" style="margin-top:6px">${r.evidence.dimensions.map(d => `
            <div class="dim"><div class="dim-top"><span>${esc(d.label || d.key || '')}</span><span>${d.score}</span></div>
            <div class="dim-bar"><i style="width:${Math.max(0, Math.min(100, d.score))}%"></i></div></div>`).join('')}</div>` : ''}</div>
        ${materials}
      </div>
    </div>

    <div class="section">
      <div class="section-head"><div class="section-title">接下来会发生什么</div><div class="section-hint">一般流程</div></div>
      <div class="card">
        ${[["提交申请", "当场或线上交材料，符合条件当天受理"], ["受理与组庭", "5 日内决定是否受理，随后组成仲裁庭"], ["开庭与调解", "开庭通知提前 5 日送达；庭上会先问愿不愿意调解"], ["裁决", "自受理之日起 45 日内审结，复杂的可延长 15 日"]].map(([s2, d2], i) => `
          <div class="mat"><div class="mat-top"><div class="mat-name">第 ${i + 1} 步 · ${esc(s2)}</div></div><div class="mat-meta"><span>${esc(d2)}</span></div></div>`).join('')}
        <div class="mat"><div class="mat-meta"><span>依据：《劳动争议调解仲裁法》第二十九条、第三十五条、第四十三条。</span></div></div>
      </div>
    </div>

    <div class="section" id="sec-venue">
      <div class="section-head"><div class="section-title">去哪儿提交</div><div class="section-hint">按${esc(r.city || '杭州市')}口径</div></div>
      <div class="card card-pad"><div class="hint" style="padding:0">劳动仲裁不收费，经费由财政保障（《劳动争议调解仲裁法》第五十三条）；请律师不是必须的。</div></div>
      <div class="card">${venues}</div>
    </div>

    <div class="section" id="sec-cites">
      <div class="section-head"><div class="section-title">依据的法条</div><div class="section-hint">${(r.citations?.articles || []).length} 条</div></div>
      <div class="card">${articles}</div>
    </div>

    ${cases ? `<div class="section"><div class="section-head"><div class="section-title">类似案件</div><div class="section-hint">按${esc((state.data?.slots?.dispute_types?.value || []).map(v => (OPTION_LABELS.dispute_types[v] || v)).join('、') || '争议类型')}匹配 · 仅供参考</div></div><div class="card">${cases}</div></div>` : ''}

`;

  $('#backToChat')?.addEventListener('click', () => go('chat'));
  $('#gotoFill')?.addEventListener('click', () => { go('chat'); $('#textInput')?.focus(); });
  $$('#reportBody [data-copy]').forEach(b => b.addEventListener('click', () => copy(b.dataset.copy)));
  $$('#reportBody .cite[data-law]').forEach(b => b.addEventListener('click', () => showArticle(b.dataset.law)));
  $$('#reportBody [data-jump]').forEach(b => b.addEventListener('click', () => {
    document.getElementById(b.dataset.jump)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
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
    gongshang: '工伤保险条例', shishitiaoli: '实施条例', nmgxz: '农民工工资支付条例',
    jiuye: '就业促进法',
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
async function rebuttal() {
  openSheet('公司会怎么反驳你', '<div class="hint">正在准备…</div>');
  try {
    let r;
    try {
      r = await api(`/api/session/${state.sid}/rebuttal`, {});
    } catch (e) {
      if (sessionGone(e)) { await ensureSession(); return rebuttal(); }
      throw e;
    }
    $('#sheetBody').innerHTML = (r.items || []).map((x, i) => `
      <div class="case">
        <div class="case-t">${i + 1}. ${esc(x.attack)}</div>
        <div class="case-p"><b>对方会拿</b> ${esc(x.evidence)}</div>
        <div class="case-p"><b>你可以说</b> ${esc(x.reply)}</div>
        <div class="cites">${(x.citations || []).map(id => `<button class="cite" data-law="${esc(id)}">${esc(lawShort(id.split(':')[0]))} 第 ${esc(id.split(':')[1])} 条</button>`).join('')}</div>
      </div>`).join('') || '<div class="hint">暂无内容</div>';
    const fullText = (r.items || []).map((x, i) =>
      `${i + 1}. ${x.attack}\n对方会拿：${x.evidence}\n你可以说：${x.reply}`).join('\n\n');
    const cp = document.createElement('div');
    cp.className = 'sheet-actions';
    cp.innerHTML = '<button class="btn btn-ghost">复制全文</button>';
    cp.querySelector('button').addEventListener('click', () => copy(fullText));
    $('#sheetBody').appendChild(cp);
    $$('#sheetBody .cite[data-law]').forEach(b => b.addEventListener('click', () => showArticle(b.dataset.law)));
  } catch (e) {
    $('#sheetBody').innerHTML = `<div class="hint">${esc(e.message)}</div>
      <div class="sheet-actions"><button class="btn btn-primary" id="rebutRetry">再试一次</button></div>`;
    $('#rebutRetry')?.addEventListener('click', () => { $('#sheetBody').innerHTML = '<div class="hint">正在准备…</div>'; rebuttal(); });
  }
}

/* ---------------- 法条 ---------------- */
async function loadLaws() {
  try {
    let r = null;
    try { r = JSON.parse(sessionStorage.getItem('lawIndex') || 'null'); } catch (_) {}
    if (!r) { r = await api('/api/laws', undefined, 'GET'); sessionStorage.setItem('lawIndex', JSON.stringify(r)); }
    const groups = {};
    (r.laws || []).forEach(l => {
      const k = l.category || '法律';
      (groups[k] = groups[k] || []).push(l);
    });
    const cats = Object.keys(groups);
    const recentHtml = () => {
      try {
        const recent = JSON.parse(sessionStorage.getItem('lawRecent') || '[]');
        if (!recent.length) return '';
        const titles = { laodonghetongfa: '劳动合同法', tiaojiezhongcai: '调解仲裁法', laodongfa: '劳动法', shebaofa: '社会保险法', sfjs1: '司法解释（一）', sfjs2: '司法解释（二）', nianxiujia: '年休假条例', jiancha: '监察条例', gongshang: '工伤保险条例', shishitiaoli: '实施条例', nmgxz: '农民工工资支付条例', jiuye: '就业促进法' };
        return `<div class="law-group-title">最近看过</div><div class="cites" style="margin:0 0 10px">${recent.map(x =>
          `<button class="cite" data-law="${esc(x)}">${esc(titles[x.split(':')[0]] || x)}</button>`).join(' ')}</div>`;
      } catch (_) { return ''; }
    };
    const render = (cat) => {
      const shown = cat ? { [cat]: groups[cat] } : groups;
      $('#lawList').innerHTML = recentHtml() + (cats.length > 1
        ? `<div class="cites" style="margin-bottom:8px">${['', ...cats].map(c2 =>
            `<button class="cite" data-cat="${esc(c2)}">${c2 || '全部'}</button>`).join('')}</div>` : '')
        + Object.entries(shown).map(([c3, list]) =>
            `<div class="law-group-title">${esc(c3)}</div>${list.map(l => `<button class="law-item" data-lawid="${esc(l.id)}">
              <div><div class="l-n">${esc(l.title)}</div><div class="l-c">施行 ${esc(l.effective || '')}</div></div>
              <div class="l-r">${l.count} 条</div></button>`).join('')}`).join('');
      $$('#lawList [data-lawid]').forEach(b => b.addEventListener('click', () => openLaw(b.dataset.lawid)));
      $$('#lawList [data-cat]').forEach(b => b.addEventListener('click', () => render(b.dataset.cat)));
    };
    const total = (r.laws || []).reduce((n, l) => n + (l.count || 0), 0);
    $('#lawSearch').placeholder = `搜 ${total} 条法条，如「二倍工资」「时效」`;
    render('');

  } catch (e) { toast(e.message); }
}

async function openLaw(id) {
  openSheet('', '<div class="hint">加载中…</div>');
  const law = await api(`/api/laws/${id}`, undefined, 'GET');
  $('#sheetTitle').textContent = law.title;
  $('#sheetBody').innerHTML = `
    <div class="hint" style="padding:0 0 10px">${esc(law.flavor)}<br>施行 ${esc(law.effective || '')} · ${esc(law.issuer)}</div>
    <input id="lawFilter" class="search-input" placeholder="在本法内筛选，如「经济补偿」" style="width:100%;margin-bottom:10px">
    <div id="lawArticles">${law.articles.map(a => `<div class="article-item" data-kw="${esc(a.no_cn)}${esc(a.text)}"><div class="a-no">${esc(a.no_cn)}</div><div class="a-txt" style="-webkit-line-clamp:6">${esc(a.text)}</div></div>`).join('')}</div>`;
  $('#lawFilter')?.addEventListener('input', e => {
    const kw = e.target.value.trim();
    $$('#lawArticles .article-item').forEach(it => {
      it.style.display = !kw || it.dataset.kw.includes(kw) ? '' : 'none';
    });
  });
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
        ${a.no > 1 ? '<button class="btn btn-ghost" id="prevArt">上一条</button>' : ''}
        <button class="btn btn-ghost" id="copyArticle">复制原文</button>
        <button class="btn btn-ghost" id="openWholeLaw">看整部法</button>
        ${a.no < (a.total || 0) ? '<button class="btn btn-ghost" id="nextArt">下一条</button>' : ''}
        <a class="btn btn-primary" href="https://flk.npc.gov.cn/" target="_blank" rel="noopener">打开官方数据库</a>
      </div>`;
    try {
      const rec = JSON.parse(sessionStorage.getItem('lawRecent') || '[]');
      const nid = `${a.law_id}:${a.no}`;
      sessionStorage.setItem('lawRecent', JSON.stringify([nid, ...rec.filter(x => x !== nid)].slice(0, 5)));
    } catch (_) {}
    $('#copyArticle').addEventListener('click', () => copy(`《${a.law}》${a.no_cn}：${a.text}`));
    $('#prevArt')?.addEventListener('click', () => showArticle(`${a.law_id}:${a.no - 1}`));
    $('#nextArt')?.addEventListener('click', () => showArticle(`${a.law_id}:${a.no + 1}`));
    $('#openWholeLaw').addEventListener('click', () => { closeSheets(); openLaw(a.law_id); });
    $('#copyArticle').addEventListener('click', () => copy(a.text));
  } catch (e) { $('#sheetBody').innerHTML = `<div class="hint">${esc(e.message)}</div>`; }
}

/* ---------------- 设置 ---------------- */
function settingsA11y() {
  const map = { setBase: '服务地址', setKey: 'API 密钥', setTextModel: '文本模型', setVisionModel: '视觉模型' };
  Object.entries(map).forEach(([id, label]) => {
    const el = document.getElementById(id);
    if (el && !el.getAttribute('aria-label')) el.setAttribute('aria-label', label);
  });
}

async function loadSettings() {
  const s = await api('/api/settings', undefined, 'GET');
  $('#setBase').value = s.base_url || '';
  $('#setKey').value = '';
  $('#setKey').placeholder = s.api_key || '未设置';
  $('#setTextModel').value = s.text_model || '';
  $('#setVisionModel').value = s.vision_model || '';
  $('#connResult').textContent = '';
  api('/api/bridge/status', undefined, 'GET').then(st => {
    const el = $('#bridgeStatus');
    if (el) el.textContent = st.mode === 'manual'
      ? (st.pending ? `桥路积压 ${st.pending} 条${st.oldest_wait_s > 90 ? '——应答方可能离线' : ''}`
                    : (st.responder_online === false ? '应答方可能离线（有请求长期无应答）' : '桥路正常，无积压'))
      : '当前为 API 模式，无需桥路';
  }).catch(() => {});
  const CITY_AGE = (city) => {
    const d = new Date(city.verified_at);
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    return days > 90 ? `⚠️ ${city.city}口径核对于 ${city.verified_at}（${days} 天前），建议复核最低工资与社平工资` : `✓ ${city.city}口径 ${city.verified_at} 核对`;
  };
  api('/api/city', undefined, 'GET').then(c => {
    const el = $('#bridgeStatus');
    if (el) el.textContent += '　|　' + CITY_AGE(c);
  }).catch(() => {});
}

async function saveSettings() {
  const key = $('#setKey').value.trim();
  const baseRaw = $('#setBase').value.trim();
  if (baseRaw && !/^https?:\/\//.test(baseRaw)) { $('#connResult').textContent = '服务地址要以 http(s):// 开头'; return; }
  const saveBtn = [...document.querySelectorAll('#view-settings button')].find(b => b.textContent.trim() === '保存');
  if (saveBtn) saveBtn.disabled = true;
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
    toast(s.mode === 'manual' ? '已切到演示桥路模式——需要会话内应答方在线' : '设置已保存');
    if (s.mode === 'manual') {
      try {
        const st = await api('/api/bridge/status', undefined, 'GET');
        const el = $('#bridgeStatus');
        if (el) el.textContent = st.pending ? `桥路积压 ${st.pending} 条——应答方没跟上` : '桥路正常，无积压';
      } catch (_) {}
    }
  } catch (e) { $('#connResult').textContent = e.message; }
  finally { const b = [...document.querySelectorAll('#view-settings button')].find(b => b.textContent.trim() === '保存'); if (b) b.disabled = false; }
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
let _sheetReturnFocus = null;
function openSheet(title, html) {
  $('#sheetTitle').textContent = title;
  $('#sheetBody').innerHTML = html;
  $('#sheet').hidden = false;
}

function closeSheets() {
  try { if (_sheetReturnFocus) { _sheetReturnFocus.focus(); _sheetReturnFocus = null; } } catch (_) {}
  const au = $('#transcriptAudio');
  if (au && !au.paused) au.pause();
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
  ['dragover', 'drop'].forEach(evt => window.addEventListener(evt, e => {
    if (!$('#view-chat').classList.contains('active')) return;
    e.preventDefault();
    const files = [...(e.dataTransfer?.files || [])].filter(f => /^image\//.test(f.type || ''));
    if (evt === 'drop' && files.length) uploadImages(files);
  }));
  $('#textInput').addEventListener('input', () => {
    autoGrow();                                             // 打字随内容长高 + 点亮发送键
    try { sessionStorage.setItem('draft', $('#textInput').value); } catch (_) {}
  });
  try {
    const draft = sessionStorage.getItem('draft');
    if (draft) { $('#textInput').value = draft; autoGrow(); $('#sendBtn').disabled = !draft.trim(); }
  } catch (_) {}
  $('#textInput').addEventListener('keydown', e => {
    if (e.isComposing || e.keyCode === 229) return;   // 中文输入法选词回车不是发送
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); }   // 移动端 enterkeyhint=send，同样直发
  });

  $('#attachBtn').addEventListener('click', () => { $('#attachSheet').hidden = false; });
  $('#pickCamera').addEventListener('click', () => { closeSheets(); $('#cameraInput').click(); });
  $('#pickAlbum').addEventListener('click', () => { closeSheets(); $('#albumInput').click(); });
  $('#cameraInput').addEventListener('change', e => { uploadImages([...e.target.files]); e.target.value = ''; });
  $('#albumInput').addEventListener('change', e => { uploadImages([...e.target.files]); e.target.value = ''; });
  window.addEventListener('paste', e => {
    if (!$('#view-chat').classList.contains('active')) return;
    const files = [...(e.clipboardData?.files || [])].filter(f => /^image\//.test(f.type || ''));
    if (files.length) { e.preventDefault(); uploadImages(files); }
  });

  const v0 = new URLSearchParams(location.search).get('view') || (location.hash || '').replace('#/', '');
  // 报告页刷新后没有渲染数据，落回对话页续会话（意见卡还在，点一下秒开缓存报告）
  if (v0 && { chat: 1, laws: 1, settings: 1, report: 1, home: 1 }[v0]) go(v0 === 'report' ? 'chat' : v0, false);
  if (v0 === 'chat' || v0 === 'report') ensureSession();   // 刷新不空屏：直接续上
  applyTheme();
  $('#micBtn').addEventListener('click', startRecording);
  let deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); deferredPrompt = e; });
  const inst = document.createElement('button');
  inst.className = 'link-btn'; inst.style.margin = '6px 0 0'; inst.textContent = '安装到桌面/主屏';
  inst.addEventListener('click', async () => {
    if (!deferredPrompt) { toast('当前浏览器不支持一键安装，可用「添加到主屏幕」'); return; }
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
  });
  $('#themeRow')?.parentElement?.appendChild(inst);
  $('#voiceDone').addEventListener('click', finishRecording);
  $('#voiceCancel').addEventListener('click', cancelRecording);
  $('#voiceCancel').textContent = '取消（Esc）';
  // sheet 打开时焦点圈在面板内，关闭归还触发点
  const sheetEl = $('.sheet:not([hidden]) .sheet-panel');
  if (sheetEl) {
    _sheetReturnFocus = document.activeElement;
    setTimeout(() => $('.sheet-close[data-close]')?.focus(), 60);
    sheetEl.addEventListener('keydown', function trap(e) {
      if (e.key !== 'Tab') return;
      const f = [...sheetEl.querySelectorAll('button, [href], input, textarea')].filter(x => !x.disabled && x.offsetParent !== null);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }
  [['auto', '跟随系统'], ['light', '浅色'], ['dark', '深色']].forEach(([v, label]) => {
    const b = document.createElement('button');
    b.className = 'chip subtle'; b.textContent = label; b.dataset.theme = v;
    b.addEventListener('click', () => { localStorage.setItem('theme', v); applyTheme(); toast(label === 'auto' ? '已跟随系统' : `已切到${label}`); });
    $('#themeRow')?.appendChild(b);
  });
  window.addEventListener('beforeprint', () => { $$('#reportBody details').forEach(d => d.open = true); });
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const open = [...document.querySelectorAll('.sheet')].find(s => !s.hidden);
      if (open) open.hidden = true;
    }
  });
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape' && state.recording) cancelRecording();
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      go('laws');
      setTimeout(() => $('#lawSearch')?.focus(), 150);
    }
  });
  // 服务探活：挂了就在页头挂横幅，别让用户对着白屏猜
  const banner = $('#healthBanner');
  if (banner && !banner.querySelector('.banner-close')) {
    const x = document.createElement('button');
    x.textContent = '×'; x.className = 'banner-close';
    x.setAttribute('aria-label', '关闭提示');
    x.style.cssText = 'float:right;background:none;border:0;color:inherit;font-size:1.1em;cursor:pointer;padding:0 4px';
    x.addEventListener('click', () => banner.style.display = 'none');
    banner.appendChild(x);
  }
  fetch('/api/health', { method: 'GET' }).then(r => r.json()).then(h => {
    if (!h.ok) { $('#healthBanner').style.display = 'block'; return; }
    if (h.asr_model === false) {
      const mic = $('#micBtn');
      mic.disabled = true;
      mic.title = '语音模型未就绪，先打字也一样';
    }
  }).catch(() => {
    if (navigator.onLine === false) {
      const b = $('#healthBanner');
      b.textContent = '当前离线——已缓存的法条库仍可以看，联网后再继续咨询。';
      b.style.display = 'block';
    } else { $('#healthBanner').style.display = 'block'; }
  });
  window.addEventListener('online', () => { $('#healthBanner').style.display = 'none'; });
  navigator.serviceWorker?.addEventListener('controllerchange', () => toast('已更新到最新版本', 2000));
  window.addEventListener('offline', () => {
    const b = $('#healthBanner');
    b.textContent = '当前离线——已缓存的法条库仍可以看，联网后再继续咨询。';
    b.style.display = 'block';
  });
  $('#transcriptSend').addEventListener('click', async () => {
    const text = $('#transcript').value.trim();
    $('#transcriptSheet').hidden = true;
    if (text) await sendText(text, 'speech');
  });
  $('#transcriptRetry').addEventListener('click', () => { $('#transcriptSheet').hidden = true; startRecording(); });

  $('#rebutBtn').addEventListener('click', rebuttal);

  $('#lawSearch').addEventListener('keydown', e => { if (e.key === 'Enter') searchLaws(); });
  let _lawSearchT = null;
  $('#lawSearch').addEventListener('input', () => {          // 边打边搜（400ms 防抖）
    clearTimeout(_lawSearchT);
    _lawSearchT = setTimeout(searchLaws, 400);
  });
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
