async function loadLoginAuditTabs() {
  const host = document.getElementById('loginAuditTabsHost');
  try {
    const res = await fetch('/static/admin/partials/login-audit-tabs.html');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    host.innerHTML = await res.text();
    initLoginAuditPage();
  } catch (e) {
    host.innerHTML = '<div class="alert alert-danger">稽核頁面載入失敗，請重新整理。</div>';
    console.error('Failed to load login audit tabs:', e);
  }
}

function initLoginAuditPage() {
  document.getElementById('la-unfreezeBar').hidden = sessionStorage.getItem('isPrivilegedAdmin') !== '1';

  document.getElementById('tab-admin-audit-btn').addEventListener('show.bs.tab', function () {
    if (!aaInitialized) { aaInitialized = true; aaLoadLogs(1); }
  });

  document.getElementById('tab-api-logs-btn').addEventListener('show.bs.tab', function () {
    if (!ulInitialized) { ulInitialized = true; ulLoadLogs(true); }
  });

  document.getElementById('tab-active-sessions-btn').addEventListener('show.bs.tab', function () {
    if (!asInitialized) { asInitialized = true; asLoad(); }
  });

  document.getElementById('ul-filterStudentId').addEventListener('keydown', e => {
    if (e.key === 'Enter') ulLoadLogs(true);
  });

  setInterval(() => {
    const activeBtn = document.querySelector('#auditTabs .nav-link.active');
    if (activeBtn && activeBtn.id === 'tab-active-sessions-btn') asLoad();
  }, 30000);

  initAuditDatePicker('la-filterDateFrom', '開始日期', () => laLoadEvents(1));
  initAuditDatePicker('la-filterDateTo', '結束日期', () => laLoadEvents(1));
  initAuditDatePicker('aa-filterDateFrom', '開始日期', () => aaLoadLogs(1));
  initAuditDatePicker('aa-filterDateTo', '結束日期', () => aaLoadLogs(1));
  initAuditDatePicker('ul-filterDateFrom', '開始日期', () => ulLoadLogs(true));
  initAuditDatePicker('ul-filterDateTo', '結束日期', () => ulLoadLogs(true));
  document.addEventListener('click', () => {
    document.querySelectorAll('.dtp-popup').forEach(p => { p.style.display = 'none'; });
  });

  laLoadEvents(1);
}

async function startLoginAuditPage() {
  await window._adminReady;
  await AdminWorkflow.ready();
  await loadLoginAuditTabs();
}

startLoginAuditPage();
