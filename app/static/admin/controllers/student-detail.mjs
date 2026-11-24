const pathParts = window.location.pathname.split('/');
    const assignmentId = parseInt(pathParts[3]);
    const userId = parseInt(pathParts[5]);

    let submissions = [];
    let student = null;
    let assignment = null;
    let navState = null;
    let navIndex = -1;
    let currentRubric = null;
    let gradeHistory = [];
    let gradingSubmission = null;
    let gradingLoadGeneration = 0;
    let gradingLoadController = null;

    function getFilename(res, fallback) {
      const cd = res.headers.get('Content-Disposition') || '';
      const m5987 = cd.match(/filename\*=UTF-8''([^\s;]+)/i);
      if (m5987) return decodeURIComponent(m5987[1]);
      const m = cd.match(/filename="?([^";\n]+)"?/);
      return m ? m[1] : fallback;
    }
    function goBack() {
      if (navState) {
        window.location.href = `/admin/assignments/${assignmentId}/results`;
      } else {
        history.back();
      }
    }

    function initNavigation() {
      try { navState = JSON.parse(sessionStorage.getItem(`admin_student_nav_${assignmentId}`)); } catch { navState = null; }

      if (!navState || !Array.isArray(navState.userIds) || !navState.userIds.length) return;

      navIndex = navState.userIds.indexOf(userId);

      const bar = document.getElementById('navBar');
      bar.classList.remove('d-none');

      // Breadcrumb
      const aEl = document.getElementById('breadcrumbAssignment');
      aEl.textContent = navState.assignmentTitle || '作業';
      document.getElementById('breadcrumbResults').href = `/admin/assignments/${assignmentId}/results`;
      document.getElementById('breadcrumbStudent').textContent = student ? student.name : '—';

      if (navIndex === -1) {
        // Student not in saved list — show breadcrumb only
        document.getElementById('navButtons').classList.add('d-none');
        document.getElementById('navCounter').textContent = '（名單已更新）';
        return;
      }

      const total = navState.userIds.length;
      document.getElementById('navCounter').textContent = `第 ${navIndex + 1} / ${total} 位`;

      const hasPrev = navIndex > 0;
      const hasNext = navIndex < total - 1;

      const btnPrev = document.getElementById('btnPrev');
      const btnNext = document.getElementById('btnNext');

      if (hasPrev) {
        const prevId = navState.userIds[navIndex - 1];
        document.getElementById('prevLabel').textContent = navState.names?.[prevId] || '上一位';
        btnPrev.disabled = false;
        btnPrev.title = `上一位：${navState.names?.[prevId] || ''}`;
      } else {
        btnPrev.title = '已是第一位';
      }

      if (hasNext) {
        const nextId = navState.userIds[navIndex + 1];
        document.getElementById('nextLabel').textContent = navState.names?.[nextId] || '下一位';
        btnNext.disabled = false;
        btnNext.title = `下一位：${navState.names?.[nextId] || ''}`;
      } else {
        btnNext.title = '已是最後一位';
      }

      document.addEventListener('keydown', e => {
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (e.key === 'ArrowLeft' || e.key === '[') { e.preventDefault(); navigatePrev(); }
        else if (e.key === 'ArrowRight' || e.key === ']') { e.preventDefault(); navigateNext(); }
      });
    }

    function navigatePrev() {
      if (!navState || navIndex <= 0) return;
      window.location.href = `/admin/assignments/${assignmentId}/students/${navState.userIds[navIndex - 1]}`;
    }

    function navigateNext() {
      if (!navState || navIndex >= navState.userIds.length - 1) return;
      window.location.href = `/admin/assignments/${assignmentId}/students/${navState.userIds[navIndex + 1]}`;
    }

    function navigateNextPending() {
      if (!navState || !Array.isArray(navState.pendingUserIds)) {
        showAlert('待批改名單尚未載入，請返回作業結果頁重新整理後再試。');
        return;
      }
      const currentPosition = navState.userIds.indexOf(userId);
      const nextId = navState.pendingUserIds.find(candidateId =>
        navState.userIds.indexOf(candidateId) > currentPosition
      );
      if (!nextId) {
        showAlert('目前沒有下一位待批改學生。', 'success');
        return;
      }
      window.location.href = `/admin/assignments/${assignmentId}/students/${nextId}`;
    }

    function renderLearningScaffold(scaffold) {
      if (!scaffold || !Array.isArray(scaffold.questions)) return pendingHtml('尚未建立個人化學習鷹架');
      const priorities = (scaffold.competency_priorities || []).map(item => `<li>${escHtml(item)}</li>`).join('');
      const questions = scaffold.questions.map(item => `
        <div class="mb-3 p-3 rounded border bg-light">
          <p class="fw-bold mb-2 text-primary">Q${Number(item.index)+1}：${escHtml(item.question)}</p>
          <p><strong>學習目標：</strong>${escHtml(item.goal)}</p>
          <p><strong>回答步驟：</strong>${(item.steps||[]).map(step=>escHtml(step)).join(' → ')}</p>
          <p><strong>職位連結：</strong>${escHtml(item.role_connection)}</p>
          <p><strong>經驗提示：</strong>${(item.experience_prompts||[]).map(prompt=>escHtml(prompt)).join('／')}</p>
          <p><strong>關鍵字：</strong>${(item.keywords||[]).map(keyword=>escHtml(keyword)).join('、')}</p>
          <p class="mb-0"><strong>短句架：</strong>${(item.sentence_starters||[]).map(starter=>escHtml(starter)).join('／')}</p>
        </div>`).join('');
      return `<p><strong>本次職位面試重點：</strong>${escHtml(scaffold.position_focus)}</p>
        ${priorities?`<p class="mb-1"><strong>優先能力：</strong></p><ul>${priorities}</ul>`:''}
        ${questions}`;
    }

    async function init() {
      await window._adminReady;
      const res = await fetch(`/api/admin/assignments/${assignmentId}/students/${userId}`, {
        headers: authHeaders()
      });
      if (res.status === 401) { redirectAdminToLogin(); return; }
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.student || !Array.isArray(data.submissions)) {
        document.getElementById('loadingMsg').innerHTML =
          `<div class="alert alert-danger">${escHtml(data.detail || '學生作業資料載入失敗，請返回上一頁後重試。')}</div>`;
        return;
      }
      student = data.student;
      assignment = data.assignment;
      submissions = data.submissions;

      document.getElementById('loadingMsg').classList.add('d-none');
      document.getElementById('content').classList.remove('d-none');
      document.getElementById('pageTitle').innerHTML =
        `<i class="bi bi-person-lines-fill me-2 text-primary"></i>${escHtml(student.name)} — ${escHtml(assignment ? assignment.title : '作業')}`;
      document.getElementById('infoStudentId').textContent = student.student_id;
      document.getElementById('infoName').textContent = student.name;
      document.getElementById('infoEmail').textContent = student.email;

      const selector = document.getElementById('attemptSelector');
      selector.innerHTML = submissions.map(s => `<option value="${s.attempt_number}">第 ${s.attempt_number} 次</option>`).join('');
      if (submissions.length) {
        const requestedSubmissionId = Number(new URLSearchParams(location.search).get('submission'));
        const requested = submissions.find(s => s.id === requestedSubmissionId);
        selector.value = (requested || submissions[submissions.length - 1]).attempt_number;
        renderAttempt();
      } else {
        document.getElementById('submissionContent').innerHTML =
          '<div class="alert alert-info"><i class="bi bi-inbox me-2"></i>尚無提交記錄。</div>';
        document.getElementById('gradingPanel').removeAttribute('data-submission-id');
      }

      if (assignment && assignment.due_date && new Date() > new Date(assignment.due_date)) {
        const btn = document.querySelector('[data-action="allowRetake"]');
        if (btn) { btn.disabled = true; btn.title = '作業已截止，無法允許重作'; }
      }

      initNavigation();
    }

    function renderAttempt() {
      const attempt = parseInt(document.getElementById('attemptSelector').value);
      const sub = submissions.find(s => s.attempt_number === attempt);
      if (!sub) return;
      const latestAttempt = Math.max(...submissions.map(s => s.attempt_number));
      rewindSub = sub.attempt_number === latestAttempt ? sub : null;

      document.getElementById('attemptStatus').textContent = sub.submitted_at
        ? `完成於 ${new Date(sub.submitted_at).toLocaleString('zh-TW')}`
        : `進行中（第 ${{1:1,2:2,3:2,4:2,5:3,6:4,7:4,8:6,9:6}[sub.stage] || 1}/6 階段）`;

      // Export buttons
      const exportDiv = document.getElementById('exportButtons');
      exportDiv.classList.remove('d-none');
      exportDiv.innerHTML = `
<button class="btn btn-outline-primary" id="btnExportAll" data-action="exportStudentAll">
          <i class="bi bi-file-earmark-zip me-1"></i>匯出全部
        </button>
        <button class="btn btn-outline-primary" id="btnWord-${sub.id}" data-action="exportWord" data-args='[${sub.id}]'>
          <i class="bi bi-file-earmark-word me-1"></i>匯出 Word
        </button>
        <button class="btn btn-outline-secondary" id="btnAudio-${sub.id}" data-action="exportAudio" data-args='[${sub.id}]'>
          <i class="bi bi-file-zip me-1"></i>匯出音檔
        </button>`;

      const html = [];
      html.push(collapsibleStageSection(
        '作答監考與異常時間軸',
        `<div id="proctorTimeline-${sub.id}" class="text-muted small"><span class="spinner-border spinner-border-sm me-1"></span>載入監考紀錄...</div>`,
      ));

      const profile = sub.job_profile_data || {};
      const profileHtml = profile.desired_position ? `
        <p><strong>欲應徵職位：</strong>${escHtml(profile.desired_position)}</p>
        <p><strong>職位工作內容：</strong>${escHtml(profile.role_description)}</p>
        <p><strong>所需職能：</strong>${escHtml(profile.required_competencies)}</p>
        <p class="mb-0"><strong>其他補充：</strong>${escHtml(profile.additional_notes || '無')}</p>` : pendingHtml('尚未填寫欲應徵的職位');
      html.push(stageSection(1, AdminWorkflow.sectionLabel(1), profileHtml, !!profile.desired_position, 1));
      html.push(collapsibleStageSection('個人化學習鷹架（唯讀）', renderLearningScaffold(sub.learning_scaffold)));

      // Section 2: Draft 1
      let draft1Html = '';
      if (sub.draft1_answers && Array.isArray(sub.draft1_answers) && sub.draft1_answers.length > 0) {
        draft1Html = sub.draft1_answers.map(item => `
          <div class="mb-3 p-3 rounded panel-muted">
            <p class="fw-semibold mb-2 small text-brand">Q${item.index+1}：${escHtml(item.question || '')}</p>
            <div class="feedback-box"><pre>${escHtml(item.text || '')}</pre></div>
          </div>`).join('');
      }
      html.push(stageSection(2, AdminWorkflow.stageLabel(2), draft1Html || pendingHtml('尚未提交草稿'),
        !!(sub.draft1_answers && sub.draft1_answers.length > 0), 2));

      // Section 3: AI Feedback
      html.push(stageSection(3, AdminWorkflow.stageLabel(3), sub.draft2_ai_feedback
        ? renderFeedback(sub.draft2_ai_feedback, sub.draft1_answers || [])
        : pendingHtml('尚未請求 AI 練習回饋'), !!sub.draft2_ai_feedback, 3));

      // Section 4: Final Draft
      let finalDraftHtml = '';
      if (sub.final_draft_answers && Array.isArray(sub.final_draft_answers) && sub.final_draft_answers.length > 0) {
        finalDraftHtml = sub.final_draft_answers.map(item => `
          <div class="mb-3 p-3 rounded panel-muted">
            <p class="fw-semibold mb-2 small text-emerald">Q${item.index+1}：${escHtml(item.question || '')}</p>
            <div class="feedback-box"><pre>${escHtml(item.text || '')}</pre></div>
          </div>`).join('');
      }
      html.push(stageSection(4, AdminWorkflow.stageLabel(4), finalDraftHtml || pendingHtml('尚未提交最終草稿'),
        !!(sub.final_draft_answers && sub.final_draft_answers.length > 0), 4));

      // Section 5: Shadowing
      let s5html = '';
      const ttsKeys = sub.shadowing_tts_keys || [];
      const spk1Qs = sub.speaking1_questions || [];
      const finalAnswers5 = sub.final_draft_answers || [];
      if (spk1Qs.length > 0 || ttsKeys.length > 0) {
        finalAnswers5.forEach((ans, i) => {
          const ttsEntry = ttsKeys.find(k => k.index === i);
          const spkEntry = spk1Qs.find(q => q.index === i);
          s5html += `<div class="mb-4 p-3 border rounded-3 bg-light">
            <div class="small fw-bold mb-2 text-brand">Q${i+1}：${escHtml(ans.question || '')}</div>
            ${ttsEntry && ttsEntry.key ? `<div class="mb-2"><div class="small fw-semibold text-muted mb-1"><i class="bi bi-volume-up me-1"></i>示範音訊</div>${audioPlayer(ttsEntry.key, sub.id, `tts-q${i}`)}</div>` : ''}
            ${spkEntry && spkEntry.audio_key ? `<div class="mb-2"><div class="small fw-semibold text-muted mb-1"><i class="bi bi-mic me-1"></i>學生錄音（第 ${spkEntry.attempts} 次）</div>${audioPlayer(spkEntry.audio_key, sub.id, `s1-q${i}`)}</div>` : ''}
            ${spkEntry && spkEntry.transcript ? `<div><div class="small fw-semibold text-muted mb-1"><i class="bi bi-chat-text me-1"></i>語音辨識</div><div class="feedback-box"><pre>${escHtml(spkEntry.transcript)}</pre></div></div>` : ''}
          </div>`;
        });
      }
      html.push(stageSection(5, AdminWorkflow.stageLabel(5), s5html || pendingHtml('尚未完成跟讀'), spk1Qs.length > 0, 5));

      // Section 6: Roleplay
      let s6html = '';
      if (sub.roleplay_conversation) {
        try {
          const conv = JSON.parse(sub.roleplay_conversation);
          (conv.turns || []).forEach(t => {
            const ttsContainerId = `audioContainer-${sub.id}-rp-tts-${t.turn_number}`;
            const stuContainerId = `audioContainer-${sub.id}-rp-stu-${t.turn_number}`;
            s6html += `
              <div class="mb-3 p-3 border rounded-3 bg-light">
                <div class="small fw-semibold text-primary mb-1">
                  <i class="bi bi-person-workspace me-1"></i>第 ${t.turn_number} 輪 — 面試官提問
                </div>
                <p class="mb-2">${escHtml(t.interviewer_question)}</p>
                ${t.interviewer_tts_key ? `
                  <div class="small fw-semibold text-muted mb-1"><i class="bi bi-volume-up me-1"></i>面試官語音</div>
                  <div id="${ttsContainerId}" class="mb-2">
                    <button class="btn btn-outline-primary" data-action="loadAudio" data-args='[${sub.id},"rp-tts-${t.turn_number}","${escAttr(t.interviewer_tts_key)}"]'>
                      <i class="bi bi-play-circle me-1"></i>載入面試官語音
                    </button>
                  </div>` : ''}
                <div class="small fw-semibold text-muted mb-1"><i class="bi bi-mic me-1"></i>學生回答</div>
                <p class="mb-1 ${t.student_transcript ? '' : 'text-muted fst-italic'}">${escHtml(t.student_transcript || '（未回答）')}</p>
                ${t.student_audio_key ? `
                  <div id="${stuContainerId}">
                    <button class="btn btn-outline-secondary" data-action="loadAudio" data-args='[${sub.id},"rp-stu-${t.turn_number}","${escAttr(t.student_audio_key)}"]'>
                      <i class="bi bi-play-circle me-1"></i>載入學生錄音
                    </button>
                  </div>` : ''}
              </div>`;
          });
        } catch { s6html = `<pre class="feedback-box">${escHtml(sub.roleplay_conversation)}</pre>`; }
      }
      html.push(stageSection(6, AdminWorkflow.stageLabel(6), s6html || pendingHtml('尚未完成角色扮演'), !!sub.roleplay_conversation, 6));

      // Section 7: Report
      let s7reportHtml = '';
      if (sub.report_data) {
        try {
          const report = JSON.parse(sub.report_data);
          s7reportHtml = renderReport(report);
        } catch { s7reportHtml = `<pre class="feedback-box">${escHtml(sub.report_data)}</pre>`; }
      }
      let s7html = '';
      if (sub.roleplay_conversation) {
        s7html += `<div class="mb-3"><button class="btn btn-outline-warning" id="btnRescore-${sub.id}" data-action="rescoreReport" data-args='[${sub.id}]'><i class="bi bi-arrow-repeat me-1"></i>重新產生回饋</button></div>`;
      }
      s7html += s7reportHtml || pendingHtml('尚未生成 AI 回饋');
      html.push(stageSection(8, AdminWorkflow.sectionLabel(5), s7html, !!sub.report_data));

      const reflection = sub.reflection_data || {};
      let reflectionHtml = '';
      (reflection.questions || []).forEach((question, index) => {
        reflectionHtml += `<div class="mb-3"><div class="small fw-bold text-primary">${index + 1}. ${escHtml(question)}</div><div class="feedback-box mt-1">${escHtml((reflection.answers || [])[index] || '（未填寫）')}</div></div>`;
      });
      if (reflection.has_issue) {
        reflectionHtml += `<div class="alert alert-warning"><strong><i class="bi bi-exclamation-triangle-fill me-1"></i>問題回報：${escHtml(reflection.issue_category || '其他')}</strong><p class="mb-2 mt-2">${escHtml(reflection.issue_description || '')}</p>${reflection.has_photo ? `<button class="btn btn-sm btn-outline-warning" data-action="viewIssuePhoto" data-args='[${sub.id}]'><i class="bi bi-image me-1"></i>查看問題照片</button>` : ''}</div>`;
      }
      html.push(stageSection(8, AdminWorkflow.sectionLabel(6), reflectionHtml || pendingHtml('尚未填寫心得'), !!reflection.submitted_at, 8));

      document.getElementById('submissionContent').innerHTML = html.join('');
      loadProctorTimeline(sub);
      loadGrading(sub);
    }

    async function loadProctorTimeline(sub) {
      const container = document.getElementById(`proctorTimeline-${sub.id}`);
      if (!container) return;
      const labels = {
        fullscreen_enter: '進入全螢幕',
        fullscreen_exit: '離開全螢幕',
        page_hidden: '切換分頁或隱藏頁面',
        window_blur: '視窗失去焦點',
        paste_blocked: '嘗試貼上文字',
        large_input: '偵測到大量瞬間輸入',
        time_expired: '作答時間結束',
      };
      const eventLabel = event => {
        if (event.event_type === 'fullscreen_enter' && event.details?.mode === 'ios_pwa') {
          return '從 iOS 主畫面 Web App 開始';
        }
        if (event.event_type === 'fullscreen_enter' && event.details?.mode === 'android_pwa') {
          return '從 Android 主畫面 Web App 開始';
        }
        return labels[event.event_type] || event.event_type;
      };
      try {
        const res = await fetch(`/api/admin/submissions/${sub.id}/proctor-events`, { headers: authHeaders() });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '監考紀錄載入失敗');
        const events = data.events || [];
        const usesIosPwaMode = events.some(event =>
          event.event_type === 'fullscreen_enter' && event.details?.mode === 'ios_pwa'
        );
        const usesAndroidPwaMode = events.some(event =>
          event.event_type === 'fullscreen_enter' && event.details?.mode === 'android_pwa'
        );
        const anomalies = events.filter(event => event.event_type !== 'fullscreen_enter');
        const counts = {};
        anomalies.forEach(event => { counts[event.event_type] = (counts[event.event_type] || 0) + 1; });
        const summary = Object.entries(counts).map(([type, count]) =>
          `<span class="badge bg-warning text-dark me-1 mb-1">${escHtml(labels[type] || type)} ${count}</span>`
        ).join('');
        const period = data.practice_started_at
          ? `<div class="small text-muted mb-3">${usesIosPwaMode ? '<span class="badge bg-primary me-2">iOS 主畫面 Web App</span>' : ''}${usesAndroidPwaMode ? '<span class="badge bg-success me-2">Android 主畫面 Web App</span>' : ''}作答開始：${new Date(data.practice_started_at).toLocaleString('zh-TW')}</div>`
          : '<div class="small text-muted mb-3">尚未開始作答。</div>';
        const timeline = events.length ? `<div class="proctor-timeline">${events.map(event => {
          const pageKey = event.page_path.split('/').pop();
          const details = event.details || {};
          const detailText = details.character_count != null
            ? `・${details.character_count} 個字元${details.field_id ? `・欄位 ${details.field_id}` : ''}`
            : '';
          return `<div class="proctor-event ${event.event_type === 'fullscreen_enter' ? 'proctor-ok' : ''}"><strong>${escHtml(eventLabel(event))}</strong><div class="text-muted">${new Date(event.created_at).toLocaleString('zh-TW')}・${escHtml(AdminWorkflow.sectionLabelByPath(pageKey))}${escHtml(detailText)}</div></div>`;
        }).join('')}</div>` : '<div class="alert alert-light border mb-0">目前沒有瀏覽器監考事件；舊提交紀錄可能早於此功能。</div>';
        container.innerHTML = `<div class="mb-2"><strong>異常事件 ${anomalies.length} 筆</strong><div class="mt-2">${summary || '<span class="badge bg-success">未記錄異常</span>'}</div></div>${period}${timeline}<p class="small text-muted mt-3 mb-0"><i class="bi bi-info-circle me-1"></i>此時間軸只供教師複查，單一事件不代表作弊。</p>`;
      } catch (error) {
        container.innerHTML = `<div class="alert alert-danger mb-0">${escHtml(error.message)}</div>`;
      }
    }

    async function viewIssuePhoto(submissionId) {
      const res = await fetch(`/api/admin/submissions/${submissionId}/reflection/photo-url`);
      const data = await res.json();
      if (!res.ok) { showAlert(data.detail || '照片無法開啟'); return; }
      window.open(data.url, '_blank', 'noopener');
    }

    function rubricLevelPoints(level, criterionPoints) {
      if (level && level.points != null) return Number(level.points);
      return Number(criterionPoints) * Number(level && level.ratio != null ? level.ratio : 0);
    }

    function gradingCriterionHtml(criterion, sharedLevels, latestRatings, canGrade) {
      const levels = Array.isArray(criterion.levels) && criterion.levels.length ? criterion.levels : sharedLevels;
      const options = levels.map(level => {
        const awarded = rubricLevelPoints(level, criterion.points);
        const awardedLabel = Number(awarded).toLocaleString('zh-TW', { maximumFractionDigits: 2 });
        const selected = latestRatings[criterion.key] === level.value ? 'selected' : '';
        return `<option value="${level.value}" data-awarded="${awarded}" ${selected}>${awardedLabel} 分｜${escHtml(level.label)}</option>`;
      }).join('');
      const guide = levels.map(level => {
        const awarded = rubricLevelPoints(level, criterion.points);
        return `<li class="mb-1"><strong>${Number(awarded).toLocaleString('zh-TW', { maximumFractionDigits: 2 })} 分｜${escHtml(level.label)}</strong><br>${escHtml(level.anchor || '')}</li>`;
      }).join('');
      return `<div class="criterion-grade">
        <label class="form-label small fw-semibold mb-1">${escHtml(criterion.name)} <span class="text-muted">/ ${criterion.points}</span></label>
        <div class="small text-muted mb-2">${escHtml(criterion.description)}</div>
        <select class="form-select form-select-sm grade-level" data-key="${escAttr(criterion.key)}" ${canGrade ? '' : 'disabled'}>
          <option value="">請選擇等級</option>${options}
        </select>
        <details class="small mt-2"><summary class="text-primary cursor-pointer">查看各級評分標準</summary><ul class="mt-2 mb-0 ps-3">${guide}</ul></details>
      </div>`;
    }

    async function loadGrading(sub) {
      gradingLoadController?.abort();
      const generation = ++gradingLoadGeneration;
      const controller = new AbortController();
      gradingLoadController = controller;
      gradingSubmission = null;
      currentRubric = null;
      gradeHistory = [];
      const panel = document.getElementById('gradingPanel');
      panel.dataset.submissionId = String(sub.id);
      panel.dataset.loadGeneration = String(generation);
      panel.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';
      let rubricRes;
      let historyRes;
      try {
        [rubricRes, historyRes] = await Promise.all([
          fetch(`/api/admin/submissions/${sub.id}/rubric`, { signal: controller.signal }),
          fetch(`/api/admin/submissions/${sub.id}/grades`, { signal: controller.signal }),
        ]);
      } catch (error) {
        if (error.name === 'AbortError') return;
        if (generation === gradingLoadGeneration) {
          panel.innerHTML = '<div class="alert alert-danger">批改資料載入失敗</div>';
        }
        return;
      }
      if (generation !== gradingLoadGeneration || panel.dataset.submissionId !== String(sub.id)) return;
      if (!rubricRes.ok || !historyRes.ok) {
        panel.innerHTML = '<div class="alert alert-danger">批改資料載入失敗</div>';
        return;
      }
      let loadedRubric;
      let loadedHistory;
      try {
        [loadedRubric, loadedHistory] = await Promise.all([rubricRes.json(), historyRes.json()]);
      } catch (error) {
        if (error.name === 'AbortError') return;
        if (generation === gradingLoadGeneration) {
          panel.innerHTML = '<div class="alert alert-danger">批改資料格式錯誤，請重新整理後再試。</div>';
        }
        return;
      }
      if (generation !== gradingLoadGeneration || panel.dataset.submissionId !== String(sub.id)) return;
      gradingSubmission = sub;
      currentRubric = loadedRubric;
      gradeHistory = loadedHistory;
      const latest = gradeHistory[0] || null;
      const latestRatings = {};
      (latest?.ratings || []).forEach(item => { latestRatings[item.criterion_key] = item.level; });
      const levels = currentRubric.definition.levels || [];
      const canGrade = !!sub.submitted_at && sub.stage >= 9;
      const notes = currentRubric.definition.notes || [];
      const notesHtml = notes.length ? `<div class="alert alert-warning small"><strong>評分注意事項</strong><ul class="mb-0 mt-1 ps-3">${notes.map(note => `<li>${escHtml(note)}</li>`).join('')}</ul></div>` : '';
      const gradeCriteriaHtml = currentRubric.definition.dimensions.map(dimension => `<div class="mb-3"><div class="fw-bold text-primary">${escHtml(dimension.name)}（${dimension.weight} 分）</div>${dimension.criteria.map(criterion => gradingCriterionHtml(criterion, levels, latestRatings, canGrade)).join('')}</div>`).join('');
      panel.innerHTML = `<div class="d-flex justify-content-between align-items-start mb-3"><div><h5 class="fw-bold mb-1"><i class="bi bi-ui-checks-grid text-primary me-1"></i>批改面板</h5><div class="small text-muted">${escHtml(currentRubric.rubric_name)} v${currentRubric.version_number}</div></div><span class="badge ${latest?'bg-success':'bg-warning text-dark'}">${latest?'已批改':'待批改'}</span></div>
        ${!canGrade?'<div class="alert alert-info small">學生完成心得並正式送出後才能批改。</div>':''}
        ${notesHtml}<div id="gradeCriteria">${gradeCriteriaHtml}</div>
        <div class="border-top pt-3"><div class="d-flex justify-content-between align-items-center"><span class="fw-bold">各項換算總分</span><span id="rubricScore" class="score-display">—</span></div><div class="mb-3"><label class="form-label fw-bold">老師評定成績</label><input id="finalScore" name="teacher_assigned_score" type="number" min="0" max="100" step="0.1" inputmode="decimal" class="form-control" value="${latest?latest.final_score:''}" autocomplete="off" readonly data-action-focus="clearReadonlyAttr" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" ${canGrade?'':'disabled'}></div><div class="mb-3"><label class="form-label fw-bold">總評 *</label><textarea id="teacherComment" class="form-control" rows="3" maxlength="10000" ${canGrade?'':'disabled'}>${escHtml(latest?.teacher_comment||'')}</textarea></div><div class="mb-3"><label class="form-label fw-bold">改進建議 *</label><textarea id="teacherFeedback" class="form-control" rows="3" maxlength="10000" ${canGrade?'':'disabled'}>${escHtml(latest?.teacher_feedback||'')}</textarea></div><div class="mb-3"><label class="form-label fw-bold">異動／調分理由 <span id="reasonRequired" class="text-danger"></span></label><textarea id="changeReason" class="form-control" rows="2" maxlength="5000" placeholder="調整分數或更新既有成績時必填" ${canGrade?'':'disabled'}></textarea></div>${canGrade?`<div class="d-grid gap-2"><button id="saveGradeBtn" class="btn btn-primary" data-action="saveGrade" data-args='[false]'><i class="bi bi-save me-1"></i>儲存並立即公開</button><button class="btn btn-outline-primary" data-action="saveGrade" data-args='[true]'>儲存並前往下一位待批改</button></div>`:''}</div>
        ${gradeHistory.length?`<details class="mt-4"><summary class="fw-bold cursor-pointer">成績異動紀錄（${gradeHistory.length}）</summary><div class="mt-2">${gradeHistory.map(g=>`<div class="border rounded p-2 mb-2 small"><strong>第 ${g.revision_number} 版：${g.final_score} 分</strong><br>${escHtml(g.grader_name||g.grader_student_id)} · ${new Date(g.created_at).toLocaleString('zh-TW')}${g.change_reason?`<br>理由：${escHtml(g.change_reason)}`:''}</div>`).join('')}</div></details>`:''}`;
      panel.querySelectorAll('.grade-level').forEach(select => select.addEventListener('change', () => calculateGrade(true)));
      finalScore?.addEventListener('input', updateReasonRequired);
      calculateGrade(!latest);
      guardNumericInputsAgainstCredentialAutofill(panel);
      updateReasonRequired();
    }

    function calculateGrade(setFinal=false) {
      let total=0,complete=true;
      document.querySelectorAll('.grade-level').forEach(select=>{if(select.value===''){complete=false;return;}const option=select.selectedOptions[0];total+=Number(option.dataset.awarded);});
      const score=complete?Math.round(total*100)/100:null;
      rubricScore.textContent=score===null?'—':score.toFixed(2);
      if(setFinal&&score!==null) {
        finalScore.value=score.toFixed(1);
        finalScore.dataset.expectedNumericValue=finalScore.value;
      }
      updateReasonRequired();
      return score;
    }

    function updateReasonRequired() {
      if (!document.getElementById('reasonRequired')) return;
      const rubric = Number(document.getElementById('rubricScore')?.textContent);
      const final = Number(document.getElementById('finalScore')?.value);
      reasonRequired.textContent = gradeHistory.length || (Number.isFinite(rubric) && Number.isFinite(final) && Math.abs(rubric-final)>=.05) ? '＊必填' : '';
    }

    async function saveGrade(goNext=false) {
      const panel = document.getElementById('gradingPanel');
      const submissionId = Number(panel.dataset.submissionId);
      const loadGeneration = Number(panel.dataset.loadGeneration);
      if (!Number.isInteger(submissionId) || !gradingSubmission || gradingSubmission.id !== submissionId) {
        showAlert('批改資料已切換，請確認目前的提交紀錄後再儲存。');
        return;
      }
      const finalScoreInput = panel.querySelector('#finalScore');
      const teacherCommentInput = panel.querySelector('#teacherComment');
      const teacherFeedbackInput = panel.querySelector('#teacherFeedback');
      const changeReasonInput = panel.querySelector('#changeReason');
      const ratings = {};
      let missing = false;
      panel.querySelectorAll('.grade-level').forEach(select => {
        if (select.value === '') missing = true;
        else ratings[select.dataset.key] = Number(select.value);
      });
      if (
        missing || !finalScoreInput || finalScoreInput.value === ''
        || !teacherCommentInput?.value.trim() || !teacherFeedbackInput?.value.trim()
      ) {
        showAlert('請完成所有評分項目、老師評定成績、總評與改進建議。');
        return;
      }
      const payload = {
        ratings,
        final_score: Number(finalScoreInput.value),
        teacher_comment: teacherCommentInput.value.trim(),
        teacher_feedback: teacherFeedbackInput.value.trim(),
        change_reason: changeReasonInput?.value.trim() || null,
      };
      const buttons = panel.querySelectorAll('button');
      buttons.forEach(button => { button.disabled = true; });
      let res;
      let data;
      try {
        res = await fetch(`/api/admin/submissions/${submissionId}/grades`, {
          method: 'POST',
          headers: { ...authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        data = await res.json().catch(() => ({}));
      } catch (error) {
        showAlert(`成績儲存失敗：${error.message}`);
        return;
      } finally {
        buttons.forEach(button => { button.disabled = false; });
      }
      if (!res.ok) { showAlert(data.detail || '成績儲存失敗'); return; }
      if (Array.isArray(navState?.pendingUserIds)) {
        navState.pendingUserIds = navState.pendingUserIds.filter(candidateId => candidateId !== userId);
        try {
          sessionStorage.setItem(`admin_student_nav_${assignmentId}`, JSON.stringify(navState));
        } catch (_) {}
      }
      showAlert(`成績第 ${data.revision_number} 版已公開。`, 'success');
      if (goNext) { navigateNextPending(); return; }
      if (
        loadGeneration === gradingLoadGeneration
        && panel.dataset.submissionId === String(submissionId)
      ) {
        const savedSubmission = submissions.find(item => item.id === submissionId);
        if (savedSubmission) await loadGrading(savedSubmission);
      }
    }

    // 退回階段：退到第 N 階段時，第 N 階段和之後的內容都會清掉。
    const REWIND_STEPS = [
      { stage: 1, label: '職位資料與學習鷹架' },
      { stage: 2, label: '草稿' },
      { stage: 3, label: 'AI 練習回饋' },
      { stage: 4, label: '最終草稿' },
      { stage: 5, label: '跟讀錄音' },
      { stage: 6, label: '角色扮演與 AI 回饋報告' },
      { stage: 8, label: '心得' },
    ];
    let rewindSub = null;
    let rewindTarget = null;

    function rewindButton(stage) {
      if (!stage || !rewindSub || stage > rewindSub.stage) return '';
      return `<button type="button" class="btn btn-sm btn-outline-danger ms-auto" data-action="openRewindModal" data-args='[${stage}]' title="清掉這一步和之後的內容，讓學生從這裡重新做">
        <i class="bi bi-skip-backward me-1"></i>從這裡重做
      </button>`;
    }

    function openRewindModal(stage) {
      if (!rewindSub) return;
      rewindTarget = stage;
      const label = stage === 1 ? AdminWorkflow.sectionLabel(1)
        : stage === 8 ? AdminWorkflow.sectionLabel(6)
        : AdminWorkflow.stageLabel(stage);
      document.getElementById('rewindStageLabel').textContent = label;
      const items = REWIND_STEPS.filter((step) => step.stage >= stage).map((step) => step.label);
      if (stage === 5) items[0] = '跟讀錄音（示範音檔會保留）';
      document.getElementById('rewindClearList').innerHTML = items.map((item) => `<li>${escHtml(item)}</li>`).join('');
      const notes = [];
      if (rewindSub.submitted_at) notes.push('這份作業已經交出。退回後要等學生重新完成，才能再批改。');
      const due = assignment && assignment.due_date ? new Date(assignment.due_date) : null;
      const late = rewindSub.late_deadline ? new Date(rewindSub.late_deadline) : null;
      if (due && new Date() > due && !(late && new Date() < late)) {
        notes.push('作業已經截止，記得另外設定補繳期限，學生才能繼續做。');
      }
      const noteEl = document.getElementById('rewindNotes');
      noteEl.innerHTML = notes.map((note) => `<div>${escHtml(note)}</div>`).join('');
      noteEl.classList.toggle('d-none', !notes.length);
      document.getElementById('rewindPassword').value = '';
      document.getElementById('rewindError').classList.add('d-none');
      new bootstrap.Modal(document.getElementById('rewindModal')).show();
    }

    async function confirmRewind() {
      const errorEl = document.getElementById('rewindError');
      const password = document.getElementById('rewindPassword').value.trim();
      if (!password) { errorEl.textContent = '請輸入管理員密碼'; errorEl.classList.remove('d-none'); return; }
      const btn = document.getElementById('btnConfirmRewind');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>處理中...';
      try {
        const res = await fetch(`/api/admin/assignments/${assignmentId}/students/${userId}/rewind`, {
          method: 'POST',
          headers: { ...authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ admin_password: password, target_stage: rewindTarget }),
        });
        if (res.ok) {
          bootstrap.Modal.getInstance(document.getElementById('rewindModal')).hide();
          showAlert(`已退回，學生下次進來會從「${document.getElementById('rewindStageLabel').textContent}」開始。`, 'success');
          init();
        } else {
          const d = await res.json().catch(() => ({}));
          errorEl.textContent = typeof d.detail === 'string' ? d.detail : '退回失敗，請稍後再試。';
          errorEl.classList.remove('d-none');
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '確認退回';
      }
    }

    function pendingHtml(msg) {
      return `<div class="text-muted small fst-italic"><i class="bi bi-hourglass me-1"></i>${msg}</div>`;
    }

    function stageSection(num, title, content, isDone, rewindStage = null) {
      return `
        <div class="stage-card">
          <div class="stage-header">
            <div class="stage-num ${isDone ? 'completed' : ''}">${isDone ? '<i class="bi bi-check"></i>' : num}</div>
            <span class="stage-title">${title}</span>
            ${rewindButton(rewindStage)}
          </div>
          <div class="stage-body">${content}</div>
        </div>`;
    }

    function collapsibleStageSection(title, content) {
      return `
        <details class="stage-card">
          <summary class="stage-header">
            <span class="stage-num"><i class="bi bi-shield-check"></i></span>
            <span class="stage-title">${title}</span>
            <span class="stage-toggle-text small text-muted ms-auto"></span>
            <i class="bi bi-chevron-down stage-toggle-icon text-muted" aria-hidden="true"></i>
          </summary>
          <div class="stage-body">${content}</div>
        </details>`;
    }

    function audioPlayer(key, subId, speaking) {
      return `
        <div id="audioContainer-${subId}-${speaking}">
          <button class="btn btn-outline-primary" data-action="loadAudio" data-args='[${subId},"${escAttr(speaking)}","${escAttr(key)}"]'>
            <i class="bi bi-play-circle me-1"></i>載入音訊
          </button>
        </div>`;
    }

    async function loadAudio(subId, speaking, key) {
      const container = document.getElementById(`audioContainer-${subId}-${speaking}`);
      container.innerHTML = '<span class="text-muted small"><div class="spinner-border spinner-border-sm me-1"></div>載入中...</span>';
      try {
        const res = await fetch(`/api/admin/audio-url?key=${encodeURIComponent(key)}`, { headers: authHeaders() });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          container.innerHTML = `<span class="text-danger small"><i class="bi bi-exclamation-circle me-1"></i>${err.detail || '音訊載入失敗'}</span>`;
          return;
        }
        const data = await res.json();
        const mimeType = key.endsWith('.webm') ? 'audio/webm' : 'audio/mpeg';
        container.innerHTML = `
          <audio controls class="w-100 mt-1">
            <source src="${escHtml(data.url)}" type="${mimeType}">
            您的瀏覽器不支援音訊播放。
          </audio>
          <a href="${escHtml(data.url)}" target="_blank" class="btn btn-outline-secondary mt-2">
            <i class="bi bi-download me-1"></i>下載音訊
          </a>`;
      } catch (e) {
        container.innerHTML = `<span class="text-danger small"><i class="bi bi-exclamation-circle me-1"></i>音訊載入失敗：${e.message}</span>`;
      }
    }

    function safeStr(v) {
      if (v === null || v === undefined) return '';
      if (typeof v === 'string') return v;
      return JSON.stringify(v);
    }

    function extractJsonObject(text) {
      try { const o = JSON.parse(text); return typeof o === 'object' && o && !Array.isArray(o) ? o : null; } catch {}
      let best = null, i = 0;
      while (i < text.length) {
        if (text[i] !== '{') { i++; continue; }
        const start = i;
        let depth = 0, inStr = false, esc = false, j = i;
        while (j < text.length) {
          const c = text[j];
          if (esc) { esc = false; }
          else if (c === '\\' && inStr) { esc = true; }
          else if (c === '"') { inStr = !inStr; }
          else if (!inStr) {
            if (c === '{') depth++;
            else if (c === '}') { depth--; if (depth === 0) {
              try { const o = JSON.parse(text.slice(start, j + 1)); if (o && typeof o === 'object' && !Array.isArray(o)) best = o; } catch {}
              i = j + 1; break;
            }}
          }
          j++;
        }
        if (j >= text.length) break;
      }
      return best;
    }

    // Render AI draft feedback (Stage 3)
    function renderCorrectionCards(corrections) {
      if (!corrections || corrections.length === 0) return '<div class="text-muted small">未發現英文文法或用字錯誤。</div>';
      return corrections.map(item => {
        const original = safeStr(item.original || item.error || '');
        const corrected = safeStr(item.corrected || item.correction || '');
        const explanation = safeStr(item.explanation || item.comment || '');
        return `<div class="correction-card">
          <div class="original"><i class="bi bi-x-circle me-1"></i>原句：${escHtml(original)}</div>
          <div class="corrected"><i class="bi bi-check-circle me-1"></i>修正：${escHtml(corrected)}</div>
          ${explanation ? `<div class="explanation"><i class="bi bi-chat-left-text me-1"></i>說明：${escHtml(explanation)}</div>` : ''}
        </div>`;
      }).join('');
    }

    function renderFeedback(obj, draft1Answers = []) {
      if (!obj) return '';
      if (typeof obj === 'string') return `<div class="feedback-box"><pre>${escHtml(obj)}</pre></div>`;

      if (obj.raw) {
        const recovered = extractJsonObject(obj.raw);
        if (recovered && !recovered.raw) return renderFeedback(recovered, draft1Answers);
      }

      let html = '';
      const qs = (assignment && Array.isArray(assignment.questions)) ? assignment.questions : [];
      const draftQuestionMap = {};
      (draft1Answers || []).forEach(item => {
        if (item && item.index != null && item.question) draftQuestionMap[item.index] = item.question;
      });

      // New per-question format
      if (obj.questions && Array.isArray(obj.questions) && obj.questions.length > 0) {
        obj.questions.forEach(q => {
          const totalCorrections = (q.grammar_corrections || []).length;
          const qText = q.question || draftQuestionMap[q.index] || qs[q.index] || '';
          html += `<div class="mb-3 p-3 rounded panel-muted">
            <div class="small fw-bold mb-2 text-brand"><i class="bi bi-chat-quote me-1"></i>Q${q.index+1}${qText ? '：' + escHtml(qText) : ''}</div>
            <div class="mb-3">
              <div class="small fw-bold text-danger mb-2"><i class="bi bi-pencil-fill me-1"></i>文法修正（${totalCorrections} 處）</div>
              ${renderCorrectionCards(q.grammar_corrections)}
            </div>
            ${q.polished_sample ? `<div>
              <div class="small fw-bold text-success mb-2"><i class="bi bi-stars me-1"></i>建議範文</div>
              <div class="polished-box"><pre>${escHtml(safeStr(q.polished_sample))}</pre></div>
            </div>` : ''}
          </div>`;
        });
      } else {
        // Legacy flat format — group corrections by question using draft1 answer text matching
        const draft1Map = {};
        (draft1Answers || []).forEach(item => { if (item && item.index != null) draft1Map[item.index] = item.text || ''; });
        const numQ = qs.length;
        const corrByQ = Array.from({ length: numQ }, () => []);
        const unmatched = [];
        if (obj.grammar_corrections && Array.isArray(obj.grammar_corrections)) {
          obj.grammar_corrections.forEach(c => {
            let hit = false;
            for (let i = 0; i < numQ; i++) {
              const ans = draft1Map[i] || '';
              if (ans && c.original && ans.includes(c.original)) { corrByQ[i].push(c); hit = true; break; }
            }
            if (!hit) unmatched.push(c);
          });
        }
        if (numQ > 0) {
          qs.forEach((qText, i) => {
            const corrs = corrByQ[i];
            if (!corrs.length) return;
            html += `<div class="mb-3 p-3 rounded panel-muted">
              <div class="small fw-bold mb-2 text-brand"><i class="bi bi-chat-quote me-1"></i>Q${i+1}：${escHtml(qText)}</div>
              <div class="small fw-bold text-danger mb-2"><i class="bi bi-pencil-fill me-1"></i>文法修正（${corrs.length} 處）</div>
              ${renderCorrectionCards(corrs)}
            </div>`;
          });
          if (unmatched.length > 0) {
            html += `<div class="mb-3">
              <div class="small fw-bold text-danger mb-2"><i class="bi bi-pencil-fill me-1"></i>其他文法修正（${unmatched.length} 處）</div>
              ${renderCorrectionCards(unmatched)}
            </div>`;
          }
        } else {
          if (obj.grammar_corrections && Array.isArray(obj.grammar_corrections)) {
            html += `<div class="mb-4">
              <div class="small fw-bold text-danger mb-2"><i class="bi bi-pencil-fill me-1"></i>文法修正（${obj.grammar_corrections.length} 處）</div>
              ${renderCorrectionCards(obj.grammar_corrections)}
            </div>`;
          }
        }
        if (obj.polished_sample) {
          html += `<div class="mb-2">
            <div class="small fw-bold text-success mb-2"><i class="bi bi-stars me-1"></i>建議範文</div>
            <div class="polished-box"><pre>${escHtml(safeStr(obj.polished_sample))}</pre></div>
          </div>`;
        }
      }

      // Organization suggestions (always shown at end)
      if (obj.organization_suggestions && Array.isArray(obj.organization_suggestions)) {
        html += `<div class="mb-4">
          <div class="small fw-bold text-primary mb-2"><i class="bi bi-diagram-3 me-1"></i>組織架構建議</div>
          <ul class="mb-0">
            ${obj.organization_suggestions.map(s => `<li class="mb-1 small">${escHtml(safeStr(s))}</li>`).join('')}
          </ul>
        </div>`;
      }

      if (obj.raw && !html) {
        html += `<div class="feedback-box"><pre>${escHtml(obj.raw)}</pre></div>`;
      }

      // Fallback: render any remaining keys generically
      const handled = ['questions','grammar_corrections','organization_suggestions','polished_sample','raw'];
      for (const [k, v] of Object.entries(obj)) {
        if (handled.includes(k)) continue;
        html += renderGenericKey(k, v);
      }

      return html || `<div class="feedback-box"><pre>${escHtml(JSON.stringify(obj, null, 2))}</pre></div>`;
    }

    function feedbackBulletItems(value) {
      if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean);
      const text = String(value || '').trim();
      if (!text) return [];
      const lines = text.split(/\n+/).flatMap(line => line.match(/[^。！？]+[。！？]?/g) || []);
      return lines.map(item => item.trim()).filter(Boolean);
    }

    // Render formative AI feedback (Stage 8)
    function renderReport(obj) {
      if (!obj) return '';
      if (typeof obj === 'string') return `<div class="feedback-box"><pre>${escHtml(obj)}</pre></div>`;

      let html = '';

      // Analysis
      if (obj.analysis && typeof obj.analysis === 'object') {
        const analysisLabels = {
          language_complexity: '語言豐富度',
          language_accuracy: '語言準確度',
          content_logic: '內容邏輯與組織', interview_strategy: '面試策略與表現效果'
        };
        html += `<div class="mb-4">
          <div class="small fw-bold text-secondary mb-2"><i class="bi bi-clipboard-data me-1"></i>質性分析</div>
          <div class="feedback-box">`;
        for (const [k, v] of Object.entries(obj.analysis)) {
          const label = analysisLabels[k] || k;
          const items = feedbackBulletItems(v);
          if (!items.length) continue;
          html += `<div class="analysis-item">
            <div class="analysis-label">${escHtml(label)}</div>
            <ul class="mb-0 ps-3">${items.map(item => `<li class="mb-1">${escHtml(item)}</li>`).join('')}</ul>
          </div>`;
        }
        html += '</div></div>';
      }

      // Strengths
      const strengths = feedbackBulletItems(obj.strengths);
      if (strengths.length) {
        html += `<div class="mb-4">
          <div class="small fw-bold text-success mb-2"><i class="bi bi-hand-thumbs-up me-1"></i>表現優點</div>
          <ul class="mb-0">${strengths.map(s => `<li class="small mb-1">${escHtml(s)}</li>`).join('')}</ul>
        </div>`;
      }

      // Overall suggestions
      const suggestions = feedbackBulletItems(obj.overall_suggestions);
      if (suggestions.length) {
        html += `<div class="mb-2">
          <div class="small fw-bold text-warning mb-2"><i class="bi bi-lightbulb me-1"></i>整體建議</div>
          <ul class="mb-0">${suggestions.map(s => `<li class="small mb-1">${escHtml(s)}</li>`).join('')}</ul>
        </div>`;
      }


      // Fallback for raw data
      if (!html) {
        html = `<div class="feedback-box"><pre>${escHtml(JSON.stringify(obj, null, 2))}</pre></div>`;
      }

      return html;
    }

    function renderGenericKey(k, v) {
      const keyLabels = {
        fluency: '流暢度', clarity: '清晰度', organization: '組織架構',
        pragmatics: '語用適切性', gap_analysis: '書面與口說落差',
        overall_suggestions: '整體建議', grammar_corrections: '文法修正',
        organization_suggestions: '組織建議', polished_sample: '建議範文'
      };
      const label = keyLabels[k] || k;
      if (Array.isArray(v)) {
        return `<p class="small fw-bold mb-1">${escHtml(label)}：</p>
          <ul class="mb-3">${v.map(i => {
            if (typeof i === 'object' && i !== null) {
              return `<li class="small">${Object.entries(i).map(([ik,iv]) => `<strong>${escHtml(ik)}：</strong>${escHtml(String(iv))}`).join(' | ')}</li>`;
            }
            return `<li class="small">${escHtml(String(i))}</li>`;
          }).join('')}</ul>`;
      } else {
        return `<p class="small"><strong>${escHtml(label)}：</strong>${escHtml(String(v))}</p>`;
      }
    }

    async function exportStudentAll() {
      const btn = document.getElementById('btnExportAll');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>匯出中...';
      try {
        const res = await fetch(`/api/admin/assignments/${assignmentId}/students/${userId}/export-words`, {
          credentials: 'include'
        });
        if (!res.ok) { showAlert((await res.json().catch(() => ({}))).detail || '匯出失敗'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = getFilename(res, `assignment_${assignmentId}_student_${userId}_all.zip`);
        a.click();
        URL.revokeObjectURL(url);
        if (res.headers.get('X-Export-Partial') === 'true') {
          showAlert('部分 Word 匯出失敗；壓縮檔內含失敗清單。', 'warning');
        }
      } catch (e) { showAlert('匯出失敗：' + e.message); }
      finally { btn.disabled = false; btn.innerHTML = '<i class="bi bi-file-earmark-zip me-1"></i>匯出全部'; }
    }

    async function exportStudentLatest() {
      const btn = document.querySelector('[id^="btnWord-"]');
      if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>匯出中...'; }
      try {
        const res = await fetch(`/api/admin/assignments/${assignmentId}/students/${userId}/export-words-latest`, {
          credentials: 'include'
        });
        if (!res.ok) { showAlert((await res.json().catch(() => ({}))).detail || '匯出失敗'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = getFilename(res, `assignment_${assignmentId}_student_${userId}_latest.docx`);
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) { showAlert('匯出失敗：' + e.message); }
      finally { if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-file-earmark-word me-1"></i>匯出 Word'; } }
    }

    async function exportWord(subId) {
      const btn = document.getElementById(`btnWord-${subId}`);
      const orig = btn.innerHTML;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>產生中...';
      btn.disabled = true;
      try {
        const res = await fetch(`/api/admin/submissions/${subId}/export-word`, {
          credentials: 'include'
        });
        if (!res.ok) { showAlert((await res.json().catch(()=>({}))).detail || 'Word 匯出失敗'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = getFilename(res, `submission_${subId}.docx`);
        a.click();
        URL.revokeObjectURL(url);
      } catch(e) { showAlert('Word 匯出失敗：' + e.message); }
      finally { btn.innerHTML = orig; btn.disabled = false; }
    }

    async function exportAudio(subId) {
      const btn = document.getElementById(`btnAudio-${subId}`);
      const orig = btn.innerHTML;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>打包中...';
      btn.disabled = true;
      try {
        const res = await fetch(`/api/admin/submissions/${subId}/export-audio`, {
          credentials: 'include'
        });
        if (!res.ok) { showAlert((await res.json().catch(()=>({}))).detail || '音檔匯出失敗'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = getFilename(res, `submission_${subId}_audio.zip`);
        a.click();
        URL.revokeObjectURL(url);
      } catch(e) { showAlert('音檔匯出失敗：' + e.message); }
      finally { btn.innerHTML = orig; btn.disabled = false; }
    }

    async function rescoreReport(subId) {
      const btn = document.getElementById(`btnRescore-${subId}`);
      const orig = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>產生中...';
      try {
        const res = await fetch(`/api/admin/submissions/${subId}/rescore`, {
          method: 'POST', headers: authHeaders()
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          showAlert('重新產生回饋失敗：' + (d.detail || res.statusText));
          return;
        }
        const updated = await res.json();
        const idx = submissions.findIndex(s => s.id === subId);
        if (idx !== -1) submissions[idx] = updated;
        renderAttempt();
        showAlert('學習回饋已重新產生。', 'success');
      } catch (e) {
        showAlert('重新產生回饋失敗：' + e.message);
      } finally {
        const b = document.getElementById(`btnRescore-${subId}`);
        if (b) { b.disabled = false; b.innerHTML = orig; }
      }
    }

    function allowRetake() {
      document.getElementById('retakePassword').value = '';
      document.getElementById('retakeError').classList.add('d-none');
      new bootstrap.Modal(document.getElementById('retakeModal')).show();
      setTimeout(() => document.getElementById('retakePassword').focus(), 300);
    }

    function openLateDeadlineModal() {
      const latest = submissions.length ? submissions[submissions.length - 1] : null;
      const existing = latest?.late_deadline;
      if (existing) {
        const iso = existing.replace(' ', 'T').slice(0, 16);
        document.getElementById('lateDeadlineDate').value = iso;
        if (window._dtpLate) window._dtpLate.syncFromHidden();
      } else {
        document.getElementById('lateDeadlineDate').value = '';
        if (window._dtpLate) window._dtpLate.clear();
      }
      document.getElementById('lateDeadlinePassword').value = '';
      document.getElementById('lateDeadlineError').classList.add('d-none');
      new bootstrap.Modal(document.getElementById('lateDeadlineModal')).show();
    }

    async function confirmLateDeadline() {
      const password = document.getElementById('lateDeadlinePassword').value.trim();
      if (!password) { document.getElementById('lateDeadlineError').textContent = '請輸入管理員密碼'; document.getElementById('lateDeadlineError').classList.remove('d-none'); return; }
      const lateVal = document.getElementById('lateDeadlineDate').value;
      const btn = document.getElementById('btnConfirmLateDeadline');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>處理中...';
      try {
        const res = await fetch(`/api/admin/assignments/${assignmentId}/students/${userId}/late-deadline`, {
          method: 'POST',
          headers: { ...authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ admin_password: password, late_deadline: lateVal || null })
        });
        if (res.ok) {
          const data = await res.json();
          bootstrap.Modal.getInstance(document.getElementById('lateDeadlineModal')).hide();
          if (lateVal && data.email_sent === false) {
            showAlert(`已設定補繳期限至 ${lateVal.replace('T', ' ')}，但通知信寄送失敗，請確認學生信箱設定。`, 'warning');
          } else {
            showAlert(lateVal ? `已設定補繳期限至 ${lateVal.replace('T', ' ')}，並已寄送通知信。` : '已清除補繳設定。', 'success');
          }
          init();
        } else {
          const d = await res.json();
          document.getElementById('lateDeadlineError').textContent = d.detail || '發生錯誤';
          document.getElementById('lateDeadlineError').classList.remove('d-none');
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '確認設定';
      }
    }

    async function confirmRetake() {
      const password = document.getElementById('retakePassword').value.trim();
      if (!password) { document.getElementById('retakeError').textContent = '請輸入管理員密碼'; document.getElementById('retakeError').classList.remove('d-none'); return; }
      const btn = document.getElementById('btnConfirmRetake');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>處理中...';
      try {
        const res = await fetch(`/api/admin/assignments/${assignmentId}/students/${userId}/retake`, {
          method: 'POST',
          headers: { ...authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ admin_password: password })
        });
        if (res.ok) {
          bootstrap.Modal.getInstance(document.getElementById('retakeModal')).hide();
          showAlert('已允許重作，已建立新的嘗試記錄。', 'success');
          init();
        } else {
          const d = await res.json();
          document.getElementById('retakeError').textContent = d.detail || '發生錯誤';
          document.getElementById('retakeError').classList.remove('d-none');
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = '確認允許重作';
      }
    }

    // This controller is an ES module, so its declarations are not globals.
    // The shared CSP-safe action delegator resolves data-action names through
    // window; expose every page-owned action before the asynchronous init can
    // render buttons that depend on them.
    Object.assign(window, {
      goBack,
      navigatePrev,
      navigateNext,
      renderAttempt,
      viewIssuePhoto,
      saveGrade,
      loadAudio,
      exportStudentAll,
      exportWord,
      exportAudio,
      rescoreReport,
      allowRetake,
      openLateDeadlineModal,
      confirmLateDeadline,
      confirmRetake,
      openRewindModal,
      confirmRewind,
    });

    init();

    document.addEventListener('DOMContentLoaded', () => {
      window._dtpLate = new DateTimePicker('lateDeadlineDate', { placeholder: '選擇補繳截止日期時間' });
      document.addEventListener('click', () => {
        DateTimePicker.closeAll();
      });
    });
