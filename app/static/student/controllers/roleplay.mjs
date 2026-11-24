import {
  attemptAudioPlayback,
  prepareAudioElement,
} from '/static/student/audio-session.mjs';
import {
  RecordingPanel,
  renderRecordingControls,
} from '/static/student/recording-panel.mjs';

const pathParts = window.location.pathname.split('/');
window.assignmentId = parseInt(pathParts[3]);
const urlParams = new URLSearchParams(window.location.search);
window.viewId = urlParams.get('view') ? parseInt(urlParams.get('view')) : null;

window.submission = null;
window.assignment = null;
window.viewedSubmission = null;

let roleplaySubmitting = false;
const interviewerAudioPlayers = new Map();
const interviewerAudioPreparations = new Map();
let activeInterviewerAudio = null;
let interviewerPlaybackGeneration = 0;
const MAX_RECORDING_SECONDS = 300;
const SECRET_RECORDING_SECONDS = 90;

function currentRecordingLimit() {
  const conversation = tryParseJson(submission?.roleplay_conversation) || { turns: [] };
  const turn = conversation.turns.find(t => t.turn_number === conversation.current_turn);
  return turn?.source_question_index === workflowLimit('secret_question_source_index')
    ? SECRET_RECORDING_SECONDS
    : MAX_RECORDING_SECONDS;
}

const recorder = new RecordingPanel({
  suffix: 'Rp',
  logTag: 'roleplay',
  maxSeconds: currentRecordingLimit,
  showAlert: message => showAlert(message),
  onBeforeStart: () => {
    interviewerPlaybackGeneration += 1;
    pauseInterviewerAudio();
  },
});

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

// One place derives roleplay progress; the guide, the controls and the
// recovery prompts all read from it.
function roleplayProgress(turns) {
  const coreCount = workflowLimit('core_question_count');
  const secretIndex = workflowLimit('secret_question_source_index');
  const answered = turns.filter(turn => turn.student_transcript);
  const completedCore = new Set(answered
    .filter(turn => Number.isInteger(turn.source_question_index) && turn.source_question_index < coreCount)
    .map(turn => turn.source_question_index)).size;
  const secretAnswered = answered.some(turn => turn.source_question_index === secretIndex);
  const allTurnsAnswered = turns.length > 0 && answered.length === turns.length;
  return {
    coreCount,
    completedTurns: answered.length,
    completedCore,
    secretAnswered,
    allTurnsAnswered,
    awaitingReport: allTurnsAnswered && completedCore >= coreCount && secretAnswered,
    awaitingNextQuestion: allTurnsAnswered && !(completedCore >= coreCount && secretAnswered),
    label: `核心題 ${completedCore}/${coreCount}・追問 ${secretAnswered ? 1 : 0}/1`,
  };
}

function renderRoleplayTaskGuide(vs, stage, isCompleted, turns, currentTurn) {
  const p = roleplayProgress(turns);
  if (viewId || isCompleted || stage >= 8 || isPastDue()) return '';
  if (stage === 6) return renderAiGuide(vs);
  if (p.awaitingReport || p.awaitingNextQuestion) return '';

  const activeTurn = turns.find(turn => turn.turn_number === currentTurn) || {};
  const sourceIndex = Number.isInteger(activeTurn.source_question_index)
    ? activeTurn.source_question_index
    : Math.max(0, currentTurn - 1);
  const isSecret = sourceIndex === workflowLimit('secret_question_source_index');
  const aiHtml = isSecret ? '' : learningScaffoldQuestionHtml(vs, sourceIndex, 'roleplay');
  return `${renderAiGuide(vs, aiHtml)}${roleplayKeywordField(currentTurn, isSecret)}`;
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
  if (!viewId && !isCompleted && stage === 7) autoplayCurrentQuestion();
}

function renderAll() {
  const vs = getView();
  const stage = vs ? vs.stage : 6;
  const isCompleted = !!(vs && vs.submitted_at);

  updateProgressSteps(isCompleted ? 9 : stage);

  renderViewBanner();
  const isViewingPast = viewedSubmission && submission && viewedSubmission.id !== submission.id;

  disposeInterviewerAudioPlayers();
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
      <div>
        <div class="section-title">口說練習二：角色扮演</div>
        <div class="section-subtitle">Speaking Practice 2 — Role Play</div>
      </div>
      ${isDone ? '<span class="section-status section-status-done"><i class="bi bi-check-circle-fill"></i>完成</span>' : isLocked ? '<span class="section-status section-status-locked"><i class="bi bi-lock-fill"></i>未解鎖</span>' : '<span class="section-status section-status-active">進行中</span>'}
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
    body.innerHTML += `<div class="chat-container mb-3" id="chatContainer">${renderChatBubbles(turns)}</div>`;
  }

  if (isActive) {
    if (stage === 6) {
      body.innerHTML += `
        <button class="btn btn-primary-custom" id="startInterviewBtn" data-action="startRoleplay">
          <span id="startInterviewSpinner" class="spinner-border spinner-border-sm d-none me-1"></span>
          <i class="bi bi-play-fill me-1"></i>開始面試
        </button>`;
    } else if (stage === 7 && currentTurn <= workflowLimit('max_roleplay_turns')) {
      const progress = roleplayProgress(turns);
      if (progress.awaitingReport) {
        body.innerHTML += `
          <div class="alert alert-warning"><i class="bi bi-exclamation-triangle-fill me-1"></i>回答都已保存，但回饋還沒產生成功。</div>
          <button class="btn btn-primary-custom" id="retryReportBtn" data-action="retryRoleplayReport">
            <span id="retryReportSpinner" class="spinner-border spinner-border-sm d-none me-1"></span>
            <i class="bi bi-arrow-clockwise me-1"></i>重新產生 AI 回饋
          </button>`;
      } else if (progress.awaitingNextQuestion) {
        body.innerHTML += `
          <div class="alert alert-warning"><i class="bi bi-exclamation-triangle-fill me-1"></i>上一輪已保存，下一題還沒出來。</div>
          <button class="btn btn-primary-custom" id="startInterviewBtn" data-action="startRoleplay">
            <span id="startInterviewSpinner" class="spinner-border spinner-border-sm d-none me-1"></span>
            <i class="bi bi-arrow-clockwise me-1"></i>準備下一題並繼續
          </button>`;
      } else {
        body.innerHTML += `
          <p class="fw-semibold mb-2"><i class="bi bi-mic me-1 text-danger"></i>錄下你的回答</p>
          <p class="text-muted small mb-3">最長 ${currentRecordingLimit() === SECRET_RECORDING_SECONDS ? '90 秒' : '5 分鐘'}</p>
          ${renderRecordingControls({ suffix: 'Rp' })}`;
      }
    }
  }

  if (isDone) {
    body.innerHTML += `<div class="alert alert-success py-2 mt-2"><i class="bi bi-check-circle me-1"></i>模擬面試已完成，回饋已產生。</div>`;
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
        <div class="chat-label text-muted ms-1">
          面試官 Interviewer · 第 ${t.turn_number} 輪
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
          <div class="chat-label text-muted me-1">
            你的回答
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

function disposeInterviewerAudioPlayers() {
  interviewerPlaybackGeneration += 1;
  for (const { audio } of interviewerAudioPlayers.values()) {
    try { audio.pause(); } catch (_) {}
  }
  interviewerAudioPlayers.clear();
  interviewerAudioPreparations.clear();
  activeInterviewerAudio = null;
}

function pauseInterviewerAudio() {
  for (const { audio } of interviewerAudioPlayers.values()) {
    try { audio.pause(); } catch (_) {}
  }
  activeInterviewerAudio = null;
}

function showInterviewerLoadFailure(turnNumber, message = '面試官語音載入失敗，請重試。') {
  const box = document.getElementById(`tts-player-${turnNumber}`);
  if (!box) return;
  box.innerHTML = `<div class="text-danger small mb-1">${escHtml(message)}</div>
    <button class="btn btn-sm btn-outline-secondary py-0 px-2" data-action="retryInterviewerTTS" data-args='[${turnNumber}]'>
      <i class="bi bi-arrow-clockwise me-1"></i>重新載入語音
    </button>`;
}

function showInterviewerPlaybackFallback(turnNumber) {
  const status = document.getElementById(`tts-status-${turnNumber}`);
  const fallback = document.getElementById(`tts-fallback-${turnNumber}`);
  if (status) {
    status.className = 'alert alert-warning py-1 px-2 mt-2 mb-1 small';
    status.textContent = 'iPad／iPhone 未允許自動播放，請點一下「播放問題」。';
  }
  if (fallback) fallback.classList.remove('d-none');
}

async function resumeInterviewerTTS(turnNumber) {
  if (recorder.isRecording()) {
    showAlert('先停止錄音，再播放問題。', 'warning');
    return;
  }
  const entry = interviewerAudioPlayers.get(turnNumber);
  if (!entry?.audio) {
    await prepareInterviewerTTS(turnNumber, { attemptAutoplay: true });
    return;
  }
  const result = await attemptAudioPlayback(entry.audio);
  if (result.status === 'blocked') {
    console.warn('[roleplay-tts:autoplay-blocked]');
    showInterviewerPlaybackFallback(turnNumber);
  } else if (result.status === 'failed') {
    console.warn('[roleplay-tts:playback-failed]', result.error?.name || 'unknown');
    showInterviewerLoadFailure(turnNumber, '面試官語音無法播放，請重新載入。');
  }
}

async function mountInterviewerTTS(turnNumber) {
  const box = document.getElementById(`tts-player-${turnNumber}`);
  if (!box) return null;
  box.innerHTML = '<span class="text-muted fs-sm"><span class="spinner-border spinner-border-sm me-1"></span>載入面試官語音…</span>';
  try {
    const audio = await prepareAudioElement(async () => {
      const res = await apiCall(`/api/student/submissions/${getView().id}/audio/roleplay-tts/${turnNumber}`);
      if (!res.ok) throw new Error(`tts_http_${res.status}`);
      const data = await res.json();
      return data.url;
    });
    if (!box.isConnected) return null;
    audio.controls = true;
    audio.preload = 'auto';
    audio.playsInline = true;
    audio.style.cssText = 'height:38px;max-width:100%;margin-top:4px';
    audio.setAttribute('aria-label', `第 ${turnNumber} 輪面試官問題`);

    const status = document.createElement('div');
    status.id = `tts-status-${turnNumber}`;
    status.className = 'text-muted small mt-1';
    status.textContent = '面試官語音已準備完成。';
    const fallback = document.createElement('button');
    fallback.type = 'button';
    fallback.id = `tts-fallback-${turnNumber}`;
    fallback.className = 'btn btn-sm btn-primary mt-1 d-none';
    fallback.dataset.action = 'resumeInterviewerTTS';
    fallback.dataset.args = JSON.stringify([turnNumber]);
    fallback.innerHTML = '<i class="bi bi-play-fill me-1"></i>播放問題';

    audio.addEventListener('play', () => {
      if (activeInterviewerAudio && activeInterviewerAudio !== audio) {
        try { activeInterviewerAudio.pause(); } catch (_) {}
      }
      activeInterviewerAudio = audio;
      status.className = 'text-primary small mt-1';
      status.textContent = '正在播放面試官問題…';
      fallback.classList.add('d-none');
    });
    audio.addEventListener('ended', () => {
      if (activeInterviewerAudio === audio) activeInterviewerAudio = null;
      status.className = 'text-success small mt-1';
      status.textContent = '問題播放完成，可以開始錄音。';
    });
    audio.addEventListener('error', () => {
      console.warn('[roleplay-tts:media-error]');
      showInterviewerLoadFailure(turnNumber, '面試官語音格式暫時無法播放，請重新載入。');
    }, { once: true });

    box.textContent = '';
    box.append(audio, status, fallback);
    interviewerAudioPlayers.set(turnNumber, { audio });
    try { audio.load(); } catch (error) {
      console.warn('[roleplay-tts:load-failed]', error?.name || 'unknown');
      showInterviewerLoadFailure(turnNumber);
      return null;
    }
    return audio;
  } catch (error) {
    console.warn('[roleplay-tts:url-load-failed]', error?.name || 'unknown');
    showInterviewerLoadFailure(turnNumber);
    return null;
  }
}

async function prepareInterviewerTTS(turnNumber, { attemptAutoplay = false } = {}) {
  const playbackGeneration = interviewerPlaybackGeneration;
  const existing = interviewerAudioPlayers.get(turnNumber);
  if (existing?.audio) {
    if (attemptAutoplay) await resumeInterviewerTTS(turnNumber);
    return existing.audio;
  }

  let preparation = interviewerAudioPreparations.get(turnNumber);
  if (!preparation) {
    preparation = mountInterviewerTTS(turnNumber);
    interviewerAudioPreparations.set(turnNumber, preparation);
  }
  let audio = null;
  try {
    audio = await preparation;
  } finally {
    if (interviewerAudioPreparations.get(turnNumber) === preparation) {
      interviewerAudioPreparations.delete(turnNumber);
    }
  }
  if (attemptAutoplay && audio && playbackGeneration === interviewerPlaybackGeneration) {
    await resumeInterviewerTTS(turnNumber);
  }
  return audio;
}

async function loadChatTTS(turnNumber) {
  await prepareInterviewerTTS(turnNumber, { attemptAutoplay: true });
}

async function retryInterviewerTTS(turnNumber) {
  const existing = interviewerAudioPlayers.get(turnNumber);
  try { existing?.audio?.pause(); } catch (_) {}
  interviewerAudioPlayers.delete(turnNumber);
  await prepareInterviewerTTS(turnNumber, { attemptAutoplay: true });
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
      box.innerHTML = '<span class="chat-audio-label">載入失敗</span>';
    }
  } catch { box.innerHTML = '<span class="chat-audio-label">載入失敗</span>'; }
}

async function playInterviewerTTS(turnNumber) {
  await prepareInterviewerTTS(turnNumber, { attemptAutoplay: true });
}

function autoplayCurrentQuestion() {
  const conversation = tryParseJson(submission?.roleplay_conversation) || { turns: [] };
  const currentTurn = conversation.current_turn || 1;
  const current = conversation.turns.find(turn => turn.turn_number === currentTurn);
  if (current?.interviewer_tts_key) playInterviewerTTS(currentTurn);
}

async function startRoleplay() {
  const btn = document.getElementById('startInterviewBtn');
  const spinner = document.getElementById('startInterviewSpinner');
  const priorConversation = tryParseJson(submission.roleplay_conversation) || { turns: [] };
  const isRecovery = roleplayProgress(priorConversation.turns).allTurnsAnswered;
  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove('d-none');
  const res = await apiCall(`/api/student/submissions/${submission.id}/roleplay/start`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) {
    if (btn && btn.isConnected) { btn.disabled = false; if (spinner) spinner.classList.add('d-none'); }
    showAlert(data.detail || '無法開始面試，請再試一次。');
    return;
  }
  submission = data.submission;
  renderAll();
  showAlert(isRecovery ? '下一題來了。' : '面試開始。', 'success');
  if (data.first_question_tts_key) autoplayCurrentQuestion();
}

async function startRecording() {
  if (roleplaySubmitting) return;
  const conversation = tryParseJson(submission?.roleplay_conversation);
  const turnNumber = conversation?.current_turn;
  if (!Number.isInteger(turnNumber) || submission?.stage !== 7) return;
  await recorder.start({ turnNumber });
}

async function stopRecording() {
  await recorder.stop();
}

function showPreview() {
  recorder.showPreview();
}

function reRecord() {
  recorder.reset();
}

function setRoleplaySubmitting(busy) {
  roleplaySubmitting = busy;
  for (const button of document.querySelectorAll('[data-action="submitAudio"], [data-action="reRecord"], [data-action="startRecording"]')) {
    button.disabled = busy;
  }
  recorder.setBusy(busy);
}

async function syncRoleplayAfterUpload(turnNumber) {
  try {
    const res = await apiCall(`/api/student/submissions/${submission.id}`);
    if (!res.ok) return false;
    const fresh = await res.json();
    const conversation = tryParseJson(fresh.roleplay_conversation);
    const saved = conversation?.turns?.some(turn => turn.turn_number === turnNumber && turn.student_transcript);
    // Preserve the pending recording if the server still awaits this exact
    // turn. Otherwise discard it before presenting any later question.
    if (!saved && fresh.stage === 7 && conversation?.current_turn === turnNumber) return false;
    reRecord();
    submission = fresh;
    renderAll();
    showAlert(saved ? '這一輪已經保存過了。' : '進度已更新，請看目前的題目再錄音。', 'success');
    return true;
  } catch (_) {
    return false;
  }
}

async function submitAudio() {
  if (roleplaySubmitting) return;
  const recordedAudio = recorder.recordedAudio;
  if (!recordedAudio?.blob?.size || !Number.isInteger(recordedAudio.turnNumber)) {
    showAlert('請先錄音再送出。');
    return;
  }
  const { blob, filename, durationMs, turnNumber } = recordedAudio;
  const formData = new FormData();
  formData.append('audio', blob, filename);
  formData.append('client_duration_ms', String(durationMs));
  formData.append('expected_turn_number', String(turnNumber));
  setRoleplaySubmitting(true);

  try {
    let res;
    let data;
    try {
      res = await fetch(`/api/student/submissions/${submission.id}/roleplay/turn`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      });
      data = await res.json();
    } catch (_) {
      if (!await syncRoleplayAfterUpload(turnNumber)) {
        showAlert('連線中斷，還不確定是否送出。錄音還在，網路恢復後再按一次送出就好，不會重複。');
      }
      return;
    }

    if (!res.ok) {
      const detail = data?.detail;
      if (detail && typeof detail === 'object' && detail.code === 'roleplay_response_rejected') {
        showAlert(detail.message || "Please answer the current question in English.");
        reRecord();
        const conversation = tryParseJson(submission.roleplay_conversation);
        const current = conversation?.turns?.find(turn => turn.turn_number === turnNumber);
        if (detail.replay_current_question && current?.interviewer_tts_key) playInterviewerTTS(turnNumber);
        return;
      }
      if (!await syncRoleplayAfterUpload(turnNumber)) {
        showAlert(typeof detail === 'string' ? detail : '錄音處理失敗。錄音還在，可以再送一次。');
      }
      return;
    }

    // The server supplies the whole conversation, including answers committed
    // before an earlier response was lost. Do not append guesses locally.
    if (!data.submission) {
      if (!await syncRoleplayAfterUpload(turnNumber)) showAlert('請重新整理頁面確認進度。');
      return;
    }
    reRecord();
    submission = data.submission;
    renderAll();
    if (submission.stage >= 8) {
      clearRoleplayScratchpads();
      showAlert('面試結束，正在前往回饋頁。', 'success');
      setTimeout(() => { navigateStudentPage(`/student/assignment/${assignmentId}/report`); }, 1200);
    } else {
      showAlert(`第 ${turnNumber} 輪已送出。`, 'success');
      autoplayCurrentQuestion();
    }
  } finally {
    setRoleplaySubmitting(false);
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

window.addEventListener('pagehide', () => {
  recorder.release();
  disposeInterviewerAudioPlayers();
});

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
  retryInterviewerTTS,
  resumeInterviewerTTS,
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
