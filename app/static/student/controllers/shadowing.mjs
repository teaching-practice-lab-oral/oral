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

const recorders = {};
const ttsSubtitles = new TtsSubtitleController();
const MAX_RECORDING_SECONDS = 300;

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

  if (stage < 5 && !viewId && !isCompleted) {
    navigateStudentPage(`/student/assignment/${assignmentId}/writing`);
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

  // Auto-load TTS for the currently active question
  if (!viewId && vs && vs.shadowing_tts_keys && stage === 5) {
    const recordedQuestions = vs.speaking1_questions || [];
    const activeIdx = recordedQuestions.length;
    setTimeout(() => loadTtsAudio(activeIdx), 300);
  }
}

function renderAll() {
  ttsSubtitles.disposeAll();
  const vs = getView();
  const stage = vs ? vs.stage : 5;
  const isCompleted = !!(vs && vs.submitted_at);

  updateProgressSteps(isCompleted ? 9 : stage);

  renderViewBanner();

  const container = document.getElementById('sectionContainer');
  container.innerHTML = '';
  renderSection2(container, stage, isCompleted);

  const shadowingDone = isCompleted || stage >= 6;
  const nav = document.getElementById('sectionNav');
  nav.innerHTML = `
    <div><button class="btn-nav" data-action="navigateSection" data-args='[2]'><i class="bi bi-chevron-left me-1"></i>寫作練習</button></div>
    <div>${shadowingDone
      ? `<button class="btn-nav-next" data-action="navigateSection" data-args='[4]'>角色扮演<i class="bi bi-chevron-right ms-1"></i></button>`
      : ''}</div>`;
}

// ── Section 2: Shadowing ───────────────────────────────────────────────

function renderSection2(container, stage, isCompleted) {
  const allShadowingDone = stage >= 6 || isCompleted;
  const isLocked = stage < 5 && !isCompleted;

  const card = document.createElement('div');
  card.className = `section-card ${isLocked ? 'locked' : allShadowingDone ? 'completed' : 'active'}`;
  card.innerHTML = `
    <div class="section-header">
      <div>
        <div class="section-title">口說練習一：跟讀</div>
        <div class="section-subtitle">Speaking Practice 1 — Shadowing</div>
      </div>
      ${allShadowingDone ? '<span class="section-status section-status-done"><i class="bi bi-check-circle-fill"></i>完成</span>' : isLocked ? '<span class="section-status section-status-locked"><i class="bi bi-lock-fill"></i>未解鎖</span>' : '<span class="section-status section-status-active">進行中</span>'}
    </div>
    <div class="section-body" id="shadowingBody"></div>`;
  container.appendChild(card);
  if (isLocked) return;

  const body = card.querySelector('#shadowingBody');
  const vs = getView();
  const finalAnswers = (vs && vs.final_draft_answers) || [];
  const ttsKeys = (vs && vs.shadowing_tts_keys) || [];
  const recordedMap = {};
  ((vs && vs.speaking1_questions) || []).forEach(q => { recordedMap[q.index] = q; });
  const nextToRecord = Object.keys(recordedMap).length;

  body.innerHTML = '<div id="questionBlocks"></div>';

  const blocksContainer = body.querySelector('#questionBlocks');

  finalAnswers.forEach((item, i) => {
    const recorded = recordedMap[i];
    const isDone = !!recorded;
    const isActive = !allShadowingDone && i === nextToRecord;
    const isLk = !allShadowingDone && i > nextToRecord;
    const statusClass = isDone ? 'q-done' : isActive ? 'q-active' : 'q-locked';
    const labelClass = isDone ? 'done' : isActive ? 'active' : 'locked';
    const labelText = isDone ? '<i class="bi bi-check-circle-fill me-1"></i>已完成' : isActive ? '<i class="bi bi-mic-fill me-1"></i>錄音中' : '<i class="bi bi-lock-fill me-1"></i>尚未開放';

    const ttsEntry = ttsKeys.find(k => k.index === i);
    const hasTts = ttsEntry && ttsEntry.key;
    const canPrepareTts = !viewId && getView()?.stage === 5 && !isPastDue();

    const qBlock = document.createElement('div');
    qBlock.className = `q-block ${statusClass}`;
    qBlock.id = `qBlock_${i}`;

    let html = `
      <div class="q-label ${labelClass}">${labelText}</div>
      <div class="q-question">Q${i+1}：${escHtml(item.question || '')}</div>
      <div class="mb-3">
        <p class="fw-semibold mb-2 small text-slate"><i class="bi bi-volume-up me-1"></i>示範音檔</p>
        <div id="ttsBox_${i}">
          ${hasTts
            ? `<button class="btn btn-outline-primary-custom btn-sm" data-action="loadTtsAudio" data-args='[${i}]'>
                <i class="bi bi-play-circle me-1"></i>播放示範音訊
              </button>`
            : canPrepareTts
              ? `<button class="btn btn-outline-primary-custom btn-sm" data-action="prepareTtsAudio" data-args='[${i}]'>產生示範音訊</button>`
              : `<span class="text-muted small"><i class="bi bi-volume-mute me-1"></i>沒有可播放的示範音訊</span>`}
        </div>
      </div>
      <p class="fw-semibold mb-1 small text-slate">跟讀字幕 Subtitle — 請跟著朗讀</p>
      <div class="q-subtitle mb-3" id="subtitle_${i}">${escHtml(item.text || '')}</div>
      <p class="tts-sync-note d-none" id="ttsSyncNotice_${i}" role="status"></p>`;

    if (isDone) {
      const canRetry = !allShadowingDone && recorded.attempts < workflowLimit('max_shadowing_attempts') && !viewId && !isPastDue();
      const remainingRetries = Math.max(0, workflowLimit('max_shadowing_attempts') - recorded.attempts);
      html += `
        <div class="mb-3">
          <p class="fw-semibold mb-2 small text-emerald-dark"><i class="bi bi-mic me-1"></i>你的錄音</p>
          <div class="d-flex align-items-center gap-2 flex-wrap mb-2">
            <button class="btn btn-outline-primary-custom btn-sm" id="playRecBtn_${i}" data-action="loadRecordingAudio" data-args='[${i}]'>
              <i class="bi bi-play me-1"></i>播放錄音
            </button>
            ${canRetry
              ? `<button class="btn btn-outline-secondary btn-sm" data-action="startRetry" data-args='[${i}]'>
                  <i class="bi bi-arrow-repeat me-1"></i>再試一次
                </button>`
              : ''}
          </div>
          <div id="recPlayContainer_${i}"></div>
        </div>
        ${recorded.transcript ? `
          <div class="mb-2">
            <p class="fw-semibold mb-1 small text-slate-dark"><i class="bi bi-chat-text me-1"></i>語音辨識結果</p>
            <div class="feedback-box"><pre>${escHtml(recorded.transcript)}</pre></div>
          </div>` : ''}
        ${canRetry
          ? `<div class="alert alert-info py-2 mb-0 small"><i class="bi bi-arrow-repeat me-1"></i>您還有 <strong>${remainingRetries} 次</strong> 重新錄音機會。</div>`
          : ''}`;
    }

    if ((isActive || (!isDone && !allShadowingDone && i === nextToRecord)) && !isPastDue()) {
      html += renderRecordingSection(i);
    }

    qBlock.innerHTML = html;
    blocksContainer.appendChild(qBlock);
  });
}

// Shared controls for a new answer and a retry of a submitted answer.
function renderRecordingSection(i) {
  return `
        <div id="recordSection_${i}">
          <p class="fw-semibold mb-2 small recording-section-title"><i class="bi bi-mic me-1"></i>錄下你的跟讀</p>
          <p class="text-muted small mb-3">最長 5 分鐘</p>
          ${renderRecordingControls({ suffix: `_${i}`, args: [i] })}
        </div>`;
}

// ── TTS Audio ─────────────────────────────────────────────────────────────

async function loadTtsAudio(qIndex) {
  const box = document.getElementById(`ttsBox_${qIndex}`);
  if (!box) return;
  ttsSubtitles.dispose(qIndex);
  box.innerHTML = '<span class="text-muted small"><i class="bi bi-hourglass-split me-1"></i>載入中...</span>';
  try {
    const res = await apiCall(`/api/student/submissions/${getView().id}/audio/shadowing-tts/${qIndex}`);
    if (res.ok) {
      const data = await res.json();
      const _a1 = document.createElement('audio'); _a1.controls = true; _a1.className = 'mb-2'; _a1.id = `ttsAudio_${qIndex}`;
      const _s1 = document.createElement('source'); _s1.src = data.url; _s1.type = 'audio/mpeg';
      _a1.appendChild(_s1); box.textContent = ''; box.appendChild(_a1);
      ttsSubtitles.setup(qIndex, _a1, data.sync_available ? data.cues : []);
    } else {
      box.innerHTML = `<button class="btn btn-outline-primary-custom btn-sm" data-action="loadTtsAudio" data-args='[${qIndex}]'>
        <i class="bi bi-play-circle me-1"></i>播放示範音訊</button>
        <button class="btn btn-outline-danger btn-sm ms-2" data-action="prepareTtsAudio" data-args='[${qIndex},true]'><i class="bi bi-arrow-clockwise me-1"></i>重新產生</button>`;
    }
  } catch {
    box.innerHTML = `<button class="btn btn-outline-primary-custom btn-sm" data-action="loadTtsAudio" data-args='[${qIndex}]'><i class="bi bi-arrow-clockwise me-1"></i>重試載入</button><button class="btn btn-outline-danger btn-sm ms-2" data-action="prepareTtsAudio" data-args='[${qIndex},true]'>重新產生音訊</button>`;
  }
}

function seekTtsCue(qIndex, cueIndex) {
  ttsSubtitles.seek(qIndex, cueIndex);
}

async function prepareTtsAudio(qIndex, force=false) {
  const box = document.getElementById(`ttsBox_${qIndex}`);
  if (!box) return;
  box.innerHTML = '<span class="text-primary small"><span class="spinner-border spinner-border-sm me-1"></span>正在產生示範音訊…</span>';
  try {
    const forceQuery=force?'?force=true':'';
    const res = await apiCall(`/api/student/submissions/${submission.id}/audio/shadowing-tts/${qIndex}${forceQuery}`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || '示範音訊產生失敗');
    const audio = document.createElement('audio');
    audio.controls = true;
    audio.className = 'mb-2';
    audio.id = `ttsAudio_${qIndex}`;
    const source = document.createElement('source');
    source.src = data.url;
    source.type = 'audio/mpeg';
    audio.appendChild(source);
    box.textContent = '';
    box.appendChild(audio);
    ttsSubtitles.setup(qIndex, audio, data.sync_available ? data.cues : []);
  } catch (error) {
    box.innerHTML = `<button class="btn btn-outline-danger btn-sm" data-action="prepareTtsAudio" data-args='[${qIndex}]'><i class="bi bi-arrow-clockwise me-1"></i>重新產生示範音訊</button><span class="text-danger small ms-2">${escHtml(error.message || '產生失敗')}</span>`;
  }
}

// ── Student Recording Playback ─────────────────────────────────────────────

async function loadRecordingAudio(qIndex) {
  const container = document.getElementById(`recPlayContainer_${qIndex}`);
  const btn = document.getElementById(`playRecBtn_${qIndex}`);
  if (!container) return;
  if (btn) btn.disabled = true;
  container.innerHTML = '<span class="text-muted small"><i class="bi bi-hourglass-split me-1"></i>載入中...</span>';
  try {
    const res = await apiCall(`/api/student/submissions/${getView().id}/audio/speaking1/${qIndex}`);
    if (res.ok) {
      const data = await res.json();
      if (btn) btn.remove();
      const _a2 = document.createElement('audio'); _a2.controls = true; _a2.style.maxWidth = '400px';
      const _s2 = document.createElement('source'); _s2.src = data.url; _s2.type = 'audio/mpeg';
      _a2.appendChild(_s2); container.textContent = ''; container.appendChild(_a2);
    } else {
      container.innerHTML = '<span class="text-muted small">音訊暫時無法載入</span>';
      if (btn) btn.disabled = false;
    }
  } catch {
    container.innerHTML = '<span class="text-danger small">音訊載入失敗</span>';
    if (btn) btn.disabled = false;
  }
}

// ── Recording ─────────────────────────────────────────────────────────────

function getState(qIndex) {
  if (!recorders[qIndex]) {
    recorders[qIndex] = new RecordingPanel({
      suffix: `_${qIndex}`,
      logTag: 'shadowing',
      maxSeconds: () => MAX_RECORDING_SECONDS,
      showAlert,
    });
  }
  return recorders[qIndex];
}

function startRetry(qIndex) {
  const vs = getView();
  const recorded = vs?.speaking1_questions?.find(q => q.index === qIndex);
  if (viewId || vs?.submitted_at || vs?.stage !== 5 || isPastDue()
      || !recorded || recorded.attempts >= workflowLimit('max_shadowing_attempts')) return;

  const block = document.getElementById(`qBlock_${qIndex}`);
  if (!block) return;
  // Append only to this question: rebuilding the page would discard other
  // questions' recording/preview controls and loaded model audio.
  if (!document.getElementById(`recordSection_${qIndex}`)) {
    block.insertAdjacentHTML('beforeend', renderRecordingSection(qIndex));
  }
  const recSection = document.getElementById(`recordSection_${qIndex}`);
  recSection.style.display = '';
  recSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function startRecording(qIndex) {
  await getState(qIndex).start();
}

async function stopRecording(qIndex) {
  await getState(qIndex).stop();
}

function showPreview(qIndex) {
  getState(qIndex).showPreview();
}

function reRecord(qIndex) {
  getState(qIndex).reset();
}

async function submitAudio(qIndex) {
  const st = getState(qIndex);
  if (!st.recordedAudio?.blob?.size) {
    showAlert('請先完成錄音再提交');
    return;
  }
  const previewEl = document.getElementById(`preview_${qIndex}`);
  st.setBusy(true);

  const { blob, filename } = st.recordedAudio;
  const formData = new FormData();
  formData.append('audio', blob, filename);
  formData.append('client_duration_ms', String(st.recordedAudio.durationMs));

  let res;
  let data;
  try {
    res = await fetch(`/api/student/submissions/${submission.id}/speaking1/${qIndex}`, {
      method: 'POST',
      credentials: 'include',
      body: formData,
    });
    data = await res.json();
  } catch (error) {
    st.setBusy(false);
    if (previewEl) previewEl.classList.remove('d-none');
    showAlert('送出失敗，請檢查網路後再試。錄音還在。');
    return;
  }
  st.setBusy(false);

  if (!res.ok) { showAlert(data.detail || '錄音處理失敗，請再試一次。'); return; }

  st.release();
  if (previewEl) previewEl.classList.add('d-none');

  // Update local submission state
  const questions = submission.speaking1_questions ? [...submission.speaking1_questions] : [];
  const existingIdx = questions.findIndex(q => q.index === qIndex);
  const entry = { index: qIndex, audio_key: data.audio_key, transcript: data.transcript, metrics: null, attempts: data.attempts };
  if (existingIdx >= 0) questions[existingIdx] = entry; else questions.push(entry);
  questions.sort((a, b) => a.index - b.index);
  submission.speaking1_questions = questions;

  if (data.all_done) {
    submission.stage = 6;
    showAlert('跟讀全部完成。', 'success');
  } else {
    showAlert(`Q${qIndex + 1} 已送出。`, 'success');
  }

  renderAll();

  // Auto-load TTS for the next question
  if (!data.all_done) {
    const nextIdx = questions.length;
    setTimeout(() => loadTtsAudio(nextIdx), 300);
  }
}

window.addEventListener('pagehide', () => {
  for (const recorder of Object.values(recorders)) recorder.release();
});

init().catch(error=>renderStudentPageLoadError(error));

Object.assign(window, {
  init,
  renderAll,
  renderSection2,
  loadTtsAudio,
  seekTtsCue,
  prepareTtsAudio,
  loadRecordingAudio,
  getState,
  startRetry,
  startRecording,
  stopRecording,
  showPreview,
  reRecord,
  submitAudio,
});
