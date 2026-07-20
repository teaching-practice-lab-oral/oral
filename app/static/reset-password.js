function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

function showAlert(message, type = 'danger') {
  const box = document.getElementById('alertBox');
  box.className = `alert alert-${type}`;
  box.textContent = message;
}

function setBusy(buttonId, spinnerId, busy) {
  document.getElementById(buttonId).disabled = busy;
  document.getElementById(spinnerId).classList.toggle('d-none', !busy);
}

window.onTurnstileSuccess = function () {
  document.getElementById('requestBtn').disabled = false;
};

window.onTurnstileExpired = function () {
  document.getElementById('requestBtn').disabled = true;
};

const token = new URLSearchParams(window.location.search).get('token') || '';
const requestForm = document.getElementById('requestForm');
const confirmForm = document.getElementById('confirmForm');
const turnstileWidget = document.getElementById('turnstileWidget');

if (token) {
  requestForm.classList.add('d-none');
  confirmForm.classList.remove('d-none');
  document.getElementById('pageTitle').textContent = '設定新密碼';
} else if (turnstileWidget && !turnstileWidget.dataset.sitekey) {
  turnstileWidget.classList.add('d-none');
  document.getElementById('requestBtn').disabled = false;
}

requestForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!requestForm.reportValidity()) return;
  const turnstileInput = document.querySelector('[name="cf-turnstile-response"]');
  const turnstileToken = turnstileInput ? turnstileInput.value : '';
  if (turnstileWidget.dataset.sitekey && !turnstileToken) {
    showAlert('請先完成人機驗證。');
    return;
  }
  setBusy('requestBtn', 'requestSpinner', true);
  try {
    const response = await fetch('/api/auth/password-reset/request', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
      body: JSON.stringify({
        course_num: document.getElementById('courseNum').value.trim(),
        name: document.getElementById('name').value.trim(),
        student_id: document.getElementById('studentId').value.trim(),
        backup_email: document.getElementById('backupEmail').value.trim() || null,
        turnstile_token: turnstileToken,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showAlert(data.detail || '申請失敗，請稍後再試。');
      return;
    }
    showAlert(data.message, 'success');
    requestForm.reset();
  } catch (_) {
    showAlert('網路錯誤，請稍後再試。');
  } finally {
    if (window.turnstile) window.turnstile.reset();
    setBusy('requestBtn', 'requestSpinner', false);
    if (turnstileWidget.dataset.sitekey) document.getElementById('requestBtn').disabled = true;
  }
});

confirmForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!confirmForm.reportValidity()) return;
  const newPassword = document.getElementById('newPassword').value;
  const confirmPassword = document.getElementById('confirmPassword').value;
  if (newPassword !== confirmPassword) {
    showAlert('兩次輸入的密碼不一致。');
    return;
  }
  setBusy('confirmBtn', 'confirmSpinner', true);
  try {
    const response = await fetch('/api/auth/password-reset/confirm', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
      body: JSON.stringify({ token, new_password: newPassword, confirm_password: confirmPassword }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showAlert(data.detail || '重設連結無效或已過期。');
      return;
    }
    showAlert(data.message, 'success');
    confirmForm.reset();
    document.getElementById('confirmBtn').classList.add('d-none');
  } catch (_) {
    showAlert('網路錯誤，請稍後再試。');
  } finally {
    setBusy('confirmBtn', 'confirmSpinner', false);
  }
});
