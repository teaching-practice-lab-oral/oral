// Owns word-level TTS subtitle rendering, seeking, and playback highlighting.
(function installTtsSubtitleController() {
  class TtsSubtitleController {
    constructor() { this.states = {}; }

    disposeAll() {
      Object.keys(this.states).forEach(questionIndex => this.dispose(questionIndex));
    }

    dispose(questionIndex) {
      const state = this.states[questionIndex];
      if (!state) return;
      if (state.frameId) cancelAnimationFrame(state.frameId);
      state.audio.pause();
      Object.entries(state.handlers).forEach(([eventName, handler]) => {
        state.audio.removeEventListener(eventName, handler);
      });
      delete this.states[questionIndex];
    }

    setActive(questionIndex, activeIndex) {
      const state = this.states[questionIndex];
      if (!state || state.activeIndex === activeIndex) return;
      state.activeIndex = activeIndex;
      state.elements.forEach((element, index) => {
        element.classList.toggle('is-active', index === activeIndex);
        element.classList.toggle('is-past', activeIndex >= 0 && index < activeIndex);
        element.setAttribute('aria-current', index === activeIndex ? 'true' : 'false');
      });
    }

    update(questionIndex) {
      const state = this.states[questionIndex];
      if (!state) return;
      const currentTime = state.audio.currentTime;
      let low = 0;
      let high = state.cues.length - 1;
      let activeIndex = -1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        if (state.cues[middle].start <= currentTime) {
          activeIndex = middle;
          low = middle + 1;
        } else high = middle - 1;
      }
      // Clear the highlight between cues instead of carrying the prior word.
      if (activeIndex >= 0 && currentTime >= state.cues[activeIndex].end) activeIndex = -1;
      this.setActive(questionIndex, activeIndex);
    }

    startLoop(questionIndex) {
      const state = this.states[questionIndex];
      if (!state) return;
      if (state.frameId) cancelAnimationFrame(state.frameId);
      const tick = () => {
        const current = this.states[questionIndex];
        if (!current) return;
        this.update(questionIndex);
        current.frameId = (!current.audio.paused && !current.audio.ended)
          ? requestAnimationFrame(tick)
          : null;
      };
      state.frameId = requestAnimationFrame(tick);
    }

    setup(questionIndex, audio, rawCues) {
      const subtitle = document.getElementById(`subtitle_${questionIndex}`);
      const notice = document.getElementById(`ttsSyncNotice_${questionIndex}`);
      if (!subtitle) return;
      const originalText = subtitle.textContent;
      const cues = Array.isArray(rawCues) ? rawCues.filter(cue => (
        cue && typeof cue.text === 'string' && cue.text
        && Number.isFinite(cue.start) && Number.isFinite(cue.end)
        && cue.start >= 0 && cue.end > cue.start
      )) : [];
      if (!cues.length || cues.map(cue => cue.text).join('') !== originalText) {
        this.showNotice(notice, '這份舊音訊沒有逐字同步資料，仍可正常播放。');
        return;
      }

      subtitle.textContent = '';
      subtitle.classList.add('sync-ready');
      const elements = [];
      cues.forEach((cue, cueIndex) => {
        const leading = cue.text.match(/^\s*/)?.[0] || '';
        const trailing = cue.text.match(/\s*$/)?.[0] || '';
        const core = cue.text.slice(leading.length, cue.text.length - trailing.length);
        if (leading) subtitle.appendChild(document.createTextNode(leading));
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'tts-word';
        button.textContent = core;
        button.dataset.action = 'seekTtsCue';
        button.dataset.args = JSON.stringify([questionIndex, cueIndex]);
        button.setAttribute('aria-label', `從「${core.trim()}」開始播放`);
        button.setAttribute('aria-current', 'false');
        button.title = '從這個字開始播放';
        subtitle.appendChild(button);
        if (trailing) subtitle.appendChild(document.createTextNode(trailing));
        elements.push(button);
      });
      if (notice) notice.classList.add('d-none');
      const handlers = {
        play: () => this.startLoop(questionIndex),
        pause: () => {
          const state = this.states[questionIndex];
          if (state?.frameId) cancelAnimationFrame(state.frameId);
          if (state) state.frameId = null;
          this.update(questionIndex);
        },
        seeked: () => this.update(questionIndex),
        timeupdate: () => this.update(questionIndex),
        ended: () => this.setActive(questionIndex, -1),
      };
      this.states[questionIndex] = { audio, cues, elements, handlers, activeIndex: -1, frameId: null };
      Object.entries(handlers).forEach(([eventName, handler]) => audio.addEventListener(eventName, handler));
    }

    seek(questionIndex, cueIndex) {
      const state = this.states[questionIndex];
      const cue = state?.cues?.[cueIndex];
      if (!state || !cue) return;
      const notice = document.getElementById(`ttsSyncNotice_${questionIndex}`);
      const seekAndPlay = () => {
        try {
          state.audio.currentTime = cue.start;
          this.update(questionIndex);
          const result = state.audio.play();
          if (result?.catch) result.catch(() => this.showNotice(notice, '瀏覽器暫時無法自動播放，請按播放器的播放鍵。'));
        } catch (_) {
          this.showNotice(notice, '音訊尚未載入完成，請稍後再點一次。');
        }
      };
      if (state.audio.readyState === 0) {
        state.audio.addEventListener('loadedmetadata', seekAndPlay, { once: true });
        state.audio.load();
      } else seekAndPlay();
    }

    showNotice(element, message) {
      if (!element) return;
      element.textContent = message;
      element.classList.remove('d-none');
    }
  }

  window.TtsSubtitleController = TtsSubtitleController;
})();
