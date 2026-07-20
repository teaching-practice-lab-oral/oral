const pathParts = window.location.pathname.split('/');
window.assignmentId = parseInt(pathParts[3]);
const urlParams = new URLSearchParams(window.location.search);
window.viewId = urlParams.get('view') ? parseInt(urlParams.get('view')) : null;

window.submission = null;
window.assignment = null;
window.viewedSubmission = null;

async function init() {
  await window.practiceLaunchReady;
  const { response: res, data } = await StudentPracticeRuntime.assignmentContext();
  if (!res.ok) {
    document.getElementById('loadingMsg').innerHTML = `<p class="text-danger">${escHtml(data.detail || '載入失敗')}</p>`;
    return;
  }

  setWorkflowLimits(data.workflow_limits);
  assignment = data.assignment;
  submission = data.submission;

  if (!submission) {
    navigateStudentPage(`/student/assignment/${assignmentId}/writing`);
    return;
  }

  if (viewId) {
    try {
      viewedSubmission = await loadViewedSubmissionForAssignment(viewId, assignmentId);
    } catch (error) {
      renderStudentPageLoadError(error);
      return;
    }
  }

  const vs = getView();
  const stage = vs ? vs.stage : 1;
  const isCompleted = !!(vs && vs.submitted_at);

  if (stage < 8 && !viewId && !isCompleted) {
    const redirect = stage >= 6
      ? `/student/assignment/${assignmentId}/roleplay`
      : (stage >= 5 ? `/student/assignment/${assignmentId}/shadowing` : `/student/assignment/${assignmentId}/writing`);
    navigateStudentPage(redirect);
    return;
  }

  if (!viewId && !submission.job_profile_data) {
    navigateStudentPage(`/student/assignment/${assignmentId}/job-profile`);
    return;
  }
  document.getElementById('loadingMsg').classList.add('d-none');
  document.getElementById('content').classList.remove('d-none');
  document.getElementById('assignmentTitle').textContent = assignment.title;
  document.getElementById('assignmentDesc').textContent = assignment.description || '';
  if (submission && submission.late_deadline && assignment.due_date && new Date() > new Date(assignment.due_date)) {
    const el = document.getElementById('dueDate');
    el.textContent = `補繳截止：${new Date(submission.late_deadline).toLocaleString('zh-TW')}`;
    el.style.color = '#d97706';
    el.style.fontWeight = '600';
  } else if (assignment.due_date) {
    document.getElementById('dueDate').textContent = `截止日期：${new Date(assignment.due_date).toLocaleString('zh-TW')}`;
  }
  if (submission) {
    renderAttemptBadge(submission);
  }

  renderAll();
}

function renderAll() {
  const vs = getView();
  const stage = vs ? vs.stage : 8;
  const isCompleted = !!(vs && vs.submitted_at);

  updateProgressSteps(isCompleted ? 9 : stage);

  renderViewBanner();
  const isViewingPast = !!viewId;

  const container = document.getElementById('sectionContainer');
  container.innerHTML = '';
  renderSection4(container, stage, isCompleted);

  const nav = document.getElementById('sectionNav');
  nav.innerHTML = `
    <div><button class="btn-nav" data-action="navigateSection" data-args='[4]'><i class="bi bi-chevron-left me-1"></i>角色扮演</button></div>
    <div>${!isViewingPast && stage >= 8 && !isCompleted ? '<button class="btn-nav-next" data-action="navigateSection" data-args="[6]">心得撰寫<i class="bi bi-chevron-right ms-1"></i></button>' : ''}</div>`;

}

// ── Section 4: Report ──────────────────────────────────────────────────

function feedbackBulletItems(value) {
  if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean);
  const text = String(value || '').trim();
  if (!text) return [];
  const lines = text.split(/\n+/).flatMap(line => line.match(/[^。！？]+[。！？]?/g) || []);
  return lines.map(item => item.trim()).filter(Boolean);
}

function renderSection4(container, stage, isCompleted) {
  const isDone = stage >= 8 || isCompleted;
  const isLocked = stage < 8 && !isCompleted;

  const card = document.createElement('div');
  card.className = `section-card ${isLocked ? 'locked' : isDone ? 'completed' : 'active'}`;
  card.innerHTML = `
    <div class="section-header">
      <div class="section-icon"><i class="bi bi-bar-chart-fill"></i></div>
      <div>
        <div class="section-title">學習回饋</div>
        <div class="section-subtitle">Learning Feedback</div>
      </div>
      ${isDone ? '<span class="ms-auto badge bg-white text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>完成</span>' : ''}
    </div>
    <div class="section-body" id="reportBody"></div>`;
  container.appendChild(card);
  if (isLocked) return;

  const body = card.querySelector('#reportBody');
  const report = getView() && getView().report_data ? tryParseJson(getView().report_data) : null;

  if (!report) {
    body.innerHTML = renderTaskGuide({
      title:'AI 回饋正在整理',
      progress:'角色扮演錄音與逐字稿已保留',
      actions:['不用重新錄音或重做角色扮演。','先留在目前頁面，等待系統完成整理。','稍後仍未顯示時，重新整理此頁再試。'],
      support:{title:'等待時先不用做什麼',items:['不要連續重整或重複提交；系統只是在重新整理回饋。']},
      checks:['原本的角色扮演回答仍可回看。','AI 回饋已出現在下方。'],
      next:'回饋出現後，先選一個優點與一個最先改善的地方。',
      view:getView(),
      state:viewId?'completed':isPastDue()?'read-only':'active',
    });
    return;
  }

  const analysis = report.analysis || {};
  const analysisLabels = {
    language_complexity:{ zh: '語言豐富度',       en: 'Language Complexity' },
    language_accuracy: { zh: '語言準確度',       en: 'Language Accuracy' },
    content_logic:     { zh: '內容邏輯與組織',   en: 'Content Logic' },
    interview_strategy:{ zh: '面試策略與表現效果', en: 'Interview Strategy' },
  };

  const strengths = feedbackBulletItems(report.strengths);
  const suggestions = feedbackBulletItems(report.overall_suggestions);
  const guideState=viewId||isCompleted?'completed':isPastDue()?'read-only':'active';
  const guideHtml=renderTaskGuide({
    title:guideState==='active'?'帶走一個優點＋一個最先改的地方':'這次 AI 回饋已整理完成',
    progress:`${strengths.length} 個優點・${suggestions.length} 個改進建議`,
    actions:['先從「優勢」找一點，回想它出現在哪一題或哪一輪。','再從「改進建議」只選一項，作為最先處理的重點。','想清楚下次要改哪個動作，不只記住「要加強」。'],
    support:{title:'回饋很多，不知道先看哪裡時',items:['先看會影響聽者理解或回答是否切題的問題，再看小文法。','這是 AI 回饋，不是老師正式成績；要用自己的作答證據判斷是否適合。'],html:learningScaffoldStageHtml(getView(),'report')},
    checks:['我能指出一個優點出現在哪裡。','我只選了一項優先改善重點。','我說得出下次要怎麼做得不一樣。'],
    next:'前往心得，把選到的優點、問題與下一步寫成具體證據。',
    view:getView(),
    state:guideState,
  });

  let html = `${guideHtml}<p class="fw-bold mb-3"><i class="bi bi-clipboard-data me-1 text-primary"></i>詳細分析 Detailed Analysis</p>
    <div class="row g-3 mb-4">`;
  for (const [key, labels] of Object.entries(analysisLabels)) {
    const items = feedbackBulletItems(analysis[key]);
    if (!items.length) continue;
    html += `
      <div class="col-12 col-md-6">
        <div class="analysis-item">
          <div class="analysis-label"><i class="bi bi-dot me-1"></i>${labels.zh} / ${labels.en}</div>
          <ul class="mb-0 ps-3 small">${items.map(item => `<li class="mb-1">${escHtml(item)}</li>`).join('')}</ul>
        </div>
      </div>`;
  }
  html += `</div>`;

  if (strengths.length > 0) {
    html += `<p class="fw-bold mb-2"><i class="bi bi-stars me-1 text-success"></i>優勢 Strengths</p><ul class="mb-3">`;
    html += strengths.map(s => `<li class="mb-1"><span class="text-success me-1">✓</span>${escHtml(s)}</li>`).join('');
    html += `</ul>`;
  }

  if (suggestions.length > 0) {
    html += `<p class="fw-bold mb-2"><i class="bi bi-lightbulb me-1 text-primary"></i>改進建議 Suggestions</p><ul class="mb-0">`;
    html += suggestions.map(s => `<li class="mb-1"><span class="text-primary me-1">→</span>${escHtml(s)}</li>`).join('');
    html += `</ul>`;
  }

  body.innerHTML = html;
}

init().catch(error=>renderStudentPageLoadError(error));

Object.assign(window, {
  init,
  renderAll,
  feedbackBulletItems,
  renderSection4,
});
