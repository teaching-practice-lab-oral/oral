// Fullscreen/PWA shell and browser-level integrity controls for practice pages.
(function installStudentPracticeRuntime() {
  const assignmentMatch = location.pathname.match(/^\/student\/assignment\/(\d+)\//);
  if (!assignmentMatch) {
    window.practiceLaunchReady = Promise.resolve();
    return;
  }

  const assignmentId = Number(assignmentMatch[1]);
  const historicalView = new URLSearchParams(location.search).has('view');
  const appleTouchDevice = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const androidDevice = /Android/i.test(navigator.userAgent);
  const mobileDevice = appleTouchDevice || androidDevice;
  const standalone = window.matchMedia('(display-mode: standalone)').matches
    || navigator.standalone === true;
  const stageTestingMode = location.hostname.startsWith('dev-');
  const embeddedDesktopShell = isEmbeddedDesktopPracticePage();
  let contextPromise = null;
  let activeSubmission = null;
  let desktopPracticeFrame = null;
  let desktopShellLeaving = false;
  let fullscreenExitTimer = null;
  let hiddenTimer = null;
  let blurTimer = null;
  let lastPasteAt = 0;
  const inputSnapshots = new WeakMap();

  function never() { return new Promise(() => {}); }

  function assignmentContext() {
    if (!contextPromise) {
      contextPromise = (async () => {
        const response = await apiCall(`/api/student/assignments/${assignmentId}`);
        const data = await response.json().catch(() => ({}));
        return { response, data };
      })();
    }
    return contextPromise;
  }

  function pastDue(data) {
    const assignment = data.assignment || {};
    const submission = data.submission || {};
    if (!assignment.due_date) return false;
    const due = new Date(assignment.due_date);
    const late = submission.late_deadline ? new Date(submission.late_deadline) : null;
    const effective = late && late > due ? late : due;
    return new Date() > effective;
  }

  function isActiveContext(data) {
    if (historicalView || !data.assignment || pastDue(data)) return false;
    const submission = data.submission;
    if (!submission) return true;
    return !submission.submitted_at && Number(submission.stage) < 9;
  }

  function postEvent(eventType, details = null) {
    if (!activeSubmission) return;
    fetch(`/api/student/submissions/${activeSubmission.id}/proctor-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: eventType, page_path: location.pathname, details }),
      keepalive: true,
    }).catch(() => {});
  }

  async function recordPracticeStart(submission = activeSubmission) {
    if (!submission) return;
    const newlyAttached = !activeSubmission;
    activeSubmission = submission;
    if (embeddedDesktopShell) {
      window.parent.postMessage({
        type: 'desktop-practice-ready',
        submissionId: Number(submission.id),
      }, location.origin);
    }
    if (newlyAttached && embeddedDesktopShell) {
      postEvent('fullscreen_enter', { mode: 'desktop_shell' });
    } else if (newlyAttached && mobileDevice) {
      postEvent('fullscreen_enter', {
        mode: appleTouchDevice ? 'ios_pwa' : 'android_pwa',
        screen_width: screen.width,
        screen_height: screen.height,
      });
    }
    if (Number(submission.stage) >= 8) return;
    await apiCall(`/api/student/submissions/${submission.id}/practice/start`, {
      method: 'POST',
    }).catch(() => {});
  }

  function leaveDesktopPracticeShell(rawHref, replace = false) {
    let target;
    try { target = new URL(rawHref, window.location.href); } catch (_) { return; }
    if (!['http:', 'https:', 'mailto:', 'tel:'].includes(target.protocol)) return;
    desktopShellLeaving = true;
    const navigate = () => {
      if (replace) window.location.replace(target.href);
      else window.location.href = target.href;
    };
    if (document.fullscreenElement && document.exitFullscreen) {
      Promise.resolve(document.exitFullscreen()).catch(() => {}).finally(navigate);
    } else navigate();
  }

  function mountDesktopPracticeShell() {
    if (embeddedDesktopShell || desktopPracticeFrame) return;
    window.__desktopPracticeShell = true;
    const frame = document.createElement('iframe');
    desktopPracticeFrame = frame;
    frame.id = 'desktopPracticeFrame';
    frame.title = '全螢幕學習階段';
    frame.allow = 'microphone; autoplay';
    frame.style.cssText = 'position:fixed;inset:0;z-index:15000;width:100%;height:100%;border:0;background:#f8fafc';
    window.addEventListener('message', event => {
      if (event.origin !== location.origin || event.source !== frame.contentWindow) return;
      if (event.data?.type === 'desktop-practice-ready' && Number.isInteger(Number(event.data.submissionId))) {
        activeSubmission = { id: Number(event.data.submissionId) };
        return;
      }
      if (event.data?.type === 'desktop-practice-leave') {
        leaveDesktopPracticeShell(event.data.href, !!event.data.replace);
      }
    });
    frame.addEventListener('load', () => {
      try {
        const childLocation = frame.contentWindow.location;
        if (!STUDENT_PRACTICE_PATH.test(childLocation.pathname)) {
          leaveDesktopPracticeShell(childLocation.href);
          return;
        }
        history.replaceState(history.state, '', `${childLocation.pathname}${childLocation.search}${childLocation.hash}`);
        frame.contentWindow.focus();
      } catch (_) {}
    });
    frame.src = `${location.pathname}${location.search}${location.hash}`;
    document.body.appendChild(frame);
    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
  }

  function fullscreenGate(message) {
    let overlay = document.getElementById('practiceFullscreenGate');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'practiceFullscreenGate';
      overlay.style.cssText = 'position:fixed;inset:0;z-index:20000;background:rgba(15,23,42,.96);color:#fff;display:flex;align-items:center;justify-content:center;padding:1.5rem;text-align:center';
      overlay.innerHTML = `<div style="max-width:520px"><i class="bi bi-arrows-fullscreen" style="font-size:3rem;color:#a5b4fc"></i><h2 class="h4 fw-bold mt-3">全螢幕練習模式</h2><p id="practiceFullscreenMessage" style="color:#cbd5e1"></p><button id="practiceEnterFullscreen" type="button" class="btn btn-primary btn-lg"><i class="bi bi-arrows-fullscreen me-2"></i>進入全螢幕並繼續</button><p class="small mt-3 mb-0" style="color:#94a3b8">離開全螢幕、切換分頁及貼上文字會留下紀錄供老師複查。</p></div>`;
      document.body.appendChild(overlay);
      overlay.querySelector('#practiceEnterFullscreen').addEventListener('click', async () => {
        const button = overlay.querySelector('#practiceEnterFullscreen');
        button.disabled = true;
        try {
          if (!document.documentElement.requestFullscreen) throw new Error('unsupported');
          await document.documentElement.requestFullscreen();
          mountDesktopPracticeShell();
          overlay.style.display = 'none';
          postEvent('fullscreen_enter', { screen_width: screen.width, screen_height: screen.height });
        } catch (_) {
          overlay.querySelector('#practiceFullscreenMessage').textContent = '此瀏覽器無法啟用全螢幕。請改用最新版 Chrome、Edge 或 Firefox。';
        } finally { button.disabled = false; }
      });
    }
    overlay.querySelector('#practiceFullscreenMessage').textContent = message;
    overlay.style.display = 'flex';
  }

  function mobileInstallGate() {
    window.PWA_INSTALL_REQUIRED = true;
    if (document.getElementById('mobilePwaInstallPrompt')) return;
    const embeddedBrowser = /(Line|FBAN|FBAV|Instagram|Messenger)/i.test(navigator.userAgent);
    const deviceName = androidDevice ? 'Android 裝置' : 'iPhone／iPad';
    const steps = androidDevice
      ? '<li>使用 Chrome 點右上角選單，選擇「安裝應用程式」或「加到主畫面」。</li><li>安裝後回到主畫面。</li>'
      : '<li>使用 Safari 點選「分享」。</li><li>點擊「檢視較多」。</li><li>選擇「加到主畫面」，並保持「打開為網頁 App」開啟。</li>';
    const gate = document.createElement('div');
    gate.id = 'mobilePwaInstallGate';
    gate.setAttribute('role', 'dialog');
    gate.setAttribute('aria-modal', 'true');
    gate.style.cssText = 'position:fixed;inset:0;z-index:30000;background:#f8fafc;color:#0f172a;overflow:auto;padding:1.25rem;display:flex;align-items:center;justify-content:center';
    gate.innerHTML = `<div style="width:min(100%,560px);background:#fff;border:1px solid #cbd5e1;border-radius:20px;padding:1.4rem"><h1 class="h4 fw-bold">請從主畫面 Web App 開始練習</h1><p>${deviceName}必須先安裝本系統；完成前不會載入題目。</p>${embeddedBrowser ? '<div class="alert alert-warning">請改用 Safari 或 Chrome。</div>' : ''}<ol>${steps}<li>點「AI 英語面試」圖示重新進入。</li></ol></div>`;
    document.body.appendChild(gate);
  }

  function activateMobileLayout() {
    document.documentElement.classList.add('mobile-practice-app-mode');
    document.body.classList.add('mobile-practice-app-mode');
    if (!document.getElementById('mobilePracticeAppStyles')) {
      const style = document.createElement('style');
      style.id = 'mobilePracticeAppStyles';
      style.textContent = `
        html.mobile-practice-app-mode,body.mobile-practice-app-mode{min-height:100%;min-height:100dvh;overscroll-behavior-y:none;background:#f8fafc}
        body.mobile-practice-app-mode{padding-bottom:max(1rem,env(safe-area-inset-bottom))}
        body.mobile-practice-app-mode .navbar{position:sticky;top:0;z-index:1030}
      `;
      document.head.appendChild(style);
    }
  }

  function installInputAndFocusControls() {
    document.addEventListener('visibilitychange', () => {
      clearTimeout(hiddenTimer);
      if (!document.hidden || desktopPracticeFrame) return;
      hiddenTimer = setTimeout(() => postEvent('page_hidden'), 1200);
    });
    window.addEventListener('blur', () => {
      clearTimeout(blurTimer);
      blurTimer = setTimeout(() => {
        if (!document.hidden && !desktopPracticeFrame) postEvent('window_blur');
      }, 1200);
    });
    document.addEventListener('paste', event => {
      const target = event.target;
      if (!target?.matches?.('textarea,input,[contenteditable="true"]')) return;
      lastPasteAt = Date.now();
      if (stageTestingMode) return;
      event.preventDefault();
      const text = event.clipboardData?.getData('text') || '';
      postEvent('paste_blocked', { field_id: target.id || null, character_count: text.length });
      showAlert('練習期間不可貼上文字，請用自己的內容作答。');
    }, true);
    document.addEventListener('beforeinput', event => {
      if (Date.now() - lastPasteAt < 500) return;
      if (!event.target?.matches?.('textarea,input,[contenteditable="true"]')) return;
      const inserted = typeof event.data === 'string' ? event.data.length : 0;
      if (inserted >= 50) postEvent('large_input', { field_id: event.target.id || null, character_count: inserted });
    }, true);
    document.addEventListener('input', event => {
      const target = event.target;
      if (!target?.matches?.('textarea,input,[contenteditable="true"]')) return;
      const value = target.isContentEditable ? target.textContent || '' : target.value || '';
      const now = Date.now();
      const previous = inputSnapshots.get(target);
      if (previous && value.length - previous.length >= 80 && now - previous.at < 1000 && now - lastPasteAt >= 500) {
        postEvent('large_input', { field_id: target.id || null, character_count: value.length - previous.length });
      }
      inputSnapshots.set(target, { length: value.length, at: now });
    }, true);
  }

  async function bootstrap() {
    if (mobileDevice && !standalone) {
      mobileInstallGate();
      return never();
    }
    // A desktop top-level document is only a launcher. It never initializes
    // assignment business data; the iframe becomes the single page runtime.
    if (!historicalView && !embeddedDesktopShell && !stageTestingMode && !mobileDevice) {
    // if (!historicalView && !embeddedDesktopShell && !mobileDevice) {
      document.addEventListener('fullscreenchange', () => {
        clearTimeout(fullscreenExitTimer);
        if (document.fullscreenElement || desktopShellLeaving) return;
        fullscreenExitTimer = setTimeout(() => {
          postEvent('fullscreen_exit');
          fullscreenGate('偵測到已離開全螢幕，請重新進入後繼續。');
        }, 1200);
      });
      fullscreenGate('請進入全螢幕後開始或繼續作答。');
      return never();
    }
    const context = await assignmentContext();
    if (!context.response.ok || !isActiveContext(context.data)) return;
    activeSubmission = context.data.submission || null;
    if (embeddedDesktopShell || stageTestingMode || mobileDevice) {
      if (embeddedDesktopShell) postEvent('fullscreen_enter', { mode: 'desktop_shell' });
      if (mobileDevice) {
        activateMobileLayout();
        postEvent('fullscreen_enter', { mode: appleTouchDevice ? 'ios_pwa' : 'android_pwa', screen_width: screen.width, screen_height: screen.height });
      }
      await recordPracticeStart();
      installInputAndFocusControls();
      return;
    }
    return;
  }

  window.StudentPracticeRuntime = { assignmentContext, isActiveContext, recordPracticeStart };
  window.practiceLaunchReady = bootstrap();
})();
