const pathParts = window.location.pathname.split('/');
window.assignmentId = parseInt(pathParts[3]);
const urlParams = new URLSearchParams(window.location.search);
window.viewId = urlParams.get('view') ? parseInt(urlParams.get('view')) : null;

window.submission = null;
window.assignment = null;
window.viewedSubmission = null;
let savedDraft1Indices = new Set();
let savedFinalDraftIndices = new Set();

function safeStr(v) { if (v === null || v === undefined) return ''; if (typeof v === 'string') return v; return JSON.stringify(v); }

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
    const startRes = await apiCall(`/api/student/assignments/${assignmentId}/start`, { method: 'POST' });
    const startData = await startRes.json();
    if (!startRes.ok) {
      document.getElementById('loadingMsg').innerHTML = `<div class="alert alert-danger">${escHtml(startData.detail || '無法開始作業')}</div>`;
      return;
    }
    submission = startData;
    await StudentPracticeRuntime.recordPracticeStart(submission);
  }

  if (viewId) {
    try {
      viewedSubmission = await loadViewedSubmissionForAssignment(viewId, assignmentId);
    } catch (error) {
      renderStudentPageLoadError(error);
      return;
    }
  }
  if (!viewId && !submission.job_profile_data) {
    navigateStudentPage(`/student/assignment/${assignmentId}/job-profile`);
    return;
  }

  document.getElementById('loadingMsg').classList.add('d-none');
  document.getElementById('content').classList.remove('d-none');
  document.getElementById('assignmentTitle').textContent = assignment.title;
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
    if (submission.draft1_answers) {
      submission.draft1_answers.forEach(a => savedDraft1Indices.add(a.index));
    }
    if (submission.final_draft_answers) {
      submission.final_draft_answers.forEach(a => savedFinalDraftIndices.add(a.index));
    }
  }

  renderAll();
}

function renderAll() {
  const vs = getView();
  const stage = vs ? vs.stage : 2;
  const isCompleted = !!(vs && vs.submitted_at);

  updateProgressSteps(isCompleted ? 9 : stage);

  renderViewBanner();
  const isViewingPast = viewedSubmission && submission && viewedSubmission.id !== submission.id;

  const container = document.getElementById('sectionContainer');
  container.innerHTML = '';
  renderSection1(container, stage, isCompleted);

  const writingDone = isCompleted || stage >= 5;
  const nav = document.getElementById('sectionNav');
  nav.innerHTML = `
    <div><button class="btn-nav" data-action="navigateSection" data-args='[1]'><i class="bi bi-chevron-left me-1"></i>欲應徵的職位</button></div>
    <div>${writingDone
      ? `<button class="btn-nav-next" data-action="navigateSection" data-args='[3]'>跟讀練習<i class="bi bi-chevron-right ms-1"></i></button>`
      : ''}</div>`;
}

// ── Section 1: Writing ─────────────────────────────────────────────────

function getQuestions() {
  return (assignment && Array.isArray(assignment.questions) && assignment.questions.length > 0)
    ? assignment.questions : [];
}

function getDraft1SavedMap(vs) {
  const map = {};
  if (vs && vs.draft1_answers && Array.isArray(vs.draft1_answers)) {
    vs.draft1_answers.forEach(a => { map[a.index] = a.text; });
  }
  return map;
}

function getFinalDraftSavedMap(vs) {
  const map = {};
  if (vs && vs.final_draft_answers && Array.isArray(vs.final_draft_answers)) {
    vs.final_draft_answers.forEach(a => { map[a.index] = a.text; });
  }
  return map;
}

function renderWritingTaskGuide(vs, stage, isCompleted, questions) {
  if (viewId || isCompleted || stage >= 5 || isPastDue()) return '';
  return renderAiGuide(vs);
}

function renderSection1(container, stage, isCompleted) {
  const isDone = stage >= 5 || isCompleted;
  // Past the deadline the page is read-only: render saved work, hide all editing controls.
  const isActive = !isDone && stage <= 4 && !isPastDue();
  const card = document.createElement('div');
  card.className = `section-card ${isDone ? 'completed' : 'active'}`;
  card.innerHTML = `
    <div class="section-header">
      <div>
        <div class="section-title">寫作練習</div>
        <div class="section-subtitle">Writing Practice</div>
      </div>
      ${isDone ? '<span class="section-status section-status-done"><i class="bi bi-check-circle-fill"></i>完成</span>' : '<span class="section-status section-status-active">進行中</span>'}
    </div>
    <div class="section-body" id="writingBody"></div>`;
  container.appendChild(card);
  const body = card.querySelector('#writingBody');
  const vs = getView();
  const questions = getQuestions();
  body.innerHTML = renderWritingTaskGuide(vs, stage, isCompleted, questions);

  // Sub-step A: Draft 1 (per-question boxes)
  const doneA = stage >= 3 || isCompleted;
  const activeA = isActive && !doneA;
  const draft1Map = getDraft1SavedMap(vs);
  const allDraft1Saved = questions.length > 0 && questions.every((_, i) => savedDraft1Indices.has(i));
  const maxFeedbackCount = workflowLimit('max_feedback_count');
  const draft1LockedAfterFeedback = !!(vs && vs.draft2_ai_feedback) && ((vs.feedback_count || 0) >= maxFeedbackCount);
  const draft1Editable = isActive && !draft1LockedAfterFeedback;

  let draft1Html = `
    <div class="sub-step ${doneA ? 'done' : activeA ? 'active-step' : ''}">
      <div class="sub-step-label">${doneA ? '✓ ' : ''}草稿一 Draft 1</div>`;

  if (questions.length === 0) {
    draft1Html += `<p class="text-muted small">（此作業未設定面試題目）</p>`;
  } else {
    questions.forEach((q, i) => {
      const saved = draft1Map[i];
      const isSaved = savedDraft1Indices.has(i);
      draft1Html += `<div class="mb-3 p-3 rounded panel-muted">
        <p id="draft1Label_${i}" class="fw-semibold mb-2 small text-brand">
          Q${i+1}：${escHtml(q)}
          ${isSaved ? '<span class="ms-2 badge bg-success fs-xs">已儲存</span>' : ''}
        </p>${learningScaffoldInlineHtml(vs,i,'writing')}`;
      if (isSaved && !draft1Editable) {
        draft1Html += `<div class="feedback-box"><pre>${escHtml(saved || '')}</pre></div>`;
      } else if (draft1Editable) {
        draft1Html += `<textarea class="form-control form-control-modern mb-2" id="draft1Input_${i}" rows="5" maxlength="2000"
          placeholder="請針對此題撰寫你的答案... / Write your answer here...">${escHtml(saved || '')}</textarea>
          <button class="btn btn-primary-custom btn-sm" id="draft1Btn_${i}" data-action="saveDraft1Answer" data-args='[${i}]'>
            ${isSaved ? '更新儲存' : '儲存此題'}
          </button>`;
      } else {
        draft1Html += `<div class="feedback-box"><pre>${escHtml(saved || '（未填寫）')}</pre></div>`;
      }
      draft1Html += `</div>`;
    });
  }
  if (draft1LockedAfterFeedback && !isCompleted && stage < 5) {
    draft1Html += `<div class="alert alert-info small mb-0"><i class="bi bi-lock-fill me-1"></i>${maxFeedbackCount} 次 AI 回饋皆已使用，草稿一已鎖定，避免終稿引用到不同版本的回饋。</div>`;
  }
  draft1Html += `</div>`;
  body.innerHTML += draft1Html;

  // Sub-step B: AI Feedback
  const doneB = stage >= 4 || isCompleted;
  const activeB = isActive && stage >= 3 && !doneB;
  const hasFeedback = vs && vs.draft2_ai_feedback;
  const feedbackIsBroken = hasFeedback && typeof hasFeedback === 'object' && hasFeedback.raw && !hasFeedback.questions && !hasFeedback.grammar_corrections;
  const feedbackCount = (vs && vs.feedback_count) || 0;
  const canReFeedback = isActive && hasFeedback && !feedbackIsBroken && feedbackCount < maxFeedbackCount && stage >= 4 && stage < 5;
  body.innerHTML += `
    <div class="sub-step ${doneB ? 'done' : activeB ? 'active-step' : ''}">
      <div class="sub-step-label">${doneB ? '✓ ' : ''}AI 練習回饋</div>
      <div class="alert alert-light border small py-2">這是給你修改用的 AI 回饋，不算成績。成績由老師依評分規準另外評分。</div>
      ${hasFeedback ? renderFeedbackHtml(vs.draft2_ai_feedback) : ''}
      ${isActive && !hasFeedback ? `
        <div id="feedbackActionArea">
          <button class="btn btn-outline-primary-custom" id="feedbackBtn" data-action="getFeedback" ${allDraft1Saved ? '' : 'disabled'}>
            獲取 AI 練習回饋
          </button>
          <p id="feedbackHint" class="text-warning small mt-2 mb-0${allDraft1Saved ? ' d-none' : ''}"><i class="bi bi-exclamation-circle me-1"></i>請先儲存所有 ${questions.length} 題草稿（已完成 <span id="feedbackHintCount">${savedDraft1Indices.size}</span>/${questions.length}）</p>
        </div>` : ''}
      ${isActive && feedbackIsBroken ? `
        <div id="feedbackActionArea">
          <button class="btn btn-outline-primary-custom mt-2" id="feedbackBtn" data-action="getFeedback">
            <i class="bi bi-arrow-clockwise me-1"></i>重新獲取 AI 練習回饋
          </button>
        </div>` : ''}
      ${canReFeedback ? `
        <div id="feedbackActionArea" class="mt-3">
          <p class="text-muted small mb-2">修改草稿後可再獲取一次 AI 練習回饋（已使用 ${feedbackCount}/${maxFeedbackCount} 次）。</p>
          <button class="btn btn-outline-primary-custom" id="feedbackBtn" data-action="getFeedback">
            <i class="bi bi-arrow-clockwise me-1"></i>重新取得 AI 練習回饋
          </button>
        </div>` : ''}
      ${isActive && hasFeedback && feedbackCount >= maxFeedbackCount && stage < 5 ? `
        <p class="text-muted small mt-3 mb-0"><i class="bi bi-check-circle me-1 text-success"></i>AI 練習回饋已使用 ${maxFeedbackCount}/${maxFeedbackCount} 次。請根據回饋撰寫最終草稿。</p>
      ` : ''}
    </div>`;

  // Sub-step C: Final Draft (per-question boxes)
  const doneC = stage >= 5 || isCompleted;
  const activeC = isActive && stage >= 4 && !doneC;
  const finalMap = getFinalDraftSavedMap(vs);
  const allFinalSaved = questions.length > 0 && questions.every((_, i) => savedFinalDraftIndices.has(i));
  const polishedMap = {};
  if (hasFeedback && typeof hasFeedback === 'object') {
    if (hasFeedback.questions && Array.isArray(hasFeedback.questions)) {
      hasFeedback.questions.forEach(q => { if (q.index != null) polishedMap[q.index] = q.polished_sample || ''; });
    } else if (hasFeedback.polished_sample) {
      const numQ = questions.length;
      const parts = numQ > 1 ? trySplitPolishedByQuestion(safeStr(hasFeedback.polished_sample), numQ) : null;
      if (parts) {
        parts.forEach((p, i) => { polishedMap[i] = p; });
      } else {
        polishedMap[0] = hasFeedback.polished_sample;
      }
    }
  }

  let finalDraftHtml = `
    <div class="sub-step ${doneC ? 'done' : activeC ? 'active-step' : ''}">
      <div class="sub-step-label">${doneC ? '✓ ' : ''}終稿</div>`;

  if (questions.length === 0) {
    finalDraftHtml += `<p class="text-muted small">（此作業未設定面試題目）</p>`;
  } else if (doneC || (vs && vs.final_draft_answers && vs.final_draft_answers.length > 0 && !activeC)) {
    questions.forEach((q, i) => {
      const savedText = finalMap[i];
      finalDraftHtml += `<div class="mb-3 p-3 rounded panel-muted">
        <p class="fw-semibold mb-2 small text-emerald">Q${i+1}：${escHtml(q)}</p>
        <div class="feedback-box"><pre>${escHtml(savedText || '（未填寫）')}</pre></div>
      </div>`;
    });
  } else if (activeC) {
    finalDraftHtml += `<div class="alert alert-info small py-2 mb-3">參考上方範文修改，但保留你自己的經驗。</div>`;
    questions.forEach((q, i) => {
      const savedText = finalMap[i];
      const isSaved = savedFinalDraftIndices.has(i);
      finalDraftHtml += `<div class="mb-3 p-3 rounded panel-muted">
        <p id="finalDraftLabel_${i}" class="fw-semibold mb-2 small text-brand">
          Q${i+1}：${escHtml(q)}
          ${isSaved ? '<span class="ms-2 badge bg-success fs-xs">已儲存</span>' : ''}
        </p>${learningScaffoldInlineHtml(vs,i,'writing')}
        <textarea class="form-control form-control-modern mb-2" id="finalDraftInput_${i}" rows="5" maxlength="2000"
          placeholder="請撰寫修改後的答案... / Write your revised answer here...">${escHtml(savedText || polishedMap[i] || '')}</textarea>
        <button class="btn btn-primary-custom btn-sm" id="finalDraftSaveBtn_${i}" data-action="saveFinalDraftAnswer" data-args='[${i}]'>
          ${isSaved ? '更新儲存' : '儲存此題'}
        </button>
      </div>`;
    });
    finalDraftHtml += `
      <button class="btn btn-success-custom" id="finalDraftBtn" data-action="submitFinalDraft" ${allFinalSaved ? '' : 'disabled'}>
        <span id="finalDraftSpinner" class="spinner-border spinner-border-sm d-none me-1"></span>
        送出終稿
      </button>
      <p id="finalDraftHint" class="text-warning small mt-2 mb-0${allFinalSaved ? ' d-none' : ''}"><i class="bi bi-exclamation-circle me-1"></i>請先儲存所有 ${questions.length} 題（已完成 <span id="finalDraftHintCount">${savedFinalDraftIndices.size}</span>/${questions.length}）</p>
      <small class="text-muted d-block mt-1"><i class="bi bi-clock me-1"></i>提交後將自動生成跟讀音訊（約 15-30 秒）</small>`;
  }
  finalDraftHtml += `</div>`;
  body.innerHTML += finalDraftHtml;
}

function trySplitPolishedByQuestion(text, numQ) {
  if (!text || numQ <= 1) return null;
  // Try Q1: / Q1： markers at line start
  const positions = [];
  const re = /(?:^|\n)\s*Q\d+\s*[:：]/gi;
  let m;
  while ((m = re.exec(text)) !== null) positions.push(m.index);
  if (positions.length === numQ) {
    return positions.map((start, i) => {
      const end = i + 1 < positions.length ? positions[i + 1] : text.length;
      return text.slice(start, end).replace(/^\s*Q\d+\s*[:：]\s*/i, '').trim();
    });
  }
  // Try splitting by double newlines
  const chunks = text.split(/\n\n+/).map(s => s.trim()).filter(s => s);
  if (chunks.length === numQ) return chunks;
  return null;
}

function extractJsonObject(text) {
  try { const o = JSON.parse(text); return typeof o === 'object' && o && !Array.isArray(o) ? o : null; } catch {}
  let best = null, i = 0;
  while (i < text.length) {
    if (text[i] !== '{') { i++; continue; }
    const start = i;
    let depth = 0, inStr = false, esc = false, j = i;
    while (j < text.length) {
      const c = text[j];
      if (esc) { esc = false; }
      else if (c === '\\' && inStr) { esc = true; }
      else if (c === '"') { inStr = !inStr; }
      else if (!inStr) {
        if (c === '{') depth++;
        else if (c === '}') { depth--; if (depth === 0) {
          try { const o = JSON.parse(text.slice(start, j + 1)); if (o && typeof o === 'object' && !Array.isArray(o)) best = o; } catch {}
          i = j + 1; break;
        }}
      }
      j++;
    }
    if (j >= text.length) break;
  }
  return best;
}

function renderCorrections(corrections) {
  if (!corrections || corrections.length === 0) return '<div class="text-muted small">未發現英文文法或用字錯誤。</div>';
  return corrections.map(c => `
    <div class="correction-card">
      <div class="cc-original"><span class="cc-tag">原句</span>${escHtml(safeStr(c.original))}</div>
      <div class="cc-corrected"><span class="cc-tag">修正</span>${escHtml(safeStr(c.corrected))}</div>
      ${c.explanation ? `<div class="cc-explanation">${escHtml(safeStr(c.explanation))}</div>` : ''}
    </div>`).join('');
}

function renderFeedbackHtml(fb) {
  if (!fb) return '';
  if (typeof fb === 'string') return `<div class="feedback-box"><pre>${escHtml(fb)}</pre></div>`;
  if (fb.raw) {
    const recovered = extractJsonObject(fb.raw);
    if (recovered && !recovered.raw) return renderFeedbackHtml(recovered);
    return `<div class="feedback-box"><pre>${escHtml(fb.raw)}</pre></div>`;
  }
  let html = '';
  const questions = getQuestions();
  const draftQuestionMap = {};
  ((getView() && getView().draft1_answers) || []).forEach(item => {
    if (item && item.index != null && item.question) draftQuestionMap[item.index] = item.question;
  });
  if (fb.questions && Array.isArray(fb.questions) && fb.questions.length > 0) {
    fb.questions.forEach(q => {
      const questionText = q.question || draftQuestionMap[q.index] || questions[q.index] || '';
      const qLabel = questionText ? `Q${q.index+1}：${escHtml(questionText)}` : `Q${q.index+1}`;
      const totalCorrections = Array.isArray(q.grammar_corrections) ? q.grammar_corrections.length : 0;
      html += `<div class="mb-3 p-3 rounded panel-muted">
        <p class="fw-semibold mb-2 small text-brand"><i class="bi bi-chat-quote me-1"></i>${qLabel}</p>
        <p class="fw-semibold mb-2 small">文法修正（${totalCorrections} 處）</p>
        ${renderCorrections(q.grammar_corrections)}`;
      if (q.polished_sample) {
        html += `<p class="fw-semibold mb-2 mt-2 small">建議範文</p>
          <div class="polished-box"><pre>${escHtml(safeStr(q.polished_sample))}</pre></div>`;
      }
      html += `</div>`;
    });
  } else {
    // Legacy flat format: group corrections + polished_sample per question
    const vs2 = getView();
    const draft1Map2 = getDraft1SavedMap(vs2);
    const numQ = questions.length;

    // Distribute corrections by matching original text against draft1 answers
    const corrByQ = Array.from({length: numQ}, () => []);
    const unmatchedCorr = [];
    if (fb.grammar_corrections && fb.grammar_corrections.length > 0) {
      fb.grammar_corrections.forEach(c => {
        let hit = false;
        for (let i = 0; i < numQ; i++) {
          const ans = draft1Map2[i] || '';
          if (ans && c.original && ans.includes(c.original)) {
            corrByQ[i].push(c); hit = true; break;
          }
        }
        if (!hit) unmatchedCorr.push(c);
      });
    }

    // Try to split polished_sample by question
    const polishedParts = fb.polished_sample
      ? trySplitPolishedByQuestion(safeStr(fb.polished_sample), numQ) : null;

    if (numQ > 0) {
      questions.forEach((q, i) => {
        const corrs = corrByQ[i];
        const polished = polishedParts ? polishedParts[i] : (numQ === 1 ? safeStr(fb.polished_sample) : null);
        if (!corrs.length && !polished) return;
        html += `<div class="mb-3 p-3 rounded panel-muted">
          <p class="fw-semibold mb-2 small text-brand"><i class="bi bi-chat-quote me-1"></i>Q${i+1}：${escHtml(q)}</p>`;
        if (corrs.length > 0) {
          html += `<p class="fw-semibold mb-2 small">文法修正</p>`;
          html += renderCorrections(corrs);
        }
        if (polished) {
          html += `<p class="fw-semibold mb-2 mt-2 small">建議範文</p>
            <div class="polished-box"><pre>${escHtml(polished)}</pre></div>`;
        }
        html += `</div>`;
      });
      if (unmatchedCorr.length > 0) {
        html += `<p class="fw-semibold mb-2 small">其他文法修正</p>`;
        html += renderCorrections(unmatchedCorr);
      }
      // Show polished_sample flat only if splitting failed and numQ > 1
      if (!polishedParts && fb.polished_sample && numQ > 1) {
        html += `<p class="fw-semibold mb-2 mt-3">建議範文</p>
          <div class="polished-box"><pre>${escHtml(safeStr(fb.polished_sample))}</pre></div>`;
      }
    } else {
      if (fb.grammar_corrections && fb.grammar_corrections.length > 0) {
        html += `<p class="fw-semibold mb-2">文法修正</p>`;
        html += renderCorrections(fb.grammar_corrections);
      }
      if (fb.polished_sample) {
        html += `<p class="fw-semibold mb-2 mt-3">建議範文</p>
          <div class="polished-box"><pre>${escHtml(safeStr(fb.polished_sample))}</pre></div>`;
      }
    }
  }
  if (fb.organization_suggestions && fb.organization_suggestions.length > 0) {
    html += `<p class="fw-semibold mb-2 mt-3">組織架構建議</p>`;
    html += `<ul class="mb-0">${fb.organization_suggestions.map(s => `<li>${escHtml(safeStr(s))}</li>`).join('')}</ul>`;
  }
  return html ? `<div class="mb-2">${html}</div>` : '';
}

async function saveDraft1Answer(index) {
  const textarea = document.getElementById(`draft1Input_${index}`);
  if (!textarea) return;
  const text = textarea.value.trim();
  if (!text) { showAlert(`請先填寫第 ${index+1} 題草稿。`); return; }
  const btn = document.getElementById(`draft1Btn_${index}`);
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>儲存中...'; }
  const questions = getQuestions();
  const existing = (submission.draft1_answers || []).filter(a => a.index !== index);
  const updated = [...existing, { index, question: questions[index] || '', text }];
  updated.sort((a, b) => a.index - b.index);
  const res = await apiCall(`/api/student/submissions/${submission.id}/draft1`, {
    method: 'POST', body: JSON.stringify({ draft1_answers: updated })
  });
  const data = await res.json();
  if (!res.ok) {
    if (btn) { btn.disabled = false; btn.innerHTML = `儲存此題`; }
    showAlert(data.detail || '儲存失敗，請再試一次。'); return;
  }
  const previousStage = submission.stage;
  const feedbackWasInvalidated = !!submission.draft2_ai_feedback && !data.draft2_ai_feedback;
  const containsChinese = /[\u3400-\u4dbf\u4e00-\u9fff]/.test(text);
  const mixedDraftReminder = containsChinese ? '；中文可先保留，稍後請依 AI 回饋整理成英文' : '';
  const savedMessage = `第 ${index+1} 題已儲存${mixedDraftReminder}。`;
  submission = data;
  savedDraft1Indices.add(index);
  if (previousStage !== data.stage || feedbackWasInvalidated) {
    renderAll();
    showAlert(
      feedbackWasInvalidated
        ? `草稿已更新；先前 AI 回饋已失效，請依新版本重新取得回饋${mixedDraftReminder}。`
        : savedMessage,
      feedbackWasInvalidated ? 'warning' : 'success'
    );
    return;
  }
  // Update badge on this question's label
  const label = document.getElementById(`draft1Label_${index}`);
  if (label && !label.querySelector('.badge')) {
    label.insertAdjacentHTML('beforeend', '<span class="ms-2 badge bg-success fs-xs">已儲存</span>');
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '更新儲存'; }
  // Update AI feedback button and hint
  const allSaved = getQuestions().every((_, i) => savedDraft1Indices.has(i));
  const fbBtn = document.getElementById('feedbackBtn');
  if (fbBtn) fbBtn.disabled = !allSaved;
  const fbHint = document.getElementById('feedbackHint');
  if (fbHint) {
    const count = document.getElementById('feedbackHintCount');
    if (count) count.textContent = savedDraft1Indices.size;
    fbHint.classList.toggle('d-none', allSaved);
  }
  showAlert(savedMessage, 'success');
}

async function saveFinalDraftAnswer(index) {
  const textarea = document.getElementById(`finalDraftInput_${index}`);
  if (!textarea) return;
  const text = textarea.value.trim();
  if (!text) { showAlert(`請先填寫第 ${index+1} 題最終草稿。`); return; }
  const saveBtn = document.getElementById(`finalDraftSaveBtn_${index}`);
  if (saveBtn) { saveBtn.disabled = true; saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>儲存中...'; }
  const questions = getQuestions();
  const existing = (submission.final_draft_answers || []).filter(a => a.index !== index);
  const updated = [...existing, { index, question: questions[index] || '', text }];
  updated.sort((a, b) => a.index - b.index);
  const res = await apiCall(`/api/student/submissions/${submission.id}/final-draft`, {
    method: 'PUT', body: JSON.stringify({ final_draft_answers: updated })
  });
  const data = await res.json();
  if (!res.ok) {
    if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = `儲存此題`; }
    showAlert(data.detail || '儲存最終草稿時發生錯誤');
    return;
  }
  submission = data;
  savedFinalDraftIndices.add(index);
  // Update badge
  const label = document.getElementById(`finalDraftLabel_${index}`);
  if (label && !label.querySelector('.badge')) {
    label.insertAdjacentHTML('beforeend', '<span class="ms-2 badge bg-success fs-xs">已儲存</span>');
  }
  if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = '更新儲存'; }
  // Update submit button and hint
  const allSaved = getQuestions().every((_, i) => savedFinalDraftIndices.has(i));
  const submitBtn = document.getElementById('finalDraftBtn');
  if (submitBtn) submitBtn.disabled = !allSaved;
  const hint = document.getElementById('finalDraftHint');
  if (hint) {
    const count = document.getElementById('finalDraftHintCount');
    if (count) count.textContent = savedFinalDraftIndices.size;
    hint.classList.toggle('d-none', allSaved);
  }
  showAlert(`第 ${index+1} 題終稿已儲存。`, 'success');
}

async function submitFinalDraft() {
  const questions = getQuestions();
  if (!questions.every((_, i) => savedFinalDraftIndices.has(i))) {
    showAlert('請先儲存所有題目的最終草稿。'); return;
  }
  const btn = document.getElementById('finalDraftBtn');
  const spinner = document.getElementById('finalDraftSpinner');
  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove('d-none');
  const res = await apiCall(`/api/student/submissions/${submission.id}/final-draft`, {
    method: 'POST', body: JSON.stringify({ final_draft_answers: submission.final_draft_answers })
  });
  const data = await res.json();
  if (btn && btn.isConnected) { btn.disabled = false; if (spinner) spinner.classList.add('d-none'); }
  if (!res.ok) { showAlert(data.detail || '儲存最終草稿時發生錯誤'); return; }
  submission = data;
  showAlert('終稿已送出，正在前往跟讀。', 'success');
  setTimeout(() => { navigateStudentPage(`/student/assignment/${assignmentId}/shadowing`); }, 1000);
}

async function getFeedback() {
  const actionArea = document.getElementById('feedbackActionArea');
  if (!actionArea) return;
  actionArea.innerHTML = `
    <div class="processing-overlay">
      <div class="spinner-border text-primary flex-shrink-0"></div>
      <div>
        <div class="fw-semibold text-brand">AI 正在生成練習回饋...</div>
        <small id="feedbackStreamCount" class="text-muted">初始化中，請稍待 15～45 秒...</small>
      </div>
    </div>`;
  try {
    const res = await fetch(`/api/student/submissions/${submission.id}/feedback/stream`, {
      method: 'POST',
      credentials: 'include',
    });
    if (!res.ok) {
      const data = await res.json();
      showAlert(data.detail || '獲取回饋時發生錯誤');
      renderAll();
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let charCount = 0;
    let firstChunkReceived = false;
    const countEl = document.getElementById('feedbackStreamCount');
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();
      for (const part of parts) {
        if (!part.startsWith('data: ')) continue;
        let event;
        try { event = JSON.parse(part.slice(6)); } catch { continue; }
        if (event.chunk) {
          firstChunkReceived = true;
          charCount += event.chunk.length;
          if (countEl) countEl.textContent = `${charCount} 字元已產生`;
        }
        if (event.done) {
          submission.draft2_ai_feedback = event.feedback;
          submission.feedback_count = event.feedback_count || ((submission.feedback_count || 0) + 1);
          submission.stage = 4;
          renderAll();
          showAlert('AI 回饋好了。', 'success');
        }
        if (event.error) {
          showAlert('生成回饋時發生錯誤：' + event.error);
          renderAll();
        }
      }
    }
  } catch {
    showAlert('連線中斷，請再試一次。');
    renderAll();
  }
}


init().catch(error=>renderStudentPageLoadError(error));

Object.assign(window, {
  safeStr,
  init,
  renderAll,
  getQuestions,
  getDraft1SavedMap,
  getFinalDraftSavedMap,
  renderWritingTaskGuide,
  renderSection1,
  trySplitPolishedByQuestion,
  extractJsonObject,
  renderCorrections,
  renderFeedbackHtml,
  saveDraft1Answer,
  saveFinalDraftAnswer,
  submitFinalDraft,
  getFeedback,
});
