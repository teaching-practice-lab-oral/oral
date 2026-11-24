if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  });
}

(function showMobileInstallPrompt() {
  const userAgent = navigator.userAgent;
  const isLineBrowser = /Line\//i.test(userAgent);
  if (isLineBrowser) {
    const externalBrowserUrl = new URL(window.location.href);
    if (externalBrowserUrl.searchParams.get('openExternalBrowser') !== '1') {
      externalBrowserUrl.searchParams.set('openExternalBrowser', '1');
      window.location.replace(externalBrowserUrl.toString());
      return;
    }
  }

  const isAppleTouchDevice = /iPad|iPhone|iPod/.test(userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isAndroidDevice = /Android/i.test(userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || navigator.standalone === true;
  const isPromptPage = location.pathname === '/login'
    || location.pathname === '/student'
    || location.pathname.startsWith('/student/');
  if ((!isAppleTouchDevice && !isAndroidDevice) || isStandalone || !isPromptPage) return;

  const isEmbeddedBrowser = isLineBrowser || /(FBAN|FBAV|Instagram|Messenger)/i.test(userAgent);
  const isAndroidChrome = isAndroidDevice
    && /Chrome\//i.test(userAgent)
    && !/(EdgA|OPR|SamsungBrowser|HuaweiBrowser|;\s*wv\))/i.test(userAgent)
    && !isEmbeddedBrowser;
  const canDetectInstalledPwa = isAndroidChrome
    && typeof navigator.getInstalledRelatedApps === 'function';
  const installedStateKey = 'aiInterviewPwaInstalled';
  const steps = isAndroidDevice
    ? `<li>使用 Chrome 點右上角「<strong>⋮</strong>」選單。</li>
       <li>選擇「<strong>安裝應用程式</strong>」或「<strong>加到主畫面</strong>」。</li>
       <li>點「安裝」，再回到主畫面。</li>
       <li>點「<strong>AI 英語面試</strong>」圖示開啟。</li>`
    : `<li>點瀏覽器的「分享」圖示 <span aria-hidden="true">▢↑</span>。</li>
       <li>點擊「<strong>檢視較多</strong>」。</li>
       <li>選擇「<strong>加到主畫面</strong>」。</li>
       <li>保持「<strong>打開為網頁 App</strong>」開啟，再點「加入」。</li>
       <li>回到主畫面，點「<strong>AI 英語面試</strong>」圖示。</li>`;

  let deferredInstallPrompt = null;
  let dismissed = false;
  let installationCheck = null;
  const overlay = document.createElement('div');
  overlay.id = 'mobilePwaInstallPrompt';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'mobilePwaPromptTitle');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:25000;background:rgba(15,23,42,.78);display:flex;align-items:center;justify-content:center;padding:max(1rem,env(safe-area-inset-top)) max(1rem,env(safe-area-inset-right)) max(1rem,env(safe-area-inset-bottom)) max(1rem,env(safe-area-inset-left));overflow:auto';
  overlay.innerHTML = `
    <div class="pwa-card">
      <button class="pwa-close" id="mobilePwaPromptClose" type="button" aria-label="稍後再安裝">&times;</button>
      <div class="pwa-head">
        <img class="pwa-icon" src="/apple-touch-icon.png" width="58" height="58" alt="AI 英語面試圖示">
        <div>
          <h2 class="pwa-title" id="mobilePwaPromptTitle">安裝 AI 英語面試</h2>
          <div class="pwa-hint" id="mobilePwaPromptHint">安裝後才能進入正式練習</div>
        </div>
      </div>
      <p class="pwa-status" id="mobilePwaInstallStatus" role="status" aria-live="polite" hidden></p>
      <div id="mobilePwaManualInstallInstructions" hidden>
        <p class="pwa-lead">請依照下列步驟安裝，之後從主畫面圖示開啟。</p>
        ${isEmbeddedBrowser ? '<div class="pwa-warning"><strong>請改用 Safari 或 Chrome：</strong>目前是 App 內建瀏覽器，通常不提供安裝功能。</div>' : ''}
        <ol class="pwa-steps">${steps}</ol>
      </div>
      <div class="mt-3">
        <button class="pwa-btn-primary" id="mobilePwaNativeInstall" type="button" hidden>立即安裝</button>
        <a class="pwa-btn-primary pwa-btn-link" id="mobilePwaOpenInstalled" hidden role="button">立即開啟 Web App</a>
        <button class="pwa-btn-secondary" id="mobilePwaPromptLater" type="button">稍後再安裝</button>
      </div>
    </div>`;

  const title = overlay.querySelector('#mobilePwaPromptTitle');
  const hint = overlay.querySelector('#mobilePwaPromptHint');
  const status = overlay.querySelector('#mobilePwaInstallStatus');
  const manualInstructions = overlay.querySelector('#mobilePwaManualInstallInstructions');
  const nativeInstallButton = overlay.querySelector('#mobilePwaNativeInstall');
  const openInstalledButton = overlay.querySelector('#mobilePwaOpenInstalled');
  const laterButton = overlay.querySelector('#mobilePwaPromptLater');
  const closeButton = overlay.querySelector('#mobilePwaPromptClose');

  const appUrl = new URL('/student', window.location.origin);
  appUrl.searchParams.set('source', 'browser-open-pwa');
  const fallbackUrl = encodeURIComponent(appUrl.toString());
  openInstalledButton.href = `intent://${appUrl.host}${appUrl.pathname}${appUrl.search}#Intent;scheme=${appUrl.protocol.slice(0, -1)};action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;S.browser_fallback_url=${fallbackUrl};end`;

  function setStoredInstalledState(installed) {
    try {
      if (installed) localStorage.setItem(installedStateKey, '1');
      else localStorage.removeItem(installedStateKey);
    } catch (_) {
      // Storage may be unavailable in hardened/private browser modes.
    }
  }

  function getStoredInstalledState() {
    try {
      return localStorage.getItem(installedStateKey) === '1';
    } catch (_) {
      return false;
    }
  }

  async function isPwaInstalled() {
    if (!canDetectInstalledPwa) return getStoredInstalledState();
    try {
      const relatedApps = await navigator.getInstalledRelatedApps();
      const installed = relatedApps.some(app => app.platform === 'webapp');
      setStoredInstalledState(installed);
      return installed;
    } catch (_) {
      return getStoredInstalledState();
    }
  }

  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

  function resetActions() {
    manualInstructions.hidden = true;
    nativeInstallButton.hidden = true;
    openInstalledButton.hidden = true;
    status.hidden = true;
    nativeInstallButton.disabled = false;
    nativeInstallButton.textContent = '立即安裝';
  }

  function showManualInstructions(message = '') {
    if (dismissed) return;
    resetActions();
    title.textContent = '安裝 AI 英語面試';
    hint.textContent = isAndroidDevice
      ? '安裝並建立主畫面捷徑後，才能進入正式練習'
      : '加到主畫面後，才能進入正式練習';
    manualInstructions.hidden = false;
    if (message) {
      status.textContent = message;
      status.hidden = false;
    }
    laterButton.textContent = '稍後再安裝';
    closeButton.setAttribute('aria-label', '稍後再安裝');
  }

  function showChecking() {
    if (dismissed) return;
    resetActions();
    title.textContent = '正在確認 Web App';
    hint.textContent = '確認這部裝置是否已完成安裝';
    status.textContent = '請稍候…';
    status.hidden = false;
  }

  function showInstallReady() {
    if (dismissed) return;
    resetActions();
    title.textContent = '安裝 AI 英語面試';
    hint.textContent = '安裝並建立主畫面捷徑後，才能進入正式練習';
    nativeInstallButton.hidden = false;
    laterButton.textContent = '稍後再安裝';
    closeButton.setAttribute('aria-label', '稍後再安裝');
  }

  function showInstalling() {
    if (dismissed) return;
    resetActions();
    title.textContent = '正在完成安裝';
    hint.textContent = 'Chrome 正在建立 Web App 與主畫面捷徑';
    status.textContent = '偵測到安裝完成後，就能直接開啟。';
    status.hidden = false;
    laterButton.textContent = '關閉，稍後再開啟';
    closeButton.setAttribute('aria-label', '關閉，稍後再開啟');
  }

  function showInstalled(pending = false) {
    if (dismissed) return;
    resetActions();
    title.textContent = pending ? '安裝即將完成' : 'AI 英語面試已安裝';
    hint.textContent = pending
      ? 'Chrome 仍在建立 Web App，可稍候後嘗試開啟'
      : '點下方按鈕，從 Web App 開啟正式練習';
    openInstalledButton.textContent = pending ? '嘗試開啟 Web App' : '立即開啟 Web App';
    openInstalledButton.hidden = false;
    laterButton.textContent = '留在瀏覽器';
    closeButton.setAttribute('aria-label', '留在瀏覽器');
  }

  async function waitForInstalledPwa() {
    if (!canDetectInstalledPwa) {
      await delay(2000);
      setStoredInstalledState(true);
      return true;
    }
    for (let attempt = 0; attempt < 30; attempt += 1) {
      if (await isPwaInstalled()) return true;
      await delay(1000);
    }
    return false;
  }

  function confirmInstallation() {
    if (installationCheck) return installationCheck;
    showInstalling();
    installationCheck = waitForInstalledPwa().then(installed => {
      showInstalled(!installed);
      return installed;
    });
    return installationCheck;
  }

  const dismiss = () => {
    dismissed = true;
    overlay.remove();
  };
  closeButton.addEventListener('click', dismiss);
  laterButton.addEventListener('click', dismiss);
  nativeInstallButton.addEventListener('click', async () => {
    if (!deferredInstallPrompt) return;
    const installPrompt = deferredInstallPrompt;
    deferredInstallPrompt = null;
    nativeInstallButton.disabled = true;
    nativeInstallButton.textContent = '等待 Chrome 確認…';
    installPrompt.prompt();
    const choice = await installPrompt.userChoice;
    if (choice.outcome === 'accepted') {
      confirmInstallation();
      return;
    }
    showManualInstructions('已取消安裝；需要時可從 Chrome 選單重新安裝。');
  });
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    deferredInstallPrompt = event;
    showInstallReady();
  });
  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    confirmInstallation();
  }, { once: true });
  document.body.appendChild(overlay);

  (async function initializePromptState() {
    if (!isAndroidChrome) {
      showManualInstructions();
      return;
    }
    showChecking();
    if (await isPwaInstalled()) {
      showInstalled();
      return;
    }
    if (deferredInstallPrompt) {
      showInstallReady();
      return;
    }
    await delay(1200);
    if (deferredInstallPrompt) showInstallReady();
    else showManualInstructions();
  })();
})();
