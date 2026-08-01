// ── State ─────────────────────────────────────────────────────────────────
const modules = { shadowing: true, roleplay: true };
let currentStep = 1;
let dtpS2Start, dtpS2Due;
let questionSets = [];

// ── Module toggles ────────────────────────────────────────────────────────
function toggleModule(name) {
  return;
}

function updateFlowPreview() {
  const icons = ['💼', '📝', '🎤', '🎭', '🤖', '📓'];
  const steps = icons.map((icon, index) => ({
    label: `${icon} ${AdminWorkflow.sectionLabel(index + 1)}`,
    on: true,
  }));
  const html = steps
    .filter(s => s.on)
    .map((s, i, arr) =>
      (i > 0 ? '<span class="flow-arrow">→</span>' : '') +
      `<span class="flow-step active-module">${s.label}</span>`
    ).join('');
  document.getElementById('flowPreview').innerHTML = html;
}

function selectedQuestions() {
  const key = document.getElementById('s2QuestionSet').value;
  if (key === 'custom') return [0,1,2,3].map(i => document.getElementById(`s2Q${i}`).value.trim());
  return (questionSets.find(row => row.key === key)?.questions || []).slice();
}

function updateQuestionSetUI() {
  const key = document.getElementById('s2QuestionSet').value;
  const isCustom = key === 'custom';
  document.getElementById('s2CustomQuestions').classList.toggle('d-none', !isCustom);
  const questions = selectedQuestions();
  document.getElementById('s2QuestionPreview').innerHTML = isCustom
    ? '<span class="text-muted small"><i class="bi bi-pencil me-1"></i>請在下方填寫四題核心題意；角色扮演會保留題意自然改問。</span>'
    : `<ol class="mb-0 ps-3">${questions.map(q => `<li class="mb-1">${escHtml(q)}</li>`).join('')}</ol>`;
}

async function loadQuestionSets() {
  await window._adminReady;
  const select = document.getElementById('s2QuestionSet');
  try {
    const res = await fetch('/api/admin/question-sets');
    if (!res.ok) throw new Error('load failed');
    questionSets = await res.json();
    select.textContent = '';
    questionSets.forEach((row, index) => select.add(new Option(`公版：${row.label}`, row.key, index === 0, index === 0)));
    select.add(new Option('自訂題組', 'custom'));
    updateQuestionSetUI();
  } catch (_) {
    select.innerHTML = '<option value="">無法載入公版題組</option>';
    document.getElementById('s2QuestionPreview').innerHTML = '<span class="text-danger small">公版題組載入失敗，請重新整理後再試。</span>';
  }
}

async function loadRubrics() {
  await window._adminReady;
  const select = document.getElementById('rubricSelect');
  try {
    const res = await fetch('/api/admin/rubrics');
    if (!res.ok) throw new Error('rubrics unavailable');
    const rows = await res.json();
    if (!rows.length) throw new Error('rubrics empty');
    rows.forEach((row, index) => select.add(new Option(`${row.rubric_name} v${row.version_number}`, row.version_id, index === 0, index === 0)));
  } catch (_) {
    select.innerHTML = '<option value="">評分規準載入失敗</option>';
    select.disabled = true;
    showGlobalAlert('評分規準載入失敗，請重新整理後再建立作業。');
  }
}

// ── Step navigation ───────────────────────────────────────────────────────
function goStep(n) {
  document.getElementById(`step${currentStep}`).classList.add('d-none');
  document.getElementById(`step${n}`).classList.remove('d-none');

  // Update indicators
  for (let i = 1; i <= 4; i++) {
    const ind = document.getElementById(`step-ind-${i}`);
    const circ = document.getElementById(`step-circle-${i}`);
    ind.className = 'step-item' + (i === n ? ' active' : i < n ? ' done' : '');
    circ.innerHTML = i < n ? '<i class="bi bi-check"></i>' : i;
  }
  currentStep = n;
  if (n === 4) renderSummary();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function validateStep2() {
  const title = document.getElementById('s2Title').value.trim();
  if (!title) { showStep2Alert('請填寫作業標題'); return; }
  const key = document.getElementById('s2QuestionSet').value;
  if (!key) { showStep2Alert('請選擇公版題組或重新整理頁面'); return; }
  const qs = selectedQuestions();
  if (key === 'custom' && (qs.length !== 4 || qs.some(q => !q))) {
    showStep2Alert('自訂題組必須填寫全部 4 題');
    return;
  }
  goStep(3);
}

function showStep2Alert(msg) {
  const el = document.getElementById('step2Alert');
  el.className = 'alert alert-danger';
  el.textContent = msg;
}

// ── Summary ───────────────────────────────────────────────────────────────
function renderSummary() {
  const title = document.getElementById('s2Title').value.trim();
  const desc = document.getElementById('s2Desc').value.trim();
  const ctx = document.getElementById('s2Context').value.trim();
  const qs = selectedQuestions();
  const questionSetLabel = document.getElementById('s2QuestionSet').selectedOptions[0]?.textContent || '';
  const classes = getTagsFromWrap('s2ClassWrap');
  const startDisplay = dtpS2Start?.display.value || '';
  const dueDisplay = dtpS2Due?.display.value || '';
  const isActive = document.getElementById('s2IsActive').checked;

  const modBadges = [
    `<span class="badge-module badge bg-success">📝 寫作練習</span>`,
    `<span class="badge-module badge bg-primary">🎤 跟讀練習</span>`,
    `<span class="badge-module badge bg-purple" style="background:#7c3aed">🎭 角色扮演+報告</span>`,
    `<span class="badge-module badge bg-info">📓 心得撰寫</span>`,
  ].filter(Boolean).join(' ');

  document.getElementById('summaryContent').innerHTML = `
    <div class="row g-3">
      <div class="col-12">
        <div class="summary-row"><span class="summary-label text-muted">啟用模組</span><span class="summary-value">${modBadges}</span></div>
        <div class="summary-row"><span class="summary-label text-muted">標題</span><span class="summary-value">${escHtml(title)}</span></div>
        ${desc ? `<div class="summary-row"><span class="summary-label text-muted">說明</span><span class="summary-value">${escHtml(desc)}</span></div>` : ''}
        ${ctx ? `<div class="summary-row"><span class="summary-label text-muted">AI 主題背景</span><span class="summary-value text-info">${escHtml(ctx)}</span></div>` : ''}
        <div class="summary-row"><span class="summary-label text-muted">題組來源</span><span class="summary-value">${escHtml(questionSetLabel)}</span></div>
        <div class="summary-row"><span class="summary-label text-muted">四題核心題意</span><span class="summary-value"><ol class="mb-0 ps-3 mt-0">${qs.map(q=>`<li>${escHtml(q)}</li>`).join('')}</ol></span></div>
        ${classes.length ? `<div class="summary-row"><span class="summary-label text-muted">指定班級</span><span class="summary-value">${classes.map(c=>`<span class="badge bg-info">${escHtml(c)}</span>`).join(' ')}</span></div>` : ''}
        ${startDisplay ? `<div class="summary-row"><span class="summary-label text-muted">開放日期</span><span class="summary-value">${escHtml(startDisplay)}</span></div>` : ''}
        ${dueDisplay ? `<div class="summary-row"><span class="summary-label text-muted">截止日期</span><span class="summary-value">${escHtml(dueDisplay)}</span></div>` : ''}
        <div class="summary-row"><span class="summary-label text-muted">狀態</span><span class="summary-value"><span class="badge ${isActive?'bg-success':'bg-secondary'}">${isActive?'立即啟用':'草稿（停用）'}</span></span></div>
      </div>
      <div class="col-12 border-top pt-3 mt-1">
        <div class="text-muted small fw-semibold mb-2">評分設定：</div>
        <div class="summary-row"><span class="summary-label text-muted">評分規準</span><span class="summary-value">${escHtml(document.getElementById('rubricSelect').selectedOptions[0]?.textContent || '未選擇')}</span></div>
      </div>
    </div>`;
}

// ── Submit ────────────────────────────────────────────────────────────────
async function submitAssignment() {
  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>建立中...';

  const questionSetKey = document.getElementById('s2QuestionSet').value;

  const payload = {
    title: document.getElementById('s2Title').value.trim(),
    description: document.getElementById('s2Desc').value.trim() || null,
    prompt_context: document.getElementById('s2Context').value.trim() || null,
    rubric_version_id: parseInt(document.getElementById('rubricSelect').value),
    course_nums: getTagsFromWrap('s2ClassWrap'),
    start_date: document.getElementById('s2StartDate').value || null,
    due_date: document.getElementById('s2DueDate').value || null,
    is_active: document.getElementById('s2IsActive').checked,
  };
  if (questionSetKey === 'custom') {
    payload.question_set_key = null;
    payload.questions = selectedQuestions();
  } else {
    payload.question_set_key = questionSetKey;
  }

  const res = await fetch('/api/admin/assignments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const el = document.getElementById('step4Alert');
    el.className = 'alert alert-danger';
    el.textContent = err.detail || '建立失敗，請稍後再試';
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-check-circle me-1"></i>建立作業';
    return;
  }

  window.location.href = '/admin/assignments?created=1';
}

// ── Tag input ─────────────────────────────────────────────────────────────
function focusTagInput(id) { document.getElementById(id).focus(); }

function getTagsFromWrap(wrapId) {
  return Array.from(document.getElementById(wrapId).querySelectorAll('.tag-badge')).map(b => b.dataset.value);
}

function handleTagKey(e, wrapId, inputId) {
  if (e.key !== 'Enter' && e.key !== ',') return;
  e.preventDefault();
  const input = document.getElementById(inputId);
  const val = input.value.trim().replace(/,/g,'');
  if (!val) return;
  const wrap = document.getElementById(wrapId);
  if (getTagsFromWrap(wrapId).includes(val)) { input.value=''; return; }
  addTagBadge(wrap, input, val);
  input.value = '';
}

function addTagBadge(wrap, input, value) {
  const badge = document.createElement('span');
  badge.className = 'tag-badge badge bg-info text-white d-flex align-items-center gap-1';
  badge.dataset.value = value;
  const text = document.createTextNode(value + ' ');
  const btn = document.createElement('span');
  btn.style.cssText = 'cursor:pointer;font-size:1.1em;line-height:1';
  btn.textContent = '×';
  btn.addEventListener('click', e => { e.stopPropagation(); badge.remove(); });
  badge.append(text, btn);
  wrap.insertBefore(badge, input);
}

// ── Load classes hint ─────────────────────────────────────────────────────
async function loadClassHint() {
  await window._adminReady;
  try {
    const res = await fetch('/api/admin/classes');
    const classes = await res.json();
    if (classes.length) {
      document.getElementById('s2ClassHint').textContent = `現有班級：${classes.join('、')}`;
    }
  } catch(_) {}
}

// ── Init ──────────────────────────────────────────────────────────────────
updateFlowPreview();
AdminWorkflow.ready().then(updateFlowPreview);
loadClassHint();
loadRubrics();
loadQuestionSets();
dtpS2Start = new DateTimePicker('s2StartDate', { placeholder: '（不限）' });
dtpS2Due = new DateTimePicker('s2DueDate', { placeholder: '（不限）' });
document.addEventListener('click', () => { DateTimePicker.closeAll(); });

Object.assign(window, {
  toggleModule,
  updateFlowPreview,
  selectedQuestions,
  updateQuestionSetUI,
  loadQuestionSets,
  loadRubrics,
  goStep,
  validateStep2,
  showStep2Alert,
  renderSummary,
  submitAssignment,
  focusTagInput,
  getTagsFromWrap,
  handleTagKey,
  addTagBadge,
  loadClassHint,
});
