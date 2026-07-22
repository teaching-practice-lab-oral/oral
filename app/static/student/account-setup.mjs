const byId = id => document.getElementById(id);

export class AccountSetupController {
  constructor({ apiReady, nativeFetch }) {
    this.apiReady = apiReady;
    this.nativeFetch = nativeFetch;
    this.mode = 'password';
    this.mandatory = false;
    this.documents = null;
    this.resolveCompletion = null;
    this.completion = Promise.resolve();
    this.installPasswordToggles();
  }

  installPasswordToggles() {
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-password-target]');
      if (!button) return;
      const input = byId(button.dataset.passwordTarget);
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.setAttribute('aria-label', show ? '隱藏密碼' : '顯示密碼');
      const icon = button.querySelector('i');
      if (icon) icon.className = show ? 'bi bi-eye-slash' : 'bi bi-eye';
    });
  }

  async requestJson(url, options = {}) {
    const { requestJson } = await this.apiReady;
    return requestJson(url, options, this.nativeFetch);
  }

  async loadDocuments({ refresh = false } = {}) {
    if (!this.documents || refresh) {
      this.documents = await this.requestJson('/api/auth/legal-documents');
    }
    const privacy = this.documents.privacy_notice;
    const terms = this.documents.system_terms;
    const privacyLink = byId('privacyNoticeLink');
    const termsLink = byId('systemTermsLink');
    privacyLink.href = privacy.url;
    termsLink.href = terms.url;
    byId('privacyNoticeText').textContent = `${privacy.title}（版本 ${privacy.version}）`;
    byId('systemTermsText').textContent = `${terms.title}（版本 ${terms.version}）`;
    byId('systemTermsConsentText').textContent = `我已閱讀、了解並同意遵守「${terms.title}」（版本 ${terms.version}）。`;
    return this.documents;
  }

  resetForm() {
    ['oldPassword', 'newPassword', 'confirmPassword'].forEach(id => {
      const input = byId(id);
      input.value = '';
      input.type = 'password';
    });
    byId('privacyAcknowledged').checked = false;
    byId('termsAccepted').checked = false;
    this.showAlert('');
  }

  showAlert(message, type = 'danger') {
    const alert = byId('changePwAlert');
    alert.className = message ? `alert alert-${type}` : 'alert d-none';
    alert.textContent = message;
    if (message) alert.focus();
  }

  configureModal(forcePassword, requiresLegal) {
    this.mode = requiresLegal && !forcePassword
      ? 'legal'
      : requiresLegal ? 'password-and-legal' : 'password';
    this.mandatory = forcePassword || requiresLegal;

    const legalOnly = this.mode === 'legal';
    document.querySelectorAll('#changePwModal .password-group')
      .forEach(group => group.classList.toggle('d-none', legalOnly));
    byId('changePwLegalDocs').classList.toggle('d-none', !requiresLegal);
    byId('changePwLegalConsent').classList.toggle('d-none', !requiresLegal);
    byId('changePwFirstLoginNote').classList.toggle('d-none', !this.mandatory);
    byId('changePwCancelBtn').classList.toggle('d-none', this.mandatory);
    byId('changePwClose').classList.toggle('d-none', this.mandatory);

    const title = byId('changePwModalTitle');
    const subtitle = byId('changePwSubtitle');
    const noteTitle = byId('changePwSetupTitle');
    const noteText = byId('changePwSetupText');
    const submit = byId('changePwSubmitBtn');
    if (this.mode === 'legal') {
      title.textContent = '確認更新的法遵事項';
      subtitle.textContent = '此確認不等同於同意參與研究，也不需要再次變更密碼。';
      noteTitle.textContent = '法遵事項已更新';
      noteText.textContent = '請閱讀更新後的個資告知事項與系統使用者條款，再分別完成確認。';
      submit.innerHTML = '<i class="bi bi-check2-circle me-1"></i>確認並繼續';
    } else if (this.mode === 'password-and-legal') {
      title.textContent = '完成帳戶設定';
      subtitle.textContent = '完成法遵確認與密碼設定後，即可繼續使用系統。';
      noteTitle.textContent = '首次使用前請完成設定';
      noteText.textContent = '請閱讀個資告知事項與系統使用者條款，並設定新的登入密碼。';
      submit.innerHTML = '<i class="bi bi-check2-circle me-1"></i>儲存設定';
    } else {
      title.textContent = '設定新的登入密碼';
      subtitle.textContent = this.mandatory
        ? '完成密碼更新後，即可繼續使用系統。'
        : '定期更新登入密碼，有助於保護您的帳戶與作業資料。';
      noteTitle.textContent = '密碼已由管理員重設';
      noteText.textContent = '請先確認並儲存您的登入密碼，再繼續使用系統。';
      submit.innerHTML = '<i class="bi bi-check2-circle me-1"></i>儲存新密碼';
    }
  }

  async open({ forcePassword = false, requiresLegal = false } = {}) {
    this.resetForm();
    this.configureModal(forcePassword === true, requiresLegal === true);
    const submit = byId('changePwSubmitBtn');
    submit.disabled = requiresLegal;
    if (requiresLegal) {
      try {
        await this.loadDocuments();
      } catch (error) {
        this.showAlert(error?.detail || '目前無法載入法遵文件，請稍後重新整理。');
      } finally {
        submit.disabled = !this.documents;
      }
    }

    const modalElement = byId('changePwModal');
    const previous = bootstrap.Modal.getInstance(modalElement);
    if (previous) previous.dispose();
    new bootstrap.Modal(modalElement, {
      backdrop: this.mandatory ? 'static' : true,
      keyboard: !this.mandatory,
    }).show();

    if (!this.mandatory) return;
    this.completion = new Promise(resolve => { this.resolveCompletion = resolve; });
    return this.completion;
  }

  acknowledgementPayload() {
    if (!this.documents) throw new Error('法遵文件尚未載入完成');
    return {
      privacy_notice_version: this.documents.privacy_notice.version,
      privacy_acknowledged: byId('privacyAcknowledged').checked,
      system_terms_version: this.documents.system_terms.version,
      terms_accepted: byId('termsAccepted').checked,
    };
  }

  validate() {
    if (this.mode !== 'legal') {
      const oldPassword = byId('oldPassword').value;
      const newPassword = byId('newPassword').value;
      const confirmPassword = byId('confirmPassword').value;
      if (!oldPassword || !newPassword || !confirmPassword) throw new Error('請填寫所有欄位');
      if (newPassword !== confirmPassword) throw new Error('新密碼與確認密碼不一致');
      if (newPassword.length < 8) throw new Error('新密碼至少需要 8 個字元');
    }
    if (this.mode !== 'password') {
      if (!byId('privacyAcknowledged').checked) throw new Error('請先閱讀並勾選個人資料告知事項');
      if (!byId('termsAccepted').checked) throw new Error('請先閱讀並同意系統使用者條款');
    }
  }

  async submit() {
    try {
      this.validate();
    } catch (error) {
      this.showAlert(error.message);
      return;
    }

    const submit = byId('changePwSubmitBtn');
    const original = submit.innerHTML;
    submit.disabled = true;
    submit.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>處理中...';
    try {
      const legal = this.mode === 'password' ? null : this.acknowledgementPayload();
      const endpoint = this.mode === 'legal'
        ? '/api/auth/legal-acknowledgement'
        : '/api/auth/change-password';
      const body = this.mode === 'legal'
        ? legal
        : {
            old_password: byId('oldPassword').value,
            new_password: byId('newPassword').value,
            ...(legal ? { legal_acknowledgement: legal } : {}),
          };
      await this.requestJson(endpoint, { method: 'POST', body: JSON.stringify(body) });
      if (this.mode !== 'legal') sessionStorage.setItem('must_change_password', '0');
      if (this.mode !== 'password') sessionStorage.setItem('requires_legal_acknowledgement', '0');
      const modal = bootstrap.Modal.getInstance(byId('changePwModal'));
      if (modal) modal.hide();
      const resolve = this.resolveCompletion;
      this.resolveCompletion = null;
      if (resolve) resolve();
    } catch (error) {
      if (error?.status === 409 && this.mode !== 'password') {
        this.documents = null;
        await this.loadDocuments({ refresh: true }).catch(() => {});
        byId('privacyAcknowledged').checked = false;
        byId('termsAccepted').checked = false;
      }
      this.showAlert(error?.detail || error?.message || '目前無法更新帳戶設定，請稍後再試。');
    } finally {
      submit.disabled = this.mode !== 'password' && !this.documents;
      submit.innerHTML = original;
    }
  }
}
