const pathParts = window.location.pathname.split('/');
window.assignmentId = parseInt(pathParts[3]);
const urlParams = new URLSearchParams(window.location.search);
window.viewId = urlParams.get('view') ? parseInt(urlParams.get('view')) : null;

window.submission = null;
window.assignment = null;
window.viewedSubmission = null;

let mediaRecorder = null;
let recordingChunks = [];
let timerInterval = null;
let recordingSeconds = 0;
let pendingAudioURL = null;
const MAX_RECORDING_SECONDS = 300;
const SECRET_RECORDING_SECONDS = 90;

function scratchpadKey(turnNumber) {
  return `roleplay-keywords:${submission?.id || 'unknown'}:${turnNumber}`;
}

function saveRoleplayKeywords(turnNumber, event) {
  sessionStorage.setItem(scratchpadKey(turnNumber), event.target.value.slice(0, 120));
}

function clearRoleplayScratchpads() {
  for (let turn = 1; turn <= workflowLimit('max_roleplay_turns'); turn++) sessionStorage.removeItem(scratchpadKey(turn));
}

function roleplayKeywordField(currentTurn, isSecret) {
  const savedKeywords = sessionStorage.getItem(scratchpadKey(currentTurn)) || '';
  return `<div class="task-guide-persistent">
    <label class="form-label small fw-semibold" for="roleplayKeywords">先記 1–3 個英文關鍵字或短語</label>
    <input id="roleplayKeywords" class="form-control" maxlength="120" value="${escAttr(savedKeywords)}" placeholder="${isSecret?'只記追問的重點，不寫完整答案':'例如：teamwork, school project, solved conflict'}" data-action-input="saveRoleplayKeywords" data-args='[${currentTurn}]'>
    <div class="form-text">這是此瀏覽器分頁的暫存筆記，不會上傳、不會送給 AI，也不會列入評分。</div>
  </div>`;
}

function renderRoleplayTaskGuide(vs, stage, isCompleted, turns, currentTurn) {
  const completedTurns=turns.filter(turn=>turn.student_transcript).length;
  const coreQuestionCount=workflowLimit('core_question_count');
  const secretQuestionIndex=workflowLimit('secret_question_source_index');
  const completedCore=new Set(turns.filter(turn=>turn.student_transcript&&Number.isInteger(turn.source_question_index)&&turn.source_question_index<coreQuestionCount).map(turn=>turn.source_question_index)).size;
  const secretAnswered=turns.some(turn=>turn.student_transcript&&turn.source_question_index===secretQuestionIndex);
  const allTurnsAnswered=turns.length>0&&turns.every(turn=>turn.student_transcript);
  const state=viewId||isCompleted||stage>=8?'completed':isPastDue()?'read-only':'active';
  const progress=`核心題目 ${completedCore}/${coreQuestionCount}・臨場追問 ${secretAnswered?'1/1':'0/1'}・已回答 ${completedTurns} 輪`;
  if(state!=='active')return renderTaskGuide({title:'角色扮演已完成',progress,next:'回看時，找一輪自己的回答，確認是否先答題、再補真實細節。',view:vs,state});

  if(stage===6){
    const questions=Array.isArray(assignment?.questions)?assignment.questions:[];
    const questionList=`<p class="small mb-2">你已寫過並跟讀過這 ${questions.length} 個主題；完成後還有一題事前不公開的臨場追問。</p><ol class="small mb-0 ps-3">${questions.map(question=>`<li class="mb-1">${escHtml(question)}</li>`).join('')}</ol>`;
    return renderTaskGuide({
      title:'準備好就開始：這次要回答，不是背稿',
      progress:`尚未開始面試・${workflowLimit('core_question_count')} 個核心題目＋1 個臨場追問`,
      actions:['確認環境安靜、麥克風可以使用。','按「開始面試」，先把面試官的問題聽完整。','先直接回答，再用簡單英文補上自己的真實經驗。'],
      support:{title:'開始前想先確認時',items:['不必記住終稿的每一個字；記得每題的重點與例子即可。','若沒聽清楚，可使用題目旁的播放按鈕再聽一次。'],html:`${questionList}${learningScaffoldModuleHtml()}`},
      starters:['I would say…','One reason is…','For example…'],
      checks:['我準備用自己的話回答，不照稿朗讀。','我知道回答要先切題，再補理由或例子。','我已準備好開始錄音。'],
      next:'按下開始後，依序完成每一輪；未使用英文或明顯偏題時，面試官可能重問。',
      view:vs,
    });
  }

  if(allTurnsAnswered&&completedCore>=coreQuestionCount&&secretAnswered){
    return renderTaskGuide({
      title:'錄音都已保留，只要重新產生 AI 回饋',
      progress,
      actions:[`不要重新錄音；${workflowLimit('core_question_count')+1} 題回答都已經儲存。`,'按「重新產生 AI 回饋」。','留在目前頁面，等系統完成整理。'],
      support:{title:'擔心答案消失時',items:['重新產生只會重做回饋，不會覆蓋已儲存的錄音與逐字稿。']},
      checks:['四個核心題目與臨場追問都已有回答。','頁面顯示不需要重新錄音。','AI 回饋成功產生。'],
      next:'系統會自動前往 AI 回饋頁。',
      view:vs,
    });
  }

  if(allTurnsAnswered){
    return renderTaskGuide({
      title:'上一輪已儲存，準備下一題後繼續',
      progress,
      actions:['不要重新錄製上一輪。','按「準備下一題並繼續」。','下一題出現後，先聽完整再作答。'],
      support:{title:'畫面看起來停住時',items:['上一輪的錄音與逐字稿已保留，這個按鈕只會接續產生下一題。']},
      checks:['上一輪已顯示在對話紀錄中。','下一題已出現並可播放。','錄音按鈕重新開放。'],
      next:`回答下一題，直到 ${workflowLimit('core_question_count')} 個核心題目與一個臨場追問都完成。`,
      view:vs,
    });
  }

  const activeTurn = turns.find(turn => turn.turn_number === currentTurn) || {};
  const sourceIndex = Number.isInteger(activeTurn.source_question_index)
    ? activeTurn.source_question_index
    : Math.max(0, currentTurn - 1);
  const profile = getView()?.job_profile_data || {};
  const isSecret=sourceIndex===workflowLimit('secret_question_source_index');
  if(isSecret)return renderTaskGuide({
    title:'臨場追問：補一個真實細節就好',
    progress,
    actions:['先找出面試官正在追問哪個細節：做法、困難或結果。','只回答這個細節，不必重講整份答案。','使用自己的真實經驗；簡單、完整的短句就可以。'],
    support:{title:'一時不知道怎麼開始時',items:['先重複題目中的關鍵字，再補你當時實際做了什麼。'],html:learningScaffoldPositionHtml(vs)},
    starters:['What I did was…','The difficult part was…','As a result…'],
    persistentHtml:roleplayKeywordField(currentTurn,true),
    checks:['我有直接回答追問的細節。','內容是自己真的做過或想過的事。','回答使用英文，而且沒有照讀完整稿件。'],
    next:'提交後，系統會整理整場面試並產生 AI 回饋。',
    view:vs,
  });
  return renderTaskGuide({
    title:`第 ${currentTurn} 輪：先回答面試官現在問的重點`,
    progress,
    actions:['沒聽清楚時，先用播放按鈕再聽一次。','只記 1–3 個英文關鍵字，不寫完整句子。','先直接回答，再補理由或例子；適合時再連結目標職位。'],
    support:{title:`Q${sourceIndex+1} 的即席回答提示`,items:[`你的目標職位是「${profile.desired_position||'尚未填寫'}」；想展現的能力是「${profile.required_competencies||'尚未填寫'}」。`,'例子可用課堂專題、社團、打工、實習或日常合作經驗。'],html:learningScaffoldQuestionHtml(vs,sourceIndex,'roleplay')},
    starters:learningScaffoldStarters(vs,sourceIndex,['I would say…','One reason is…','For example…']),
    persistentHtml:roleplayKeywordField(currentTurn,false),
    checks:['開頭有直接回應面試官的問題。','回答包含真實理由、做法或例子。','我用自己的話回答，沒有朗讀完整稿件。'],
    next:'回聽並提交這一輪；系統會接著準備下一題。',
    view:vs,
  });
}

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

  if (stage < 6 && !viewId && !isCompleted) {
    const redirect = stage >= 5
      ? `/student/assignment/${assignmentId}/shadowing`
      : `/student/assignment/${assignmentId}/writing`;
    navigateStudentPage(redirect);
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
  const stage = vs ? vs.stage : 6;
  const isCompleted = !!(vs && vs.submitted_at);

  updateProgressSteps(isCompleted ? 9 : stage);

  renderViewBanner();
  const isViewingPast = viewedSubmission && submission && viewedSubmission.id !== submission.id;

  const container = document.getElementById('sectionContainer');
  container.innerHTML = '';
  renderSection3(container, stage, isCompleted);

  const roleplayDone = isCompleted || stage >= 8;
  const nav = document.getElementById('sectionNav');
  nav.innerHTML = `
    <div><button class="btn-nav" data-action="navigateSection" data-args='[3]'><i class="bi bi-chevron-left me-1"></i>跟讀練習</button></div>
    <div>${roleplayDone
      ? `<button class="btn-nav-next" data-action="navigateSection" data-args='[5]'>AI 回饋<i class="bi bi-chevron-right ms-1"></i></button>`
      : ''}</div>`;
}

// ── Section 3: Roleplay ────────────────────────────────────────────────

function renderSection3(container, stage, isCompleted) {
  const isDone = stage >= 8 || isCompleted;
  if (isDone && !viewId) clearRoleplayScratchpads();
  // Past the deadline the page is read-only: keep the transcript visible, hide the interview controls.
  const isActive = (stage === 6 || stage === 7) && !isCompleted && !isPastDue();
  const isLocked = stage < 6 && !isCompleted;

  const card = document.createElement('div');
  card.className = `section-card ${isLocked ? 'locked' : isDone ? 'completed' : 'active'}`;
  card.innerHTML = `
    <div class="section-header">
      <div class="section-icon"><i class="bi bi-chat-dots-fill"></i></div>
      <div>
        <div class="section-title">口說練習二：角色扮演</div>
        <div class="section-subtitle">Speaking Practice 2 — Role Play</div>
      </div>
      ${isDone ? '<span class="ms-auto badge bg-white text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>完成</span>' : ''}
    </div>
    <div class="section-body" id="roleplayBody"></div>`;
  container.appendChild(card);
  if (isLocked) return;

  const body = card.querySelector('#roleplayBody');
  const vs = getView();
  const conversation = vs && vs.roleplay_conversation ? tryParseJson(vs.roleplay_conversation) : null;
  const turns = conversation ? conversation.turns : [];
  const currentTurn = conversation ? conversation.current_turn : 0;

  body.innerHTML = renderRoleplayTaskGuide(vs,stage,isCompleted,turns,currentTurn);

  if (turns.length > 0) {
    const completedTurns = turns.filter(t => t.student_transcript).length;
    const coreQuestionCount = workflowLimit('core_question_count');
    const secretQuestionIndex = workflowLimit('secret_question_source_index');
    const completedCore = new Set(turns.filter(t => t.student_transcript && Number.isInteger(t.source_question_index) && t.source_question_index < coreQuestionCount).map(t => t.source_question_index)).size;
    const secretAnswered = turns.some(t => t.student_transcript && t.source_question_index === secretQuestionIndex);
    body.innerHTML += `<div class="mb-3"><span class="turn-badge">核心題目 ${completedCore} / ${coreQuestionCount}・臨場追問 ${secretAnswered ? '1 / 1' : '0 / 1'}（已回答 ${completedTurns} 輪）</span></div>`;
    body.innerHTML += `<div class="chat-container mb-3" id="chatContainer">${renderChatBubbles(turns)}</div>`;
  }

  if (isActive) {
    if (stage === 6) {
      body.innerHTML += `
        <button class="btn btn-primary-custom" id="startInterviewBtn" data-action="startRoleplay">
          <span id="startInterviewSpinner" class="spinner-border spinner-border-sm d-none me-1"></span>
          <i class="bi bi-play-fill me-1"></i>開始面試 Start Interview
        </button>`;
    } else if (stage === 7 && currentTurn <= workflowLimit('max_roleplay_turns')) {
      const allTurnsAnswered = turns.length > 0 && turns.every(t => t.student_transcript);
      const completedCore = new Set(turns.filter(t => t.student_transcript && Number.isInteger(t.source_question_index) && t.source_question_index < workflowLimit('core_question_count')).map(t => t.source_question_index)).size;
      const secretAnswered = turns.some(t => t.student_transcript && t.source_question_index === workflowLimit('secret_question_source_index'));
      if (allTurnsAnswered && completedCore >= workflowLimit('core_question_count') && secretAnswered) {
        body.innerHTML += `
          <div class="alert alert-warning"><i class="bi bi-exclamation-triangle-fill me-1"></i>五個面試題目都已完成，但 AI 回饋尚未產生。你的錄音與回答已保留，不需要重新錄音。</div>
          <button class="btn btn-primary-custom" id="retryReportBtn" data-action="retryRoleplayReport">
            <span id="retryReportSpinner" class="spinner-border spinner-border-sm d-none me-1"></span>
            <i class="bi bi-arrow-clockwise me-1"></i>重新產生 AI 回饋
          </button>`;
      } else if (allTurnsAnswered) {
        body.innerHTML += `
          <div class="alert alert-warning"><i class="bi bi-exclamation-triangle-fill me-1"></i>上一輪回答已經儲存，但下一題還沒準備完成。你不需要重新錄音，可以直接從這裡接著進行。</div>
          <button class="btn btn-primary-custom" id="startInterviewBtn" data-action="startRoleplay">
            <span id="startInterviewSpinner" class="spinner-border spinner-border-sm d-none me-1"></span>
            <i class="bi bi-arrow-clockwise me-1"></i>準備下一題並繼續
          </button>`;
      } else {
        body.innerHTML += `
          <p class="fw-semibold mb-2"><i class="bi bi-mic me-1 text-danger"></i>第 ${currentTurn} 輪：請錄製你的回答</p>
          <p class="text-muted small mb-3">${turns.find(t => t.turn_number === currentTurn)?.source_question_index === workflowLimit('secret_question_source_index') ? '臨場追問最長 90 秒' : '最長 5 分鐘 / Max 5 minutes'}</p>
          <div class="d-flex align-items-center gap-3 mb-3 flex-wrap">
            <button class="btn btn-record" id="recordBtnRp" data-action="startRecording">
              <i class="bi bi-record-circle me-1"></i>開始錄音
            </button>
            <button class="btn btn-stop d-none" id="stopBtnRp" data-action="stopRecording">
              <i class="bi bi-stop-circle me-1"></i>停止
            </button>
            <span class="timer-display d-none" id="timerRp">0:00</span>
          </div>
          <div id="statusRp" class="text-muted small mb-2"></div>
          <div id="previewRp" class="d-none mb-3">
            <p class="fw-semibold mb-2" style="color:#10b981"><i class="bi bi-play-circle me-1"></i>錄音預覽，確認後再提交</p>
            <audio id="previewAudioRp" controls class="d-block mb-3" style="max-width:400px"></audio>
            <div class="d-flex gap-2">
              <button class="btn btn-outline-secondary btn-sm" data-action="reRecord">
                <i class="bi bi-arrow-repeat me-1"></i>重錄
              </button>
              <button class="btn btn-success-custom btn-sm" data-action="submitAudio">
                <i class="bi bi-send me-1"></i>確認提交
              </button>
            </div>
          </div>
          <div id="spinnerRp" class="d-none processing-overlay">
            <div class="spinner-border text-primary"></div>
            <span>音訊處理中，請稍候... Processing audio...</span>
          </div>`;
      }
    }
  }

  if (isDone) {
    body.innerHTML += `<div class="alert alert-success py-2 mt-2"><i class="bi bi-check-circle me-1"></i>角色扮演已完成！AI 回饋已產生。</div>`;
  }

  if (turns.length > 0) {
    setTimeout(() => {
      const chatBox = document.getElementById('chatContainer');
      if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;
    }, 100);
  }
}

function renderChatBubbles(turns) {
  return turns.map(t => {
    let html = `
      <div class="d-flex flex-column mb-1">
        <div class="chat-label text-muted" style="margin-left:4px">
          <i class="bi bi-person-workspace me-1"></i>面試官 Interviewer · 第 ${t.turn_number} 輪
        </div>
        <div class="chat-bubble chat-interviewer">
          ${escHtml(t.interviewer_question)}
          ${t.interviewer_tts_key ? `
            <div class="mt-2" id="tts-player-${t.turn_number}">
              <button class="btn btn-sm btn-outline-secondary py-0 px-2" data-action="loadChatTTS" data-args='[${t.turn_number}]'>
                <i class="bi bi-volume-up me-1"></i>播放問題
              </button>
            </div>` : ''}
        </div>
      </div>`;
    if (t.student_transcript) {
      html += `
        <div class="d-flex flex-column align-items-end mb-1">
          <div class="chat-label text-muted" style="margin-right:4px">
            <i class="bi bi-person me-1"></i>你的回答
          </div>
          <div class="chat-bubble chat-student">
            ${escHtml(t.student_transcript)}
            ${t.student_audio_key ? `
              <div class="mt-2" id="student-player-${t.turn_number}">
                <button class="btn btn-sm btn-outline-light py-0 px-2" data-action="loadChatStudentAudio" data-args='[${t.turn_number}]'>
                  <i class="bi bi-play-circle me-1"></i>播放錄音
                </button>
              </div>` : ''}
          </div>
        </div>`;
    }
    return html;
  }).join('');
}

async function loadChatTTS(turnNumber) {
  const box = document.getElementById(`tts-player-${turnNumber}`);
  if (!box) return;
  box.innerHTML = '<span class="text-muted" style="font-size:0.8rem">載入中...</span>';
  try {
    const res = await apiCall(`/api/student/submissions/${getView().id}/audio/roleplay-tts/${turnNumber}`);
    if (res.ok) {
      const data = await res.json();
      const _a1 = document.createElement('audio'); _a1.controls = true; _a1.style.cssText = 'height:30px;max-width:220px;margin-top:4px';
      const _s1 = document.createElement('source'); _s1.src = data.url; _s1.type = 'audio/mpeg';
      _a1.appendChild(_s1); box.textContent = ''; box.appendChild(_a1);
    } else {
      box.textContent = '載入失敗';
    }
  } catch { box.textContent = '載入失敗'; }
}

async function loadChatStudentAudio(turnNumber) {
  const box = document.getElementById(`student-player-${turnNumber}`);
  if (!box) return;
  box.textContent = '載入中...';
  try {
    const res = await apiCall(`/api/student/submissions/${getView().id}/audio/roleplay/${turnNumber}`);
    if (res.ok) {
      const data = await res.json();
      const _a2 = document.createElement('audio'); _a2.controls = true; _a2.style.cssText = 'height:30px;max-width:220px;margin-top:4px';
      const _s2 = document.createElement('source'); _s2.src = data.url; _s2.type = 'audio/mpeg';
      _a2.appendChild(_s2); box.textContent = ''; box.appendChild(_a2);
    } else {
      box.innerHTML = '<span style="font-size:0.8rem;opacity:0.8">載入失敗</span>';
    }
  } catch { box.innerHTML = '<span style="font-size:0.8rem;opacity:0.8">載入失敗</span>'; }
}

async function playInterviewerTTS(turnNumber) {
  try {
    const res = await apiCall(`/api/student/submissions/${getView().id}/audio/roleplay-tts/${turnNumber}`);
    if (res.ok) {
      const data = await res.json();
      const audio = new Audio(data.url);
      audio.play().catch(() => {});
      setTimeout(() => loadChatTTS(turnNumber), 100);
    }
  } catch {}
}

async function startRoleplay() {
  const btn = document.getElementById('startInterviewBtn');
  const spinner = document.getElementById('startInterviewSpinner');
  const priorConversation = tryParseJson(submission.roleplay_conversation) || { turns: [] };
  const isRecovery = priorConversation.turns.length > 0
    && priorConversation.turns.every(t => t.student_transcript);
  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove('d-none');
  const res = await apiCall(`/api/student/submissions/${submission.id}/roleplay/start`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) {
    if (btn && btn.isConnected) { btn.disabled = false; if (spinner) spinner.classList.add('d-none'); }
    showAlert(data.detail || '開始面試時發生錯誤');
    return;
  }
  submission = data.submission;
  renderAll();
  showAlert(isRecovery ? '下一題已準備完成，可以接著回答。' : '面試已開始！請聆聽問題並錄製你的回答。', 'success');
  if (data.first_question_tts_key) {
    const conversation = tryParseJson(submission.roleplay_conversation) || { current_turn: 1 };
    setTimeout(() => playInterviewerTTS(conversation.current_turn || 1), 400);
  }
}

async function startRecording() {
  if (!window.isSecureContext) {
    showAlert('麥克風功能需要安全連線（HTTPS）才能使用。請確認網址以 <strong>https://</strong> 開頭後再試。');
    return;
  }
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== 'function') {
    showAlert('你的瀏覽器不支援麥克風錄音功能。請改用 Chrome 或 Firefox 最新版本。');
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    recordingChunks = [];
    recordingSeconds = 0;

    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) recordingChunks.push(e.data); };
    mediaRecorder.onstop = () => showPreview();
    // Let the browser finalize one complete native audio container on stop.
    // This is especially important for Safari's MP4 output.
    mediaRecorder.start();

    document.getElementById('recordBtnRp').classList.add('d-none');
    document.getElementById('stopBtnRp').classList.remove('d-none');
    document.getElementById('timerRp').classList.remove('d-none');
    const status = document.getElementById('statusRp');
    if (status) status.textContent = '錄音中... Recording...';

    const activeConversation = tryParseJson(submission.roleplay_conversation) || { turns: [] };
    const activeTurn = activeConversation.turns.find(
      turn => turn.turn_number === activeConversation.current_turn
    );
    const recordingLimit = activeTurn?.source_question_index === workflowLimit('secret_question_source_index')
      ? SECRET_RECORDING_SECONDS
      : MAX_RECORDING_SECONDS;

    timerInterval = setInterval(() => {
      recordingSeconds++;
      const m = Math.floor(recordingSeconds / 60);
      const s = recordingSeconds % 60;
      document.getElementById('timerRp').textContent = `${m}:${s.toString().padStart(2, '0')}`;
      if (recordingSeconds >= recordingLimit) stopRecording();
    }, 1000);
  } catch (err) {
    if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      showAlert('麥克風存取被拒絕。請點選瀏覽器網址列旁的鎖頭圖示，允許本網站使用麥克風後重新整理頁面再試。');
    } else if (err.name === 'NotFoundError') {
      showAlert('找不到麥克風裝置。請確認電腦已連接麥克風後再試。');
    } else if (err.name === 'NotReadableError') {
      showAlert('麥克風目前被其他程式佔用中，請關閉其他正在使用麥克風的應用程式後再試。');
    } else {
      showAlert(`無法存取麥克風（${err.name || '未知錯誤'}）。請確認麥克風已連接且瀏覽器已授權使用。`);
    }
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
  clearInterval(timerInterval);
  document.getElementById('stopBtnRp').classList.add('d-none');
  document.getElementById('timerRp').classList.add('d-none');
  const status = document.getElementById('statusRp');
  if (status) status.textContent = '錄音完成，可先預覽再提交。 Recording complete.';
}

function showPreview() {
  if (recordingChunks.length === 0) { reRecord(); return; }
  const { blob } = buildRecordedAudio(recordingChunks, mediaRecorder);
  if (pendingAudioURL) URL.revokeObjectURL(pendingAudioURL);
  pendingAudioURL = URL.createObjectURL(blob);
  setAudioPreview(document.getElementById('previewAudioRp'), pendingAudioURL);
  document.getElementById('previewRp').classList.remove('d-none');
}

function reRecord() {
  if (pendingAudioURL) { URL.revokeObjectURL(pendingAudioURL); pendingAudioURL = null; }
  recordingChunks = [];
  document.getElementById('previewRp').classList.add('d-none');
  document.getElementById('recordBtnRp').classList.remove('d-none');
}

async function submitAudio() {
  const previewEl = document.getElementById('previewRp');
  const spinnerEl = document.getElementById('spinnerRp');
  spinnerEl.classList.remove('d-none');

  const { blob, filename } = buildRecordedAudio(recordingChunks, mediaRecorder);
  const formData = new FormData();
  formData.append('audio', blob, filename);

  let res;
  let data;
  try {
    res = await fetch(`/api/student/submissions/${submission.id}/roleplay/turn`, {
      method: 'POST',
      credentials: 'include',
      body: formData,
    });
    data = await res.json();
  } catch (error) {
    spinnerEl.classList.add('d-none');
    previewEl.classList.remove('d-none');
    showAlert('無法送出錄音，請檢查網路後再試一次。');
    return;
  }
  spinnerEl.classList.add('d-none');

  if (!res.ok) {
    const detail = data && data.detail;
    if (detail && typeof detail === 'object' && detail.code === 'roleplay_response_rejected') {
      showAlert(detail.message || "Let's stay focused on the interview. Please answer the current question in English.");
      reRecord();
      const conversation = tryParseJson(submission.roleplay_conversation) || { current_turn: 1, turns: [] };
      const current = conversation.turns.find(turn => turn.turn_number === conversation.current_turn);
      if (detail.replay_current_question && current?.interviewer_tts_key) {
        setTimeout(() => playInterviewerTTS(conversation.current_turn || 1), 300);
      }
      return;
    }
    showAlert(typeof detail === 'string' ? detail : '音訊處理時發生錯誤');
    if (res.status === 503) {
      const refreshed = await apiCall(`/api/student/submissions/${submission.id}`);
      if (refreshed.ok) {
        submission = await refreshed.json();
        renderAll();
      }
    } else {
      previewEl.classList.remove('d-none');
    }
    return;
  }

  if (pendingAudioURL) { URL.revokeObjectURL(pendingAudioURL); pendingAudioURL = null; }
  previewEl.classList.add('d-none');

  if (data.is_complete) {
    submission.report_data = JSON.stringify(data.report);
    submission.stage = 8;
    clearRoleplayScratchpads();
    showAlert('面試完成！AI 回饋已生成，前往查看回饋。', 'success');
    setTimeout(() => { navigateStudentPage(`/student/assignment/${assignmentId}/report`); }, 1200);
    return;
  }

  submission.stage = 7;
  const conv = tryParseJson(submission.roleplay_conversation) || { current_turn: 1, turns: [] };
  const currentTurn = data.turn_number;
  for (const t of conv.turns) {
    if (t.turn_number === currentTurn) {
      t.source_question_index = data.source_question_index;
      t.student_transcript = data.student_transcript;
      t.student_audio_key = data.student_audio_key || null;
      break;
    }
  }
  if (data.next_question) {
    conv.turns.push({
      turn_number: currentTurn + 1,
      source_question_index: data.next_question_source_index,
      interviewer_question: data.next_question,
      interviewer_tts_key: data.next_question_tts_key || null,
      student_transcript: null,
      student_audio_key: null,
    });
    conv.current_turn = currentTurn + 1;
  }
  submission.roleplay_conversation = JSON.stringify(conv);
  renderAll();
  showAlert(`第 ${currentTurn} 輪完成！請回答下一個問題。`, 'success');
  if (data.next_question_tts_key) {
    setTimeout(() => playInterviewerTTS(currentTurn + 1), 400);
  }
}

async function retryRoleplayReport() {
  const btn = document.getElementById('retryReportBtn');
  const spinner = document.getElementById('retryReportSpinner');
  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove('d-none');
  const res = await apiCall(`/api/student/submissions/${submission.id}/roleplay/report/regenerate`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) {
    if (btn) btn.disabled = false;
    if (spinner) spinner.classList.add('d-none');
    showAlert(data.detail || 'AI 回饋重新產生失敗，請稍後再試。');
    return;
  }
  submission = data.submission;
  clearRoleplayScratchpads();
  showAlert('AI 回饋已產生。', 'success');
  setTimeout(() => { navigateStudentPage(`/student/assignment/${assignmentId}/report`); }, 700);
}

init().catch(error=>renderStudentPageLoadError(error));

Object.assign(window, {
  scratchpadKey,
  saveRoleplayKeywords,
  clearRoleplayScratchpads,
  roleplayKeywordField,
  renderRoleplayTaskGuide,
  init,
  renderAll,
  renderSection3,
  renderChatBubbles,
  loadChatTTS,
  loadChatStudentAudio,
  playInterviewerTTS,
  startRoleplay,
  startRecording,
  stopRecording,
  showPreview,
  reRecord,
  submitAudio,
  retryRoleplayReport,
});
