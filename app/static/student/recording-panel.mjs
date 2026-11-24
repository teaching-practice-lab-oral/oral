// Record → preview → re-record controls shared by roleplay and shadowing.
//
// Each page owns what happens on submit; this module owns the microphone,
// timer, preview and button states, so a browser fix lands in one place.
import {
  AudioRecordingSession,
  RecordedAudioPreview,
} from '/static/student/audio-session.mjs';

export function microphoneUnavailableMessage() {
  if (!window.isSecureContext) {
    return '麥克風只能在 https:// 網址下使用，請確認網址後再試。';
  }
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== 'function'
      || typeof window.MediaRecorder !== 'function') {
    return '這個瀏覽器不支援錄音，請改用最新版的 Chrome、Edge 或 Safari。';
  }
  return null;
}

export function microphoneErrorMessage(err) {
  switch (err?.name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return '沒有麥克風權限。請點網址列左側的鎖頭，允許使用麥克風後重新整理。';
    case 'NotFoundError':
      return '找不到麥克風，請確認已接上後再試。';
    case 'NotReadableError':
      return '麥克風正被其他程式使用，請先關閉那個程式。';
    default:
      return `無法使用麥克風（${err?.name || '未知錯誤'}）。`;
  }
}

function formatClock(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// `suffix` keeps element ids unique per panel (e.g. "Rp" or "_2");
// `args` is the JSON placed in data-args for the page's action handlers.
export function renderRecordingControls({ suffix, args = null }) {
  const dataArgs = args === null ? '' : ` data-args='${JSON.stringify(args)}'`;
  return `
          <div class="d-flex align-items-center gap-3 mb-3 flex-wrap">
            <button class="btn btn-record" id="recordBtn${suffix}" data-action="startRecording"${dataArgs}>
              <i class="bi bi-record-circle me-1"></i>開始錄音
            </button>
            <button class="btn btn-stop d-none" id="stopBtn${suffix}" data-action="stopRecording"${dataArgs}>
              <i class="bi bi-stop-circle me-1"></i>停止
            </button>
            <span class="timer-display d-none" id="timer${suffix}">0:00</span>
          </div>
          <div id="status${suffix}" class="text-muted small mb-2"></div>
          <div id="preview${suffix}" class="d-none mb-3">
            <p class="fw-semibold mb-2 recording-preview-title"><i class="bi bi-play-circle me-1"></i>先聽一次，沒問題再送出</p>
            <audio id="previewAudio${suffix}" controls class="d-block mb-3 recording-preview-audio"></audio>
            <div id="previewFallback${suffix}" class="d-none mb-3">
              <button type="button" class="btn btn-outline-primary-custom btn-sm me-2" id="previewPlayBtn${suffix}" aria-label="播放錄音">播放錄音</button>
              <span class="small text-muted" id="previewDuration${suffix}"></span>
            </div>
            <div id="previewError${suffix}" class="alert alert-warning py-2 small d-none">這台裝置無法播放預覽，但錄音已完成。可以直接送出，或重錄一次。</div>
            <div class="d-flex gap-2">
              <button class="btn btn-outline-secondary btn-sm" data-action="reRecord"${dataArgs}>
                <i class="bi bi-arrow-repeat me-1"></i>重錄
              </button>
              <button class="btn btn-success-custom btn-sm" data-action="submitAudio"${dataArgs}>
                送出
              </button>
            </div>
          </div>
          <div id="spinner${suffix}" class="d-none processing-overlay">
            <div class="spinner-border text-primary"></div>
            <span>正在處理錄音…</span>
          </div>`;
}

export class RecordingPanel {
  constructor({ suffix, logTag, maxSeconds, showAlert, onBeforeStart = null }) {
    this.suffix = suffix;
    this.logTag = logTag;
    this.maxSeconds = maxSeconds;
    this.showAlert = showAlert;
    this.onBeforeStart = onBeforeStart;
    this.session = null;
    this.recordedAudio = null;
    this.pendingURL = null;
    this.timerInterval = null;
    this.previewController = null;
    this.meta = {};
  }

  el(name) {
    return document.getElementById(`${name}${this.suffix}`);
  }

  setStatus(text) {
    const status = this.el('status');
    if (status) status.textContent = text;
  }

  // Resolves true once recording has started. `meta` (e.g. the question the
  // recording answers) is captured now and attached to the finished
  // recording, so a later progress change — or the automatic stop at the time
  // limit — cannot rebind it.
  async start(meta = {}) {
    const unavailable = microphoneUnavailableMessage();
    if (unavailable) {
      this.showAlert(unavailable);
      return false;
    }
    let stream = null;
    try {
      this.onBeforeStart?.();
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.session?.dispose();
      const session = new AudioRecordingSession(stream, {
        onError: error => this.recover(error, session),
      });
      this.session = session;
      this.recordedAudio = null;
      this.meta = { ...meta };
      session.start();

      this.el('recordBtn')?.classList.add('d-none');
      const stopButton = this.el('stopBtn');
      if (stopButton) {
        stopButton.disabled = false;
        stopButton.classList.remove('d-none');
      }
      this.el('timer')?.classList.remove('d-none');
      this.setStatus('錄音中');

      const limit = this.maxSeconds();
      clearInterval(this.timerInterval);
      this.timerInterval = setInterval(() => {
        const seconds = Math.floor(session.elapsedMilliseconds() / 1000);
        const timer = this.el('timer');
        if (timer) timer.textContent = formatClock(seconds);
        if (seconds >= limit) this.stop();
      }, 1000);
      return true;
    } catch (err) {
      for (const track of stream?.getTracks?.() || []) track.stop();
      this.showAlert(microphoneErrorMessage(err));
      return false;
    }
  }

  // Resolves to the recording, or null when it failed or was superseded.
  async stop() {
    const session = this.session;
    if (!session || !['recording', 'finalizing'].includes(session.state)) return null;
    clearInterval(this.timerInterval);
    const stopButton = this.el('stopBtn');
    if (stopButton) { stopButton.disabled = true; stopButton.classList.add('d-none'); }
    this.el('timer')?.classList.add('d-none');
    this.setStatus('正在整理錄音…');
    try {
      const result = await session.stop();
      if (this.session !== session) return null;
      this.recordedAudio = { ...result, ...this.meta };
      this.showPreview();
      return this.recordedAudio;
    } catch (error) {
      if (this.session !== session) return null;
      this.recover(error, session);
      return null;
    }
  }

  showPreview() {
    if (!this.recordedAudio?.blob?.size) { this.reset(); return; }
    if (this.pendingURL) URL.revokeObjectURL(this.pendingURL);
    this.pendingURL = URL.createObjectURL(this.recordedAudio.blob);
    this.el('preview')?.classList.remove('d-none');
    this.setStatus('錄好了。');
    const previewError = this.el('previewError');
    this.previewController?.dispose();
    this.previewController = new RecordedAudioPreview(this.el('previewAudio'), {
      fallbackContainer: this.el('previewFallback'),
      playButton: this.el('previewPlayBtn'),
      durationLabel: this.el('previewDuration'),
      onError: () => {
        console.warn(`[audio-recorder:${this.logTag}-preview-failed]`);
        previewError?.classList.remove('d-none');
      },
    }).mount(this.pendingURL, this.recordedAudio.durationMs);
  }

  recover(error, session = this.session) {
    if (session && this.session !== session) return;
    clearInterval(this.timerInterval);
    this.recordedAudio = null;
    this.el('stopBtn')?.classList.add('d-none');
    this.el('timer')?.classList.add('d-none');
    this.el('recordBtn')?.classList.remove('d-none');
    const message = error?.message || '錄音失敗，請再錄一次。';
    this.setStatus(message);
    console.warn(`[audio-recorder:${this.logTag}-${error?.code || 'unknown'}]`);
    this.showAlert(message);
  }

  // Drop the current recording and show the record button again.
  reset() {
    this.release();
    this.el('preview')?.classList.add('d-none');
    this.el('previewError')?.classList.add('d-none');
    this.el('recordBtn')?.classList.remove('d-none');
    this.setStatus('');
  }

  // Free the microphone, timer and object URL without touching the DOM.
  release() {
    clearInterval(this.timerInterval);
    this.timerInterval = null;
    this.previewController?.dispose();
    this.previewController = null;
    const session = this.session;
    this.session = null;
    session?.dispose();
    this.recordedAudio = null;
    this.meta = {};
    if (this.pendingURL) { URL.revokeObjectURL(this.pendingURL); this.pendingURL = null; }
  }

  isRecording() {
    return Boolean(this.session && ['recording', 'finalizing'].includes(this.session.state));
  }

  setBusy(busy) {
    this.el('spinner')?.classList.toggle('d-none', !busy);
  }
}
