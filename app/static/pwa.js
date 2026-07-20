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
    <div style="position:relative;width:min(100%,520px);background:#fff;color:#0f172a;border-radius:20px;padding:1.35rem;box-shadow:0 24px 60px rgba(0,0,0,.28)">
      <button id="mobilePwaPromptClose" type="button" aria-label="稍後再安裝" style="position:absolute;right:.8rem;top:.8rem;border:0;background:#e2e8f0;color:#334155;width:2.25rem;height:2.25rem;border-radius:999px;font-size:1.25rem;line-height:1">&times;</button>
      <div style="display:flex;align-items:center;gap:.8rem;padding-right:2.5rem">
        <img src="/apple-touch-icon.png" width="58" height="58" alt="AI 英語面試圖示" style="border-radius:13px;box-shadow:0 2px 8px rgba(15,23,42,.2)">
        <div>
          <h2 id="mobilePwaPromptTitle" style="font-size:1.2rem;font-weight:800;margin:0 0 .25rem">安裝 AI 英語面試</h2>
          <div id="mobilePwaPromptHint" style="font-size:.86rem;color:#64748b">安裝後才能進入正式練習</div>
        </div>
      </div>
      <p id="mobilePwaInstallStatus" role="status" aria-live="polite" hidden style="color:#475569;margin:1rem 0 0"></p>
      <div id="mobilePwaManualInstallInstructions" hidden>
        <p style="color:#475569;margin:1rem 0 .8rem">請依照下列步驟安裝，之後從主畫面圖示開啟。</p>
        ${isEmbeddedBrowser ? '<div style="background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;border-radius:10px;padding:.7rem;margin-bottom:.8rem"><strong>請改用 Safari 或 Chrome：</strong>目前是 App 內建瀏覽器，通常不提供安裝功能。</div>' : ''}
        <ol style="padding-left:1.25rem;line-height:1.65;color:#334155;margin:0">${steps}</ol>
      </div>
      <div style="margin-top:1rem">
        <button id="mobilePwaNativeInstall" type="button" hidden style="width:100%;border:0;background:#4f46e5;color:#fff;border-radius:10px;padding:.72rem;font-weight:800;margin-bottom:.65rem">立即安裝</button>
        <a id="mobilePwaOpenInstalled" hidden role="button" style="display:block;width:100%;border:0;background:#4f46e5;color:#fff;border-radius:10px;padding:.72rem;font-weight:800;margin-bottom:.65rem;text-align:center;text-decoration:none">立即開啟 Web App</a>
        <button id="mobilePwaPromptLater" type="button" style="width:100%;border:1px solid #cbd5e1;background:#f8fafc;color:#334155;border-radius:10px;padding:.65rem;font-weight:700">稍後再安裝</button>
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
