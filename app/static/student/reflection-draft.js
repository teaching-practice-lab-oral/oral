// Reflection-specific optimistic concurrency and local-draft persistence.
(function installReflectionDraftController() {
  class ReflectionDraftController {
    constructor({ storagePrefix, submissionId, assignmentId, revision = 0 }) {
      this.storagePrefix = storagePrefix;
      this.submissionId = Number(submissionId);
      this.assignmentId = Number(assignmentId);
      this.revision = Number(revision) || 0;
    }

    get key() { return `${this.storagePrefix}${this.submissionId}`; }

    withExpectedRevision(body) {
      return { ...body, expected_revision: this.revision };
    }

    appendExpectedRevision(formData) {
      formData.set('expected_revision', String(this.revision));
      return formData;
    }

    adopt(responseData) {
      const revision = Number(responseData?.revision);
      if (!Number.isInteger(revision) || revision < 0) {
        throw new Error('伺服器未回傳有效的心得版本。');
      }
      this.revision = revision;
      return revision;
    }

    conflictDetail(responseData) {
      const detail = responseData?.detail;
      if (detail?.code !== 'reflection_revision_conflict' || !detail.latest) return null;
      return detail;
    }

    write(data, localRevision) {
      localStorage.setItem(this.key, JSON.stringify({
        submission_id: this.submissionId,
        assignment_id: this.assignmentId,
        base_revision: this.revision,
        saved_at: new Date().toISOString(),
        revision: localRevision,
        data,
      }));
    }

    read() {
      const value = JSON.parse(localStorage.getItem(this.key) || 'null');
      if (!value || Number(value.submission_id) !== this.submissionId || !value.data) return null;
      return value;
    }

    clear() { localStorage.removeItem(this.key); }

    hasSameBase(localDraft) {
      return Number(localDraft?.base_revision) === this.revision;
    }
  }

  window.ReflectionDraftController = ReflectionDraftController;
})();
