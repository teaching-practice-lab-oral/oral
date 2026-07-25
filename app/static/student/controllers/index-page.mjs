import { AccountSetupController } from '/static/student/account-setup.mjs?v=1';

function clearStudentAuthState() {
  ['role', 'name', 'user_id', 'userId', 'studentId', 'must_change_password', 'requires_legal_acknowledgement', 'isPrivilegedAdmin']
    .forEach(key => sessionStorage.removeItem(key));
}

function redirectToStudentLogin(message = '登入逾期，請重新登入。') {
  clearStudentAuthState();
  sessionStorage.setItem('loginAlert', message);
  window.location.replace('/login');
}

window.ApiUnauthorizedHandler = async response => {
  let message = '登入逾期，請重新登入。';
  try { message = (await response.json()).detail || message; } catch (_) {}
  redirectToStudentLogin(message);
};

const accountSetup = new AccountSetupController({
  apiReady: window.StudentApiClientReady,
  nativeFetch: window.StudentApiNativeFetch,
});

async function bootstrapStudentPage() {
  try {
    const refresh = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
    if (refresh.status === 401) {
      redirectToStudentLogin();
      return;
    }
    const response = await fetch('/api/auth/me', { credentials: 'include' });
    if (response.status === 401 || response.status === 403) {
      redirectToStudentLogin();
      return;
    }
    if (!response.ok) throw new Error('auth_unavailable');
    const data = await response.json();
    if (data.role === 'admin') {
      window.location.href = '/admin';
      return;
    }
    sessionStorage.setItem('role', data.role);
    sessionStorage.setItem('name', data.name);
    sessionStorage.setItem('must_change_password', data.must_change_password ? '1' : '0');
    sessionStorage.setItem('requires_legal_acknowledgement', data.requires_legal_acknowledgement ? '1' : '0');
    sessionStorage.setItem('isPrivilegedAdmin', data.is_privileged_admin ? '1' : '0');
    document.getElementById('userName').textContent = data.name || '';
    if (data.must_change_password || data.requires_legal_acknowledgement) {
      await accountSetup.open({
        forcePassword: data.must_change_password,
        requiresLegal: data.requires_legal_acknowledgement,
      });
    }
    await loadAssignments();
  } catch (_) {
    document.getElementById('loadingMsg').innerHTML = '<p class="text-danger">目前無法連線，請稍後重新整理。</p>';
  }
}

async function logout() {
  try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }); } catch(_) {}
  sessionStorage.clear();
  window.location.href = '/login';
}

function authHeaders() {
  const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return { 'Content-Type': 'application/json', 'X-CSRF-Token': m ? m[1] : '' };
}

const assignmentItemsById = new Map();
function stageLabel(stage) { return StudentWorkflow.stageLabel(stage); }

function fmtDatetime(str) {
  if (!str) return '';
  const d = new Date(str);
  return d.toLocaleString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

function dateStatus(a) {
  return StudentWorkflow.dateStatus(a);
}

function retryAvailability(assignment, dateState = dateStatus(assignment)) {
  const maxAttempts = Number(StudentWorkflow.metadata()?.limits?.max_attempts);
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1) {
    return { allowed: false, reason: '目前無法確認練習次數限制，請重新整理。' };
  }
  if (Number(assignment.attempt_number) >= maxAttempts) {
    return { allowed: false, reason: `已達最多練習次數（${maxAttempts}/${maxAttempts}）` };
  }
  if (dateState.state === 'pending') {
    return { allowed: false, reason: '作業尚未開放，暫時無法再次練習。' };
  }
  if (dateState.state === 'overdue') {
    return { allowed: false, reason: '作業已截止，無法再次練習。' };
  }
  return { allowed: true, reason: '' };
}

function reportViewUrl(assignmentId, submissionId) {
  const normalizedAssignmentId = Number(assignmentId);
  const normalizedSubmissionId = Number(submissionId);
  if (!Number.isInteger(normalizedAssignmentId) || normalizedAssignmentId < 1
      || !Number.isInteger(normalizedSubmissionId) || normalizedSubmissionId < 1) {
    return '';
  }
  return `/student/assignment/${normalizedAssignmentId}/report?view=${normalizedSubmissionId}`;
}

function renderCompletedActions(assignment, dateState) {
  const availability = retryAvailability(assignment, dateState);
  const assignmentId = Number(assignment.id);
  const resultUrl = reportViewUrl(assignmentId, assignment.latest_submitted_submission_id);
  const exportSubmissionId = Number(assignment.result_export_submission_id);
  const canExport = Number.isInteger(exportSubmissionId) && exportSubmissionId > 0;
  const resultAction = resultUrl
    ? `<a href="${resultUrl}" class="btn btn-view"><i class="bi bi-eye me-1"></i>查看成果</a>`
    : '<button type="button" class="btn btn-view" disabled title="找不到已完成的提交紀錄"><i class="bi bi-eye me-1"></i>查看成果</button>';
  const exportAction = canExport
    ? `<button type="button" class="btn btn-export-result" data-action="exportResultPackage" data-args='[${assignmentId},${exportSubmissionId}]' data-export-submission-id="${exportSubmissionId}"><i class="bi bi-file-earmark-zip me-1"></i>作業匯出</button>`
    : '<button type="button" class="btn btn-export-result" disabled title="老師完成批改後即可匯出"><i class="bi bi-file-earmark-zip me-1"></i>作業匯出</button>';
  const retryAttributes = availability.allowed
    ? `data-action="retryAssignment" data-args='[${assignmentId}]' data-retry-assignment-id="${assignmentId}"`
    : `disabled title="${escHtml(availability.reason)}"`;
  return `<div class="completed-actions">
    ${resultAction}
    <button type="button" class="btn btn-retry" ${retryAttributes}><i class="bi bi-arrow-repeat me-1"></i>再次練習</button>
    ${exportAction}
  </div>
  <div id="resultExportFeedback-${assignmentId}" class="result-export-feedback" role="status" aria-live="polite"></div>
  <div id="retryFeedback-${assignmentId}" class="retry-feedback" role="status" aria-live="polite">${availability.allowed ? '' : escHtml(availability.reason)}</div>`;
}

function setResultExportFeedback(assignmentId, message, success = false) {
  const feedback = document.getElementById(`resultExportFeedback-${Number(assignmentId)}`);
  if (!feedback) return;
  feedback.textContent = message || '';
  feedback.classList.toggle('is-success', success);
}

function resultPackageFilename(response, fallback) {
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (!match) return fallback;
  try { return decodeURIComponent(match[1].trim()); } catch (_) { return fallback; }
}

async function exportResultPackage(assignmentId, submissionId) {
  const normalizedAssignmentId = Number(assignmentId);
  const normalizedSubmissionId = Number(submissionId);
  const button = document.querySelector(`[data-export-submission-id="${normalizedSubmissionId}"]`);
  const originalHtml = button?.innerHTML || '';
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>正在打包…';
  }
  setResultExportFeedback(normalizedAssignmentId, '');

  try {
    const response = await fetch(
      `/api/student/submissions/${normalizedSubmissionId}/export-result-package`,
      { credentials: 'include', headers: authHeaders() },
    );
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(error?.detail || '成果包匯出失敗，請稍後再試。');
    }
    const blob = await response.blob();
    const filename = resultPackageFilename(response, `學習成果_${normalizedSubmissionId}.zip`);
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    setResultExportFeedback(normalizedAssignmentId, '成果包下載已開始。', true);
  } catch (error) {
    setResultExportFeedback(
      normalizedAssignmentId,
      error?.message || '成果包匯出失敗，請稍後再試。',
    );
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.innerHTML = originalHtml;
    }
  }
}

function setRetryFeedback(assignmentId, message) {
  const feedback = document.getElementById(`retryFeedback-${Number(assignmentId)}`);
  if (feedback) feedback.textContent = message || '';
}

async function retryAssignment(assignmentId) {
  const id = Number(assignmentId);
  const assignment = assignmentItemsById.get(id);
  if (!assignment) return;

  const availability = retryAvailability(assignment);
  if (!availability.allowed) {
    setRetryFeedback(id, availability.reason);
    return;
  }

  const button = document.querySelector(`[data-retry-assignment-id="${id}"]`);
  const originalHtml = button?.innerHTML || '';
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>準備中...';
  }
  setRetryFeedback(id, '');

  try {
    const { requestJson } = await window.StudentApiClientReady;
    await requestJson(`/api/student/assignments/${id}/start`, {
      method: 'POST',
    }, window.StudentApiNativeFetch);
    window.location.href = `/student/assignment/${id}/job-profile`;
  } catch (error) {
    setRetryFeedback(id, error?.detail || error?.message || '目前無法開始新的練習，請稍後再試。');
    if (button?.isConnected) {
      button.disabled = false;
      button.innerHTML = originalHtml;
    }
  }
}

function openRecordsModal(assignment, label) {
  const modalEl = document.getElementById('assignmentRecordsModal');
  document.getElementById('assignmentRecordsModalTitle').textContent = `${assignment.title}｜${label}`;
  const body = document.getElementById('assignmentRecordsModalBody');
  body.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div><p class="text-muted mt-2 mb-0">載入中...</p></div>';
  bootstrap.Modal.getOrCreateInstance(modalEl).show();
  return body;
}

async function fetchStudentRecord(url) {
  const response = await fetch(url, { credentials: 'include', headers: authHeaders() });
  if (response.status === 401) {
    redirectToStudentLogin();
    return null;
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error((data && data.detail) || '資料載入失敗，請稍後再試。');
  }
  return data;
}

function renderRecordError(body, error) {
  body.innerHTML = `<div class="alert alert-danger mb-0"><i class="bi bi-exclamation-triangle-fill me-1"></i>${escHtml(error && error.message ? error.message : '資料載入失敗，請稍後再試。')}</div>`;
}

async function openSubmissionHistory(assignmentId) {
  const assignment = assignmentItemsById.get(Number(assignmentId));
  if (!assignment) return;
  const body = openRecordsModal(assignment, '提交紀錄');
  try {
    const data = await fetchStudentRecord(`/api/student/assignments/${Number(assignmentId)}/attempts`);
    if (!data) return;
    const attempts = (Array.isArray(data) ? data : [])
      .filter(item => item && item.submitted_at)
      .sort((left, right) => Number(right.attempt_number) - Number(left.attempt_number));
    if (!attempts.length) {
      body.innerHTML = '<div class="text-center text-muted py-5"><i class="bi bi-inbox fs-1 d-block mb-2"></i>目前尚無已正式送出的提交紀錄。</div>';
      return;
    }
    body.innerHTML = `<div class="d-grid gap-3">${attempts.map(attempt => {
      const submissionId = Number(attempt.id);
      const attemptNumber = Number(attempt.attempt_number);
      return `<div class="record-list-item d-flex align-items-center justify-content-between gap-3 flex-wrap">
        <div><div class="fw-bold">第 ${attemptNumber} 次練習</div><div class="small text-muted mt-1">完成時間：${escHtml(fmtDatetime(attempt.submitted_at))}</div></div>
        <a class="btn btn-outline-primary btn-sm" href="${reportViewUrl(assignmentId, submissionId)}"><i class="bi bi-eye me-1"></i>查看完整結果</a>
      </div>`;
    }).join('')}</div>`;
  } catch (error) {
    renderRecordError(body, error);
  }
}

function gradeReason(grade) {
  const reason = String(grade.change_reason || '').trim();
  if (reason) return reason;
  return Number(grade.revision_number) === 1 ? '初次批改' : '未留存修改理由';
}

function gradeIdentity(grade) {
  const name = String(grade.grader_name || '').trim();
  const studentId = String(grade.grader_student_id || '').trim();
  if (name && studentId) return `${name}（${studentId}）`;
  return name || studentId || '未留存批改者';
}

function renderGradeRatings(ratings) {
  const items = Array.isArray(ratings) ? ratings : [];
  if (!items.length) return '<p class="text-muted small mb-0">此版本沒有可顯示的評分項目。</p>';
  return items.map(item => {
    const dimension = String(item.dimension_name || '').trim();
    const criterion = String(item.criterion_name || '').trim();
    const label = [dimension, criterion].filter(Boolean).join(' · ') || '評分項目';
    const anchor = String(item.level_anchor || '').trim();
    return `<div class="grade-rating d-flex justify-content-between align-items-start gap-3 flex-wrap">
      <div class="flex-grow-1"><span>${escHtml(label)}</span>${anchor ? `<div class="small text-muted mt-1">${escHtml(anchor)}</div>` : ''}</div>
      <strong class="text-primary">${escHtml(item.level_label || '—')}</strong>
    </div>`;
  }).join('');
}

function renderGradeRevision(grade, isCurrentVersion, open) {
  const revisionNumber = Number(grade.revision_number);
  const finalScore = Number(grade.final_score);
  const scoreText = Number.isFinite(finalScore) ? finalScore.toLocaleString('zh-TW', { maximumFractionDigits: 1 }) : '—';
  return `<details class="grade-revision"${open ? ' open' : ''}>
    <summary class="d-flex justify-content-between align-items-center gap-3 flex-wrap">
      <span><strong>第 ${revisionNumber} 版</strong>${isCurrentVersion ? '<span class="badge text-bg-success ms-2">目前版本</span>' : '<span class="badge text-bg-secondary ms-2">舊版本</span>'}<span class="small text-muted ms-2">${escHtml(fmtDatetime(grade.graded_at))}</span></span>
      <strong class="text-primary fs-5">${scoreText} 分</strong>
    </summary>
    <div class="grade-revision-body">
      <div class="row g-2 small mb-3">
        <div class="col-md-6"><strong>評分規準：</strong>${escHtml(grade.rubric_name || '—')} v${escHtml(grade.rubric_version_number || '—')}</div>
        <div class="col-md-6"><strong>批改者：</strong>${escHtml(gradeIdentity(grade))}</div>
        <div class="col-12"><strong>修改理由：</strong>${escHtml(gradeReason(grade))}</div>
      </div>
      <h6 class="fw-bold">總評</h6><p style="white-space:pre-wrap">${escHtml(grade.teacher_comment || '—')}</p>
      <h6 class="fw-bold">改進建議</h6><p style="white-space:pre-wrap">${escHtml(grade.teacher_feedback || '—')}</p>
      <h6 class="fw-bold mb-1">各項評分等級</h6>${renderGradeRatings(grade.ratings)}
    </div>
  </details>`;
}

async function openGradeHistory(assignmentId) {
  const assignment = assignmentItemsById.get(Number(assignmentId));
  if (!assignment) return;
  const body = openRecordsModal(assignment, '成績');
  try {
    const data = await fetchStudentRecord(`/api/student/assignments/${Number(assignmentId)}/grade-history`);
    if (!data) return;
    const grades = (Array.isArray(data) ? data : []).sort((left, right) => (
      Number(right.attempt_number) - Number(left.attempt_number)
      || Number(right.revision_number) - Number(left.revision_number)
    ));
    if (!grades.length) {
      body.innerHTML = '<div class="text-center text-muted py-5"><i class="bi bi-award fs-1 d-block mb-2"></i>老師尚未完成批改。</div>';
      return;
    }
    const attempts = new Map();
    grades.forEach(grade => {
      const attemptNumber = Number(grade.attempt_number);
      if (!attempts.has(attemptNumber)) attempts.set(attemptNumber, []);
      attempts.get(attemptNumber).push(grade);
    });
    body.innerHTML = [...attempts.entries()].map(([attemptNumber, revisions], attemptIndex) => `
      <section class="grade-attempt">
        <h6 class="fw-bold mb-3"><i class="bi bi-journal-check me-1 text-primary"></i>第 ${attemptNumber} 次練習</h6>
        ${revisions.map((grade, revisionIndex) => renderGradeRevision(grade, revisionIndex === 0, attemptIndex === 0 && revisionIndex === 0)).join('')}
      </section>`).join('');
  } catch (error) {
    renderRecordError(body, error);
  }
}

async function loadAssignments() {
  await StudentWorkflow.ready();
  const loading = document.getElementById('loadingMsg');
  const empty = document.getElementById('emptyMsg');
  const list = document.getElementById('assignmentList');
  loading.classList.remove('d-none');
  empty.classList.add('d-none');
  list.innerHTML = '';

  const res = await fetch('/api/student/assignments', { credentials: 'include', headers: authHeaders() });
  if (res.status === 401) { let m='登入逾期，請重新登入。'; try{const e=await res.clone().json();if(e.detail)m=e.detail;}catch(_){} redirectToStudentLogin(m); return; }
  if (res.status === 403) {
    loading.classList.add('d-none');
    let detail = '';
    try { const e = await res.clone().json(); detail = e.detail || ''; } catch (_) {}
    if (detail.includes('完成帳戶設定')) await bootstrapStudentPage();
    return;
  }
  const data = await res.json();

  loading.classList.add('d-none');
  assignmentItemsById.clear();
  data.forEach(assignment => assignmentItemsById.set(Number(assignment.id), assignment));

  if (!data.length) {
    empty.classList.remove('d-none');
    return;
  }

  data.forEach(a => {
    const stageNum = a.current_stage || 1;
    const isCompleted = a.is_submitted;
    const stageToStep = {1:1,2:2,3:2,4:2,5:3,6:4,7:4,8:6,9:6};
    const displayStage = stageToStep[stageNum] || 1;
    const pct = Math.round((displayStage / 6) * 100);
    const ds = dateStatus(a);

    const accentClass = isCompleted ? 'completed' : (ds.state === 'overdue' ? 'overdue' : ds.state === 'late' ? 'warning' : stageNum >= 6 ? 'warning' : '');
    let statusHtml;
    if (ds.state === 'pending') {
      statusHtml = `<span class="status-badge status-pending"><i class="bi bi-clock me-1"></i>尚未開放</span>`;
    } else if (ds.state === 'overdue' && !isCompleted) {
      statusHtml = `<span class="status-badge status-overdue"><i class="bi bi-calendar-x me-1"></i>已截止</span>`;
    } else if (ds.state === 'late' && !isCompleted) {
      statusHtml = `<span class="status-badge status-late"><i class="bi bi-calendar-plus me-1"></i>補繳中・第 ${displayStage}/6 階段：${stageLabel(stageNum)}</span>`;
    } else if (isCompleted) {
      statusHtml = `<span class="status-badge status-completed"><i class="bi bi-check-circle-fill"></i>已完成</span>`;
    } else if (stageNum >= 6) {
      statusHtml = `<span class="status-badge status-warning"><i class="bi bi-hourglass-split"></i>第 ${displayStage}/6 階段：${stageLabel(stageNum)}</span>`;
    } else {
      statusHtml = `<span class="status-badge status-active"><i class="bi bi-play-circle-fill"></i>第 ${displayStage}/6 階段：${stageLabel(stageNum)}</span>`;
    }

    const barColor = isCompleted ? 'bg-success' : (stageNum >= 6 ? 'bg-warning' : 'bg-primary');
    const sectionUrl = StudentWorkflow.assignmentPath({
      assignmentId: a.id,
      stage: a.current_stage,
      completed: isCompleted,
      hasJobProfile: a.has_job_profile,
    });

    let btnHtml;
    if (isCompleted) {
      btnHtml = renderCompletedActions(a, ds);
    } else if (ds.state === 'pending') {
      btnHtml = `<button class="btn btn-locked" disabled><i class="bi bi-lock me-1"></i>尚未開放</button>`;
    } else if (ds.state === 'late') {
      btnHtml = `<a href="${sectionUrl}" class="btn btn-start w-100" style="background:linear-gradient(90deg,#d97706,#b45309)"><i class="bi bi-pencil-fill me-1"></i>${stageNum === 1 ? '開始補繳' : '繼續補繳'}</a>`;
    } else if (ds.state === 'overdue') {
      btnHtml = a.attempt_number > 0
        ? `<a href="${sectionUrl}" class="btn btn-view w-100"><i class="bi bi-eye me-1"></i>檢視作業</a>`
        : `<button class="btn btn-locked" disabled><i class="bi bi-calendar-x me-1"></i>已截止</button>`;
    } else {
      btnHtml = `<a href="${sectionUrl}" class="btn btn-start w-100"><i class="bi bi-play-fill me-1"></i>${stageNum === 1 ? '開始作業' : '繼續練習'}</a>`;
    }

    const dueBadgeClass = ds.state === 'overdue' ? 'overdue' : ds.state === 'late' ? 'late' : '';
    const dueBadgeIcon = ds.state === 'overdue' ? 'calendar-x' : ds.state === 'late' ? 'calendar-plus' : (ds.state === 'pending' ? 'calendar-plus' : 'calendar');

    const col = document.createElement('div');
    col.className = 'col-md-6 col-lg-4';
    col.innerHTML = `
      <div class="assignment-card">
        <div class="card-accent ${accentClass}"></div>
        <div class="card-content">
          <div class="d-flex justify-content-between align-items-start mb-2">
            <div class="assignment-title">${escHtml(a.title)}</div>
          </div>
          <p class="assignment-desc">${escHtml(a.description || '—')}</p>
          <div class="stage-progress">
            <div class="stage-label">
              <span class="stage-name">${statusHtml}</span>
              <span class="stage-count">${displayStage}/6</span>
            </div>
            <div class="progress">
              <div class="progress-bar ${barColor}" style="width:${pct}%"></div>
            </div>
          </div>
          <div class="due-badge ${dueBadgeClass}">
            <i class="bi bi-${dueBadgeIcon}"></i>
            ${escHtml(ds.text)}
          </div>
          <div class="assignment-actions">
            ${btnHtml}
            <div class="record-actions">
              <button type="button" class="btn-record" data-action="openSubmissionHistory" data-args='[${Number(a.id)}]' ${a.has_submission_history ? '' : 'disabled title="尚無提交紀錄"'}><i class="bi bi-clock-history me-1"></i>查看提交紀錄</button>
              <button type="button" class="btn-record" data-action="openGradeHistory" data-args='[${Number(a.id)}]' ${a.has_grade_history ? '' : 'disabled title="老師尚未完成批改"'}><i class="bi bi-award me-1"></i>查看成績</button>
            </div>
          </div>
        </div>
      </div>`;
    list.appendChild(col);
  });
}

function escHtml(str) {
  return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

bootstrapStudentPage();

Object.assign(window, {
  clearStudentAuthState,
  redirectToStudentLogin,
  bootstrapStudentPage,
  logout,
  authHeaders,
  openChangePw: () => accountSetup.open(),
  doChangePassword: () => accountSetup.submit(),
  stageLabel,
  fmtDatetime,
  dateStatus,
  retryAvailability,
  reportViewUrl,
  renderCompletedActions,
  setResultExportFeedback,
  resultPackageFilename,
  exportResultPackage,
  setRetryFeedback,
  retryAssignment,
  openRecordsModal,
  fetchStudentRecord,
  renderRecordError,
  openSubmissionHistory,
  gradeReason,
  gradeIdentity,
  renderGradeRatings,
  renderGradeRevision,
  openGradeHistory,
  loadAssignments,
  escHtml,
});
