window.assignmentId = parseInt(location.pathname.split('/')[3]);
const params=new URLSearchParams(location.search);
window.viewId = params.get('view')?parseInt(params.get('view')):null;
window.assignment = null;
window.submission = null;
window.viewedSubmission = null;
let previousSubmission=null;
function listItems(items){return(items||[]).filter(Boolean).slice(0,2).map(item=>`<li>${escHtml(item)}</li>`).join('');}
function applyProfileFields(p){const profile=p||{};desiredPosition.value=profile.desired_position||'';roleDescription.value=profile.role_description||'';competencies.value=profile.required_competencies||'';additionalNotes.value=profile.additional_notes||'';}
function usePreviousProfile(){const p=previousSubmission&&previousSubmission.job_profile_data;if(!p)return;applyProfileFields(p);prefillNotice.classList.add('d-none');showAlert('已帶入上次的職位資料，請確認是否仍符合這次練習目標。','success');desiredPosition.focus();}
async function loadProfilePrefill(v,locked){
  if(viewId||locked||v.job_profile_data)return;
  try{
    const r=await apiCall(`/api/student/submissions/${v.id}/job-profile/prefill`);
    if(!r.ok)throw new Error('prefill request failed');
    const p=await r.json();
    if(!p)return;
    applyProfileFields(p);
    prefillNotice.classList.remove('d-none');
  }catch(error){
    showAlert('無法自動帶入最近一次儲存的職位資料，請手動填寫。');
  }
}
async function loadPreviousLearning(v){if(viewId||!v||v.attempt_number<=1)return;const showFailure=()=>{priorLearning.classList.remove('d-none');priorLearning.innerHTML='<div class="alert alert-warning mb-0">前次學習資料載入失敗；本次仍可繼續填寫，稍後重新整理可再試一次。</div>';};try{const r=await apiCall(`/api/student/assignments/${assignmentId}/attempts`);if(!r.ok){showFailure();return;}const attempts=await r.json();const previous=[...attempts].reverse().find(item=>item.attempt_number<v.attempt_number&&item.submitted_at);if(!previous)return;const detail=await apiCall(`/api/student/submissions/${previous.id}`);if(!detail.ok){showFailure();return;}previousSubmission=await detail.json();const report=tryParseJson(previousSubmission.report_data)||{};const reflection=previousSubmission.reflection_data||{};const answers=Array.isArray(reflection.answers)?reflection.answers:[];const strengths=listItems(report.strengths);const suggestions=listItems(report.overall_suggestions);const reflectionFocus=answers[2]||'';const nextAction=answers[4]||'';priorLearning.classList.remove('d-none');priorLearning.innerHTML=`<section class="carryover-card" aria-label="上次練習帶入本次"><div class="d-flex justify-content-between align-items-start gap-3 flex-wrap mb-3"><div><div class="small fw-bold text-success mb-1">第 ${previousSubmission.attempt_number} 次練習 → 第 ${v.attempt_number} 次練習</div><h5 class="fw-bold mb-1">先回顧證據，再決定本次焦點</h5><p class="text-muted small mb-0">不要只是重做相同流程；選一項上次的建議，在這次回答中刻意練習。</p></div><div class="d-flex gap-2 flex-wrap"><button type="button" class="btn btn-sm btn-outline-success" data-action="usePreviousProfile"><i class="bi bi-arrow-repeat me-1"></i>沿用上次職位資料</button><a class="btn btn-sm btn-outline-primary" href="/student/assignment/${assignmentId}/report?view=${previousSubmission.id}">查看完整結果</a></div></div><div class="carryover-grid"><div class="carryover-item"><h6><i class="bi bi-stars me-1"></i>上次做得好的地方</h6>${strengths?`<ul>${strengths}</ul>`:'<p class="text-muted small mb-0">上次報告沒有列出優勢摘要。</p>'}</div><div class="carryover-item"><h6><i class="bi bi-lightbulb me-1"></i>上次優先改善建議</h6>${suggestions?`<ul>${suggestions}</ul>`:'<p class="text-muted small mb-0">上次報告沒有列出改善摘要。</p>'}</div></div>${reflectionFocus?`<div class="carryover-action"><strong>上次自我判斷：</strong>${escHtml(reflectionFocus)}</div>`:''}${nextAction?`<div class="carryover-action"><strong>上次訂下的行動：</strong>${escHtml(nextAction)}</div>`:''}</section>`;}catch(_){showFailure();}}
function rubricLevelPoints(level,criterionPoints){return level&&level.points!=null?Number(level.points):Number(criterionPoints)*Number(level&&level.ratio!=null?level.ratio:0);}
function studentRubricHtml(v){const shared=v.definition.levels||[],notes=v.definition.notes||[];const notesHtml=notes.length?`<div class="alert alert-warning small"><strong>評分注意事項</strong><ul class="mb-0 mt-1 ps-3">${notes.map(note=>`<li>${escHtml(note)}</li>`).join('')}</ul></div>`:'';const dimensions=(v.definition.dimensions||[]).map(d=>`<div class="rubric-dimension"><strong>${escHtml(d.name)}（${d.weight} 分）</strong>${d.criteria.map(c=>{const levels=Array.isArray(c.levels)&&c.levels.length?c.levels:shared;return `<div class="mt-2"><div>${escHtml(c.name)}：${c.points} 分</div><div class="small text-muted">${escHtml(c.description||'')}</div><ul class="small mb-0 mt-2 ps-3">${levels.map(level=>`<li class="mb-1"><strong>${rubricLevelPoints(level,c.points)} 分｜${escHtml(level.label)}</strong>：${escHtml(level.anchor||'')}</li>`).join('')}</ul></div>`;}).join('')}</div>`).join('');return `<p class="mb-2"><strong>${escHtml(v.rubric_name)} v${v.version_number}</strong></p>${notesHtml}${dimensions}`;}
async function loadRubric(submissionId){const box=document.getElementById('rubricBox');try{const r=await apiCall(`/api/student/submissions/${submissionId}/rubric`);if(!r.ok)throw new Error();const v=await r.json();box.innerHTML=studentRubricHtml(v);}catch(_){box.innerHTML='<div class="alert alert-warning mb-0">評分規準載入失敗，請稍後重新整理。</div>';}}
function renderProfileTaskGuide(v,locked){
  const repeated=Number(v.attempt_number)>1;
  const state=locked?(viewId||v.submitted_at?'completed':'read-only'):'active';
  if(state!=='active')return renderTaskGuide({title:'職位資料已設定',progress:'職位、工作內容與能力已帶入本次練習',next:'回看這些資料時，確認後面的回答是否真的符合這份工作。',view:v,state});
  return renderTaskGuide({
    title:repeated?'先選定這次只改一件事':'先選定這次要練的職位',
    progress:repeated?'先回顧上次，再設定本次焦點':'3 個必填欄位＋1 個選填欄位',
    actions:repeated?[
      '先看下方的上次改善建議與後續行動。',
      '確認這次是否沿用同一個職位；沿用時仍要檢查內容。',
      '只選一項本次焦點，寫在「其他補充」，例如「每題多補一個具體例子」。',
    ]:[
      '填一個明確職稱，例如「飯店櫃檯人員」，不要只寫「服務業」。',
      '用自己的話整理這份工作主要會做的 2–3 件事。',
      '列出 2–3 項必要能力；有相關課堂專題、社團、打工或實習經驗，也可寫在「其他補充」。',
    ],
    support:{
      title:'卡住時',
      items:repeated?[
        '先選上次最常出現、也最能在這次練到的一項問題。',
        '焦點要寫成看得出動作的句子，不只寫「加強英文」。',
      ]:[
        '不熟悉職位時，可先參考 104、1111 或公司徵才頁，再改寫成自己的話。',
        '能力可從溝通、問題解決、英文應用、數位工具或服務經驗中挑選。',
      ],
      html:`${learningScaffoldModuleHtml()}${learningScaffoldStageHtml(v,'job_profile')}`,
    },
    checks:repeated?[
      '職位資料仍符合這次要練的情境。',
      '本次焦點只有一項，而且看得出要怎麼做。',
      '我知道要在哪些回答中練這個焦點。',
    ]:[
      '職位名稱明確，不只有產業名稱。',
      '工作內容與必要能力都有具體描述。',
      '內容是我理解後整理的，不是整段照貼職缺。',
    ],
    next:'儲存後進入寫作；系統會用這些資料判斷回答是否符合職位。',
    view:v,
    state,
  });
}
async function init(){await window.practiceLaunchReady;let{response:r,data:d}=await StudentPracticeRuntime.assignmentContext();if(!r.ok){document.getElementById('loadingMsg').textContent=d.detail||'載入失敗';return;}setWorkflowLimits(d.workflow_limits);assignment=d.assignment;submission=d.submission;if(!submission&&!viewId){r=await apiCall(`/api/student/assignments/${assignmentId}/start`,{method:'POST'});submission=await r.json();if(!r.ok){document.getElementById('loadingMsg').textContent=submission.detail||'無法開始作業';return;}await StudentPracticeRuntime.recordPracticeStart(submission);}if(viewId){try{viewedSubmission=await loadViewedSubmissionForAssignment(viewId,assignmentId);}catch(error){renderStudentPageLoadError(error);return;}}
  const v=getView();if(!v){renderStudentPageLoadError(new Error('找不到這筆練習紀錄。'));return;}
  document.getElementById('assignmentTitle').textContent=assignment.title;document.getElementById('assignmentDesc').textContent=assignment.description||'';renderAttemptBadge(v);updateProgressSteps(v.stage);renderViewBanner();
  const p=v.job_profile_data||{};applyProfileFields(p);const locked=!!viewId||!!p.is_locked||!!v.submitted_at||isPastDue();profileLearningGuide.innerHTML=renderProfileTaskGuide(v,locked);await loadProfilePrefill(v,locked);if(locked){profileForm.querySelectorAll('input,textarea,button').forEach(el=>el.disabled=true);lockedNotice.classList.remove('d-none');saveBtn.classList.add('d-none');}
  document.getElementById('loadingMsg').classList.add('d-none');document.getElementById('content').classList.remove('d-none');await loadPreviousLearning(v);
  await loadRubric(v.id);
}
profileForm.addEventListener('submit',async e=>{
  e.preventDefault();
  saveBtn.disabled=true;
  saveSpinner.classList.remove('d-none');
  const body={desired_position:desiredPosition.value,role_description:roleDescription.value,required_competencies:competencies.value,additional_notes:additionalNotes.value||null};
  const r=await apiCall(`/api/student/submissions/${submission.id}/job-profile`,{method:'PUT',body:JSON.stringify(body)});
  const d=await r.json();
  if(!r.ok){saveBtn.disabled=false;saveSpinner.classList.add('d-none');showAlert(d.detail||'儲存失敗');return;}
  submission.job_profile_data=d;
  submission.learning_scaffold_status=submission.question_set_key?'missing':'not_applicable';
  showAlert(submission.question_set_key?'職位資料已儲存，正在建立四題不同的個人化提示。':'職位資料已儲存。','success');
  if(submission.question_set_key)await retryLearningScaffold();
  saveBtn.disabled=false;
  saveSpinner.classList.add('d-none');
  navigateStudentPage(`/student/assignment/${assignmentId}/${submission.stage>=8?'report':'writing'}`);
});
init().catch(error=>renderStudentPageLoadError(error));

Object.assign(window, {
  listItems,
  applyProfileFields,
  usePreviousProfile,
  loadProfilePrefill,
  loadPreviousLearning,
  rubricLevelPoints,
  studentRubricHtml,
  loadRubric,
  renderProfileTaskGuide,
  init,
});
