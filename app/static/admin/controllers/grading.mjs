const loadingState = document.getElementById('loadingState');
const errorState = document.getElementById('errorState');
const emptyState = document.getElementById('emptyState');
const gradingGrid = document.getElementById('gradingGrid');

function setState(state) {
  loadingState.classList.toggle('d-none', state !== 'loading');
  errorState.classList.toggle('d-none', state !== 'error');
  emptyState.classList.toggle('d-none', state !== 'empty');
  gradingGrid.classList.toggle('d-none', state !== 'ready');
}

async function loadGradingQueue() {
  await window._adminReady;
  try {
    const assignmentResponse = await fetch('/api/admin/assignments', { headers: authHeaders() });
    if (assignmentResponse.status === 401) {
      redirectAdminToLogin();
      return;
    }
    if (!assignmentResponse.ok) throw new Error('作業列表載入失敗');
    const assignments = await assignmentResponse.json();
    const queue = await Promise.all(assignments.map(async assignment => {
      const resultResponse = await fetch(`/api/admin/assignments/${assignment.id}/results`, { headers: authHeaders() });
      if (!resultResponse.ok) return { ...assignment, pending: 0, completed: 0, total: 0, unavailable: true };
      const results = await resultResponse.json();
      return {
        ...assignment,
        pending: results.filter(student => student.grading_status === 'pending').length,
        graded: results.filter(student => student.grading_status === 'graded').length,
        inProgress: results.filter(student => student.attempt_count > 0 && !student.is_submitted).length,
        notStarted: results.filter(student => student.attempt_count === 0).length,
        needsHelp: results.filter(student => student.has_issue).length,
        total: results.length,
      };
    }));

    if (!queue.length) {
      setState('empty');
      return;
    }
    gradingGrid.innerHTML = queue.map(assignment => {
      const countClass = assignment.pending ? '' : 'is-clear';
      const status = assignment.unavailable
        ? '<span class="badge bg-warning text-dark">目前無法載入</span>'
        : assignment.is_active ? '<span class="badge bg-success">開放中</span>' : '<span class="badge bg-secondary">已關閉</span>';
      return `<div class="col-12 col-md-6 col-xl-4">
        <article class="card grading-card">
          <div class="card-header d-flex align-items-center gap-2">
            ${status}<strong class="text-truncate" title="${escAttr(assignment.title)}">${escHtml(assignment.title)}</strong>
          </div>
          <div class="card-body">
            <div class="d-flex align-items-end gap-2 mb-3">
              <span class="pending-count ${countClass}">${assignment.pending}</span>
              <span class="text-muted small mb-1">位待批改</span>
            </div>
            <div class="queue-status-grid" aria-label="${escAttr(assignment.title)}工作狀態摘要">
              <div class="queue-status"><strong>${assignment.notStarted || 0}</strong><span>未開始</span></div>
              <div class="queue-status"><strong>${assignment.inProgress || 0}</strong><span>練習中</span></div>
              <div class="queue-status"><strong>${assignment.graded || 0}</strong><span>已批改</span></div>
              <div class="queue-status needs-help"><strong>${assignment.needsHelp || 0}</strong><span>需協助</span></div>
            </div>
          </div>
          <div class="card-footer bg-transparent border-0 pt-0">
            <a class="btn btn-primary w-100" href="/admin/assignments/${assignment.id}/results?filter=pending">
              <i class="bi bi-clipboard-check me-1"></i>${assignment.pending ? '開始批改' : '查看作業結果'}
            </a>
            ${assignment.needsHelp ? `<a class="btn btn-outline-danger w-100 mt-2" href="/admin/assignments/${assignment.id}/results?filter=issue"><i class="bi bi-exclamation-triangle me-1"></i>查看需協助學生（${assignment.needsHelp}）</a>` : ''}
          </div>
        </article>
      </div>`;
    }).join('');
    setState('ready');
  } catch (error) {
    errorState.textContent = error.message || '批改名單載入失敗，請重新整理後再試。';
    setState('error');
  }
}

loadGradingQueue();

Object.assign(window, {
  setState,
  loadGradingQueue,
});
