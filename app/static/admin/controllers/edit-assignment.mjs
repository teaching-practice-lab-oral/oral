const pathParts = location.pathname.split('/');
const assignmentId = parseInt(pathParts[3]);

let assignment = null;
let dtpStart, dtpDue;
let questionSets = [];

function toLocalInput(dt) {
  if (!dt) return '';
  const d = new Date(dt);
  return new Date(d.getTime() - d.getTimezoneOffset()*60000).toISOString().slice(0,16);
}

function showGlobalAlert(msg, type='danger') {
  const el = document.getElementById('globalAlert');
  el.className = `alert alert-${type}`;
  el.textContent = msg;
  el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function showError(msg) {
  document.getElementById('loadingState').classList.add('d-none');
  document.getElementById('errorMsg').textContent = msg;
  document.getElementById('errorState').classList.remove('d-none');
}

function updateRoleplayVisibility() {
  document.getElementById('s6TemplateWrap').style.display = '';
}

function selectedQuestions() {
  const key = document.getElementById('editQuestionSet').value;
  if (key === 'custom') return [0,1,2,3].map(i => document.getElementById(`editQ${i}`).value.trim());
  return (questionSets.find(row => row.key === key)?.questions || []).slice();
}

function updateQuestionSetUI() {
  const key = document.getElementById('editQuestionSet').value;
  const isCustom = key === 'custom';
  document.getElementById('editCustomQuestions').classList.toggle('d-none', !isCustom);
  const questions = selectedQuestions();
  document.getElementById('editQuestionPreview').innerHTML = isCustom
    ? '<span class="text-muted small"><i class="bi bi-pencil me-1"></i>同一組自訂題目會用於寫作、跟讀與角色扮演。</span>'
    : `<ol class="mb-0 ps-3">${questions.map(q => `<li class="mb-1">${escHtml(q)}</li>`).join('')}</ol>`;
}

// ── Tag input helpers ─────────────────────────────────────────────────────
function focusTagInput(inputId) { document.getElementById(inputId).focus(); }

function getTagsFromWrap(wrapId) {
  return Array.from(document.getElementById(wrapId).querySelectorAll('.tag-badge')).map(b => b.dataset.value);
}

function setTagsToWrap(wrapId, inputId, values) {
  const wrap = document.getElementById(wrapId);
  wrap.querySelectorAll('.tag-badge').forEach(b => b.remove());
  const input = document.getElementById(inputId);
  (values || []).forEach(v => { if (v) addTagBadge(wrap, input, v); });
}

function addTagBadge(wrap, input, value) {
  const badge = document.createElement('span');
  badge.className = 'tag-badge badge bg-info text-white d-flex align-items-center gap-1';
  badge.dataset.value = value;
  const text = document.createTextNode(value + ' ');
  const btn = document.createElement('span');
  btn.style.cssText = 'cursor:pointer;font-size:1.1em;line-height:1';
  btn.textContent = '×';
  btn.addEventListener('click', e => { e.stopPropagation(); badge.remove(); });
  badge.append(text, btn);
  wrap.insertBefore(badge, input);
}

function handleTagKey(e, wrapId, inputId) {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    const input = document.getElementById(inputId);
    const val = input.value.trim().replace(/,/g, '');
    if (!val) return;
    const wrap = document.getElementById(wrapId);
    const existing = getTagsFromWrap(wrapId);
    if (!existing.includes(val)) addTagBadge(wrap, input, val);
    input.value = '';
  } else if (e.key === 'Backspace') {
    const input = document.getElementById(inputId);
    if (!input.value) {
      const badges = document.getElementById(wrapId).querySelectorAll('.tag-badge');
      if (badges.length) badges[badges.length - 1].remove();
    }
  }
}

async function loadAvailableClasses() {
  const res = await fetch('/api/admin/classes');
  if (!res.ok) return;
  const classes = await res.json();
  const hint = document.getElementById('editClassHint');
  if (classes.length) hint.innerHTML = `現有課號：${classes.map(c => `<span class="badge bg-light text-dark border me-1" style="cursor:pointer" data-action="addClassTag" data-args='["${escAttr(c)}"]'>${escHtml(c)}</span>`).join('')}`;
}

function addClassTag(val) {
  const wrap = document.getElementById('editClassTagsWrap');
  const input = document.getElementById('editClassTagInput');
  const existing = getTagsFromWrap('editClassTagsWrap');
  if (!existing.includes(val)) addTagBadge(wrap, input, val);
}

// ── Load prompt templates into selects ────────────────────────────────────
async function loadPromptTemplates() {
  try {
    const res = await fetch('/api/admin/prompts');
    if (!res.ok) return;
    const templates = await res.json();
    populateTemplateSelect('editS3Template', templates.filter(t => t.stage === 3), 'face-主題寫作回饋提示詞');
    populateTemplateSelect('editS6Template', templates.filter(t => t.stage === 6), '面試官提示詞');
  } catch(e) { /* ignore, will use system default */ }
}

function populateTemplateSelect(selectId, templates, defaultLabel) {
  const sel = document.getElementById(selectId);
  const currentVal = sel.value;
  // Keep first default option, remove rest
  while (sel.options.length > 1) sel.remove(1);
  templates.filter(t => !t.is_system).forEach(t => {
    const opt = new Option(`${t.name}`, t.id);
    sel.add(opt);
  });
  if (currentVal) sel.value = currentVal;
}

// ── Init ─────────────────────────────────────────────────────────────────
async function init() {
  await window._adminReady;
  if (!assignmentId || isNaN(assignmentId)) { showError('未指定作業 ID'); return; }

  let aRes;
  try {
    aRes = await fetch(`/api/admin/assignments/${assignmentId}`);
  } catch (_) {
    showError('作業資料載入失敗，請檢查網路後重新整理。');
    return;
  }
  if (!aRes.ok) { showError('找不到指定的作業'); return; }
  assignment = await aRes.json();

  let tRes;
  let rRes;
  let qRes;
  try {
    [tRes, rRes, qRes] = await Promise.all([
      fetch('/api/admin/prompts'),
      fetch(`/api/admin/rubrics?include_version_id=${assignment.rubric_version_id}`),
      fetch('/api/admin/question-sets'),
    ]);
  } catch (_) {
    showError('評分規準或作業選項載入失敗，為避免變更原設定，目前無法儲存。');
    return;
  }

  if (!rRes.ok) { showError('評分規準載入失敗，為避免變更原設定，目前無法儲存。'); return; }
  const templates = tRes.ok ? await tRes.json() : [];
  const rubrics = await rRes.json();
  questionSets = qRes.ok ? await qRes.json() : [];

  const assignedRubric = rubrics.find(row => row.version_id === assignment.rubric_version_id);
  if (!assignedRubric) {
    showError('找不到這份作業原本使用的評分規準，為避免變更原設定，目前無法儲存。');
    return;
  }

  // Populate dropdowns
  populateTemplateSelect('editS3Template', templates.filter(t => t.stage === 3));
  populateTemplateSelect('editS6Template', templates.filter(t => t.stage === 6));
  populateTemplateSelect('editS8Template', templates.filter(t => t.stage === 8));
  rubrics.forEach(row => {
    const archivedLabel = row.is_archived ? '（已封存，保留原設定）' : '';
    document.getElementById('editRubric').add(
      new Option(`${row.rubric_name} v${row.version_number}${archivedLabel}`, row.version_id)
    );
  });
  const questionSetSelect = document.getElementById('editQuestionSet');
  questionSets.forEach(row => questionSetSelect.add(new Option(`公版：${row.label}`, row.key)));
  questionSetSelect.add(new Option('自訂題組', 'custom'));

  // Fill basic fields
  document.getElementById('editTitle').value = assignment.title;
  document.getElementById('editDesc').value = assignment.description || '';
  document.getElementById('editPromptContext').value = assignment.prompt_context || '';

  const qs = Array.isArray(assignment.questions) ? assignment.questions : [];
  [0,1,2,3].forEach(i => { document.getElementById(`editQ${i}`).value = qs[i] || ''; });
  questionSetSelect.value = questionSets.some(row => row.key === assignment.question_set_key)
    ? assignment.question_set_key
    : 'custom';
  updateQuestionSetUI();

  setTagsToWrap('editClassTagsWrap', 'editClassTagInput', assignment.course_nums || []);

  document.getElementById('editStartDate').value = toLocalInput(assignment.start_date);
  document.getElementById('editDueDate').value = toLocalInput(assignment.due_date);
  dtpStart.syncFromHidden();
  dtpDue.syncFromHidden();

  // Set template selections
  if (assignment.stage3_template_id) document.getElementById('editS3Template').value = assignment.stage3_template_id;
  if (assignment.stage6_template_id) document.getElementById('editS6Template').value = assignment.stage6_template_id;
  if (assignment.stage8_template_id) document.getElementById('editS8Template').value = assignment.stage8_template_id;
  document.getElementById('editRubric').value = assignment.rubric_version_id;

  updateRoleplayVisibility();

  document.getElementById('pageTitle').innerHTML = `<i class="bi bi-pencil me-2 text-warning"></i>編輯作業：<span class="fw-normal text-secondary">${escHtml(assignment.title)}</span>`;
  document.title = `${assignment.title} - 編輯作業`;

  document.getElementById('loadingState').classList.add('d-none');
  document.getElementById('mainContent').classList.remove('d-none');

  loadAvailableClasses();
}

// ── Save all ──────────────────────────────────────────────────────────────
async function saveAll() {
  const title = document.getElementById('editTitle').value.trim();
  if (!title) { showGlobalAlert('請填寫標題'); return; }
  const questionSetKey = document.getElementById('editQuestionSet').value;
  const questions = selectedQuestions();
  if (!questionSetKey) {
    showGlobalAlert('公版題組載入失敗，請重新整理後再試。');
    return;
  }
  if (questionSetKey === 'custom' && (questions.length !== 4 || questions.some(q => !q))) {
    showGlobalAlert('自訂題組必須填寫全部 4 題，每題不可空白。');
    return;
  }

  const s3TemplateVal = document.getElementById('editS3Template').value;
  const s6TemplateVal = document.getElementById('editS6Template').value;
  const s8TemplateVal = document.getElementById('editS8Template').value;
  const selectedRubricId = Number(document.getElementById('editRubric').value);
  if (!Number.isInteger(selectedRubricId) || selectedRubricId <= 0) {
    showGlobalAlert('評分規準載入失敗，請重新整理後再試。');
    return;
  }

  const classNames = getTagsFromWrap('editClassTagsWrap');
  const payload = {
    title,
    description: document.getElementById('editDesc').value.trim() || null,
    prompt_context: document.getElementById('editPromptContext').value.trim() || null,
    stage3_template_id: s3TemplateVal ? parseInt(s3TemplateVal) : null,
    stage6_template_id: s6TemplateVal ? parseInt(s6TemplateVal) : null,
    stage8_template_id: s8TemplateVal ? parseInt(s8TemplateVal) : null,
    course_nums: classNames,
    start_date: document.getElementById('editStartDate').value || null,
    due_date: document.getElementById('editDueDate').value || null,
  };
  if (selectedRubricId !== assignment.rubric_version_id) {
    payload.rubric_version_id = selectedRubricId;
  }
  if (questionSetKey === 'custom') {
    payload.question_set_key = null;
    payload.questions = questions;
  } else {
    payload.question_set_key = questionSetKey;
  }

  const res = await fetch(`/api/admin/assignments/${assignmentId}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
  });
  if (res.ok) {
    assignment = { ...assignment, ...(await res.json()) };
    updateQuestionSetUI();
    document.getElementById('pageTitle').innerHTML = `<i class="bi bi-pencil me-2 text-warning"></i>編輯作業：<span class="fw-normal text-secondary">${escHtml(assignment.title)}</span>`;
    document.title = `${assignment.title} - 編輯作業`;
    updateRoleplayVisibility();
    showToast('已儲存', 'success');
    document.getElementById('globalAlert').className = 'alert d-none';
  } else {
    const data = await res.json().catch(() => ({}));
    showGlobalAlert(data.detail || '儲存失敗，請稍後再試。');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  dtpStart = new DateTimePicker('editStartDate', { placeholder: '選擇開放日期時間' });
  dtpDue   = new DateTimePicker('editDueDate',   { placeholder: '選擇截止日期時間' });
  document.addEventListener('click', () => {
    DateTimePicker.closeAll();
  });
  init();
});

Object.assign(window, {
  toLocalInput,
  showGlobalAlert,
  showError,
  updateRoleplayVisibility,
  selectedQuestions,
  updateQuestionSetUI,
  focusTagInput,
  getTagsFromWrap,
  setTagsToWrap,
  addTagBadge,
  handleTagKey,
  loadAvailableClasses,
  addClassTag,
  loadPromptTemplates,
  populateTemplateSelect,
  init,
  saveAll,
});
