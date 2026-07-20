const pathParts = window.location.pathname.split('/');
window.assignmentId = parseInt(pathParts[3]);
const urlParams = new URLSearchParams(window.location.search);
window.viewId = urlParams.get('view') ? parseInt(urlParams.get('view')) : null;

window.submission = null;
window.assignment = null;
window.viewedSubmission = null;

const recorderState = {};
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

function renderShadowingTaskGuide(vs, nextToRecord, total, allShadowingDone, answerText = '') {
  const state=viewId||allShadowingDone?'completed':isPastDue()?'read-only':'active';
  if(state!=='active')return renderTaskGuide({title:'跟讀階段已完成',progress:`跟讀錄音 ${Math.min(nextToRecord,total)}/${total} 題已提交`,next:'回看時，找出一個最想帶進角色扮演的調整，例如說清楚關鍵字或減少不自然停頓。',view:vs,state});
  return renderTaskGuide({
    title:`Q${nextToRecord+1}：先聽懂，再錄自己的版本`,
    progress:`跟讀錄音已提交 ${nextToRecord}/${total} 題`,
    actions:[
      '先播放示範音訊，從字幕找出 1–2 個最重要的字。',
      '再聽一次，留意重點字怎麼說，以及句子在哪裡停頓。',
      '錄完先回聽；若關鍵字不清楚或逐字稿漏字，放慢後再錄。',
    ],
    support:{title:`Q${nextToRecord+1} 的口說焦點`,items:[
      '先求關鍵字清楚、句子有停頓、速度穩定，一次只調整一件事。',
      '不用模仿母語者口音；重點是讓聽者容易理解。',
    ],html:learningScaffoldQuestionHtml(vs,nextToRecord,'shadowing',answerText)},
    checks:['整段回答都有錄到，沒有少念一大段。','關鍵字聽得清楚，速度沒有快到吃字。','我已回聽，並能指出這次調整的一個地方。'],
    next:nextToRecord+1<total?'提交後開放下一題。':'提交最後一題後，進入角色扮演，用同一批內容即席回答。',
    view:vs,
  });
}

function renderSection2(container, stage, isCompleted) {
  const allShadowingDone = stage >= 6 || isCompleted;
  const isLocked = stage < 5 && !isCompleted;

  const card = document.createElement('div');
  card.className = `section-card ${isLocked ? 'locked' : allShadowingDone ? 'completed' : 'active'}`;
  card.innerHTML = `
    <div class="section-header">
      <div class="section-icon"><i class="bi bi-mic-fill"></i></div>
      <div>
        <div class="section-title">口說練習一：跟讀</div>
        <div class="section-subtitle">Speaking Practice 1 — Shadowing</div>
      </div>
      ${allShadowingDone ? '<span class="ms-auto badge bg-white text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>完成</span>' : ''}
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

  const activeAnswer=finalAnswers[nextToRecord]&&finalAnswers[nextToRecord].text||'';
  body.innerHTML = `${renderShadowingTaskGuide(vs,nextToRecord,finalAnswers.length,allShadowingDone,activeAnswer)}<div id="questionBlocks"></div>`;

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
        <p class="fw-semibold mb-2 small" style="color:#64748b;"><i class="bi bi-volume-up me-1"></i>示範音訊 Model Audio</p>
        <div id="ttsBox_${i}">
          ${hasTts
            ? `<button class="btn btn-outline-primary-custom btn-sm" data-action="loadTtsAudio" data-args='[${i}]'>
                <i class="bi bi-play-circle me-1"></i>播放示範音訊
              </button>`
            : canPrepareTts
              ? `<button class="btn btn-outline-primary-custom btn-sm" data-action="prepareTtsAudio" data-args='[${i}]'><i class="bi bi-stars me-1"></i>產生示範音訊</button>`
              : `<span class="text-muted small"><i class="bi bi-volume-mute me-1"></i>沒有可播放的示範音訊</span>`}
        </div>
      </div>
      <p class="fw-semibold mb-1 small" style="color:#64748b;"><i class="bi bi-type me-1"></i>跟讀字幕 Subtitle — 請跟著朗讀</p>
      <div class="q-subtitle mb-3" id="subtitle_${i}">${escHtml(item.text || '')}</div>
      <p class="tts-sync-note d-none" id="ttsSyncNotice_${i}" role="status"></p>`;

    if (isDone) {
      const canRetry = !allShadowingDone && recorded.attempts < workflowLimit('max_shadowing_attempts') && !viewId && !isPastDue();
      const remainingRetries = Math.max(0, workflowLimit('max_shadowing_attempts') - recorded.attempts);
      html += `
        <div class="mb-3">
          <p class="fw-semibold mb-2 small" style="color:#059669;"><i class="bi bi-mic me-1"></i>你的錄音</p>
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
            <p class="fw-semibold mb-1 small" style="color:#475569;"><i class="bi bi-chat-text me-1"></i>語音辨識結果</p>
            <div class="feedback-box"><pre>${escHtml(recorded.transcript)}</pre></div>
          </div>` : ''}
        ${canRetry
          ? `<div class="alert alert-info py-2 mb-0 small"><i class="bi bi-arrow-repeat me-1"></i>您還有 <strong>${remainingRetries} 次</strong> 重新錄音機會。</div>`
          : ''}`;
    }

    if ((isActive || (!isDone && !allShadowingDone && i === nextToRecord)) && !isPastDue()) {
      html += `
        <div id="recordSection_${i}">
          <p class="fw-semibold mb-2 small" style="color:#ef4444;"><i class="bi bi-mic me-1"></i>錄製跟讀 Record Shadowing</p>
          <p class="text-muted small mb-3">最長 5 分鐘 / Max 5 minutes</p>
          <div class="d-flex align-items-center gap-3 mb-3 flex-wrap">
            <button class="btn btn-record" id="recordBtn_${i}" data-action="startRecording" data-args='[${i}]'>
              <i class="bi bi-record-circle me-1"></i>開始錄音
            </button>
            <button class="btn btn-stop d-none" id="stopBtn_${i}" data-action="stopRecording" data-args='[${i}]'>
              <i class="bi bi-stop-circle me-1"></i>停止
            </button>
            <span class="timer-display d-none" id="timer_${i}">0:00</span>
          </div>
          <div id="status_${i}" class="text-muted small mb-2"></div>
          <div id="preview_${i}" class="d-none mb-3">
            <p class="fw-semibold mb-2" style="color:#10b981"><i class="bi bi-play-circle me-1"></i>錄音預覽，確認後再提交</p>
            <audio id="previewAudio_${i}" controls class="d-block mb-3" style="max-width:400px"></audio>
            <div class="d-flex gap-2">
              <button class="btn btn-outline-secondary btn-sm" data-action="reRecord" data-args='[${i}]'>
                <i class="bi bi-arrow-repeat me-1"></i>重錄
              </button>
              <button class="btn btn-success-custom btn-sm" data-action="submitAudio" data-args='[${i}]'>
                <i class="bi bi-send me-1"></i>確認提交
              </button>
            </div>
          </div>
          <div id="spinner_${i}" class="d-none processing-overlay">
            <div class="spinner-border text-primary"></div>
            <span>音訊處理中，請稍候... Processing audio...</span>
          </div>
        </div>`;
    }

    qBlock.innerHTML = html;
    blocksContainer.appendChild(qBlock);
  });
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
    box.innerHTML = `<button class="btn btn-outline-primary-custom btn-sm" data-action="loadTtsAudio" data-args='[${qIndex}]'><i class="bi bi-arrow-clockwise me-1"></i>重試載入</button><button class="btn btn-outline-danger btn-sm ms-2" data-action="prepareTtsAudio" data-args='[${qIndex},true]'><i class="bi bi-stars me-1"></i>重新產生音訊</button>`;
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
  if (!recorderState[qIndex]) recorderState[qIndex] = { chunks: [], seconds: 0, pendingURL: null, timerInterval: null };
  return recorderState[qIndex];
}

function startRetry(qIndex) {
  const block = document.getElementById(`qBlock_${qIndex}`);
  if (!block) return;
  const recSection = document.getElementById(`recordSection_${qIndex}`);
  if (recSection) { recSection.style.display = ''; return; }
  renderAll();
}

async function startRecording(qIndex) {
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
    const st = getState(qIndex);
    st.chunks = [];
    st.seconds = 0;

    const mr = new MediaRecorder(stream);
    st.mediaRecorder = mr;
    mr.ondataavailable = e => { if (e.data.size > 0) st.chunks.push(e.data); };
    mr.onstop = () => showPreview(qIndex);
    // Let the browser finalize one complete native audio container on stop.
    // This is especially important for Safari's MP4 output.
    mr.start();

    document.getElementById(`recordBtn_${qIndex}`).classList.add('d-none');
    document.getElementById(`stopBtn_${qIndex}`).classList.remove('d-none');
    document.getElementById(`timer_${qIndex}`).classList.remove('d-none');
    const statusEl = document.getElementById(`status_${qIndex}`);
    if (statusEl) statusEl.textContent = '錄音中... Recording...';

    st.timerInterval = setInterval(() => {
      st.seconds++;
      const m = Math.floor(st.seconds / 60);
      const s = st.seconds % 60;
      const timerEl = document.getElementById(`timer_${qIndex}`);
      if (timerEl) timerEl.textContent = `${m}:${s.toString().padStart(2, '0')}`;
      if (st.seconds >= MAX_RECORDING_SECONDS) stopRecording(qIndex);
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

function stopRecording(qIndex) {
  const st = getState(qIndex);
  if (st.mediaRecorder && st.mediaRecorder.state !== 'inactive') {
    st.mediaRecorder.stop();
    st.mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
  clearInterval(st.timerInterval);
  const stopBtn = document.getElementById(`stopBtn_${qIndex}`);
  const timerEl = document.getElementById(`timer_${qIndex}`);
  if (stopBtn) stopBtn.classList.add('d-none');
  if (timerEl) timerEl.classList.add('d-none');
  const statusEl = document.getElementById(`status_${qIndex}`);
  if (statusEl) statusEl.textContent = '錄音完成，可先預覽再提交。 Recording complete.';
}

function showPreview(qIndex) {
  const st = getState(qIndex);
  if (st.chunks.length === 0) { reRecord(qIndex); return; }
  const { blob } = buildRecordedAudio(st.chunks, st.mediaRecorder);
  if (st.pendingURL) URL.revokeObjectURL(st.pendingURL);
  st.pendingURL = URL.createObjectURL(blob);
  const previewAudio = document.getElementById(`previewAudio_${qIndex}`);
  setAudioPreview(previewAudio, st.pendingURL);
  const previewEl = document.getElementById(`preview_${qIndex}`);
  if (previewEl) previewEl.classList.remove('d-none');
}

function reRecord(qIndex) {
  const st = getState(qIndex);
  if (st.pendingURL) { URL.revokeObjectURL(st.pendingURL); st.pendingURL = null; }
  st.chunks = [];
  const previewEl = document.getElementById(`preview_${qIndex}`);
  const recordBtn = document.getElementById(`recordBtn_${qIndex}`);
  if (previewEl) previewEl.classList.add('d-none');
  if (recordBtn) recordBtn.classList.remove('d-none');
}

async function submitAudio(qIndex) {
  const st = getState(qIndex);
  if (!st.chunks || st.chunks.length === 0) {
    showAlert('請先完成錄音再提交');
    return;
  }
  const previewEl = document.getElementById(`preview_${qIndex}`);
  const spinnerEl = document.getElementById(`spinner_${qIndex}`);
  if (spinnerEl) spinnerEl.classList.remove('d-none');

  const { blob, filename } = buildRecordedAudio(st.chunks, st.mediaRecorder);
  const formData = new FormData();
  formData.append('audio', blob, filename);

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
    if (spinnerEl) spinnerEl.classList.add('d-none');
    if (previewEl) previewEl.classList.remove('d-none');
    showAlert('無法送出錄音，請檢查網路後再試一次。');
    return;
  }
  if (spinnerEl) spinnerEl.classList.add('d-none');

  if (!res.ok) { showAlert(data.detail || '音訊處理時發生錯誤'); return; }

  if (st.pendingURL) { URL.revokeObjectURL(st.pendingURL); st.pendingURL = null; }
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
    showAlert('所有題目跟讀錄音已提交完成！', 'success');
  } else {
    showAlert(`Q${qIndex + 1} 錄音已提交！請繼續完成下一題。`, 'success');
  }

  renderAll();

  // Auto-load TTS for the next question
  if (!data.all_done) {
    const nextIdx = questions.length;
    setTimeout(() => loadTtsAudio(nextIdx), 300);
  }
}

init().catch(error=>renderStudentPageLoadError(error));

Object.assign(window, {
  init,
  renderAll,
  renderShadowingTaskGuide,
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
