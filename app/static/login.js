let loginAttemptInProgress = false;

function clearStoredAuthState() {
  ['role', 'name', 'user_id', 'userId', 'studentId', 'must_change_password', 'requires_legal_acknowledgement', 'isPrivilegedAdmin']
    .forEach(key => sessionStorage.removeItem(key));
}

// sessionStorage can outlive an expired cookie inside an installed PWA. Never
// redirect from this page based on cached role data; the server cookie is the
// only source of truth for whether a session is still authenticated.
(async function restoreVerifiedSession() {
  try {
    const r = await fetch('/api/auth/me', { credentials: 'include' });
    if (loginAttemptInProgress) return;
    if (r.ok) {
      const data = await r.json();
      if (loginAttemptInProgress) return;
      sessionStorage.setItem('role', data.role);
      sessionStorage.setItem('name', data.name);
      sessionStorage.setItem('must_change_password', data.must_change_password ? '1' : '0');
      sessionStorage.setItem('requires_legal_acknowledgement', data.requires_legal_acknowledgement ? '1' : '0');
      sessionStorage.setItem('isPrivilegedAdmin', data.is_privileged_admin ? '1' : '0');
      window.location.replace(data.role === 'admin' ? '/admin' : '/student');
      return;
    }
    clearStoredAuthState();
  } catch (_) {}
})();

function onTurnstileSuccess() {
  document.getElementById('loginBtn').disabled = false;
}

function onTurnstileExpired() {
  document.getElementById('loginBtn').disabled = true;
}

function showAlert(msg, type = 'danger') {
  const box = document.getElementById('alertBox');
  box.className = `alert alert-${type}`;
  box.textContent = msg;
}

const turnstileWidget = document.getElementById('turnstileWidget');
if (turnstileWidget && !turnstileWidget.dataset.sitekey) {
  turnstileWidget.classList.add('d-none');
  document.getElementById('loginBtn').disabled = false;
}

const _loginAlert = sessionStorage.getItem('loginAlert');
if (_loginAlert) { sessionStorage.removeItem('loginAlert'); showAlert(_loginAlert, 'warning'); }

document.getElementById('togglePassword').addEventListener('click', (e) => {
  const button = e.currentTarget;
  const passwordInput = document.getElementById('password');
  const showPassword = passwordInput.type === 'password';

  passwordInput.type = showPassword ? 'text' : 'password';
  button.setAttribute('aria-label', showPassword ? '隱藏密碼' : '顯示密碼');
  button.setAttribute('aria-pressed', showPassword ? 'true' : 'false');
  button.querySelector('i').className = showPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
  passwordInput.focus();
});

document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = document.getElementById('loginBtn');
  const spinner = document.getElementById('loginSpinner');

  const turnstileInput = document.querySelector('[name="cf-turnstile-response"]');
  const turnstileToken = turnstileInput ? turnstileInput.value : '';
  if (turnstileWidget && turnstileWidget.dataset.sitekey && !turnstileToken) {
    showAlert('請先完成人機驗證。');
    return;
  }

  btn.disabled = true;
  spinner.classList.remove('d-none');

  const studentId = document.getElementById('studentId').value.trim();
  const password = document.getElementById('password').value;
  loginAttemptInProgress = true;

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_id: studentId, password, turnstile_token: turnstileToken }),
    });
    const data = await res.json();
    if (!res.ok) {
      loginAttemptInProgress = false;
      showAlert(data.detail || '登入失敗，請確認學號與密碼是否正確。');
      if (window.turnstile) window.turnstile.reset();
      return;
    }
    sessionStorage.setItem('role', data.role);
    sessionStorage.setItem('name', data.name);
    sessionStorage.setItem('user_id', data.user_id);
    sessionStorage.setItem('must_change_password', data.must_change_password ? '1' : '0');
    sessionStorage.setItem('requires_legal_acknowledgement', data.requires_legal_acknowledgement ? '1' : '0');
    sessionStorage.setItem('isPrivilegedAdmin', data.is_privileged_admin ? '1' : '0');
    window.location.replace(data.role === 'admin' ? '/admin' : '/student');
  } catch (err) {
    loginAttemptInProgress = false;
    showAlert('網路錯誤，請稍後再試。');
    if (window.turnstile) window.turnstile.reset();
  } finally {
    spinner.classList.add('d-none');
  }
});
