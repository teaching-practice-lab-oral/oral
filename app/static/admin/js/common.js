// Shared utilities for admin pages.

const AdminWorkflow = (() => {
  let metadata = null;
  const readyPromise = import('/static/js/workflow-contract.mjs?v=1')
    .then(module => module.loadWorkflowMetadata())
    .then(value => { metadata = value; return value; })
    .catch(() => ({ version: 0, sections: [], stages: [], limits: {} }));
  return Object.freeze({
    ready: () => readyPromise,
    stageLabel: stage => metadata?.stages?.find(item => Number(item.number) === Number(stage))?.label
      || `第 ${Number(stage)} 階段`,
    sectionLabel: section => metadata?.sections?.find(item => Number(item.id) === Number(section))?.label
      || `第 ${Number(section)} 區段`,
    sectionLabelByPath: path => metadata?.sections?.find(item => item.path === path)?.label || path,
  });
})();
window.AdminWorkflow = AdminWorkflow;

function _adminPageContext() {
  const path = window.location.pathname.replace(/\/$/, '') || '/admin';
  const assignmentMatch = path.match(/^\/admin\/assignments\/(\d+)/);
  if (/^\/admin\/assignments\/\d+\/students\/\d+$/.test(path)) {
    return { key: 'grading', gradingHref: `/admin/assignments/${assignmentMatch[1]}/results` };
  }
  if (/^\/admin\/assignments\/\d+\/results$/.test(path)) {
    return { key: 'grading', gradingHref: path };
  }
  if (path === '/admin/users') return { key: 'users', gradingHref: '/admin/grading' };
  if (path === '/admin/grading') return { key: 'grading', gradingHref: path };
  if (path === '/admin/login-audit') return { key: 'audit', gradingHref: '/admin/grading' };
  if (path === '/admin/rubrics') return { key: 'rubrics', gradingHref: '/admin/grading' };
  if (path === '/admin/create-assignment' || path.startsWith('/admin/assignments')) {
    return { key: 'assignments', gradingHref: '/admin/grading' };
  }
  return { key: 'dashboard', gradingHref: '/admin/grading' };
}

function _adminNavLink(context, key, href, icon, label, extraClass = '') {
  const active = context.key === key;
  return `<a class="nav-link ${extraClass}${active ? ' active' : ''}" href="${href}"${active ? ' aria-current="page"' : ''}>
    <i class="bi ${icon}" aria-hidden="true"></i><span>${label}</span>
  </a>`;
}

function _syncAdminChrome() {
  const privileged = sessionStorage.getItem('isPrivilegedAdmin') === '1';
  document.querySelectorAll('[data-privileged-nav]').forEach((el) => {
    el.hidden = !privileged;
  });
  const name = sessionStorage.getItem('name') || '';
  const adminName = document.getElementById('adminName');
  if (adminName) adminName.textContent = name;
}

function _renderAdminChrome() {
  const nav = document.querySelector('nav.navbar-admin');
  if (!nav) return;

  const context = _adminPageContext();
  document.body.dataset.adminPage = context.key;
  nav.setAttribute('aria-label', '管理後台主要導覽');
  nav.innerHTML = `
    <div class="container-fluid admin-nav-shell">
      <a class="navbar-brand" href="/admin" aria-label="AI 面試練習管理後台首頁">
        <span class="admin-brand-mark"><i class="bi bi-shield-check" aria-hidden="true"></i></span>
        <span class="admin-brand-copy">AI 面試練習<small>管理後台</small></span>
      </a>
      <button class="navbar-toggler admin-nav-toggle" type="button" data-bs-toggle="collapse" data-bs-target="#adminPrimaryNav" aria-controls="adminPrimaryNav" aria-expanded="false" aria-label="開啟導覽選單">
        <i class="bi bi-list" aria-hidden="true"></i>
      </button>
      <div class="collapse navbar-collapse" id="adminPrimaryNav">
        <div class="navbar-nav admin-nav-links">
          ${_adminNavLink(context, 'dashboard', '/admin', 'bi-grid-1x2', '總覽')}
          ${_adminNavLink(context, 'users', '/admin/users', 'bi-people', '使用者')}
          ${_adminNavLink(context, 'assignments', '/admin/assignments', 'bi-journal-text', '作業')}
          ${_adminNavLink(context, 'grading', context.gradingHref, 'bi-clipboard-check', '批改', 'admin-grading-link')}
          ${_adminNavLink(context, 'audit', '/admin/login-audit', 'bi-shield-check', '稽核')}
          <span class="admin-nav-divider" aria-hidden="true"></span>
          ${_adminNavLink(context, 'rubrics', '/admin/rubrics', 'bi-ui-checks-grid', '評分規準', 'admin-settings-link')}
        </div>
        <div class="admin-account">
          <span class="admin-account-name" title="目前登入的管理員">
            <i class="bi bi-person-circle" aria-hidden="true"></i><span id="adminName"></span>
          </span>
          <button class="btn admin-logout-btn" type="button" data-action="logout">
            <i class="bi bi-box-arrow-right" aria-hidden="true"></i><span>登出</span>
          </button>
        </div>
      </div>
    </div>`;

  nav.querySelectorAll('.admin-settings-link').forEach((el) => {
    el.dataset.privilegedNav = '';
    el.hidden = true;
  });

  const pageRoot = Array.from(document.body.children).find((el) =>
    el !== nav && (el.matches('main') || el.matches('.container') || el.matches('.container-fluid'))
  );
  if (pageRoot) {
    pageRoot.classList.add('admin-page');
    const title = pageRoot.querySelector('h1, h2, h3, h4, h5');
    if (title) {
      title.classList.add('admin-page-title');
      let cursor = title.parentElement;
      let header = null;
      while (cursor && cursor !== pageRoot) {
        if (cursor.classList.contains('mb-3') || cursor.classList.contains('mb-4')) {
          header = cursor;
          break;
        }
        cursor = cursor.parentElement;
      }
      if (header) header.classList.add('admin-page-header');
      else title.classList.add('admin-page-title-standalone');
    }
  }

  document.querySelectorAll('[id*="loading" i], [id*="empty" i], [id*="error" i]').forEach((el) => {
    el.classList.add('admin-state');
  });
}

_renderAdminChrome();

const AdminApiClientReady = import('/static/js/api-client.mjs?v=2');
const adminNativeFetch = window.fetch.bind(window);
window.AdminApiClientReady = AdminApiClientReady;
window.fetch = (url, options = {}) => {
  const sameOrigin = typeof url === 'string'
    && (url.startsWith('/') || url.startsWith(window.location.origin));
  if (!sameOrigin) return adminNativeFetch(url, options);
  return AdminApiClientReady.then(({ apiRequest }) => apiRequest(url, options, adminNativeFetch));
};

function _waitForBootstrap() {
  if (window.bootstrap?.Modal) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setInterval(() => {
      if (window.bootstrap?.Modal) {
        clearInterval(timer);
        resolve();
      }
    }, 20);
  });
}

async function _forceAdminPasswordChange() {
  await _waitForBootstrap();
  let modalEl = document.getElementById('adminForcedPasswordModal');
  if (!modalEl) {
    modalEl = document.createElement('div');
    modalEl.id = 'adminForcedPasswordModal';
    modalEl.className = 'modal fade';
    modalEl.tabIndex = -1;
    modalEl.setAttribute('aria-labelledby', 'adminForcedPasswordTitle');
    modalEl.setAttribute('aria-hidden', 'true');
    modalEl.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content border-0 shadow-lg">
          <div class="modal-header border-0 pb-0">
            <div>
              <div class="small fw-semibold text-primary mb-1">帳號安全</div>
              <h2 class="modal-title fs-5" id="adminForcedPasswordTitle">請先更換初始密碼</h2>
            </div>
          </div>
          <div class="modal-body pt-3">
            <p class="text-secondary small">目前使用的是管理員設定的臨時密碼。完成更換後，才會開放管理功能。</p>
            <div id="adminForcedPasswordAlert" class="alert alert-danger d-none" role="alert"></div>
            <label class="form-label fw-semibold" for="adminOldPassword">目前密碼</label>
            <input class="form-control mb-3" id="adminOldPassword" type="password" maxlength="256" autocomplete="off" readonly data-action-focus="clearReadonlyAttr" data-lpignore="true" data-1p-ignore="true" data-bwignore="true">
            <label class="form-label fw-semibold" for="adminNewPassword">新密碼</label>
            <input class="form-control mb-2" id="adminNewPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" readonly data-action-focus="clearReadonlyAttr" data-lpignore="true" data-1p-ignore="true" data-bwignore="true">
            <div class="form-text mb-3">至少 8 個字元，請勿沿用臨時密碼。</div>
            <label class="form-label fw-semibold" for="adminConfirmPassword">再次輸入新密碼</label>
            <input class="form-control" id="adminConfirmPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" readonly data-action-focus="clearReadonlyAttr" data-lpignore="true" data-1p-ignore="true" data-bwignore="true">
          </div>
          <div class="modal-footer border-0 pt-0">
            <button class="btn btn-primary w-100" id="adminForcedPasswordSubmit" type="button">更換密碼並進入管理後台</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modalEl);
  }

  const modal = new bootstrap.Modal(modalEl, { backdrop: 'static', keyboard: false });
  modal.show();
  document.getElementById('adminOldPassword').focus();

  return new Promise((resolve) => {
    document.getElementById('adminForcedPasswordSubmit').onclick = async function () {
      const oldPassword = document.getElementById('adminOldPassword').value;
      const newPassword = document.getElementById('adminNewPassword').value;
      const confirmPassword = document.getElementById('adminConfirmPassword').value;
      const alertEl = document.getElementById('adminForcedPasswordAlert');
      const showError = (message) => {
        alertEl.textContent = message;
        alertEl.classList.remove('d-none');
      };
      if (!oldPassword || !newPassword || !confirmPassword) return showError('請把三個密碼欄位都填好。');
      if (newPassword.length < 8) return showError('新密碼至少需要 8 個字元。');
      if (newPassword !== confirmPassword) return showError('兩次輸入的新密碼不一致。');
      this.disabled = true;
      this.textContent = '正在更換密碼…';
      try {
        const response = await fetch('/api/auth/change-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          showError(data.detail || '密碼更換失敗，請確認目前密碼後再試。');
          return;
        }
        sessionStorage.setItem('must_change_password', '0');
        modal.hide();
        resolve();
      } catch (_) {
        showError('連線失敗，請稍後再試。');
      } finally {
        this.disabled = false;
        this.textContent = '更換密碼並進入管理後台';
      }
    };
  });
}

// Validate session on every page load via /api/auth/me (read-only — no token
// rotation, so rapid refreshes and multiple tabs never race).
// A background timer calls /refresh once per hour to keep the JWT alive.
function clearAdminAuthState() {
  ['role', 'name', 'userId', 'studentId', 'isPrivilegedAdmin', 'must_change_password']
    .forEach(key => sessionStorage.removeItem(key));
}

function redirectAdminToLogin(message = '登入逾期，請重新登入。') {
  clearAdminAuthState();
  sessionStorage.setItem('loginAlert', message);
  window.location.replace('/login');
}

window.ApiUnauthorizedHandler = async response => {
  let message = '登入逾期，請重新登入。';
  try { message = (await response.json()).detail || message; } catch (_) {}
  redirectAdminToLogin(message);
};

window._adminReady = (async function () {
  try {
    await AdminWorkflow.ready();
    const r = await fetch('/api/auth/me', { credentials: 'include' });
    if (r.status === 401) {
      redirectAdminToLogin();
      return;
    }
    if (r.ok) {
      const data = await r.json();
      sessionStorage.setItem('role', data.role);
      sessionStorage.setItem('name', data.name);
      sessionStorage.setItem('userId', String(data.id || ''));
      sessionStorage.setItem('studentId', data.student_id || '');
      sessionStorage.setItem('isPrivilegedAdmin', data.is_privileged_admin ? '1' : '0');
      sessionStorage.setItem('must_change_password', data.must_change_password ? '1' : '0');
      _syncAdminChrome();
      if (data.role === 'admin' && data.must_change_password) {
        await _forceAdminPasswordChange();
      }
    }
    if (sessionStorage.getItem('role') !== 'admin') {
      window.location.href = '/login';
      return;
    }
    _syncAdminChrome();
  } catch (_) {}
})();

// Rotate token at most once per hour so the JWT expiry keeps rolling forward
// without the race condition that per-page-load rotation causes.
(function () {
  const HOUR = 60 * 60 * 1000;
  function _scheduleRefresh() {
    setTimeout(async function () {
      try {
        const r = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
        if (r.status === 401) {
          redirectAdminToLogin();
          return;
        }
      } catch (_) {}
      _scheduleRefresh();
    }, HOUR);
  }
  _scheduleRefresh();
})();

async function logout() {
  try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (_) {}
  sessionStorage.clear();
  window.location.href = '/login';
}

function authHeaders() { return { 'Content-Type': 'application/json' }; }

function escHtml(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function escAttr(s) {
  return escHtml(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showToast(msg, type = 'danger') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast-msg toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'toastOut 0.25s ease forwards';
    setTimeout(() => toast.remove(), 260);
  }, 5000);
}

function showAlert(msg, type = 'danger') {
  showToast(msg, type);
}

async function _adminDialog({ title, message, confirmText = '確定', variant = 'primary', input = false }) {
  await _waitForBootstrap();
  let el = document.getElementById('adminSharedDialog');
  if (!el) {
    el = document.createElement('div');
    el.id = 'adminSharedDialog';
    el.className = 'modal fade';
    el.tabIndex = -1;
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = `<div class="modal-dialog modal-dialog-centered"><div class="modal-content">
      <div class="modal-header"><h2 class="modal-title fs-5" id="adminSharedDialogTitle"></h2><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="關閉"></button></div>
      <div class="modal-body"><p id="adminSharedDialogMessage" class="mb-3"></p><div id="adminSharedDialogInputWrap" class="d-none"><label class="form-label" for="adminSharedDialogInput">名稱</label><input id="adminSharedDialogInput" class="form-control" maxlength="120" autocomplete="off"><div id="adminSharedDialogError" class="invalid-feedback">請輸入名稱。</div></div></div>
      <div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">取消</button><button type="button" id="adminSharedDialogConfirm" class="btn">確定</button></div>
    </div></div>`;
    document.body.appendChild(el);
  }

  document.getElementById('adminSharedDialogTitle').textContent = title;
  document.getElementById('adminSharedDialogMessage').textContent = message;
  const inputWrap = document.getElementById('adminSharedDialogInputWrap');
  const inputEl = document.getElementById('adminSharedDialogInput');
  const confirmBtn = document.getElementById('adminSharedDialogConfirm');
  inputWrap.classList.toggle('d-none', !input);
  inputEl.value = '';
  inputEl.classList.remove('is-invalid');
  confirmBtn.textContent = confirmText;
  confirmBtn.className = `btn btn-${variant}`;

  const modal = bootstrap.Modal.getOrCreateInstance(el);
  return new Promise((resolve) => {
    let value = input ? null : false;
    const finish = () => {
      el.removeEventListener('hidden.bs.modal', finish);
      confirmBtn.onclick = null;
      inputEl.onkeydown = null;
      resolve(value);
    };
    const accept = () => {
      if (input) {
        const entered = inputEl.value.trim();
        if (!entered) {
          inputEl.classList.add('is-invalid');
          inputEl.focus();
          return;
        }
        value = entered;
      } else {
        value = true;
      }
      modal.hide();
    };
    confirmBtn.onclick = accept;
    inputEl.onkeydown = (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        accept();
      }
    };
    el.addEventListener('hidden.bs.modal', finish);
    el.addEventListener('shown.bs.modal', () => (input ? inputEl : confirmBtn).focus(), { once: true });
    modal.show();
  });
}

function confirmAdminAction(message, options = {}) {
  return _adminDialog({
    title: options.title || '確認操作',
    message,
    confirmText: options.confirmText || '確定',
    variant: options.variant || 'primary',
  });
}

function promptAdminText(message, options = {}) {
  return _adminDialog({
    title: options.title || '輸入資料',
    message,
    confirmText: options.confirmText || '建立',
    variant: options.variant || 'primary',
    input: true,
  });
}

function guardNumericInputsAgainstCredentialAutofill(root = document) {
  root.querySelectorAll('input[type="number"]').forEach((input) => {
    if (input.dataset.numericAutofillGuarded === 'true') return;
    input.dataset.numericAutofillGuarded = 'true';

    const isWithinBounds = () => {
      if (input.value === '') return true;
      const value = Number(input.value);
      const min = input.min === '' ? -Infinity : Number(input.min);
      const max = input.max === '' ? Infinity : Number(input.max);
      return Number.isFinite(value) && value >= min && value <= max;
    };
    if (!input.dataset.expectedNumericValue) {
      input.dataset.expectedNumericValue = input.value !== '' && isWithinBounds()
        ? input.value
        : '__EMPTY__';
    }
    const restoreIfInvalid = () => {
      if (isWithinBounds()) return;
      input.value = input.dataset.expectedNumericValue === '__EMPTY__'
        ? ''
        : input.dataset.expectedNumericValue;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    input.addEventListener('input', () => {
      if (isWithinBounds()) {
        input.dataset.expectedNumericValue = input.value || '__EMPTY__';
      } else {
        restoreIfInvalid();
      }
    });
    restoreIfInvalid();
    [100, 500, 1200].forEach(delay => window.setTimeout(restoreIfInvalid, delay));
  });
}

async function apiCall(url, options = {}) {
  const res = await fetch(url, { credentials: 'include', ...options, headers: options.headers || authHeaders() });
  if (res.status === 401) {
    let m = '登入逾期，請重新登入。';
    try { const e = await res.clone().json(); if (e.detail) m = e.detail; } catch (_) {}
    redirectAdminToLogin(m);
  }
  return res;
}
