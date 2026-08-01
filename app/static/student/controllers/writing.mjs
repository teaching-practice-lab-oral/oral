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
  const profile = (vs && vs.job_profile_data) || {};
  const position = profile.desired_position || '你設定的目標職位';
  const competencies = profile.required_competencies || '你想展現的工作能力';
  const total=questions.length;
  const draftCount=questions.filter((_,index)=>savedDraft1Indices.has(index)).length;
  const finalCount=questions.filter((_,index)=>savedFinalDraftIndices.has(index)).length;
  const state=viewId||isCompleted||stage>=5?'completed':isPastDue()?'read-only':'active';
  if(state!=='active')return renderTaskGuide({title:'寫作階段已完成',progress:`終稿 ${finalCount}/${total} 題已儲存`,next:'回看時，比較草稿、AI 練習回饋與終稿，找出自己真正做了哪一項修改。',view:vs,state});

  if(stage<=2){
    const nextIndex=Math.max(0,questions.findIndex((_,index)=>!savedDraft1Indices.has(index)));
    const questionScaffold=learningScaffoldQuestionHtml(vs,nextIndex,'writing');
    return renderTaskGuide({
      title:`先完成 Q${nextIndex+1}：第一版只求完整`,
      progress:`草稿已儲存 ${draftCount}/${total} 題`,
      actions:[
        '第一句直接回答題目，不要先繞一大段背景。',
        '經驗題補上情境、做法和結果；想法題補上理由和例子。',
        '使用自己現在說得出口的英文，不必先追求難字。',
      ],
      support:{title:`Q${nextIndex+1} 的回答鷹架`,items:[
        '例子可從課堂專題、社團、打工、實習或日常合作經驗中找。',
        `目前職位是「${position}」；可連結的能力包括「${competencies}」。`,
      ],html:questionScaffold},
      starters:learningScaffoldStarters(vs,nextIndex,['I would say…','For example…','As a result…']),
      checks:[
        '第一句有直接回答這一題。',
        '內容是真實經驗或真實想法。',
        '這段英文可以由我自己說出口。',
      ],
      next:`儲存目前答案；${workflowLimit('core_question_count')} 題都儲存後取得 AI 練習回饋。`,
      view:vs,
    });
  }

  if(stage===3){
    return renderTaskGuide({
      title:`${total} 題都存好了，現在取得 AI 練習回饋`,
      progress:`草稿已儲存 ${draftCount}/${total} 題`,
      actions:[
        '快速確認每一題都有回答到題目，不是貼錯題。',
        '確認內容是自己的真實經驗，沒有為了完整而虛構。',
        '按「獲取 AI 練習回饋」，等待回饋顯示。',
      ],
      support:{title:'送出前不確定時',items:['先看每題第一句；只要第一句答錯重點，就先回去修改。'],html:learningScaffoldModuleHtml()},
      checks:['所有題目都已儲存。','沒有空白、貼錯題或明顯未完成的句子。','AI 練習回饋成功顯示。'],
      next:'先找每題最值得修改的一點，再完成自己的終稿。',
      view:vs,
    });
  }

  const unresolvedFinalIndex=questions.findIndex((_,index)=>!savedFinalDraftIndices.has(index));
  const finalIndex=Math.max(0,unresolvedFinalIndex);
  const finalScaffold=unresolvedFinalIndex>=0
    ? learningScaffoldQuestionHtml(vs,finalIndex,'writing')
    : learningScaffoldModuleHtml();
  return renderTaskGuide({
    title:'先改內容，再修文法；完成你自己的終稿',
    progress:`終稿已儲存 ${finalCount}/${total} 題`,
    actions:[
      '比較原稿與 AI 練習回饋，每題只挑一項最有幫助的建議。',
      '保留自己的真實經驗，不把建議範文直接當成自己的答案。',
      '改成自己說得出口的英文；逐題儲存，全部完成後再提交。',
    ],
    support:{title:`Q${finalIndex+1} 的修改鷹架`,items:[
      '先補一個具體細節，再處理影響理解的文法或用字。',
      '題目問到能力或經驗時，再補一句它和目標職位的關係。',
    ],html:finalScaffold},
    starters:unresolvedFinalIndex>=0?learningScaffoldStarters(vs,finalIndex,['One example is…','What I learned was…','This would help me…']):[],
    checks:['每題都有直接回答並補充具體內容。','答案保留自己的事實與說話方式。',`${workflowLimit('core_question_count')} 題都已儲存，而且能拿來口說。`],
    next:'提交終稿後，系統會產生示範音訊，接著進行跟讀。',
    view:vs,
  });
}

function renderSection1(container, stage, isCompleted) {
  const isDone = stage >= 5 || isCompleted;
  // Past the deadline the page is read-only: render saved work, hide all editing controls.
  const isActive = !isDone && stage <= 4 && !isPastDue();
  const card = document.createElement('div');
  card.className = `section-card ${isDone ? 'completed' : 'active'}`;
  card.innerHTML = `
    <div class="section-header">
      <div class="section-icon"><i class="bi bi-pencil-square"></i></div>
      <div>
        <div class="section-title">寫作練習</div>
        <div class="section-subtitle">Writing Practice</div>
      </div>
      ${isDone ? '<span class="ms-auto badge bg-white text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>完成</span>' : ''}
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
      draft1Html += `<div class="mb-3 p-3 rounded" style="background:#f8fafc;border:1px solid #e2e8f0;">
        <p id="draft1Label_${i}" class="fw-semibold mb-2 small" style="color:#4f46e5;">
          Q${i+1}：${escHtml(q)}
          ${isSaved ? '<span class="ms-2 badge bg-success" style="font-size:0.7rem;">已儲存</span>' : ''}
        </p>${learningScaffoldInlineHtml(vs,i,'writing')}`;
      if (isSaved && !draft1Editable) {
        draft1Html += `<div class="feedback-box"><pre>${escHtml(saved || '')}</pre></div>`;
      } else if (draft1Editable) {
        draft1Html += `<textarea class="form-control form-control-modern mb-2" id="draft1Input_${i}" rows="5" maxlength="2000"
          placeholder="請針對此題撰寫你的答案... / Write your answer here...">${escHtml(saved || '')}</textarea>
          <button class="btn btn-primary-custom btn-sm" id="draft1Btn_${i}" data-action="saveDraft1Answer" data-args='[${i}]'>
            <i class="bi bi-save me-1"></i>${isSaved ? '更新儲存' : '儲存此題'}
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
      <div class="alert alert-light border small py-2"><i class="bi bi-info-circle me-1 text-primary"></i>這裡是協助修改的形成性練習回饋，不是正式成績；完成整次練習後，老師才會依評分規準進行正式評分。</div>
      ${hasFeedback ? renderFeedbackHtml(vs.draft2_ai_feedback) : ''}
      ${isActive && !hasFeedback ? `
        <div id="feedbackActionArea">
          <p class="text-muted small mb-2">所有題目草稿儲存完畢後，點擊按鈕獲取 AI 練習回饋與改寫示例。</p>
          <button class="btn btn-outline-primary-custom" id="feedbackBtn" data-action="getFeedback" ${allDraft1Saved ? '' : 'disabled'}>
            <i class="bi bi-stars me-1"></i>獲取 AI 練習回饋
          </button>
          <p id="feedbackHint" class="text-warning small mt-2 mb-0" ${allDraft1Saved ? 'style="display:none"' : ''}><i class="bi bi-exclamation-circle me-1"></i>請先儲存所有 ${questions.length} 題草稿（已完成 <span id="feedbackHintCount">${savedDraft1Indices.size}</span>/${questions.length}）</p>
        </div>` : ''}
      ${isActive && feedbackIsBroken ? `
        <div id="feedbackActionArea">
          <button class="btn btn-outline-primary-custom mt-2" id="feedbackBtn" data-action="getFeedback">
            <i class="bi bi-arrow-clockwise me-1"></i>重新獲取 AI 練習回饋
          </button>
        </div>` : ''}
      ${canReFeedback ? `
        <div id="feedbackActionArea" class="mt-3">
          <p class="text-muted small mb-2"><i class="bi bi-info-circle me-1"></i>修改草稿後可再獲取一次 AI 練習回饋（已使用 ${feedbackCount}/${maxFeedbackCount} 次）。</p>
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
      <div class="sub-step-label">${doneC ? '✓ ' : ''}最終草稿 Final Draft</div>`;

  if (questions.length === 0) {
    finalDraftHtml += `<p class="text-muted small">（此作業未設定面試題目）</p>`;
  } else if (doneC || (vs && vs.final_draft_answers && vs.final_draft_answers.length > 0 && !activeC)) {
    questions.forEach((q, i) => {
      const savedText = finalMap[i];
      finalDraftHtml += `<div class="mb-3 p-3 rounded" style="background:#f8fafc;border:1px solid #e2e8f0;">
        <p class="fw-semibold mb-2 small" style="color:#10b981;">Q${i+1}：${escHtml(q)}</p>
        <div class="feedback-box"><pre>${escHtml(savedText || '（未填寫）')}</pre></div>
      </div>`;
    });
  } else if (activeC) {
    finalDraftHtml += `<div class="alert alert-info small py-2 mb-3"><i class="bi bi-info-circle me-1"></i>可參考上方 AI 建議範文修改你的答案。請保留自己的原意與經驗；每題儲存後，全部完成再提交。</div>`;
    questions.forEach((q, i) => {
      const savedText = finalMap[i];
      const isSaved = savedFinalDraftIndices.has(i);
      finalDraftHtml += `<div class="mb-3 p-3 rounded" style="background:#f8fafc;border:1px solid #e2e8f0;">
        <p id="finalDraftLabel_${i}" class="fw-semibold mb-2 small" style="color:#4f46e5;">
          Q${i+1}：${escHtml(q)}
          ${isSaved ? '<span class="ms-2 badge bg-success" style="font-size:0.7rem;">已儲存</span>' : ''}
        </p>${learningScaffoldInlineHtml(vs,i,'writing')}
        <textarea class="form-control form-control-modern mb-2" id="finalDraftInput_${i}" rows="5" maxlength="2000"
          placeholder="請撰寫修改後的答案... / Write your revised answer here...">${escHtml(savedText || polishedMap[i] || '')}</textarea>
        <button class="btn btn-primary-custom btn-sm" id="finalDraftSaveBtn_${i}" data-action="saveFinalDraftAnswer" data-args='[${i}]'>
          <i class="bi bi-save me-1"></i>${isSaved ? '更新儲存' : '儲存此題'}
        </button>
      </div>`;
    });
    finalDraftHtml += `
      <button class="btn btn-success-custom" id="finalDraftBtn" data-action="submitFinalDraft" ${allFinalSaved ? '' : 'disabled'}>
        <span id="finalDraftSpinner" class="spinner-border spinner-border-sm d-none me-1"></span>
        <i class="bi bi-send me-1"></i>提交最終草稿 Submit Final Draft
      </button>
      <p id="finalDraftHint" class="text-warning small mt-2 mb-0" ${allFinalSaved ? 'style="display:none"' : ''}><i class="bi bi-exclamation-circle me-1"></i>請先儲存所有 ${questions.length} 題（已完成 <span id="finalDraftHintCount">${savedFinalDraftIndices.size}</span>/${questions.length}）</p>
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
  if (!corrections || corrections.length === 0) return '<div class="text-muted small">未發現明顯文法錯誤。</div>';
  return corrections.map(c => `
    <div class="correction-card">
      <div class="cc-original"><i class="bi bi-x-circle me-1"></i>原句：${escHtml(safeStr(c.original))}</div>
      <div class="cc-corrected"><i class="bi bi-check-circle me-1"></i>修正：${escHtml(safeStr(c.corrected))}</div>
      ${c.explanation ? `<div class="cc-explanation"><i class="bi bi-chat-left-text me-1"></i>說明：${escHtml(safeStr(c.explanation))}</div>` : ''}
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
      html += `<div class="mb-3 p-3 rounded" style="background:#f8fafc;border:1px solid #e2e8f0;">
        <p class="fw-semibold mb-2 small" style="color:#4f46e5;"><i class="bi bi-chat-quote me-1"></i>${qLabel}</p>
        <p class="fw-semibold mb-2 small"><i class="bi bi-spellcheck me-1 text-danger"></i>文法修正（${totalCorrections} 處）</p>
        ${renderCorrections(q.grammar_corrections)}`;
      if (q.polished_sample) {
        html += `<p class="fw-semibold mb-2 mt-2 small"><i class="bi bi-stars me-1 text-primary"></i>建議範文</p>
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
        html += `<div class="mb-3 p-3 rounded" style="background:#f8fafc;border:1px solid #e2e8f0;">
          <p class="fw-semibold mb-2 small" style="color:#4f46e5;"><i class="bi bi-chat-quote me-1"></i>Q${i+1}：${escHtml(q)}</p>`;
        if (corrs.length > 0) {
          html += `<p class="fw-semibold mb-2 small"><i class="bi bi-spellcheck me-1 text-danger"></i>文法修正</p>`;
          html += renderCorrections(corrs);
        }
        if (polished) {
          html += `<p class="fw-semibold mb-2 mt-2 small"><i class="bi bi-stars me-1 text-primary"></i>建議範文</p>
            <div class="polished-box"><pre>${escHtml(polished)}</pre></div>`;
        }
        html += `</div>`;
      });
      if (unmatchedCorr.length > 0) {
        html += `<p class="fw-semibold mb-2 small"><i class="bi bi-spellcheck me-1 text-danger"></i>其他文法修正</p>`;
        html += renderCorrections(unmatchedCorr);
      }
      // Show polished_sample flat only if splitting failed and numQ > 1
      if (!polishedParts && fb.polished_sample && numQ > 1) {
        html += `<p class="fw-semibold mb-2 mt-3"><i class="bi bi-stars me-1 text-primary"></i>建議範文</p>
          <div class="polished-box"><pre>${escHtml(safeStr(fb.polished_sample))}</pre></div>`;
      }
    } else {
      if (fb.grammar_corrections && fb.grammar_corrections.length > 0) {
        html += `<p class="fw-semibold mb-2"><i class="bi bi-spellcheck me-1 text-danger"></i>文法修正</p>`;
        html += renderCorrections(fb.grammar_corrections);
      }
      if (fb.polished_sample) {
        html += `<p class="fw-semibold mb-2 mt-3"><i class="bi bi-stars me-1 text-primary"></i>建議範文</p>
          <div class="polished-box"><pre>${escHtml(safeStr(fb.polished_sample))}</pre></div>`;
      }
    }
  }
  if (fb.organization_suggestions && fb.organization_suggestions.length > 0) {
    html += `<p class="fw-semibold mb-2 mt-3"><i class="bi bi-list-check me-1 text-warning"></i>組織架構建議</p>`;
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
    if (btn) { btn.disabled = false; btn.innerHTML = `<i class="bi bi-save me-1"></i>儲存此題`; }
    showAlert(data.detail || '儲存草稿時發生錯誤'); return;
  }
  const previousStage = submission.stage;
  const feedbackWasInvalidated = !!submission.draft2_ai_feedback && !data.draft2_ai_feedback;
  submission = data;
  savedDraft1Indices.add(index);
  if (previousStage !== data.stage || feedbackWasInvalidated) {
    renderAll();
    showAlert(
      feedbackWasInvalidated
        ? '草稿已更新；先前 AI 回饋已失效，請依新版本重新取得回饋。'
        : `第 ${index+1} 題草稿已儲存！`,
      feedbackWasInvalidated ? 'warning' : 'success'
    );
    return;
  }
  const currentGuide=document.querySelector('#sectionContainer .task-guide');
  if(currentGuide)currentGuide.outerHTML=renderWritingTaskGuide(getView(),submission.stage,!!submission.submitted_at,getQuestions());
  // Update badge on this question's label
  const label = document.getElementById(`draft1Label_${index}`);
  if (label && !label.querySelector('.badge')) {
    label.insertAdjacentHTML('beforeend', '<span class="ms-2 badge bg-success" style="font-size:0.7rem;">已儲存</span>');
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-save me-1"></i>更新儲存'; }
  // Update AI feedback button and hint
  const allSaved = getQuestions().every((_, i) => savedDraft1Indices.has(i));
  const fbBtn = document.getElementById('feedbackBtn');
  if (fbBtn) fbBtn.disabled = !allSaved;
  const fbHint = document.getElementById('feedbackHint');
  if (fbHint) {
    const count = document.getElementById('feedbackHintCount');
    if (count) count.textContent = savedDraft1Indices.size;
    fbHint.style.display = allSaved ? 'none' : '';
  }
  showAlert(`第 ${index+1} 題草稿已儲存！`, 'success');
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
    if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = `<i class="bi bi-save me-1"></i>儲存此題`; }
    showAlert(data.detail || '儲存最終草稿時發生錯誤');
    return;
  }
  submission = data;
  savedFinalDraftIndices.add(index);
  // Update badge
  const label = document.getElementById(`finalDraftLabel_${index}`);
  if (label && !label.querySelector('.badge')) {
    label.insertAdjacentHTML('beforeend', '<span class="ms-2 badge bg-success" style="font-size:0.7rem;">已儲存</span>');
  }
  if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = '<i class="bi bi-save me-1"></i>更新儲存'; }
  // Update submit button and hint
  const allSaved = getQuestions().every((_, i) => savedFinalDraftIndices.has(i));
  const submitBtn = document.getElementById('finalDraftBtn');
  if (submitBtn) submitBtn.disabled = !allSaved;
  const hint = document.getElementById('finalDraftHint');
  if (hint) {
    const count = document.getElementById('finalDraftHintCount');
    if (count) count.textContent = savedFinalDraftIndices.size;
    hint.style.display = allSaved ? 'none' : '';
  }
  showAlert(`第 ${index+1} 題最終草稿已儲存！`, 'success');
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
  showAlert('最終草稿已提交！跟讀音訊已生成，前往跟讀練習。', 'success');
  setTimeout(() => { navigateStudentPage(`/student/assignment/${assignmentId}/shadowing`); }, 1000);
}

async function getFeedback() {
  const actionArea = document.getElementById('feedbackActionArea');
  if (!actionArea) return;
  actionArea.innerHTML = `
    <div class="processing-overlay">
      <div class="spinner-border text-primary" style="flex-shrink:0"></div>
      <div>
        <div class="fw-semibold" style="color:#4f46e5">AI 正在生成練習回饋...</div>
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
          showAlert('已獲取 AI 回饋！', 'success');
        }
        if (event.error) {
          showAlert('生成回饋時發生錯誤：' + event.error);
          renderAll();
        }
      }
    }
  } catch {
    showAlert('連線發生錯誤，請重試。');
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
