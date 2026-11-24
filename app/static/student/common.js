// Shared utilities for student assignment pages.

const STUDENT_PRACTICE_PATH = /^\/student\/assignment\/\d+\/(?:job-profile|writing|shadowing|roleplay|report|reflection)\/?$/;

function isEmbeddedDesktopPracticePage() {
  try {
    return window.self !== window.top && window.parent.__desktopPracticeShell === true;
  } catch (_) {
    return false;
  }
}

function navigateStudentPage(url, { replace = false } = {}) {
  const target = new URL(url, window.location.href);
  if (
    isEmbeddedDesktopPracticePage()
    && !(target.origin === window.location.origin && STUDENT_PRACTICE_PATH.test(target.pathname))
  ) {
    window.parent.postMessage({
      type: 'desktop-practice-leave',
      href: target.href,
      replace,
    }, window.location.origin);
    return;
  }
  if (replace) window.location.replace(target.href);
  else window.location.href = target.href;
}

// Normal same-origin links should leave the persistent desktop practice shell.
// Assignment links continue to navigate inside its iframe so fullscreen stays active.
(function installDesktopPracticeLinkRouting() {
  if (!isEmbeddedDesktopPracticePage()) return;
  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.target.closest?.('a[href]');
    if (!anchor || anchor.hasAttribute('download') || anchor.dataset.action) return;
    const target = new URL(anchor.href, window.location.href);
    if (target.origin === window.location.origin && STUDENT_PRACTICE_PATH.test(target.pathname)) return;
    event.preventDefault();
    navigateStudentPage(target.href);
  }, true);
})();

function clearStudentAuthState() {
  ['role', 'name', 'user_id', 'userId', 'studentId', 'must_change_password', 'requires_legal_acknowledgement', 'isPrivilegedAdmin']
    .forEach(key => sessionStorage.removeItem(key));
}

function redirectToStudentLogin(message = '登入逾期，請重新登入。') {
  clearStudentAuthState();
  sessionStorage.setItem('loginAlert', message);
  navigateStudentPage('/login', { replace: true });
}

window.ApiUnauthorizedHandler = async response => {
  let message = '登入逾期，請重新登入。';
  try { message = (await response.json()).detail || message; } catch (_) {}
  redirectToStudentLogin(message);
};

const StudentApiClientReady = import('/static/js/api-client.mjs');
const studentNativeFetch = window.fetch.bind(window);
window.StudentApiClientReady = StudentApiClientReady;
window.StudentApiNativeFetch = studentNativeFetch;
window.fetch = (url, options = {}) => {
  const sameOrigin = typeof url === 'string'
    && (url.startsWith('/') || url.startsWith(window.location.origin));
  if (!sameOrigin) return studentNativeFetch(url, options);
  return StudentApiClientReady.then(({ apiRequest }) => apiRequest(url, options, studentNativeFetch));
};
// Each page must set window.CURRENT_SECTION (int) and window.PAGE_PATH (string) before loading this file.
// Pages declare top-level `let assignment`, `let submission`, `let viewedSubmission`, `let assignmentId`, `let viewId`
// which are window-scoped in non-module scripts and readable here as window.*.

window.studentAuthReady = (async function () {
  try {
    const r = await fetch('/api/auth/me', { credentials: 'include' });
    if (r.status === 401) {
      redirectToStudentLogin();
      return new Promise(() => {});
    }
    if (!r.ok) throw new Error(`auth_${r.status}`);
    const data = await r.json();
    sessionStorage.setItem('role', data.role);
    sessionStorage.setItem('name', data.name);
    sessionStorage.setItem('must_change_password', data.must_change_password ? '1' : '0');
    sessionStorage.setItem('requires_legal_acknowledgement', data.requires_legal_acknowledgement ? '1' : '0');
    if ((data.must_change_password || data.requires_legal_acknowledgement) && location.pathname !== '/student') {
      navigateStudentPage('/student', { replace: true });
      return new Promise(() => {});
    }
    if (data.role === 'admin') {
      navigateStudentPage('/admin', { replace: true });
      return new Promise(() => {});
    }
    if (data.role !== 'student') {
      redirectToStudentLogin('此帳號無法使用學生介面。');
      return new Promise(() => {});
    }
    return data;
  } catch (_) {
    redirectToStudentLogin('目前無法確認登入狀態，請重新登入。');
    return new Promise(() => {});
  }
})();

// Rotate token once per hour to keep the JWT alive without per-page-load races.
(function () {
  const HOUR = 60 * 60 * 1000;
  function _scheduleRefresh() {
    setTimeout(async function () {
      try {
        const r = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
        if (r.status === 401) {
          redirectToStudentLogin();
          return;
        }
      } catch (_) {}
      _scheduleRefresh();
    }, HOUR);
  }
  _scheduleRefresh();
})();

function getView() { return viewedSubmission || submission; }

let studentWorkflowLimits = null;

function setWorkflowLimits(limits) {
  const required = [
    'max_attempts',
    'max_feedback_count',
    'max_shadowing_attempts',
    'core_question_count',
    'reflection_question_count',
    'secret_question_source_index',
    'max_roleplay_turns',
  ];
  if (!limits || required.some(name => !Number.isInteger(Number(limits[name])) || Number(limits[name]) < 1)) {
    throw new Error('伺服器未提供完整的學習流程限制。');
  }
  studentWorkflowLimits = Object.freeze(Object.fromEntries(
    required.map(name => [name, Number(limits[name])]),
  ));
  return studentWorkflowLimits;
}

function workflowLimit(name) {
  if (!studentWorkflowLimits || !(name in studentWorkflowLimits)) {
    throw new Error(`尚未載入流程限制：${name}`);
  }
  return studentWorkflowLimits[name];
}

function renderAttemptBadge(view = submission) {
  const badge = document.getElementById('attemptBadge');
  if (!badge || !view) return;
  badge.textContent = `第 ${view.attempt_number} / ${workflowLimit('max_attempts')} 次嘗試`;
  badge.classList.remove('d-none');
}

async function loadViewedSubmissionForAssignment(requestedViewId, expectedAssignmentId) {
  if (!requestedViewId) return null;
  const response = await apiCall(`/api/student/submissions/${requestedViewId}`);
  let data = null;
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) {
    throw new Error((data && data.detail) || '無法載入這筆練習紀錄。');
  }
  if (Number(data.assignment_id) !== Number(expectedAssignmentId)) {
    throw new Error('這筆練習紀錄不屬於目前的作業。');
  }
  return data;
}

function renderStudentPageLoadError(error) {
  const loading = document.getElementById('loadingMsg');
  if (!loading) return;
  loading.innerHTML = `<p class="text-danger">${escHtml(error?.message || '載入失敗')}</p>`;
}

// True once the current assignment's deadline has passed AND there is no active
// late-submission window. Past the due date the work stays viewable but becomes
// read-only — interactive pages use this to hide editing controls (the backend
// also rejects any stage-advancing call after due / after late_deadline).
function isPastDue() {
  if (typeof assignment === 'undefined' || !assignment || !assignment.due_date) return false;
  if (new Date() <= new Date(assignment.due_date)) return false;
  const sub = typeof submission !== 'undefined' ? submission : null;
  if (sub && sub.late_deadline && new Date() < new Date(sub.late_deadline)) return false;
  return true;
}

async function logout() {
  try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }); } catch (_) {}
  sessionStorage.clear();
  navigateStudentPage('/login');
}

function authHeaders() { return { 'Content-Type': 'application/json' }; }

function escHtml(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function escAttr(s) {
  return escHtml(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function tryParseJson(str) { try { return typeof str === 'object' ? str : JSON.parse(str); } catch { return null; } }

function getLearningScaffold(view = getView()) {
  return view && view.learning_scaffold_status === 'ready' && view.learning_scaffold
    ? view.learning_scaffold
    : null;
}

function learningScaffoldQuestion(view, index) {
  const scaffold = getLearningScaffold(view);
  if (!scaffold || !Array.isArray(scaffold.questions)) return null;
  return scaffold.questions.find(item => Number(item.index) === Number(index)) || null;
}

function _scaffoldList(items) {
  return `<ul class="personalized-scaffold-list">${(items || []).map(item => `<li>${escHtml(item)}</li>`).join('')}</ul>`;
}

function _scaffoldChips(items, className, label, itemClass = '') {
  const cls = itemClass ? ` class="${itemClass}"` : '';
  return items.length
    ? `<div class="${className}" aria-label="${escAttr(label)}">${items.map(item => `<span${cls}>${escHtml(item)}</span>`).join('')}</div>`
    : '';
}

// Only AI-generated, job-specific guidance is shown. Nothing renders until
// the scaffold for this attempt is ready.
function learningScaffoldQuestionHtml(view, index, stage) {
  const item = learningScaffoldQuestion(view, index);
  if (!item) return '';
  const keywords = Array.isArray(item.keywords) ? item.keywords : [];
  const starters = Array.isArray(item.sentence_starters) ? item.sentence_starters : [];
  const parts = [];
  if (stage === 'writing') {
    if (item.role_connection) parts.push(`<p>${escHtml(item.role_connection)}</p>`);
    if (Array.isArray(item.experience_prompts)) parts.push(_scaffoldList(item.experience_prompts));
  } else if (stage === 'roleplay') {
    if (item.roleplay_focus) parts.push(`<p>${escHtml(item.roleplay_focus)}</p>`);
  }
  parts.push(_scaffoldChips(keywords, 'personalized-scaffold-keywords', '關鍵字'));
  parts.push(_scaffoldChips(starters, 'sentence-starters mt-2', '句子開頭', 'sentence-starter'));
  const body = parts.join('');
  if (!body) return '';
  return `<aside class="personalized-scaffold" aria-label="Q${Number(index) + 1} 提示">${body}</aside>`;
}

function learningScaffoldInlineHtml(view, index, stage) {
  const content = learningScaffoldQuestionHtml(view, index, stage);
  if (!content) return '';
  return `<details class="question-scaffold-details" open>
    <summary>Q${Number(index)+1} 提示</summary>
    ${content}
  </details>`;
}

// Wraps AI guidance for a page. Returns '' when there is nothing to show.
function renderAiGuide(view, html = '') {
  const status = renderLearningScaffoldStatus(view);
  if (!status && !html) return '';
  return `<section class="ai-guide">${status}${html}</section>`;
}

function renderLearningScaffoldStatus(view) {
  if (!view || !view.job_profile_data || !view.question_set_key) return '';
  if (!['missing', 'stale'].includes(view.learning_scaffold_status)) return '';
  const label = view.learning_scaffold_status === 'stale'
    ? '職位資料改過了，提示要重新產生。'
    : '提示還沒產生。';
  return `<div class="learning-scaffold-status" role="status">
    <span><i class="bi bi-info-circle-fill" aria-hidden="true"></i>${escHtml(label)}</span>
    <button type="button" class="btn btn-sm btn-outline-primary" data-action="retryLearningScaffold">產生提示</button>
  </div>`;
}

async function retryLearningScaffold() {
  const active = window.submission || null;
  if (!active || active.submitted_at) return false;
  const buttons = document.querySelectorAll('[data-action="retryLearningScaffold"]');
  buttons.forEach(button => { button.disabled = true; button.textContent = '產生中…'; });
  try {
    const response = await apiCall(`/api/student/submissions/${active.id}/learning-scaffold`, { method: 'POST' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showAlert(data.detail || '提示暫時產生不出來，請稍後再試。');
      return false;
    }
    active.learning_scaffold_status = 'ready';
    active.learning_scaffold = data.scaffold;
    if (typeof renderAll === 'function') renderAll();
    showAlert('提示已產生。', 'success');
    return true;
  } catch (_) {
    showAlert('提示暫時產生不出來，請稍後再試。');
    return false;
  } finally {
    buttons.forEach(button => { button.disabled = false; button.textContent = '產生提示'; });
  }
}

function showAlert(msg, type = 'danger') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast-msg toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => { toast.style.animation = 'toastOut 0.25s ease forwards'; setTimeout(() => toast.remove(), 260); }, 5000);
}

// MediaRecorder uses different containers across browsers (Safari/iOS normally
// records MP4, while Chromium/Firefox commonly use WebM/Ogg).  Keep the native
// MIME type when building the preview/upload Blob; relabelling Safari MP4 bytes
// as audio/webm makes the iOS audio element report a playback error.
function buildRecordedAudio(chunks, mediaRecorder) {
  const chunkWithType = chunks.find(chunk => chunk && chunk.type);
  const mimeType = (mediaRecorder && mediaRecorder.mimeType) ||
    (chunkWithType && chunkWithType.type) || 'audio/webm';
  const normalizedType = mimeType.split(';', 1)[0].toLowerCase();
  const extensions = {
    'audio/mp4': 'm4a',
    'video/mp4': 'mp4',
    'audio/ogg': 'ogg',
    'audio/webm': 'webm',
  };
  return {
    blob: new Blob(chunks, { type: mimeType }),
    filename: `recording.${extensions[normalizedType] || 'audio'}`,
  };
}

function setAudioPreview(audioElement, url) {
  if (!audioElement) return;
  audioElement.src = url;
  // Explicit load is needed by some iOS Safari versions after replacing a
  // blob URL on an existing audio element.
  audioElement.load();
}

async function apiCall(url, options = {}) {
  const { apiRequest } = await StudentApiClientReady;
  const res = await apiRequest(url, options, studentNativeFetch);
  if (res.status === 401) {
    let m = '登入逾期，請重新登入。';
    try { const e = await res.clone().json(); if (e.detail) m = e.detail; } catch (_) {}
    redirectToStudentLogin(m);
  }
  return res;
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  });
}

function getActiveSection(stage) {
  return StudentWorkflow.activeSection(stage, window.CURRENT_SECTION);
}

function navigateSection(section) {
  const viewParam = viewId ? `?view=${viewId}` : '';
  navigateStudentPage(StudentWorkflow.sectionPath(assignmentId, section) + viewParam);
}

function updateProgressSteps(stage) {
  const allSteps = [
    { icon: 'bi-briefcase-fill', section: 1, doneAt: 2 },
    { icon: 'bi-pencil-square', section: 2, doneAt: 5 },
    { icon: 'bi-mic-fill', section: 3, doneAt: 6 },
    { icon: 'bi-chat-dots-fill', section: 4, doneAt: 8 },
    { icon: 'bi-bar-chart-fill', section: 5, doneAt: 8 },
    { icon: 'bi-journal-check', section: 6, doneAt: 9 },
  ];
  allSteps.forEach(step => { step.label = StudentWorkflow.sectionLabel(step.section); });
  const steps = allSteps;
  const container = document.getElementById('progressSteps');
  const activeSection = getActiveSection(stage);
  container.innerHTML = steps.map(s => {
    const isDone = stage >= s.doneAt;
    const isActive = s.section === activeSection && !isDone;
    const isClickable = isDone || isActive;
    const isCurrentPage = s.section === (window.CURRENT_SECTION || 0);
    const cls = [isDone ? 'done' : isActive ? 'active' : 'pending', isCurrentPage ? 'viewing' : ''].join(' ');
    const icon = isDone ? 'bi-check-circle-fill' : s.icon;
    return `<div class="progress-step ${cls}" ${isClickable ? `data-action="navigateSection" data-args='[${s.section}]'` : ''} title="${s.label}">
        <i class="bi ${icon}"></i>${s.label}
      </div>`;
  }).join('');
}

function exitViewMode() {
  navigateStudentPage(`/student/assignment/${assignmentId}/${window.PAGE_PATH || 'writing'}`);
}

function renderViewBanner() {
  const viewBanner = document.getElementById('viewModeBanner');
  if (!viewBanner) return;
  const isViewingPast = !!viewedSubmission && typeof viewId !== 'undefined' && !!viewId;
  if (isViewingPast) {
    viewBanner.classList.remove('d-none');
    viewBanner.innerHTML = `
      <div class="notice-banner notice-banner-view">
        <div><i class="bi bi-eye me-1 text-brand"></i>
          <strong>正在查看：第 ${viewedSubmission.attempt_number} 次練習結果</strong>
          <span class="text-muted ms-2 small">（唯讀模式）</span>
        </div>
        <button class="btn btn-sm ms-auto btn-outline-brand" data-action="exitViewMode">
          <i class="bi bi-arrow-left me-1"></i>返回當前練習
        </button>
      </div>`;
  } else if (isPastDue()) {
    viewBanner.classList.remove('d-none');
    viewBanner.innerHTML = `
      <div class="notice-banner notice-banner-closed">
        <div><i class="bi bi-calendar-x me-1 text-danger-strong"></i>
          <strong>作業已截止</strong>
          <span class="text-muted ms-2 small">（唯讀模式，可檢視先前作答，但無法繼續或修改）</span>
        </div>
      </div>`;
  } else if ((() => {
    if (typeof assignment === 'undefined' || !assignment || !assignment.due_date) return false;
    if (new Date() <= new Date(assignment.due_date)) return false;
    const sub = typeof submission !== 'undefined' ? submission : null;
    return sub && sub.late_deadline && new Date() < new Date(sub.late_deadline);
  })()) {
    viewBanner.classList.remove('d-none');
    const sub = typeof submission !== 'undefined' ? submission : null;
    const lateStr = sub && sub.late_deadline ? new Date(sub.late_deadline).toLocaleString('zh-TW') : '';
    viewBanner.innerHTML = `
      <div class="notice-banner notice-banner-late">
        <div><i class="bi bi-calendar-plus me-1 text-amber"></i>
          <strong class="text-amber-dark">補繳期間</strong>
          <span class="text-muted ms-2 small">（補繳截止：${lateStr}，請在期限前完成並提交）</span>
        </div>
      </div>`;
  } else {
    viewBanner.classList.add('d-none');
  }
}
