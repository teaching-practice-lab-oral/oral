function getFilename(res, fallback) {
  const cd = res.headers.get('Content-Disposition') || '';
  const m5987 = cd.match(/filename\*=UTF-8''([^\s;]+)/i);
  if (m5987) return decodeURIComponent(m5987[1]);
  const m = cd.match(/filename="?([^";\n]+)"?/);
  return m ? m[1] : fallback;
}

const pathParts = window.location.pathname.split('/');
const assignmentId = parseInt(pathParts[3]);
document.getElementById('btnEditAssignment').href = `/admin/assignments/${assignmentId}/edit`;

let allResults = [];
let filteredResults = [];
let currentSort = { by: 'student_id', dir: 'asc' };
let currentStatusFilter = 'all';
let assignmentTitle = '';
let assignmentDueDate = null;
let selectedUserIds = new Set();

function stageNameZh(stage) { return AdminWorkflow.stageLabel(stage); }

// sessionStorage helpers
function getNavState() {
  try { return JSON.parse(sessionStorage.getItem(`admin_student_nav_${assignmentId}`)); } catch { return null; }
}
function saveNavState() {
  try {
    const namesMap = {};
    filteredResults.forEach(s => { namesMap[s.user_id] = s.name; });
    sessionStorage.setItem(`admin_student_nav_${assignmentId}`, JSON.stringify({
      userIds: filteredResults.map(s => s.user_id),
      pendingUserIds: filteredResults
        .filter(s => s.grading_status === 'pending')
        .map(s => s.user_id),
      names: namesMap,
      sortBy: currentSort.by,
      sortDir: currentSort.dir,
      filters: { search: document.getElementById('searchInput').value.trim(), status: currentStatusFilter },
      assignmentTitle: assignmentTitle,
    }));
  } catch (_) {}
}

function pruneSelection() {
  const validIds = new Set(allResults.map(s => s.user_id));
  selectedUserIds.forEach(userId => {
    if (!validIds.has(userId)) selectedUserIds.delete(userId);
  });
}

function syncSelectAllCheckbox() {
  const checkbox = document.getElementById('selectAllVisible');
  if (!checkbox) return;
  const visibleIds = filteredResults.map(s => s.user_id);
  const selectedVisibleCount = visibleIds.filter(userId => selectedUserIds.has(userId)).length;
  checkbox.disabled = !visibleIds.length;
  checkbox.checked = !!visibleIds.length && selectedVisibleCount === visibleIds.length;
  checkbox.indeterminate = selectedVisibleCount > 0 && selectedVisibleCount < visibleIds.length;
}

function updateSelectionUI() {
  const count = selectedUserIds.size;
  document.getElementById('selectionCount').textContent = `已選 ${count} 人`;
  document.getElementById('btnBulkLateDeadline').disabled = count === 0;
  document.getElementById('btnClearSelection').disabled = count === 0;
  syncSelectAllCheckbox();
}

function clearSelection() {
  selectedUserIds.clear();
  renderTable();
}

function toggleStudentSelection(userId, e) {
  if (e.target.checked) selectedUserIds.add(userId);
  else selectedUserIds.delete(userId);
  updateSelectionUI();
}

function toggleSelectAllVisible(e) {
  if (e.target.checked) {
    filteredResults.forEach(student => selectedUserIds.add(student.user_id));
  } else {
    filteredResults.forEach(student => selectedUserIds.delete(student.user_id));
  }
  renderTable();
}

function applyFilterSort() {
  const search = document.getElementById('searchInput').value.trim().toLowerCase();
  const clsFilter = document.getElementById('classFilter').value;

  filteredResults = allResults.filter(s => {
    const matchSearch = !search
      || s.name.toLowerCase().includes(search)
      || (s.student_id || '').toLowerCase().includes(search);
    const matchStatus = currentStatusFilter === 'all'
      || (currentStatusFilter === 'not_started' && s.attempt_count === 0)
      || (currentStatusFilter === 'in_progress' && s.attempt_count > 0 && !s.is_submitted)
      || (currentStatusFilter === 'completed' && s.is_submitted)
      || (currentStatusFilter === 'incomplete' && !s.is_submitted)
      || (currentStatusFilter === 'pending' && s.grading_status === 'pending')
      || (currentStatusFilter === 'graded' && s.grading_status === 'graded')
      || (currentStatusFilter === 'issue' && s.has_issue)
      || (currentStatusFilter === 'late' && !!s.late_deadline);
    const matchClass = !clsFilter || (s.course_num || '') === clsFilter;
    return matchSearch && matchStatus && matchClass;
  });

  const dir = currentSort.dir === 'asc' ? 1 : -1;
  filteredResults.sort((a, b) => {
    switch (currentSort.by) {
      case 'name':       return dir * a.name.localeCompare(b.name, 'zh-TW');
      case 'student_id': return dir * (a.student_id || '').localeCompare(b.student_id || '');
      case 'stage':      return dir * ((a.latest_stage || 0) - (b.latest_stage || 0));
      case 'feedback':   return dir * (Number(a.has_feedback) - Number(b.has_feedback));
      case 'updated_at': {
        const da = a.updated_at ? new Date(a.updated_at) : new Date(0);
        const db = b.updated_at ? new Date(b.updated_at) : new Date(0);
        return dir * (da - db);
      }
      default: return 0;
    }
  });

  // Update sort button highlights
  document.querySelectorAll('#sortButtons .sort-btn').forEach(btn => {
    const isActive = btn.dataset.sort === currentSort.by;
    btn.classList.toggle('active', isActive);
    const base = btn.dataset.sort === 'student_id' ? '學號'
      : btn.dataset.sort === 'name' ? '姓名'
      : btn.dataset.sort === 'stage' ? '進度'
      : btn.dataset.sort === 'feedback' ? '詳細回饋'
      : '更新';
    btn.textContent = isActive ? base + (currentSort.dir === 'asc' ? ' ▲' : ' ▼') : base;
  });

  // Update quick-filter highlights
  ['all', 'not_started', 'in_progress', 'incomplete', 'completed', 'pending', 'graded', 'issue', 'late'].forEach(v => {
    document.getElementById(`qf-${v}`).classList.toggle('active', v === currentStatusFilter);
  });

  document.getElementById('resultCount').textContent =
    `顯示 ${filteredResults.length} / ${allResults.length} 名學生`;

  const pendingCount = allResults.filter(s => s.grading_status === 'pending').length;
  const startButton = document.getElementById('btnStartGrading');
  startButton.classList.toggle('d-none', pendingCount === 0);
  startButton.querySelector('span').textContent = `開始批改${pendingCount ? `（${pendingCount}）` : ''}`;

  saveNavState();
  renderTable();
}

function setSort(by) {
  if (currentSort.by === by) {
    currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
  } else {
    currentSort.by = by;
    currentSort.dir = 'asc';
  }
  applyFilterSort();
}

function setStatusFilter(status) {
  currentStatusFilter = status;
  applyFilterSort();
}

function startPendingGrading() {
  currentStatusFilter = 'pending';
  applyFilterSort();
  const firstPending = filteredResults.find(s => s.grading_status === 'pending');
  if (!firstPending) {
    showAlert('目前沒有待批改的學生。', 'success');
    return;
  }
  saveNavState();
  window.location.href = `/admin/assignments/${assignmentId}/students/${firstPending.user_id}`;
}

function renderTable() {
  const tbody = document.getElementById('resultsTable');

  if (!filteredResults.length) {
    const msg = allResults.length
      ? '<tr><td colspan="13" class="text-center text-muted py-5"><i class="bi bi-funnel me-2"></i>沒有符合條件的學生</td></tr>'
      : '<tr><td colspan="13" class="text-center text-muted py-5"><i class="bi bi-inbox fs-2 d-block mb-2 opacity-25"></i>尚無學生資料</td></tr>';
    tbody.innerHTML = msg;
    updateSelectionUI();
    return;
  }

  tbody.innerHTML = filteredResults.map(s => {
    const rowClass = s.is_submitted ? 'row-completed'
      : (s.latest_stage > 1) ? 'row-in-progress'
      : 'row-not-started';
    return `<tr class="${rowClass}">
      <td class="ps-3 select-col">
        <input
          type="checkbox"
          class="form-check-input"
          data-action-change="toggleStudentSelection"
          data-args='[${s.user_id}]'
          ${selectedUserIds.has(s.user_id) ? 'checked' : ''}
          aria-label="選取 ${escAttr(s.name)}"
        >
      </td>
      <td><code class="text-primary">${escHtml(s.student_id)}</code></td>
      <td>
        <a href="/admin/assignments/${assignmentId}/students/${s.user_id}"
           class="text-decoration-none fw-semibold"
           data-action="saveNavState">
          ${escHtml(s.name)}
        </a>
      </td>
      <td>${s.course_num ? `<span class="badge bg-info text-white">${escHtml(s.course_num)}</span>` : '<span class="text-muted">—</span>'}</td>
      <td>
        <div class="d-flex align-items-center gap-2">
          <div class="progress" style="width:60px;height:6px">
            <div class="progress-bar ${s.is_submitted ? 'bg-success' : 'bg-primary'}" style="width:${Math.round(({1:1,2:2,3:2,4:2,5:3,6:4,7:4,8:6,9:6}[s.latest_stage]||0)/6*100)}%"></div>
          </div>
          <span class="badge bg-light text-dark border">${({1:1,2:2,3:2,4:2,5:3,6:4,7:4,8:6,9:6}[s.latest_stage]||0)}/6</span>
          <small class="text-muted d-none d-xl-inline">${stageNameZh(s.latest_stage)}</small>
        </div>
      </td>
      <td class="text-center">${s.attempt_count}</td>
      <td><span class="badge ${s.has_feedback ? 'bg-primary' : 'bg-light text-muted border'}">
        <i class="bi bi-${s.has_feedback ? 'chat-square-text' : 'dash-circle'} me-1"></i>
        ${s.has_feedback ? '已產生' : '尚未產生'}
      </span></td>
      <td class="text-center fw-bold">${s.latest_final_score == null ? '<span class="text-muted">—</span>' : `${s.latest_final_score}`}</td>
      <td>${s.grading_status === 'graded' ? `<span class="badge bg-success">已批改</span><div class="small text-muted mt-1">${escHtml(s.latest_grader_name || '—')}</div>` : s.grading_status === 'pending' ? '<span class="badge bg-warning text-dark">待批改</span>' : '<span class="badge bg-light text-muted border">未就緒</span>'}</td>
      <td>${s.has_issue ? '<span class="badge bg-danger"><i class="bi bi-exclamation-triangle me-1"></i>有問題</span>' : '<span class="text-muted">—</span>'}</td>
      <td><span class="badge ${s.is_submitted ? 'bg-success' : 'bg-warning text-dark'}">
        <i class="bi bi-${s.is_submitted ? 'check-circle' : 'hourglass-split'} me-1"></i>
        ${s.is_submitted ? '已完成' : '進行中'}
      </span></td>
      <td class="small text-muted">${s.updated_at ? new Date(s.updated_at).toLocaleDateString('zh-TW') : '—'}</td>
      <td>
        <div class="d-flex gap-1">
          <a href="/admin/assignments/${assignmentId}/students/${s.user_id}"
             class="btn btn-sm ${s.grading_status === 'pending' ? 'btn-primary' : 'btn-outline-primary'}" data-action="saveNavState">
            <i class="bi bi-pencil-square me-1"></i>${s.is_submitted ? '批改' : '查看'}
          </a>
          ${(() => { const overdue = assignmentDueDate && new Date() > new Date(assignmentDueDate); return overdue ? `<button class="btn btn-sm btn-outline-secondary" disabled title="作業已截止，無法允許重作"><i class="bi bi-arrow-repeat me-1"></i>允許重作</button>` : `<button class="btn btn-sm btn-outline-secondary" data-action="openRetakeModal" data-args='[${s.user_id}]'><i class="bi bi-arrow-repeat me-1"></i>允許重作</button>`; })()}
          <button class="btn btn-sm btn-outline-secondary" data-action="openLateDeadlineModal" data-args='[${s.user_id}]'>
            <i class="bi bi-calendar-plus me-1"></i>補繳設定
          </button>
        </div>
      </td>
    </tr>`;
  }).join('');
  updateSelectionUI();
}

async function loadResults() {
  await window._adminReady;
  // Restore saved filter/sort state when returning from student detail
  const saved = getNavState();
  if (saved) {
    currentSort = { by: saved.sortBy || 'student_id', dir: saved.sortDir || 'asc' };
    currentStatusFilter = saved.filters?.status || 'all';
    document.getElementById('searchInput').value = saved.filters?.search || '';
    ['all', 'not_started', 'in_progress', 'incomplete', 'completed', 'pending', 'graded', 'issue', 'late'].forEach(v => {
      document.getElementById(`qf-${v}`).classList.toggle('active', v === currentStatusFilter);
    });
  }
  const requestedFilter = new URLSearchParams(location.search).get('filter');
  if (['all', 'not_started', 'in_progress', 'incomplete', 'completed', 'pending', 'graded', 'issue', 'late'].includes(requestedFilter)) {
    currentStatusFilter = requestedFilter;
    ['all', 'not_started', 'in_progress', 'incomplete', 'completed', 'pending', 'graded', 'issue', 'late'].forEach(v => {
      document.getElementById(`qf-${v}`).classList.toggle('active', v === currentStatusFilter);
    });
  }

  const aRes = await fetch(`/api/admin/assignments/${assignmentId}`, { headers: authHeaders() });
  if (aRes.status === 401) { redirectAdminToLogin(); return; }
  if (aRes.ok) {
    const a = await aRes.json();
    assignmentTitle = a.title;
    assignmentDueDate = a.due_date || null;
    document.getElementById('pageTitle').innerHTML =
      `<i class="bi bi-bar-chart me-2 text-primary"></i>學生作業：${escHtml(a.title)}`;
  } else {
    const data = await aRes.json().catch(() => ({}));
    showAlert(data.detail || '載入作業資料失敗，請稍後再試。');
    return;
  }

  const res = await fetch(`/api/admin/assignments/${assignmentId}/results`, { headers: authHeaders() });
  if (res.status === 401) { redirectAdminToLogin(); return; }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    showAlert(data.detail || '載入學生作業結果失敗，請稍後再試。');
    allResults = [];
    applyFilterSort();
    return;
  }
  allResults = await res.json();
  if (!Array.isArray(allResults)) {
    showAlert('學生作業結果格式錯誤，請重新整理後再試。');
    allResults = [];
  }
  pruneSelection();

  // Populate class filter from returned data
  const classSet = new Set(allResults.map(r => r.course_num).filter(Boolean));
  const sel = document.getElementById('classFilter');
  while (sel.options.length > 1) sel.remove(1);
  [...classSet].sort().forEach(c => {
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = c;
    sel.appendChild(opt);
  });

  applyFilterSort();
}

let _retakeUserId = null;

function openRetakeModal(userId) {
  _retakeUserId = userId;
  document.getElementById('retakePassword').value = '';
  document.getElementById('retakeError').classList.add('d-none');
  new bootstrap.Modal(document.getElementById('retakeModal')).show();
  setTimeout(() => document.getElementById('retakePassword').focus(), 300);
}

async function confirmRetake() {
  const password = document.getElementById('retakePassword').value.trim();
  if (!password) { document.getElementById('retakeError').textContent = '請輸入管理員密碼'; document.getElementById('retakeError').classList.remove('d-none'); return; }
  const btn = document.getElementById('btnConfirmRetake');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>處理中...';
  try {
    const res = await fetch(`/api/admin/assignments/${assignmentId}/students/${_retakeUserId}/retake`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ admin_password: password })
    });
    if (res.ok) {
      bootstrap.Modal.getInstance(document.getElementById('retakeModal')).hide();
      showAlert('已允許重作，已建立新的嘗試記錄。', 'success');
      loadResults();
    } else {
      const d = await res.json();
      document.getElementById('retakeError').textContent = d.detail || '發生錯誤';
      document.getElementById('retakeError').classList.remove('d-none');
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '確認允許重作';
  }
}

let dtpLate;
document.addEventListener('DOMContentLoaded', () => {
  dtpLate = new DateTimePicker('lateDeadlineDate', { placeholder: '選擇補繳截止日期時間' });
  document.addEventListener('click', () => {
    DateTimePicker.closeAll();
  });
});

let _lateDeadlineTargetUserIds = [];
let _lateDeadlineMode = 'single';

function openLateDeadlineModalForUsers(userIds, mode) {
  _lateDeadlineTargetUserIds = userIds.slice();
  _lateDeadlineMode = mode;
  const students = userIds
    .map(userId => allResults.find(r => r.user_id === userId))
    .filter(Boolean);
  const firstStudent = students[0] || null;
  const firstLateDeadline = firstStudent?.late_deadline || null;
  const allSameLateDeadline = students.every(student => (student?.late_deadline || null) === firstLateDeadline);
  const existing = mode === 'single' ? firstLateDeadline : (allSameLateDeadline ? firstLateDeadline : null);

  document.getElementById('lateDeadlineTitleText').textContent = mode === 'batch' ? '批量補繳設定' : '補繳設定';
  document.getElementById('lateDeadlineScopeText').textContent = mode === 'batch'
    ? `將同一個補繳截止日期套用到 ${userIds.length} 位已選學生，留空可批量清除補繳設定。`
    : '設定允許該學生補繳的截止日期，逾期後將恢復為唯讀狀態。留空可清除補繳設定。';
  document.getElementById('lateDeadlineSelectionHint').textContent = mode === 'batch'
    ? (allSameLateDeadline && existing
      ? `目前 ${userIds.length} 位學生的補繳期限一致，已自動帶入原設定。`
      : `這次會更新 ${userIds.length} 位學生；如果原本期限不同，送出後會統一覆蓋。`)
    : (firstStudent ? `對象：${firstStudent.name}（${firstStudent.student_id || '—'}）` : '');

  if (existing) {
    const iso = existing.replace(' ', 'T').slice(0, 16);
    document.getElementById('lateDeadlineDate').value = iso;
    if (dtpLate) dtpLate.syncFromHidden();
  } else {
    document.getElementById('lateDeadlineDate').value = '';
    if (dtpLate) dtpLate.clear();
  }
  document.getElementById('lateDeadlinePassword').value = '';
  document.getElementById('lateDeadlineError').classList.add('d-none');
  new bootstrap.Modal(document.getElementById('lateDeadlineModal')).show();
}

function openLateDeadlineModal(userId) {
  openLateDeadlineModalForUsers([userId], 'single');
}

function openBulkLateDeadlineModal() {
  const userIds = Array.from(selectedUserIds);
  if (!userIds.length) {
    showAlert('請先勾選至少一位學生。');
    return;
  }
  openLateDeadlineModalForUsers(userIds, 'batch');
}

async function confirmLateDeadline() {
  const password = document.getElementById('lateDeadlinePassword').value.trim();
  if (!password) { document.getElementById('lateDeadlineError').textContent = '請輸入管理員密碼'; document.getElementById('lateDeadlineError').classList.remove('d-none'); return; }
  const lateVal = document.getElementById('lateDeadlineDate').value;
  if (!_lateDeadlineTargetUserIds.length) {
    document.getElementById('lateDeadlineError').textContent = '請先選擇要設定的學生';
    document.getElementById('lateDeadlineError').classList.remove('d-none');
    return;
  }
  const btn = document.getElementById('btnConfirmLateDeadline');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>處理中...';
  try {
    const isBatch = _lateDeadlineMode === 'batch';
    const res = await fetch(
      isBatch
        ? `/api/admin/assignments/${assignmentId}/students/late-deadline`
        : `/api/admin/assignments/${assignmentId}/students/${_lateDeadlineTargetUserIds[0]}/late-deadline`,
      {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(
          isBatch
            ? { admin_password: password, user_ids: _lateDeadlineTargetUserIds, late_deadline: lateVal || null }
            : { admin_password: password, late_deadline: lateVal || null }
        )
      }
    );
    if (res.ok) {
      const data = await res.json();
      bootstrap.Modal.getInstance(document.getElementById('lateDeadlineModal')).hide();
      if (isBatch) {
        const failedCount = (data.email_failed_user_ids || []).length;
        showAlert(
          lateVal
            ? (failedCount
                ? `已為 ${_lateDeadlineTargetUserIds.length} 位學生設定補繳期限，但有 ${failedCount} 位學生的通知信寄送失敗。`
                : `已為 ${_lateDeadlineTargetUserIds.length} 位學生設定補繳期限至 ${lateVal.replace('T', ' ')}，並已寄送通知信。`)
            : `已清除 ${_lateDeadlineTargetUserIds.length} 位學生的補繳設定。`,
          failedCount ? 'warning' : 'success'
        );
        clearSelection();
      } else {
        if (lateVal && data.email_sent === false) {
          showAlert(`已設定補繳期限至 ${lateVal.replace('T', ' ')}，但通知信寄送失敗，請確認學生信箱設定。`, 'warning');
        } else {
          showAlert(lateVal ? `已設定補繳期限至 ${lateVal.replace('T', ' ')}，並已寄送通知信。` : '已清除補繳設定。', 'success');
        }
      }
      loadResults();
    } else {
      const d = await res.json();
      document.getElementById('lateDeadlineError').textContent = d.detail || '發生錯誤';
      document.getElementById('lateDeadlineError').classList.remove('d-none');
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '確認設定';
  }
}

async function exportLatestWords() {
  const btn = document.getElementById('btnExportLatest');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>匯出中...';
  try {
    const res = await fetch(`/api/admin/assignments/${assignmentId}/export-words-latest`, { headers: authHeaders() });
    if (!res.ok) {
      showAlert('匯出失敗，請稍後再試。');
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = getFilename(res, `assignment_${assignmentId}_latest.zip`);
    a.click();
    URL.revokeObjectURL(url);
    if (res.headers.get('X-Export-Partial') === 'true') {
      showAlert('部分 Word 匯出失敗；壓縮檔內含失敗清單，請依清單處理。', 'warning');
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-file-earmark-zip me-1"></i>批次匯出最新版本';
  }
}

async function exportGradesXlsx() {
  const btn = document.getElementById('btnExportXlsx');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>匯出中...';
  try {
    const res = await fetch(`/api/admin/assignments/${assignmentId}/export-xlsx`, { headers: authHeaders() });
    if (res.status === 401) {
      redirectAdminToLogin();
      return;
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showAlert(data.detail || '匯出成績失敗，請稍後再試。');
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = getFilename(res, `assignment_${assignmentId}_grades.xlsx`);
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (_) {
    showAlert('匯出成績失敗，請檢查網路連線後再試。');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-file-earmark-spreadsheet me-1"></i>匯出成績 XLSX';
  }
}

async function exportAllWords() {
  const btn = document.getElementById('btnExportWords');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>匯出中...';
  try {
    const res = await fetch(`/api/admin/assignments/${assignmentId}/export-words`, { headers: authHeaders() });
    if (!res.ok) {
      showAlert('匯出失敗，請稍後再試。');
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = getFilename(res, `assignment_${assignmentId}_words.zip`);
    a.click();
    URL.revokeObjectURL(url);
    if (res.headers.get('X-Export-Partial') === 'true') {
      showAlert('部分 Word 匯出失敗；壓縮檔內含失敗清單，請依清單處理。', 'warning');
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-file-earmark-zip me-1"></i>批次匯出所有版本';
  }
}

AdminWorkflow.ready().then(loadResults);

Object.assign(window, {
  getFilename,
  stageNameZh,
  getNavState,
  saveNavState,
  pruneSelection,
  syncSelectAllCheckbox,
  updateSelectionUI,
  clearSelection,
  toggleStudentSelection,
  toggleSelectAllVisible,
  applyFilterSort,
  setSort,
  setStatusFilter,
  startPendingGrading,
  renderTable,
  loadResults,
  openRetakeModal,
  confirmRetake,
  openLateDeadlineModalForUsers,
  openLateDeadlineModal,
  openBulkLateDeadlineModal,
  confirmLateDeadline,
  exportLatestWords,
  exportGradesXlsx,
  exportAllWords,
});
