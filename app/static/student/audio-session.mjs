const DEFAULT_FINALIZE_TIMEOUT_MS = 10_000;
const DURATION_TOLERANCE_SECONDS = 5;
const DURATION_TOLERANCE_RATIO = 0.2;

function defaultNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

export class AudioRecordingError extends Error {
  constructor(code, message, cause = null) {
    super(message);
    this.name = 'AudioRecordingError';
    this.code = code;
    this.cause = cause;
  }
}

export function buildRecordedAudio(chunks, mediaRecorder) {
  const usableChunks = (chunks || []).filter(chunk => chunk && chunk.size > 0);
  const chunkWithType = usableChunks.find(chunk => chunk.type);
  const mimeType = (mediaRecorder && mediaRecorder.mimeType)
    || (chunkWithType && chunkWithType.type)
    || 'audio/webm';
  const normalizedType = mimeType.split(';', 1)[0].toLowerCase();
  const extensions = {
    'audio/mp4': 'm4a',
    'video/mp4': 'mp4',
    'audio/ogg': 'ogg',
    'audio/webm': 'webm',
  };
  return {
    blob: new Blob(usableChunks, { type: mimeType }),
    filename: `recording.${extensions[normalizedType] || 'audio'}`,
  };
}

export function formatRecordingDuration(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs) / 1000) || 0);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

export function hasSuspiciousMediaDuration(mediaDurationSeconds, recordedDurationMs) {
  const recordedSeconds = Number(recordedDurationMs) / 1000;
  if (!Number.isFinite(mediaDurationSeconds) || mediaDurationSeconds <= 0) return true;
  if (!Number.isFinite(recordedSeconds) || recordedSeconds <= 0) return true;
  return Math.abs(mediaDurationSeconds - recordedSeconds)
    > Math.max(DURATION_TOLERANCE_SECONDS, recordedSeconds * DURATION_TOLERANCE_RATIO);
}

function stopStreamTracks(stream) {
  try {
    for (const track of stream?.getTracks?.() || []) track.stop();
  } catch (error) {
    console.warn('[audio-recorder:track-stop-failed]', error?.name || 'unknown');
  }
}

/**
 * One recording attempt. The instance is intentionally single-use so a late
 * Safari event from an old attempt cannot mutate the next attempt's chunks.
 */
export class AudioRecordingSession {
  constructor(stream, {
    MediaRecorderClass = globalThis.MediaRecorder,
    finalizeTimeoutMs = DEFAULT_FINALIZE_TIMEOUT_MS,
    setTimeoutFn = globalThis.setTimeout.bind(globalThis),
    clearTimeoutFn = globalThis.clearTimeout.bind(globalThis),
    nowFn = defaultNow,
    onError = null,
  } = {}) {
    if (!stream) throw new AudioRecordingError('missing_stream', '找不到麥克風串流。');
    if (typeof MediaRecorderClass !== 'function') {
      throw new AudioRecordingError('unsupported', '此瀏覽器不支援錄音功能。');
    }
    this.stream = stream;
    this.recorder = new MediaRecorderClass(stream);
    this.finalizeTimeoutMs = finalizeTimeoutMs;
    this.setTimeoutFn = setTimeoutFn;
    this.clearTimeoutFn = clearTimeoutFn;
    this.nowFn = nowFn;
    this.onError = typeof onError === 'function' ? onError : null;
    this.chunks = [];
    this.state = 'idle';
    this.result = null;
    this.stopPromise = null;
    this.finalizeTimer = null;
    this.resolveStop = null;
    this.rejectStop = null;
    this.stopEventReceived = false;
    this.startedAtMs = null;
    this.stoppedAtMs = null;

    this.recorder.ondataavailable = event => {
      if (event?.data?.size > 0 && this.state !== 'disposed') {
        this.chunks.push(event.data);
        if (this.state === 'finalizing' && this.stopEventReceived) this.finish('stop');
      }
    };
    this.recorder.onstop = () => {
      this.stopEventReceived = true;
      if (this.hasAudioData()) this.finish('stop');
    };
    this.recorder.onerror = event => {
      const cause = event?.error || event;
      this.fail(new AudioRecordingError(
        'recorder_error',
        '錄音處理失敗，請重新錄音。',
        cause,
      ));
    };
  }

  start() {
    if (this.state !== 'idle') {
      throw new AudioRecordingError('invalid_state', '錄音工作階段已經開始。');
    }
    this.chunks = [];
    this.stopEventReceived = false;
    this.startedAtMs = this.nowFn();
    this.stoppedAtMs = null;
    this.state = 'recording';
    try {
      this.recorder.start();
    } catch (error) {
      stopStreamTracks(this.stream);
      this.state = 'failed';
      throw new AudioRecordingError('start_failed', '開始錄音失敗，請重新嘗試。', error);
    }
    return this;
  }

  stop() {
    if (this.state === 'ready') return Promise.resolve(this.result);
    if (this.state === 'finalizing' && this.stopPromise) return this.stopPromise;
    if (this.state !== 'recording') {
      return Promise.reject(new AudioRecordingError('invalid_state', '目前沒有可停止的錄音。'));
    }

    this.stoppedAtMs = this.nowFn();
    this.state = 'finalizing';
    this.stopPromise = new Promise((resolve, reject) => {
      this.resolveStop = resolve;
      this.rejectStop = reject;
    });
    this.finalizeTimer = this.setTimeoutFn(() => {
      console.warn('[audio-recorder:finalize-timeout]');
      if (this.hasAudioData()) this.finish('timeout');
      else this.fail(new AudioRecordingError(
        'finalize_timeout',
        '沒有取得錄音內容，請重新錄音。',
      ));
    }, this.finalizeTimeoutMs);

    try {
      this.recorder.stop();
    } catch (error) {
      this.fail(new AudioRecordingError('stop_failed', '停止錄音失敗，請重新錄音。', error));
    }
    return this.stopPromise;
  }

  hasAudioData() {
    return this.chunks.some(chunk => chunk && chunk.size > 0);
  }

  elapsedMilliseconds() {
    if (this.startedAtMs === null) return 0;
    const end = this.stoppedAtMs ?? this.nowFn();
    return Math.max(0, Math.round(end - this.startedAtMs));
  }

  finish(source = 'stop') {
    if (this.state !== 'finalizing') return;
    if (!this.hasAudioData()) {
      this.fail(new AudioRecordingError('empty_recording', '沒有取得錄音內容，請重新錄音。'));
      return;
    }
    this.clearFinalizeTimer();
    stopStreamTracks(this.stream);
    const recordedAudio = buildRecordedAudio(this.chunks, this.recorder);
    if (!recordedAudio.blob.size) {
      this.fail(new AudioRecordingError('empty_recording', '沒有取得錄音內容，請重新錄音。'));
      return;
    }
    this.result = {
      ...recordedAudio,
      source,
      durationMs: this.elapsedMilliseconds(),
    };
    this.state = 'ready';
    this.resolveStop?.(this.result);
    this.clearPromiseHandlers();
  }

  fail(error) {
    if (['ready', 'failed', 'disposed'].includes(this.state)) return;
    const wasFinalizing = this.state === 'finalizing';
    this.clearFinalizeTimer();
    stopStreamTracks(this.stream);
    this.state = 'failed';
    this.rejectStop?.(error);
    this.clearPromiseHandlers();
    if (!wasFinalizing) this.onError?.(error);
  }

  dispose() {
    if (this.state === 'disposed') return;
    this.clearFinalizeTimer();
    try {
      if (this.recorder.state !== 'inactive') this.recorder.stop();
    } catch (_) {}
    stopStreamTracks(this.stream);
    if (this.state === 'finalizing') {
      this.rejectStop?.(new AudioRecordingError('disposed', '錄音工作階段已結束。'));
    }
    this.clearPromiseHandlers();
    this.state = 'disposed';
  }

  clearFinalizeTimer() {
    if (this.finalizeTimer !== null) this.clearTimeoutFn(this.finalizeTimer);
    this.finalizeTimer = null;
  }

  clearPromiseHandlers() {
    this.resolveStop = null;
    this.rejectStop = null;
  }
}

/**
 * Keeps the native player for normal files and replaces it with a minimal,
 * measured-duration player when browser container metadata is implausible.
 */
export class RecordedAudioPreview {
  constructor(audio, {
    fallbackContainer,
    playButton,
    durationLabel,
    onError = null,
  } = {}) {
    this.audio = audio;
    this.fallbackContainer = fallbackContainer;
    this.playButton = playButton;
    this.durationLabel = durationLabel;
    this.onError = typeof onError === 'function' ? onError : null;
    this.listeners = [];
    this.errorReported = false;
    this.usingFallback = false;
  }

  listen(target, eventName, handler) {
    if (!target?.addEventListener) return;
    target.addEventListener(eventName, handler);
    this.listeners.push([target, eventName, handler]);
  }

  mount(url, durationMs) {
    if (!this.audio) return this;
    this.durationMs = Math.max(0, Math.round(Number(durationMs) || 0));
    this.audio.controls = true;
    this.audio.classList?.remove('d-none');
    this.fallbackContainer?.classList?.add('d-none');
    if (this.durationLabel) {
      this.durationLabel.textContent = `實際錄音時間 ${formatRecordingDuration(this.durationMs)}`;
    }

    this.listen(this.audio, 'loadedmetadata', () => {
      if (hasSuspiciousMediaDuration(this.audio.duration, this.durationMs)) {
        this.showFallback();
      }
    });
    this.listen(this.audio, 'play', () => this.setPlaying(true));
    this.listen(this.audio, 'pause', () => this.setPlaying(false));
    this.listen(this.audio, 'ended', () => this.setPlaying(false));
    this.listen(this.audio, 'error', () => this.reportError());
    this.listen(this.playButton, 'click', () => this.togglePlayback());

    this.audio.src = url;
    try {
      this.audio.load();
    } catch (_) {
      this.reportError();
    }
    return this;
  }

  showFallback() {
    this.usingFallback = true;
    this.audio.controls = false;
    this.audio.classList?.add('d-none');
    this.fallbackContainer?.classList?.remove('d-none');
    this.setPlaying(false);
  }

  setPlaying(isPlaying) {
    if (!this.playButton) return;
    this.playButton.textContent = isPlaying ? '暫停錄音' : '播放錄音';
    this.playButton.setAttribute?.('aria-label', this.playButton.textContent);
  }

  async togglePlayback() {
    if (!this.audio) return;
    try {
      if (this.audio.paused || this.audio.ended) await this.audio.play();
      else this.audio.pause();
    } catch (_) {
      this.reportError();
    }
  }

  reportError() {
    if (this.errorReported) return;
    this.errorReported = true;
    this.onError?.();
  }

  dispose() {
    for (const [target, eventName, handler] of this.listeners) {
      target.removeEventListener?.(eventName, handler);
    }
    this.listeners = [];
    try { this.audio?.pause?.(); } catch (_) {}
    if (this.audio) {
      this.audio.removeAttribute?.('src');
      try { this.audio.load?.(); } catch (_) {}
    }
    this.fallbackContainer?.classList?.add('d-none');
    this.usingFallback = false;
  }
}

export function isAutoplayBlocked(error) {
  return error?.name === 'NotAllowedError' || error?.name === 'AbortError';
}

export async function prepareAudioElement(loadUrl, {
  createAudio = url => {
    const audio = document.createElement('audio');
    audio.src = url;
    return audio;
  },
} = {}) {
  const url = await loadUrl();
  if (!url) throw new Error('missing_audio_url');
  return createAudio(url);
}

export async function attemptAudioPlayback(audio) {
  try {
    await audio.play();
    return { status: 'playing', error: null };
  } catch (error) {
    return {
      status: isAutoplayBlocked(error) ? 'blocked' : 'failed',
      error,
    };
  }
}
