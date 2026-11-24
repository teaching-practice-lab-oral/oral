const DEVICE_ICONS = {
  mobile: '<i class="bi bi-phone device-icon text-primary"></i>',
  tablet: '<i class="bi bi-tablet device-icon text-info"></i>',
  desktop: '<i class="bi bi-display device-icon text-secondary"></i>',
  unknown: '<i class="bi bi-question-circle device-icon text-muted"></i>',
};
const DEVICE_LABELS = { mobile: '手機', tablet: '平板', desktop: '電腦', unknown: '未知' };
const AA_ACTION_LABELS = {
  'admin.user.create': '建立帳號',
  'admin.user.import_xlsx': 'XLSX 匯入帳號',
  'admin.user.send_import_emails': '寄送匯入通知信',
  'admin.user.export_batch_xlsx': '匯出匯入帳號 XLSX',
  'admin.user.reset_password': '重設密碼',
  'student.password_reset.request': '學生申請重設密碼',
  'student.password_reset.confirm': '學生設定新密碼',
  'admin.user.update': '更新使用者',
  'admin.user.delete': '刪除使用者',
  'admin.assignment.send_due_reminders': '手動寄送提醒',
  'admin.assignment.seed_presets': '同步預設作業',
  'admin.login.unfreeze_all': '解除全站登入限制',
  'admin.assignment.create': '建立作業',
  'admin.assignment.update': '更新作業',
  'admin.assignment.delete': '刪除作業',
  'admin.assignment.toggle': '切換作業啟用',
  'admin.assignment.reset_submissions': '清空提交紀錄',
  'admin.assignment.allow_retake': '允許重作',
  'admin.assignment.rewind_submission': '退回作答階段',
  'admin.assignment.set_late_deadline': '設定補繳期限',
  'admin.rubric.create': '建立評分規準',
  'admin.rubric.update': '更新評分規準草稿',
  'admin.rubric.publish': '發布評分規準',
  'admin.rubric.clone_version': '建立評分規準新版',
  'admin.rubric.archive': '封存評分規準',
  'admin.submission.grade': '登錄或更新成績',
  'admin.submission.rescore': '重新產生學習回饋',
  'admin.export.submission_word': '匯出提交 Word',
  'admin.export.submission_audio': '匯出提交音檔',
  'admin.export.student_words_all': '匯出學生全部 Word',
  'admin.export.student_word_latest': '匯出學生最新 Word',
  'admin.export.assignment_words_latest': '匯出作業最新 Word',
  'admin.export.assignment_words_all': '匯出作業全部 Word',
  'admin.export.assignment_xlsx': '匯出作業成績 XLSX',
  'admin.assignment.send_result_packages': '寄送學生學習成果',
  'admin.assignment.retry_result_packages': '重寄失敗學習成果',
  'admin.assignment.result_packages_completed': '學生學習成果寄送結果',
};
const AA_TARGET_LABELS = {
  user: '使用者',
  user_batch: '批次使用者',
  email_job: '寄信工作',
  user_batch_export: '匯入帳號匯出',
  assignment: '作業',
  assignment_batch: '批次作業',
  reminder_job: '提醒工作',
  submission: '提交紀錄',
  rubric: '評分規準',
  rubric_version: '評分規準版本',
  submission_grade: '提交成績',
  student_export: '學生匯出',
  assignment_export: '作業匯出',
};

// ──────────────────────────────────────────
// 登入稽核
// ──────────────────────────────────────────
let laCurrentPage = 1;

function laClearFilters() {
  document.getElementById('la-filterStudentId').value = '';
  clearAuditDatePickers('la-filterDateFrom', 'la-filterDateTo');
  document.getElementById('la-filterSuccess').value = '';
  laLoadEvents(1);
}

async function laLoadEvents(page) {
  laCurrentPage = page;
  const studentId = document.getElementById('la-filterStudentId').value.trim();
  const dateFrom  = document.getElementById('la-filterDateFrom').value;
  const dateTo    = document.getElementById('la-filterDateTo').value;
  const success   = document.getElementById('la-filterSuccess').value;
  const limit     = parseInt(document.getElementById('la-filterLimit').value);

  const params = new URLSearchParams({ page, limit });
  if (studentId) params.set('student_id', studentId);
  if (dateFrom)  params.set('date_from', dateFrom);
  if (dateTo)    params.set('date_to', dateTo);
  if (success !== '') params.set('success', success);

  const tbody = document.getElementById('la-eventsTableBody');
  tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">載入中…</td></tr>';

  const res = await apiCall(`/api/admin/login-events?${params}`);
  if (!res.ok) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger py-4">載入失敗</td></tr>';
    return;
  }
  const data = await res.json();

  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">無符合記錄</td></tr>';
    document.getElementById('la-paginationInfo').textContent = '';
    document.getElementById('la-paginationControls').innerHTML = '';
    return;
  }

  tbody.innerHTML = data.items.map(ev => {
    const dt = new Date(ev.login_at);
    const timeStr   = dt.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
    const deviceKey = ev.device_type || 'unknown';
    const deviceIcon  = DEVICE_ICONS[deviceKey] || DEVICE_ICONS.unknown;
    const deviceLabel = DEVICE_LABELS[deviceKey] || deviceKey;
    const resultBadge = ev.success
      ? '<span class="badge badge-success px-2 py-1"><i class="bi bi-check-circle me-1"></i>成功</span>'
      : '<span class="badge badge-fail px-2 py-1"><i class="bi bi-x-circle me-1"></i>失敗</span>';
    return `
      <tr>
        <td class="text-nowrap">${escHtml(timeStr)}</td>
        <td class="fw-mono">${escHtml(ev.student_id)}</td>
        <td>${escHtml(ev.name || '—')}</td>
        <td class="fw-mono">${escHtml(ev.ip_address || '—')}</td>
        <td>${deviceIcon} <span class="ms-1">${escHtml(deviceLabel)}</span></td>
        <td>${resultBadge}</td>
      </tr>`;
  }).join('');

  const totalPages = Math.ceil(data.total / data.limit);
  const start = (data.page - 1) * data.limit + 1;
  const end   = Math.min(data.page * data.limit, data.total);
  document.getElementById('la-paginationInfo').textContent = `顯示 ${start}–${end}，共 ${data.total} 筆`;

  const ctrl = document.getElementById('la-paginationControls');
  ctrl.innerHTML = '';
  if (totalPages <= 1) return;

  const mkBtn = (label, p, disabled = false) => {
    const btn = document.createElement('button');
    btn.className = `btn btn-sm ${p === laCurrentPage ? 'btn-primary' : 'btn-outline-secondary'}`;
    btn.textContent = label;
    btn.disabled = disabled;
    btn.onclick = () => laLoadEvents(p);
    return btn;
  };

  ctrl.appendChild(mkBtn('«', 1, laCurrentPage === 1));
  ctrl.appendChild(mkBtn('‹', laCurrentPage - 1, laCurrentPage === 1));
  const startP = Math.max(1, laCurrentPage - 2);
  const endP   = Math.min(totalPages, startP + 4);
  for (let p = startP; p <= endP; p++) ctrl.appendChild(mkBtn(String(p), p));
  ctrl.appendChild(mkBtn('›', laCurrentPage + 1, laCurrentPage === totalPages));
  ctrl.appendChild(mkBtn('»', totalPages, laCurrentPage === totalPages));
}

// ──────────────────────────────────────────
// 敏感操作稽核
// ──────────────────────────────────────────
let aaCurrentPage = 1;
let aaInitialized = false;

function aaRenderJson(label, value) {
  if (!value || (Array.isArray(value) && !value.length) || (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length)) return '';
  return `<div class="mt-2"><div class="small text-muted mb-1">${escHtml(label)}</div><pre class="audit-code mb-0">${escHtml(JSON.stringify(value, null, 2))}</pre></div>`;
}

function aaDecodeDisplayText(value) {
  if (!value || typeof value !== 'string' || !/%[0-9A-Fa-f]{2}/.test(value)) return value;
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function aaClearFilters() {
  document.getElementById('aa-filterAdminStudentId').value = '';
  document.getElementById('aa-filterAction').value = '';
  document.getElementById('aa-filterTargetType').value = '';
  clearAuditDatePickers('aa-filterDateFrom', 'aa-filterDateTo');
  document.getElementById('aa-filterLimit').value = '50';
  aaLoadLogs(1);
}

async function aaLoadLogs(page) {
  aaCurrentPage = page;
  const adminStudentId = document.getElementById('aa-filterAdminStudentId').value.trim();
  const action = document.getElementById('aa-filterAction').value;
  const targetType = document.getElementById('aa-filterTargetType').value;
  const dateFrom = document.getElementById('aa-filterDateFrom').value;
  const dateTo = document.getElementById('aa-filterDateTo').value;
  const limit = parseInt(document.getElementById('aa-filterLimit').value, 10);

  const params = new URLSearchParams({ page, limit });
  if (adminStudentId) params.set('admin_student_id', adminStudentId);
  if (action) params.set('action', action);
  if (targetType) params.set('target_type', targetType);
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);

  const tbody = document.getElementById('aa-logsTableBody');
  tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">載入中…</td></tr>';

  const res = await apiCall(`/api/admin/admin-audit-logs?${params}`);
  if (!res.ok) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-4">載入失敗</td></tr>';
    return;
  }

  const data = await res.json();
  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">無符合記錄</td></tr>';
    document.getElementById('aa-paginationInfo').textContent = '';
    document.getElementById('aa-paginationControls').innerHTML = '';
    return;
  }

  tbody.innerHTML = data.items.map(item => {
    const timeStr = new Date(item.created_at).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
    const actionLabel = AA_ACTION_LABELS[item.action] || item.action;
    const targetLabel = AA_TARGET_LABELS[item.target_type] || item.target_type || '—';
    const targetValue = aaDecodeDisplayText(item.target_label || item.target_id || '—');
    const summaryText = aaDecodeDisplayText(item.summary || '—');
    const resultBadge = item.result === 'success'
      ? '<span class="badge badge-success px-2 py-1">成功</span>'
      : '<span class="badge badge-fail px-2 py-1">失敗</span>';
    const detailHtml = [
      aaRenderJson('Before', item.before_json),
      aaRenderJson('After', item.after_json),
      aaRenderJson('Details', item.detail_json),
    ].join('');
    return `
      <tr>
        <td class="text-nowrap">${escHtml(timeStr)}</td>
        <td>
          <div class="fw-semibold">${escHtml(item.admin_name || '—')}</div>
          <div class="text-muted small">${escHtml(item.admin_student_id)}</div>
        </td>
        <td>
          <span class="badge badge-audit px-2 py-1 mb-1">${escHtml(actionLabel)}</span>
          <div>${resultBadge}</div>
        </td>
        <td>
          <div>${escHtml(targetLabel)}</div>
          <div class="text-muted small audit-text-wrap">${escHtml(targetValue)}</div>
        </td>
        <td class="audit-text-wrap">${escHtml(summaryText)}</td>
        <td class="fw-mono">${escHtml(item.ip_address || '—')}</td>
        <td>
          ${detailHtml ? `<details><summary class="text-primary">檢視</summary>${detailHtml}</details>` : '<span class="text-muted">—</span>'}
        </td>
      </tr>`;
  }).join('');

  const totalPages = Math.ceil(data.total / data.limit);
  const start = (data.page - 1) * data.limit + 1;
  const end = Math.min(data.page * data.limit, data.total);
  document.getElementById('aa-paginationInfo').textContent = `顯示 ${start}–${end}，共 ${data.total} 筆`;

  const ctrl = document.getElementById('aa-paginationControls');
  ctrl.innerHTML = '';
  if (totalPages <= 1) return;

  const mkBtn = (label, p, disabled = false) => {
    const btn = document.createElement('button');
    btn.className = `btn btn-sm ${p === aaCurrentPage ? 'btn-primary' : 'btn-outline-secondary'}`;
    btn.textContent = label;
    btn.disabled = disabled;
    btn.onclick = () => aaLoadLogs(p);
    return btn;
  };

  ctrl.appendChild(mkBtn('«', 1, aaCurrentPage === 1));
  ctrl.appendChild(mkBtn('‹', aaCurrentPage - 1, aaCurrentPage === 1));
  const startP = Math.max(1, aaCurrentPage - 2);
  const endP = Math.min(totalPages, startP + 4);
  for (let p = startP; p <= endP; p++) ctrl.appendChild(mkBtn(String(p), p));
  ctrl.appendChild(mkBtn('›', aaCurrentPage + 1, aaCurrentPage === totalPages));
  ctrl.appendChild(mkBtn('»', totalPages, aaCurrentPage === totalPages));
}

// ──────────────────────────────────────────
// API 記錄
// ──────────────────────────────────────────
let ulCurrentSkip = 0;
let ulTotalCount  = 0;
let ulAllLoaded   = [];
let ulInitialized = false;

function ulShowAlert(msg, type = 'danger') {
  const el = document.getElementById('ul-alertBox');
  el.className = `alert alert-${type}`;
  el.textContent = msg;
}

function ulBuildParams(skip) {
  const params = new URLSearchParams();
  const sid  = document.getElementById('ul-filterStudentId').value.trim();
  const from = document.getElementById('ul-filterDateFrom').value;
  const to   = document.getElementById('ul-filterDateTo').value;
  const limit = document.getElementById('ul-filterLimit').value;
  if (sid)  params.set('student_id', sid);
  if (from) params.set('date_from', from);
  if (to)   params.set('date_to', to);
  params.set('limit', limit);
  params.set('skip', skip || 0);
  return params.toString();
}

async function ulLoadLogs(reset = false) {
  if (reset) { ulCurrentSkip = 0; ulAllLoaded = []; }
  const tbody = document.getElementById('ul-logsTable');
  if (reset) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center py-5">
      <div class="spinner-border text-primary spinner-border-sm me-2"></div>載入中...
    </td></tr>`;
  }
  try {
    const res = await fetch(`/api/admin/usage-logs?${ulBuildParams(ulCurrentSkip)}`);
    if (res.status === 401) { sessionStorage.clear(); window.location.href = '/login'; return; }
    if (!res.ok) { ulShowAlert('載入失敗，請稍後再試。'); return; }
    const data = await res.json();
    ulTotalCount = data.total;
    ulAllLoaded  = ulAllLoaded.concat(data.logs || []);
    ulCurrentSkip = ulAllLoaded.length;
    ulRenderTable();
    ulUpdateSummary();
  } catch (e) {
    ulShowAlert('載入失敗：' + e.message);
  }
}

function ulRenderTable() {
  const tbody = document.getElementById('ul-logsTable');
  if (!ulAllLoaded.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-5">
      <i class="bi bi-inbox fs-2 d-block mb-2 opacity-25"></i>沒有符合條件的記錄
    </td></tr>`;
    document.getElementById('ul-loadMoreBar').classList.add('d-none');
    return;
  }
  tbody.innerHTML = ulAllLoaded.map((l, i) => {
    const stageName  = AdminWorkflow.stageLabel(l.stage);
    const badgeColor = l.stage <= 3 ? 'bg-info' : l.stage <= 5 ? 'bg-primary' : l.stage <= 7 ? 'bg-success' : 'bg-secondary';
    return `<tr>
      <td class="ps-3 text-muted small">${i + 1}</td>
      <td><code class="text-primary">${escHtml(l.student_id || '—')}</code></td>
      <td>${escHtml(l.name || '—')}</td>
      <td><span class="badge ${badgeColor} bg-opacity-75">第 ${l.stage} 階段 <span class="fw-normal opacity-75">— ${escHtml(stageName)}</span></span></td>
      <td class="text-muted small">${new Date(l.called_at).toLocaleString('zh-TW')}</td>
    </tr>`;
  }).join('');
  const bar = document.getElementById('ul-loadMoreBar');
  if (ulAllLoaded.length < ulTotalCount) {
    bar.classList.remove('d-none');
    document.getElementById('ul-loadMoreInfo').textContent = `已顯示 ${ulAllLoaded.length} / ${ulTotalCount} 筆`;
  } else {
    bar.classList.add('d-none');
  }
}

function ulUpdateSummary() {
  document.getElementById('ul-resultSummary').textContent =
    `共 ${ulTotalCount} 筆記錄，顯示 ${ulAllLoaded.length} 筆`;
}

function ulLoadMore() { ulLoadLogs(false); }

function ulResetFilters() {
  document.getElementById('ul-filterStudentId').value = '';
  clearAuditDatePickers('ul-filterDateFrom', 'ul-filterDateTo');
  document.getElementById('ul-filterLimit').value     = '100';
  ulLoadLogs(true);
}

// ──────────────────────────────────────────
// 已登入裝置
// ──────────────────────────────────────────
let asInitialized = false;

function asFmtTime(iso) {
  return new Date(iso).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
}

function asRelativeTime(iso) {
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60)    return `${diff} 秒前`;
  if (diff < 3600)  return `${Math.floor(diff / 60)} 分鐘前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
  return `${Math.floor(diff / 86400)} 天前`;
}

function asIsFresh(iso) {
  return (Date.now() - new Date(iso)) < 5 * 60 * 1000;
}

async function asLoad() {
  const btn  = document.getElementById('as-refreshBtn');
  const icon = btn.querySelector('i');
  icon.classList.add('spinning');

  const res = await apiCall('/api/admin/active-sessions');
  icon.classList.remove('spinning');

  const tbody = document.getElementById('as-sessionsTableBody');
  if (!res.ok) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-5">載入失敗</td></tr>';
    return;
  }

  const sessions = await res.json();
  const count = sessions.length;
  document.getElementById('as-sessionCount').textContent = `${count} 個裝置`;
  document.getElementById('as-lastRefresh').textContent  = `更新於 ${new Date().toLocaleTimeString('zh-TW', { hour12: false })}`;

  const badge = document.getElementById('as-sessionBadge');
  badge.textContent = count;
  badge.classList.toggle('d-none', !(count > 0));

  if (!sessions.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-5">目前無已登入裝置</td></tr>';
    return;
  }

  tbody.innerHTML = sessions.map(s => {
    const deviceKey   = s.device_type || 'unknown';
    const deviceIcon  = DEVICE_ICONS[deviceKey] || DEVICE_ICONS.unknown;
    const deviceLabel = DEVICE_LABELS[deviceKey] || deviceKey;
    const roleBadge   = s.role === 'admin'
      ? '<span class="badge badge-admin px-2 py-1">Admin</span>'
      : '<span class="badge badge-student px-2 py-1">學生</span>';
    const fresh       = asIsFresh(s.last_seen_at);
    const lastSeenHtml = `<span class="${fresh ? 'last-seen-fresh' : 'last-seen-idle'}" title="${asFmtTime(s.last_seen_at)}">${asRelativeTime(s.last_seen_at)}</span>`;
    const expiresAt   = new Date(s.expires_at);
    const expiredSoon = (expiresAt - Date.now()) < 60 * 60 * 1000;
    const expiresHtml = `<span class="${expiredSoon ? 'text-warning' : 'text-muted'}">${asFmtTime(s.expires_at)}</span>`;
    return `
      <tr>
        <td>
          <div class="fw-semibold">${escHtml(s.name)}</div>
          <div class="text-muted small">${escHtml(s.student_id)}</div>
        </td>
        <td>${roleBadge}</td>
        <td class="fw-mono">${escHtml(s.ip_address || '—')}</td>
        <td>${deviceIcon} <span class="ms-1">${escHtml(deviceLabel)}</span></td>
        <td class="text-muted small">${asFmtTime(s.created_at)}</td>
        <td>${lastSeenHtml}</td>
        <td class="small">${expiresHtml}</td>
      </tr>`;
  }).join('');
}

// ──────────────────────────────────────────
// 一鍵解除登入限制
// ──────────────────────────────────────────
async function laUnfreezeAll() {
  const ok = await confirmAdminAction(
    '所有因為密碼輸錯而被暫停的帳號會馬上可以登入，同一個 IP 的失敗次數也會歸零。要繼續嗎？',
    { title: '解除登入限制', confirmText: '解除' },
  );
  if (!ok) return;
  const btn = document.getElementById('la-unfreezeBtn');
  btn.disabled = true;
  try {
    const res = await apiCall('/api/admin/login-unfreeze', { method: 'POST' });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      showToast(data.detail || '解除失敗，請稍後再試。');
      return;
    }
    showToast(data.message || '已解除登入限制。', 'success');
  } catch (e) {
    showToast('解除失敗，請稍後再試。');
  } finally {
    btn.disabled = false;
  }
}
