function showAlert(id, msg, type='danger') {
  if (id === 'alertBox') {
    showToast(msg, type);
    return;
  }
  const el = document.getElementById(id);
  el.className = `alert alert-${type}`;
  el.textContent = msg;
}
let assignments = [];

function isPrivilegedAdmin() {
  return sessionStorage.getItem('isPrivilegedAdmin') === '1';
}

function syncPrivilegedControls() {
  const privileged = isPrivilegedAdmin();
  ['btnSeedPresets', 'btnSendReminders'].forEach((id) => {
    document.getElementById(id)?.classList.toggle('d-none', !privileged);
  });
}

async function loadAssignments() {
  await window._adminReady;
  syncPrivilegedControls();
  const res = await fetch('/api/admin/assignments', { headers: authHeaders() });
  if (res.status === 401) { redirectAdminToLogin(); return; }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    showAlert('alertBox', data.detail || '載入作業列表失敗，請稍後再試。');
    assignments = [];
    renderAssignments();
    return;
  }
  assignments = await res.json();
  if (!Array.isArray(assignments)) {
    showAlert('alertBox', '作業列表格式錯誤，請重新整理後再試。');
    assignments = [];
  }
  renderAssignments();
}

function renderAssignments() {
  const container = document.getElementById('assignmentContainer');
  if (!assignments.length) {
    container.innerHTML = `
      <div class="admin-empty-state text-center py-5 text-muted">
        <i class="bi bi-journal-plus fs-1 opacity-25 d-block mb-3"></i>
        <strong class="d-block mb-1">目前還沒有作業</strong>
        請按「新增作業」建立第一份練習。
      </div>`;
    return;
  }
  const now = new Date();
  container.innerHTML = assignments.map(a => {
    const modBadges = [
      `<span class="badge bg-success" style="font-size:0.7rem">📝 寫作</span>`,
      `<span class="badge bg-primary" style="font-size:0.7rem">🎤 跟讀</span>`,
      `<span class="badge" style="background:#7c3aed;font-size:0.7rem">🎭 角色扮演</span>`,
      `<span class="badge bg-info" style="font-size:0.7rem">📓 心得</span>`,
    ].filter(Boolean).join(' ');
    const overdue = a.is_active && a.due_date && now > new Date(a.due_date);
    const stCls = !a.is_active ? 'bg-secondary' : overdue ? 'bg-danger' : 'bg-success';
    const stTxt = !a.is_active ? '已關閉' : overdue ? '已截止' : '開放中';
    return `
    <div class="assignment-card">
      <div class="card-header flex-wrap">
        <span class="badge ${stCls} me-1">
          <i class="bi bi-circle-fill me-1" style="font-size:0.5rem"></i>${stTxt}
        </span>
        <strong class="flex-grow-1">${escHtml(a.title)}</strong>
        <div class="d-flex align-items-center gap-1 me-2">${modBadges}</div>
        ${a.due_date ? `<span class="text-muted small"><i class="bi bi-calendar me-1"></i>${new Date(a.due_date).toLocaleDateString('zh-TW')}</span>` : ''}
        <div class="d-flex gap-2 ms-auto flex-wrap assignment-actions">
          <a href="/admin/assignments/${a.id}/results" class="btn btn-sm btn-primary">
            <i class="bi bi-clipboard-check me-1"></i>查看與批改
          </a>
          <a href="/admin/assignments/${a.id}/edit" class="btn btn-sm btn-outline-primary">
            <i class="bi bi-pencil me-1"></i>編輯
          </a>
          <button class="btn btn-sm ${a.is_active ? 'btn-outline-warning' : 'btn-success'}" data-action="toggleActive" data-args='[${a.id}]'>
            <i class="bi bi-${a.is_active ? 'pause' : 'play'}-fill me-1"></i>${a.is_active ? '停用' : '啟用'}
          </button>
          <button class="btn btn-sm btn-outline-secondary" data-action="openResetAssignmentH" data-id="${a.id}" data-title="${escAttr(a.title)}" title="清除所有學生提交紀錄（測試用）">
            <i class="bi bi-arrow-counterclockwise me-1"></i>初始化
          </button>
          <button class="btn btn-sm btn-outline-danger" data-action="openDeleteAssignmentH" data-id="${a.id}" data-title="${escAttr(a.title)}">
            <i class="bi bi-trash me-1"></i>刪除
          </button>
        </div>
      </div>
      <div class="card-body">
        ${a.description ? `<p class="text-muted small mb-3">${escHtml(a.description)}</p>` : ''}
        ${a.course_nums && a.course_nums.length ? `
          <div class="mb-2">
            <span class="text-muted small fw-semibold me-2"><i class="bi bi-mortarboard me-1"></i>指定班級：</span>
            ${a.course_nums.map(c=>`<span class="badge bg-info text-white me-1">${escHtml(c)}</span>`).join('')}
          </div>` : ''}
        ${a.questions ? `
          <div class="mb-3">
            <div class="text-muted small fw-semibold mb-1">
              <i class="bi bi-question-circle me-1"></i>寫作／跟讀／角色扮演共用題目
              <span class="badge ${a.question_set_key ? 'bg-primary' : 'bg-secondary'} ms-1">${a.question_set_key ? '公版題組' : '自訂題組'}</span>
            </div>
            <ol class="mb-0 ps-3">
              ${(Array.isArray(a.questions)?a.questions:[a.questions]).map(q=>`<li class="small">${escHtml(String(q))}</li>`).join('')}
            </ol>
          </div>` : ''}

      </div>
    </div>`;
  }).join('');

}

async function toggleActive(id) {
  const res = await fetch(`/api/admin/assignments/${id}/toggle`, {
    method: 'PATCH', headers: authHeaders()
  });
  if (res.ok) {
    loadAssignments();
  } else {
    const data = await res.json().catch(() => ({}));
    showAlert('alertBox', data.detail || '操作失敗，請稍後再試。');
  }
}

let resetAssignmentId = null;

function openResetAssignment(id, title) {
  resetAssignmentId = id;
  document.getElementById('resetAssignmentTitle').textContent = title;
  document.getElementById('resetAssignmentPassword').value = '';
  document.getElementById('resetAssignmentAlert').className = 'alert d-none';
  new bootstrap.Modal(document.getElementById('resetAssignmentModal')).show();
}

async function confirmResetAssignment() {
  const pw = document.getElementById('resetAssignmentPassword').value;
  if (!pw) { showAlert('resetAssignmentAlert', '請輸入密碼'); return; }
  const res = await fetch(`/api/admin/assignments/${resetAssignmentId}/submissions`, {
    method: 'DELETE', headers: authHeaders(), body: JSON.stringify({ admin_password: pw })
  });
  if (res.ok || res.status === 204) {
    bootstrap.Modal.getInstance(document.getElementById('resetAssignmentModal')).hide();
    showAlert('alertBox', '作業已初始化，所有提交紀錄已清除。', 'success');
    loadAssignments();
  } else {
    const data = await res.json().catch(() => ({}));
    showAlert('resetAssignmentAlert', data.detail || '初始化失敗，請稍後再試。');
  }
}

async function seedPresets() {
  const btn = document.getElementById('btnSeedPresets');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>建立中...';
  try {
    const res = await fetch('/api/admin/assignments/seed-presets', {
      method: 'POST', headers: authHeaders()
    });
    const data = await res.json();
    if (!res.ok) { showAlert('alertBox', data.detail || '建立失敗'); return; }
    const msgs = [];
    if (data.created.length) msgs.push(`已建立：${data.created.join('、')}`);
    if (data.updated.length) msgs.push(`已更新：${data.updated.join('、')}`);
    if (data.skipped.length) msgs.push(`已略過（無變更）：${data.skipped.join('、')}`);
    const hasChange = data.created.length || data.updated.length;
    showAlert('alertBox', msgs.join('　'), hasChange ? 'success' : 'info');
    loadAssignments();
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-stars me-1"></i>建立預設五套作業';
  }
}

async function sendDueReminders() {
  const btn = document.getElementById('btnSendReminders');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>寄送中...';
  try {
    const res = await fetch('/api/admin/assignments/send-due-reminders', {
      method: 'POST', headers: authHeaders()
    });
    const data = await res.json();
    if (!res.ok) { showAlert('alertBox', data.detail || '寄送失敗，請稍後再試。'); return; }
    showAlert('alertBox', data.message, data.pending ? 'success' : 'info');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-alarm me-1"></i>寄送截止提醒';
  }
}

let deleteAssignmentId = null;

function openDeleteAssignment(id, title) {
  deleteAssignmentId = id;
  document.getElementById('deleteAssignmentTitle').textContent = title;
  document.getElementById('deleteAssignmentPassword').value = '';
  document.getElementById('deleteAssignmentAlert').className = 'alert d-none';
  new bootstrap.Modal(document.getElementById('deleteAssignmentModal')).show();
}

async function confirmDeleteAssignment() {
  const pw = document.getElementById('deleteAssignmentPassword').value;
  if (!pw) { showAlert('deleteAssignmentAlert', '請輸入密碼'); return; }
  const res = await fetch(`/api/admin/assignments/${deleteAssignmentId}/delete`, {
    method: 'POST', headers: authHeaders(), body: JSON.stringify({ admin_password: pw })
  });
  if (res.status === 403) { showAlert('deleteAssignmentAlert', '密碼錯誤，請重新輸入'); return; }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    showAlert('deleteAssignmentAlert', data.detail || '刪除失敗，請稍後再試');
    return;
  }
  bootstrap.Modal.getInstance(document.getElementById('deleteAssignmentModal')).hide();
  showAlert('alertBox', '作業已成功刪除。', 'success');
  loadAssignments();
}

loadAssignments();
const pageParams = new URLSearchParams(location.search);
if (pageParams.get('created')) {
  showAlert('alertBox', '作業建立成功！', 'success');
  history.replaceState(null, '', location.pathname);
}

Object.assign(window, {
  showAlert,
  isPrivilegedAdmin,
  syncPrivilegedControls,
  loadAssignments,
  renderAssignments,
  toggleActive,
  openResetAssignment,
  confirmResetAssignment,
  seedPresets,
  sendDueReminders,
  openDeleteAssignment,
  confirmDeleteAssignment,
});
