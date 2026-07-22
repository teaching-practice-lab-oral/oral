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

const StudentApiClientReady = import('/static/js/api-client.mjs?v=2');
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

function getLearningSupport(view = getView()) {
  const attemptNumber = Math.min(
    workflowLimit('max_attempts'),
    Math.max(1, Number(view && view.attempt_number) || 1),
  );
  if (attemptNumber === 1) return { attemptNumber, mode: 'guided', badge: '第 1 次｜跟著提示做' };
  if (attemptNumber === 2) return { attemptNumber, mode: 'supported', badge: '第 2 次｜先自己做' };
  return { attemptNumber, mode: 'independent', badge: `第 ${attemptNumber} 次｜獨立完成` };
}

function getLearningScaffold(view = getView()) {
  return view && view.learning_scaffold_status === 'ready' && view.learning_scaffold
    ? view.learning_scaffold
    : null;
}

function learningScaffoldQuestion(view, index) {
  const scaffold = getLearningScaffold(view);
  if (scaffold && Array.isArray(scaffold.questions)) {
    return scaffold.questions.find(item => Number(item.index) === Number(index)) || null;
  }
  const fallback = window.assignment && Array.isArray(window.assignment.question_scaffolds)
    ? window.assignment.question_scaffolds
    : [];
  return fallback.find(item => Number(item.index) === Number(index)) || null;
}

function learningScaffoldStarters(view, index, fallback = []) {
  const item = learningScaffoldQuestion(view, index);
  if (item && Array.isArray(item.sentence_starters) && item.sentence_starters.length) {
    return item.sentence_starters;
  }
  if (item && Array.isArray(item.starters) && item.starters.length) return item.starters;
  return fallback;
}

function _scaffoldList(items) {
  return `<ul class="personalized-scaffold-list">${(items || []).map(item => `<li>${escHtml(item)}</li>`).join('')}</ul>`;
}

function learningScaffoldQuestionHtml(view, index, stage, answerText = '') {
  const item = learningScaffoldQuestion(view, index);
  if (!item) return '';
  const keywordSource = Array.isArray(item.keywords) ? item.keywords : [];
  const answer = String(answerText || '').toLocaleLowerCase();
  const keywords = stage === 'shadowing'
    ? keywordSource.filter(keyword => answer.includes(String(keyword).toLocaleLowerCase()))
    : keywordSource;
  const keywordHtml = keywords.length
    ? `<div class="personalized-scaffold-keywords" aria-label="職位關鍵字">${keywords.map(keyword => `<span>${escHtml(keyword)}</span>`).join('')}</div>`
    : '';
  const stageFocus = stage === 'shadowing'
    ? item.shadowing_focus
    : stage === 'roleplay' ? item.roleplay_focus : '';
  return `<aside class="personalized-scaffold" aria-label="Q${Number(index) + 1} 個人化鷹架">
    <div class="personalized-scaffold-title"><i class="bi bi-person-check-fill" aria-hidden="true"></i>Q${Number(index) + 1}｜依你的職位調整</div>
    <p><strong>這題要證明：</strong>${escHtml(item.goal)}</p>
    ${stage === 'writing' ? `<div><strong>回答順序：</strong>${_scaffoldList(item.steps)}</div><p><strong>找證據：</strong>${escHtml(item.evidence)}</p>` : ''}
    ${item.role_connection ? `<p><strong>職位連結：</strong>${escHtml(item.role_connection)}</p>` : ''}
    ${stageFocus ? `<p><strong>本階段焦點：</strong>${escHtml(stageFocus)}</p>` : ''}
    ${stage !== 'shadowing' && Array.isArray(item.experience_prompts) ? `<div><strong>想一想：</strong>${_scaffoldList(item.experience_prompts)}</div>` : ''}
    ${keywordHtml}
  </aside>`;
}

function learningScaffoldInlineHtml(view, index, stage, answerText = '') {
  const support = getLearningSupport(view);
  if (support.mode === 'independent') return '';
  const content = learningScaffoldQuestionHtml(view, index, stage, answerText);
  if (!content) return '';
  return `<details class="question-scaffold-details" ${support.mode === 'guided' ? 'open' : ''}>
    <summary>Q${Number(index)+1} 的${getLearningScaffold(view)?'職位化':'專屬'}作答鷹架</summary>
    ${content}
  </details>`;
}

function learningScaffoldStageHtml(view, stage) {
  const scaffold = getLearningScaffold(view);
  if (!scaffold) return '';
  const field = {
    job_profile: 'job_profile_focus',
    report: 'report_focus',
    reflection: 'reflection_focus',
  }[stage];
  if (!field || !scaffold[field]) return '';
  return `<aside class="personalized-scaffold" aria-label="個人化階段焦點">
    <div class="personalized-scaffold-title"><i class="bi bi-person-check-fill" aria-hidden="true"></i>依你的職位調整</div>
    <p><strong>本次面試重點：</strong>${escHtml(scaffold.position_focus)}</p>
    <p><strong>這一階段：</strong>${escHtml(scaffold[field])}</p>
    ${_scaffoldList(scaffold.competency_priorities || [])}
  </aside>`;
}

function learningScaffoldModuleHtml() {
  const items = window.assignment && Array.isArray(window.assignment.question_scaffolds)
    ? window.assignment.question_scaffolds
    : [];
  if (!items.length) return '';
  return `<aside class="personalized-scaffold" aria-label="四題不同的準備重點">
    <div class="personalized-scaffold-title"><i class="bi bi-list-check" aria-hidden="true"></i>這四題要準備不同證據</div>
    <ol class="personalized-scaffold-list">${items.map(item => `<li><strong>Q${Number(item.index) + 1}：</strong>${escHtml(item.goal)}</li>`).join('')}</ol>
  </aside>`;
}

function learningScaffoldPositionHtml(view) {
  const scaffold = getLearningScaffold(view);
  if (!scaffold || !scaffold.position_focus) return '';
  return `<aside class="personalized-scaffold" aria-label="本次職位面試重點">
    <div class="personalized-scaffold-title"><i class="bi bi-briefcase-fill" aria-hidden="true"></i>本次職位面試重點</div>
    <p>${escHtml(scaffold.position_focus)}</p>
    ${_scaffoldList(scaffold.competency_priorities || [])}
  </aside>`;
}

function renderLearningScaffoldStatus(view) {
  if (!view || !view.job_profile_data || !view.question_set_key) return '';
  if (!['missing', 'stale'].includes(view.learning_scaffold_status)) return '';
  const label = view.learning_scaffold_status === 'stale'
    ? '職位資料或題目已更新，先前的個人化提示不再使用。'
    : '個人化提示尚未建立，目前仍可使用每題不同的公版鷹架。';
  return `<div class="learning-scaffold-status" role="status">
    <span><i class="bi bi-info-circle-fill" aria-hidden="true"></i>${escHtml(label)}</span>
    <button type="button" class="btn btn-sm btn-outline-primary" data-action="retryLearningScaffold">重新產生個人化提示</button>
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
      showAlert(data.detail || '個人化提示暫時無法產生；可使用公版提示繼續。');
      return false;
    }
    active.learning_scaffold_status = 'ready';
    active.learning_scaffold = data.scaffold;
    if (typeof renderAll === 'function') renderAll();
    showAlert('已依你的職位建立四題不同的個人化提示。', 'success');
    return true;
  } catch (_) {
    showAlert('個人化提示暫時無法產生；可使用公版提示繼續。');
    return false;
  } finally {
    buttons.forEach(button => { button.disabled = false; button.textContent = '重新產生個人化提示'; });
  }
}

function _taskGuideList(items, icon) {
  return (items || []).map(item => `<li><i class="bi ${icon}" aria-hidden="true"></i><span>${escHtml(item)}</span></li>`).join('');
}

function _taskGuideSupport({ support, starters, persistentHtml }, learningSupport) {
  // support.html and persistentHtml are caller-owned markup. Callers must
  // escape every dynamic value before passing either trusted HTML slot.
  const alwaysHtml = persistentHtml || (support && support.persistentHtml) || '';
  if (learningSupport.mode === 'independent') return alwaysHtml;

  const help = support || {};
  const helpItems = _taskGuideList(help.items || [], 'bi-lightbulb');
  const helpHtml = help.html || '';
  const starterHtml = (starters || []).length
    ? `<div class="sentence-starters" aria-label="作答句架">${starters.map(item => `<span class="sentence-starter">${escHtml(item)}</span>`).join('')}</div>`
    : '';
  if (!helpItems && !helpHtml && !starterHtml) return alwaysHtml;

  const content = `${helpItems ? `<ul class="task-guide-help-list">${helpItems}</ul>` : ''}${helpHtml}${starterHtml}`;
  if (learningSupport.mode === 'guided') {
    return `<section class="task-guide-support task-guide-support-open" aria-label="卡住時">
      <h6><i class="bi bi-life-preserver" aria-hidden="true"></i>${escHtml(help.title || '卡住時')}</h6>
      ${content}
    </section>${alwaysHtml}`;
  }
  return `<details class="task-guide-support task-guide-support-collapsed">
    <summary><i class="bi bi-lightbulb" aria-hidden="true"></i>${escHtml(help.title || '卡住時')}（需要時再展開）</summary>
    <div class="task-guide-support-body">${content}</div>
  </details>${alwaysHtml}`;
}

function renderTaskGuide({
  title,
  progress = '',
  actions = [],
  support = null,
  starters = [],
  persistentHtml = '',
  checks = [],
  next = '',
  view = getView(),
  state = 'active',
}) {
  const learningSupport = getLearningSupport(view);
  const isReview = state === 'completed' || state === 'read-only';
  const stateLabel = state === 'completed' ? '這個階段已完成' : '唯讀回顧';
  if (isReview) {
    return `<section class="task-guide task-guide-review" aria-label="${escAttr(title)}任務回顧">
      <div class="task-guide-heading">
        <div>
          <div class="task-guide-kicker">${stateLabel}</div>
          <h5>${escHtml(title)}</h5>
        </div>
        <span class="learning-mode learning-mode-${learningSupport.mode}">${escHtml(learningSupport.badge)}</span>
      </div>
      ${progress ? `<div class="task-guide-progress">${escHtml(progress)}</div>` : ''}
      ${next ? `<div class="task-guide-next"><i class="bi bi-arrow-repeat" aria-hidden="true"></i><span><strong>回看重點：</strong>${escHtml(next)}</span></div>` : ''}
    </section>`;
  }

  return `<section class="task-guide" aria-label="${escAttr(title)}任務導航">
    <div class="task-guide-heading">
      <div>
        <div class="task-guide-kicker">現在的任務</div>
        <h5>${escHtml(title)}</h5>
      </div>
      <span class="learning-mode learning-mode-${learningSupport.mode}">${escHtml(learningSupport.badge)}</span>
    </div>
    ${progress ? `<div class="task-guide-progress">${escHtml(progress)}</div>` : ''}
    ${renderLearningScaffoldStatus(view)}
    <div class="task-guide-grid">
      <div>
        <h6><i class="bi bi-cursor-fill" aria-hidden="true"></i>現在做</h6>
        <ol class="task-guide-actions">${actions.map(item => `<li>${escHtml(item)}</li>`).join('')}</ol>
      </div>
      <div>
        <h6><i class="bi bi-ui-checks" aria-hidden="true"></i>完成條件</h6>
        <ul class="task-guide-checks">${_taskGuideList(checks, 'bi-check2-circle')}</ul>
      </div>
    </div>
    ${_taskGuideSupport({ support, starters, persistentHtml }, learningSupport)}
    ${next ? `<div class="task-guide-next"><i class="bi bi-arrow-right-circle-fill" aria-hidden="true"></i><span><strong>完成後：</strong>${escHtml(next)}</span></div>` : ''}
  </section>`;
}

(function injectLearningGuideStyles() {
  if (document.getElementById('studentLearningGuideStyles')) return;
  const style = document.createElement('style');
  style.id = 'studentLearningGuideStyles';
  style.textContent = `
    .task-guide{background:linear-gradient(135deg,#eef2ff 0%,#f8fafc 100%);border:1px solid #c7d2fe;border-radius:16px;padding:1rem 1.1rem;margin-bottom:1.25rem;color:#1e293b}
    .task-guide-review{background:linear-gradient(135deg,#f0fdf4 0%,#f8fafc 100%);border-color:#bbf7d0}
    .task-guide-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:.75rem;flex-wrap:wrap;margin-bottom:.7rem}
    .task-guide-heading h5{font-size:1.05rem;font-weight:800;margin:0}.task-guide-kicker{color:#6366f1;font-size:.73rem;font-weight:800;letter-spacing:.08em;margin-bottom:.15rem}.task-guide-review .task-guide-kicker{color:#15803d}
    .learning-mode{border-radius:999px;padding:.3rem .7rem;font-size:.76rem;font-weight:800;white-space:nowrap}.learning-mode-guided{background:#fef3c7;color:#92400e}.learning-mode-supported{background:#e0f2fe;color:#075985}.learning-mode-independent{background:#dcfce7;color:#166534}
    .task-guide-progress{display:inline-flex;align-items:center;background:#fff;border:1px solid #cbd5e1;border-radius:999px;color:#475569;font-size:.78rem;font-weight:700;padding:.23rem .62rem;margin:0 0 .75rem}
    .task-guide-grid{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}.task-guide-grid>div{background:rgba(255,255,255,.82);border:1px solid #e2e8f0;border-radius:12px;padding:.75rem .85rem}
    .task-guide-grid h6,.task-guide-support h6{font-size:.86rem;font-weight:800;margin:0 0 .5rem}.task-guide-grid h6 i,.task-guide-support h6 i{color:#4f46e5;margin-right:.4rem}
    .task-guide-actions{margin:0;padding-left:1.2rem;font-size:.87rem}.task-guide-actions li+li{margin-top:.32rem}.task-guide-checks,.task-guide-help-list{list-style:none;margin:0;padding:0;font-size:.87rem}.task-guide-checks li,.task-guide-help-list li{display:flex;gap:.4rem;align-items:flex-start}.task-guide-checks li+li,.task-guide-help-list li+li{margin-top:.32rem}.task-guide-checks i{color:#059669;margin-top:.08rem}.task-guide-help-list i{color:#d97706;margin-top:.08rem}
    .task-guide-support{border-radius:12px;margin-top:.75rem;padding:.75rem .85rem}.task-guide-support-open{background:#fffbeb;border:1px solid #fde68a}.task-guide-support-collapsed{background:#fff;border:1px solid #cbd5e1}.task-guide-support summary{cursor:pointer;font-size:.88rem;font-weight:800;color:#334155}.task-guide-support summary i{color:#d97706;margin-right:.4rem}.task-guide-support-body{padding-top:.75rem}.task-guide-support .sentence-starters{margin-top:.6rem}
    .task-guide-next{display:flex;align-items:flex-start;gap:.45rem;background:#fff;border-left:3px solid #4f46e5;border-radius:0 8px 8px 0;padding:.55rem .7rem;margin-top:.8rem;font-size:.87rem}.task-guide-next i{color:#4f46e5}
    .planning-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;margin-bottom:.7rem}.planning-step{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:.65rem .7rem}.planning-step strong{display:block;font-size:.86rem;margin-bottom:.2rem}.planning-step span{color:#64748b;font-size:.8rem}
    .sentence-starters{display:flex;gap:.35rem;flex-wrap:wrap}.sentence-starter{display:inline-block;background:#fff;border:1px solid #f59e0b;color:#92400e;border-radius:999px;padding:.2rem .58rem;font-size:.77rem}
    .learning-scaffold-status{display:flex;align-items:center;justify-content:space-between;gap:.75rem;flex-wrap:wrap;background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a;border-radius:12px;padding:.7rem .8rem;margin-top:.75rem;font-size:.86rem}.learning-scaffold-status i{margin-right:.4rem}.personalized-scaffold{background:#eefbf5;border:1px solid #a7f3d0;border-radius:12px;padding:.75rem .85rem;margin-top:.7rem;color:#164e3f}.personalized-scaffold-title{font-weight:800;margin-bottom:.45rem}.personalized-scaffold-title i{margin-right:.4rem;color:#059669}.personalized-scaffold p{font-size:.84rem;margin:0 0 .45rem}.personalized-scaffold-list{font-size:.84rem;margin:.25rem 0 .5rem;padding-left:1.15rem}.personalized-scaffold-keywords{display:flex;gap:.35rem;flex-wrap:wrap;margin-top:.45rem}.personalized-scaffold-keywords span{background:#fff;border:1px solid #6ee7b7;border-radius:999px;padding:.18rem .55rem;font-size:.76rem;color:#065f46}
    .question-scaffold-details{margin:.65rem 0;background:#fff;border:1px solid #a7f3d0;border-radius:10px;padding:.55rem .7rem}.question-scaffold-details>summary{cursor:pointer;color:#047857;font-size:.82rem;font-weight:800}.question-scaffold-details .personalized-scaffold{border:0;background:transparent;padding:.55rem 0 0;margin:0}
    .task-guide-persistent{background:#fff;border:1px solid #dbeafe;border-radius:12px;padding:.75rem .85rem;margin-top:.75rem}
    @media(max-width:767.98px){.task-guide-grid,.planning-grid{grid-template-columns:1fr}.task-guide{padding:.9rem}.learning-mode{white-space:normal}}
  `;
  document.head.appendChild(style);
})();

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
      <div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:12px;padding:0.9rem 1.25rem;display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
        <div><i class="bi bi-eye me-1" style="color:#4f46e5;"></i>
          <strong>正在查看：第 ${viewedSubmission.attempt_number} 次練習結果</strong>
          <span class="text-muted ms-2 small">（唯讀模式）</span>
        </div>
        <button class="btn btn-sm ms-auto" style="border:1.5px solid #4f46e5;color:#4f46e5;background:white;border-radius:8px;font-weight:600;" data-action="exitViewMode">
          <i class="bi bi-arrow-left me-1"></i>返回當前練習
        </button>
      </div>`;
  } else if (isPastDue()) {
    viewBanner.classList.remove('d-none');
    viewBanner.innerHTML = `
      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:0.9rem 1.25rem;display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
        <div><i class="bi bi-calendar-x me-1" style="color:#dc2626;"></i>
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
      <div style="background:#fffbeb;border:1px solid #fcd34d;border-radius:12px;padding:0.9rem 1.25rem;display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
        <div><i class="bi bi-calendar-plus me-1" style="color:#d97706;"></i>
          <strong style="color:#b45309;">補繳期間</strong>
          <span class="text-muted ms-2 small">（補繳截止：${lateStr}，請在期限前完成並提交）</span>
        </div>
      </div>`;
  } else {
    viewBanner.classList.add('d-none');
  }
}
