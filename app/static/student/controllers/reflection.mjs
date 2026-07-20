window.assignmentId = parseInt(location.pathname.split('/')[3]);
const params=new URLSearchParams(location.search);
window.viewId = params.get('view')?parseInt(params.get('view')):null;
const AUTOSAVE_DELAY_MS=1000;
const LOCAL_DRAFT_PREFIX='meet:reflection-draft:';
window.assignment = null;
window.submission = null;
window.viewedSubmission = null;
let reflectionDraft=null;
let autosaveEnabled=false,saveTimer=null,saveWorkerPromise=null;
let editRevision=0,savedRevision=0,serverUpdatedAt=null,serverDraftExists=false;
let localBackupHealthy=true,pendingRecovery=null;
let currentPhotoData={},photoUploadPromise=null,photoUploadFailed=false;
let allowNavigation=false,isSubmitting=false;
const questions=['這次練習中，你最滿意或最有進步的地方是什麼？請舉一個具體例子。','寫作、跟讀、角色扮演中，哪一部分最有挑戰？你遇到什麼困難，又如何處理？','看完 AI 回饋後，你認為自己的一項優勢與一項最需要改進的地方是什麼？','如果重新進行一次面試，你會如何調整準備方式或回答內容？','請訂下一個具體行動：要做什麼、何時完成、如何確認自己有進步？'];

function rawFormBody(){
  return{
    answers:[...document.querySelectorAll('.reflection-answer')].map(x=>x.value.slice(0,3000)),
    has_issue:hasIssue.checked,
    issue_category:hasIssue.checked?issueCategory.value:null,
    issue_description:hasIssue.checked?issueDescription.value.slice(0,3000):null,
  };
}

function formBody(state=rawFormBody()){
  return{
    answers:(state.answers||[]).map(value=>String(value||'').trim()),
    has_issue:!!state.has_issue,
    issue_category:state.has_issue?String(state.issue_category||'').trim()||null:null,
    issue_description:state.has_issue?String(state.issue_description||'').trim()||null:null,
  };
}

function setSaveStatus(kind,message){
  saveStatus.className=`save-status ${kind||''}`.trim();
  saveStatus.textContent=message;
}

function formatSavedTime(value){
  if(!value)return'';
  const date=new Date(value);
  if(Number.isNaN(date.getTime()))return'';
  return date.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'});
}

function setSavedStatus(value=serverUpdatedAt){
  const time=formatSavedTime(value);
  setSaveStatus('saved',time?`已於 ${time} 儲存`:'已儲存');
}

function adoptServerUpdatedAt(value){
  if(!value)return;
  if(!serverUpdatedAt){serverUpdatedAt=value;return;}
  const currentTime=new Date(serverUpdatedAt).getTime();
  const nextTime=new Date(value).getTime();
  if(Number.isNaN(currentTime)||Number.isNaN(nextTime)||nextTime>=currentTime)serverUpdatedAt=value;
}

function persistLocalDraft(state=rawFormBody()){
  if(!reflectionDraft)return false;
  try{
    reflectionDraft.write(state,editRevision);
    localBackupHealthy=true;
    return true;
  }catch(_){
    localBackupHealthy=false;
    return false;
  }
}

function readLocalDraft(){
  if(!reflectionDraft)return null;
  try{
    return reflectionDraft.read();
  }catch(_){return null;}
}

function clearLocalDraft(){
  if(!reflectionDraft)return;
  try{reflectionDraft.clear();localBackupHealthy=true;}catch(_){localBackupHealthy=false;}
}

function applyFormState(data){
  const answers=Array.isArray(data&&data.answers)?data.answers:[];
  document.querySelectorAll('.reflection-answer').forEach((input,index)=>{input.value=String(answers[index]||'').slice(0,3000);});
  hasIssue.checked=!!(data&&data.has_issue);
  issueCategory.value=(data&&data.issue_category)||'';
  issueDescription.value=(data&&data.issue_description)||'';
  issueFields.classList.toggle('d-none',!hasIssue.checked);
  const v=getView();
  if(v)reflectionGuide.innerHTML=renderReflectionTaskGuide(v,{answers});
}

function setEditingDisabled(disabled){
  reflectionForm.querySelectorAll('textarea,input,select,button').forEach(el=>{el.disabled=disabled;});
}

function scheduleAutosave(delay=AUTOSAVE_DELAY_MS){
  clearTimeout(saveTimer);
  if(!autosaveEnabled||savedRevision>=editRevision)return;
  if(!navigator.onLine){
    setSaveStatus('error',localBackupHealthy?'連線中斷，已保存在此裝置':'無法備份，請勿離開此頁');
    return;
  }
  saveTimer=setTimeout(()=>{saveTimer=null;void drainSaveQueue();},delay);
}

function markDraftDirty(){
  if(!autosaveEnabled)return;
  editRevision+=1;
  const backedUp=persistLocalDraft();
  setSaveStatus(backedUp?'':'error',backedUp?'尚未儲存':'無法備份，請立即儲存且不要離開此頁');
  scheduleAutosave();
}

function presentRecoveryChoice(recovery,data,headline='偵測到兩個不同版本的心得草稿'){
  pendingRecovery=recovery;
  autosaveEnabled=false;
  setEditingDisabled(true);
  const localTime=recovery.saved_at?new Date(recovery.saved_at).toLocaleString('zh-TW'):'未知時間';
  const serverTime=data.updated_at?new Date(data.updated_at).toLocaleString('zh-TW'):'尚未建立';
  recoveryNotice.classList.remove('d-none');
  recoveryNotice.innerHTML=`<strong><i class="bi bi-exclamation-triangle-fill me-1"></i>${escHtml(headline)}</strong><div class="small mt-2">此裝置備份：${escHtml(localTime)}；伺服器草稿：${escHtml(serverTime)}。請選擇要繼續編輯的版本，系統不會自動覆蓋。</div><div class="recovery-actions"><button type="button" class="btn btn-warning btn-sm" data-action="recoverLocalDraft">復原此裝置草稿</button><button type="button" class="btn btn-outline-secondary btn-sm" data-action="keepServerDraft">使用伺服器草稿</button></div>`;
}

function handleRevisionConflict(detail,localState){
  const latest=detail&&detail.latest;
  if(!latest||!reflectionDraft)return false;
  const recovery={
    submission_id:submission.id,
    assignment_id:assignmentId,
    base_revision:reflectionDraft.revision,
    saved_at:new Date().toISOString(),
    revision:editRevision,
    data:localState,
  };
  persistLocalDraft(localState);
  reflectionDraft.adopt(latest);
  serverDraftExists=true;
  adoptServerUpdatedAt(latest.updated_at);
  applyFormState(latest);
  loadPhoto(latest);
  presentRecoveryChoice(recovery,latest,detail.message||'心得已在其他分頁更新');
  setSaveStatus('error','偵測到版本衝突，已停止自動儲存');
  return true;
}

async function saveLatestSnapshot(){
  const targetRevision=editRevision;
  const state=rawFormBody();
  setSaveStatus('saving','正在自動儲存…');
  try{
    const response=await apiCall(`/api/student/submissions/${submission.id}/reflection`,{
      method:'PUT',body:JSON.stringify(reflectionDraft.withExpectedRevision(formBody(state))),
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok){
      const conflict=reflectionDraft.conflictDetail(data);
      if(conflict&&handleRevisionConflict(conflict,state))return false;
      throw new Error(typeof data.detail==='string'?data.detail:'儲存失敗');
    }
    reflectionDraft.adopt(data);
    serverDraftExists=true;
    savedRevision=Math.max(savedRevision,targetRevision);
    adoptServerUpdatedAt(data.updated_at);
    if(editRevision===targetRevision){
      clearLocalDraft();
      setSavedStatus();
    }else{
      persistLocalDraft();
    }
    return true;
  }catch(error){
    const backedUp=persistLocalDraft();
    setSaveStatus('error',backedUp?`未同步：${error.message||'連線失敗'}；已保存在此裝置`:(error.message||'儲存失敗，請勿離開此頁'));
    return false;
  }
}

async function drainSaveQueue(){
  if(!autosaveEnabled||savedRevision>=editRevision)return true;
  if(saveWorkerPromise)return saveWorkerPromise;
  saveWorkerPromise=(async()=>{
    while(autosaveEnabled&&savedRevision<editRevision){
      if(!await saveLatestSnapshot())return false;
    }
    return true;
  })();
  try{return await saveWorkerPromise;}finally{saveWorkerPromise=null;}
}

async function flushTextDraft(forceCreate=false){
  clearTimeout(saveTimer);saveTimer=null;
  if(forceCreate&&autosaveEnabled&&!serverDraftExists&&savedRevision>=editRevision){
    editRevision+=1;persistLocalDraft();
  }
  while(autosaveEnabled&&savedRevision<editRevision){
    if(!await drainSaveQueue())return false;
  }
  return true;
}

function restoreLocalDraftIfNeeded(data){
  const recovery=readLocalDraft();
  if(!recovery)return;
  const sameBase=reflectionDraft.hasSameBase(recovery);
  if(sameBase){
    applyFormState(recovery.data);
    editRevision=1;savedRevision=0;
    persistLocalDraft();
    setSaveStatus('error','已復原上次中斷前內容，準備同步');
    scheduleAutosave(0);
    showAlert('已復原上次中斷前尚未上傳的心得內容。','success');
    return;
  }
  presentRecoveryChoice(recovery,data);
}

function finishRecoveryChoice(){
  pendingRecovery=null;
  recoveryNotice.classList.add('d-none');
  recoveryNotice.innerHTML='';
  setEditingDisabled(false);
  autosaveEnabled=true;
}

function recoverLocalDraft(){
  if(!pendingRecovery)return;
  const state=pendingRecovery.data;
  finishRecoveryChoice();
  applyFormState(state);
  editRevision=1;savedRevision=0;
  persistLocalDraft();
  setSaveStatus('error','已復原此裝置草稿，準備同步');
  scheduleAutosave(0);
}

function keepServerDraft(){
  if(!pendingRecovery)return;
  clearLocalDraft();
  finishRecoveryChoice();
  editRevision=0;savedRevision=0;
  if(serverUpdatedAt)setSavedStatus();else setSaveStatus('','尚未儲存');
}
function renderReflectionTaskGuide(v,data){
  const answers=Array.isArray(data.answers)?data.answers:[];
  const completed=answers.filter(answer=>String(answer||'').trim()).length;
  const state=viewId||v.submitted_at||data.submitted_at?'completed':isPastDue()?'read-only':'active';
  if(state!=='active')return renderTaskGuide({title:state==='read-only'?'作業已截止，心得僅供查看':'心得已正式送出',progress:`心得 ${completed}/${questions.length} 題已完成`,next:'回看時，找出當時訂下的行動，確認下一次練習是否真的有做到。',view:v,state});
  return renderTaskGuide({
    title:'用「哪裡、發現、下一步」把心得寫具體',
    progress:`心得已完成 ${completed}/${questions.length} 題`,
    actions:['先指出證據在哪一題、哪一輪或哪一段逐字稿。','再寫你做得好的地方或遇到的問題，以及判斷原因。','最後寫清楚下次做什麼、何時做、怎麼確認進步。'],
    support:{title:'只想到「很好」或「要加強」時',items:['回到一段實際回答、錄音或回饋，先描述當時發生了什麼。','把「多練習」改成可執行的動作，例如每週錄兩次並比較關鍵字是否更清楚。'],html:learningScaffoldStageHtml(v,'reflection')},
    starters:['在第 __ 題／第 __ 輪，我……','回聽或查看回饋後，我發現……','下次我會在 __ 前，用 __ 練習，並用 __ 確認進步。'],
    checks:[`${workflowLimit('reflection_question_count')} 題都有引用這次練習的具體內容。`,'優勢與待改進處都有說明原因。','後續行動包含做法、時間與檢查方式。'],
    next:`系統會自動保存；確認 ${workflowLimit('reflection_question_count')} 題完整後正式送出，本次作業才算完成。`,
    view:v,
  });
}
function reflectionSuggestionItems(value){
  if(Array.isArray(value))return value.map(item=>String(item||'').trim()).filter(Boolean);
  if(typeof value!=='string')return[];
  const text=value.trim();
  if(!text)return[];
  const parts=text.split(/\n+/).flatMap(line=>line.match(/[^。！？]+[。！？]?/g)||[]);
  return parts.map(item=>item.trim()).filter(Boolean);
}
function renderAiSuggestionCard(v){
  const report=v&&v.report_data?tryParseJson(v.report_data):null;
  const suggestions=reflectionSuggestionItems(report&&report.overall_suggestions);
  const suggestionHtml=suggestions.length
    ?`<ul class="mb-2">${suggestions.map(item=>`<li class="mb-1">${escHtml(item)}</li>`).join('')}</ul>`
    :'<p class="text-muted small mb-2">本次 AI 回饋目前沒有可顯示的改進建議，請依照你看到的回饋與實際作答完成反思。</p>';
  return `<aside class="ai-suggestion-card" aria-label="本次 AI 回饋的改進建議"><div class="fw-bold mb-2"><i class="bi bi-lightbulb me-1 text-primary"></i>先讀這次 AI 回饋的改進建議</div>${suggestionHtml}<div class="small text-primary-emphasis"><strong>回答前想一想：</strong>從中挑一項，對照你的實際回答，說明自己的一項優勢、最需要改進之處，以及判斷的證據。</div></aside>`;
}
function renderQuestions(data){
  const support=getLearningSupport(getView());
  const placeholder=support.mode==='guided'?'請指出發生在哪一題或哪一輪，再寫下具體例子。':support.mode==='supported'?'先寫你的判斷，再補上本次練習中的證據。':'請用具體證據完成你的獨立反思。';
  questionsBox.innerHTML=questions.map((q,i)=>{
    const suggestionCard=i===2?renderAiSuggestionCard(getView()):'';
    return `<div class="question-card"><label class="form-label fw-bold" for="answer${i}">${i+1}. ${escHtml(q)} <span class="text-danger">*</span></label>${suggestionCard}<textarea id="answer${i}" class="form-control reflection-answer" maxlength="3000" placeholder="${escAttr(placeholder)}">${escHtml((data.answers||[])[i]||'')}</textarea><div class="form-text">避免只寫「很好」或「要加強」；請交代你從哪一段回答、錄音或報告做出這個判斷。</div></div>`;
  }).join('');
}
function setLocked(reason='submitted',clearDraft=false){
  autosaveEnabled=false;
  clearTimeout(saveTimer);saveTimer=null;
  reflectionForm.querySelectorAll('textarea,input,select,button:not([data-readonly-action="true"])').forEach(el=>el.disabled=true);
  actions.classList.add('d-none');
  lockedNotice.innerHTML=reason==='past-due'
    ?'<i class="bi bi-calendar-x-fill me-1"></i>作業已截止，心得內容僅供查看。'
    :'<i class="bi bi-check-circle-fill me-1"></i>心得已正式送出，內容已鎖定。';
  lockedNotice.classList.remove('d-none');
  if(clearDraft)clearLocalDraft();
}

function setReflectionCardCompleted(completed){
  const card=document.getElementById('reflectionCard');
  if(!card)return;
  card.classList.toggle('active',!completed);
  card.classList.toggle('completed',completed);
}

function renderPhotoState(message='',busy=false){
  const disabled=busy?' disabled':'';
  const saved=currentPhotoData.has_photo
    ?`<span class="text-success"><i class="bi bi-image me-1"></i>${escHtml(currentPhotoData.photo_original_name||'已上傳照片')}</span> <button type="button" class="btn btn-sm btn-link" data-readonly-action="true" data-action="viewPhoto">查看</button> <button type="button" class="btn btn-sm btn-link text-danger" data-action="removePhoto"${disabled}>移除</button>`
    :'';
  photoState.innerHTML=`${saved}${saved&&message?'　':''}${message}`;
}

function loadPhoto(data){
  currentPhotoData={
    has_photo:!!(data&&data.has_photo),
    photo_original_name:(data&&data.photo_original_name)||null,
  };
  renderPhotoState();
}

function validateSelectedPhoto(file){
  if(!file)return'請先選擇照片。';
  if(file.size<=0)return'照片檔案不可為空。';
  if(file.size>10*1024*1024)return'照片不可超過 10 MB。';
  const type=String(file.type||'').toLowerCase();
  const typeAllowed=['image/jpeg','image/png','image/webp','image/heic','image/heif'].includes(type);
  const nameAllowed=/\.(jpe?g|png|webp|heic|heif)$/i.test(file.name||'');
  return typeAllowed||nameAllowed?'':'僅支援 JPEG、PNG、WebP、HEIC 或 HEIF 照片。';
}

async function uploadSelectedPhoto(announce=true){
  if(photoUploadPromise)return photoUploadPromise;
  const file=photoInput.files&&photoInput.files[0];
  if(!file)return true;
  const validationError=validateSelectedPhoto(file);
  if(validationError){
    photoInput.value='';photoUploadFailed=false;
    renderPhotoState();showAlert(validationError);return false;
  }
  const task=(async()=>{
    photoInput.disabled=true;
    renderPhotoState('<span class="text-primary"><span class="spinner-border spinner-border-sm me-1"></span>照片上傳中…</span>',true);
    if(!await flushTextDraft(true)){
      photoUploadFailed=true;
      renderPhotoState('<span class="text-warning">文字尚未同步，照片暫未上傳。 <button type="button" class="btn btn-sm btn-link" data-action="retryPhoto">重試</button> <button type="button" class="btn btn-sm btn-link text-secondary" data-action="cancelPendingPhoto">取消</button></span>');
      return false;
    }
    try{
      const body=new FormData();body.append('photo',file);reflectionDraft.appendExpectedRevision(body);
      const response=await apiCall(`/api/student/submissions/${submission.id}/reflection/photo`,{
        method:'POST',body,headers:{},
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok){
        const conflict=reflectionDraft.conflictDetail(data);
        if(conflict&&handleRevisionConflict(conflict,rawFormBody()))return false;
        throw new Error(typeof data.detail==='string'?data.detail:'照片上傳失敗');
      }
      reflectionDraft.adopt(data);
      photoInput.value='';photoUploadFailed=false;
      adoptServerUpdatedAt(data.updated_at);
      if(editRevision>savedRevision)persistLocalDraft();
      loadPhoto(data);
      if(announce)showAlert('問題照片已上傳。','success');
      return true;
    }catch(error){
      photoUploadFailed=true;
      renderPhotoState(`<span class="text-warning">${escHtml(error.message||'照片上傳失敗')} <button type="button" class="btn btn-sm btn-link" data-action="retryPhoto">重試</button> <button type="button" class="btn btn-sm btn-link text-secondary" data-action="cancelPendingPhoto">取消</button></span>`);
      return false;
    }
  })();
  photoUploadPromise=task;
  try{return await task;}finally{
    photoUploadPromise=null;
    if(autosaveEnabled&&!isSubmitting)photoInput.disabled=false;
  }
}

async function retryPhoto(){return uploadSelectedPhoto(true);}

function cancelPendingPhoto(){
  if(photoUploadPromise)return;
  photoInput.value='';photoUploadFailed=false;renderPhotoState();
}
async function loadGrade(id){try{const r=await apiCall(`/api/student/submissions/${id}/grade`);if(!r.ok)throw new Error();const {grade}=await r.json();if(!grade)return;gradeBox.innerHTML=`<div class="d-flex align-items-center gap-4 flex-wrap"><div><div class="grade-score">${grade.final_score}</div><div class="text-muted">老師評定成績 / 100</div></div><div><strong>${escHtml(grade.rubric_name)} v${grade.rubric_version_number}</strong><div class="small text-muted">批改時間：${new Date(grade.graded_at).toLocaleString('zh-TW')}</div></div></div><hr><h6>總評</h6><p>${escHtml(grade.teacher_comment)}</p><h6>改進建議</h6><p>${escHtml(grade.teacher_feedback)}</p><h6>各項評分等級</h6>${(grade.ratings||[]).map(x=>`<div class="rating-row d-flex justify-content-between gap-3"><span>${escHtml(x.dimension_name)} · ${escHtml(x.criterion_name)}</span><strong>${escHtml(x.level_label)}</strong></div>`).join('')}`;}catch(_){gradeBox.innerHTML='<div class="alert alert-warning mb-0">正式成績載入失敗，請稍後重新整理。</div>';}}
function rubricLevelPoints(level,criterionPoints){return level&&level.points!=null?Number(level.points):Number(criterionPoints)*Number(level&&level.ratio!=null?level.ratio:0);}
function studentRubricHtml(v){const shared=v.definition.levels||[],notes=v.definition.notes||[];const notesHtml=notes.length?`<div class="alert alert-warning small"><strong>評分注意事項</strong><ul class="mb-0 mt-1 ps-3">${notes.map(note=>`<li>${escHtml(note)}</li>`).join('')}</ul></div>`:'';const dimensions=(v.definition.dimensions||[]).map(d=>`<div class="rubric-dimension"><strong>${escHtml(d.name)}（${d.weight} 分）</strong>${d.criteria.map(c=>{const levels=Array.isArray(c.levels)&&c.levels.length?c.levels:shared;return `<div class="mt-2"><div>${escHtml(c.name)}：${c.points} 分</div><div class="small text-muted">${escHtml(c.description||'')}</div><ul class="small mb-0 mt-2 ps-3">${levels.map(level=>`<li class="mb-1"><strong>${rubricLevelPoints(level,c.points)} 分｜${escHtml(level.label)}</strong>：${escHtml(level.anchor||'')}</li>`).join('')}</ul></div>`;}).join('')}</div>`).join('');return `<p class="mb-2"><strong>${escHtml(v.rubric_name)} v${v.version_number}</strong></p>${notesHtml}${dimensions}`;}
async function loadRubric(id){try{const r=await apiCall(`/api/student/submissions/${id}/rubric`);if(!r.ok)throw new Error();const v=await r.json();rubricBox.innerHTML=studentRubricHtml(v);}catch(_){rubricBox.innerHTML='<div class="alert alert-warning mb-0">評分規準載入失敗，請稍後重新整理。</div>';}}
async function init(){
  await window.practiceLaunchReady;
  const context=await StudentPracticeRuntime.assignmentContext();
  let response=context.response,payload=context.data;
  if(!response.ok){renderStudentPageLoadError(new Error(payload.detail||'心得資料載入失敗，請稍後再試。'));return;}
  setWorkflowLimits(payload.workflow_limits);assignment=payload.assignment;submission=payload.submission;
  if(!submission){navigateStudentPage(`/student/assignment/${assignmentId}/job-profile`);return;}
  if(viewId){
    try{viewedSubmission=await loadViewedSubmissionForAssignment(viewId,assignmentId);}
    catch(error){renderStudentPageLoadError(error);return;}
  }
  const v=getView();
  if(!viewId&&v.stage<8){navigateStudentPage(`/student/assignment/${assignmentId}/${v.stage>=6?'roleplay':v.stage>=5?'shadowing':v.stage<=1?'job-profile':'writing'}`);return;}
  if(!viewId&&!v.job_profile_data){navigateStudentPage(`/student/assignment/${assignmentId}/job-profile`);return;}
  document.getElementById('loadingMsg').classList.add('d-none');
  document.getElementById('content').classList.remove('d-none');
  document.getElementById('assignmentTitle').textContent=assignment.title;
  document.getElementById('assignmentDesc').textContent=assignment.description||'';
  const dueDate=document.getElementById('dueDate');
  if(assignment.due_date){
    dueDate.textContent=`截止日期：${new Date(assignment.due_date).toLocaleString('zh-TW')}`;
  }else{
    dueDate.classList.add('d-none');
  }
  renderAttemptBadge(v);
  updateProgressSteps(v.stage);renderViewBanner();
  const data=v.reflection_data||{answers:['','','','',''],has_issue:false};
  reflectionDraft=new ReflectionDraftController({storagePrefix:LOCAL_DRAFT_PREFIX,submissionId:v.id,assignmentId,revision:data.revision||0});
  serverDraftExists=!!v.reflection_data;
  reflectionGuide.innerHTML=renderReflectionTaskGuide(v,data);
  renderQuestions(data);applyFormState(data);loadPhoto(data);
  serverUpdatedAt=data.updated_at||null;
  const submitted=!!(v.submitted_at||data.submitted_at);
  setReflectionCardCompleted(submitted);
  await Promise.all([loadGrade(v.id),loadRubric(v.id)]);
  if(viewId||submitted||isPastDue()){
    setLocked(isPastDue()&&!submitted?'past-due':'submitted',!viewId&&submitted);
    return;
  }
  autosaveEnabled=true;
  if(serverUpdatedAt)setSavedStatus();else setSaveStatus('','尚未儲存');
  restoreLocalDraftIfNeeded(data);
}

questionsBox.addEventListener('input',event=>{
  if(!event.target.classList.contains('reflection-answer'))return;
  const v=getView();
  if(v)reflectionGuide.innerHTML=renderReflectionTaskGuide(v,{answers:[...document.querySelectorAll('.reflection-answer')].map(input=>input.value)});
  markDraftDirty();
});
hasIssue.addEventListener('change',()=>{issueFields.classList.toggle('d-none',!hasIssue.checked);markDraftDirty();});
issueCategory.addEventListener('change',markDraftDirty);
issueDescription.addEventListener('input',markDraftDirty);
photoInput.addEventListener('change',()=>{if(photoInput.files&&photoInput.files[0])void uploadSelectedPhoto(true);});

async function saveDraftManually(){
  if(!autosaveEnabled)return false;
  draftBtn.disabled=true;draftSpinner.classList.remove('d-none');
  try{
    const textSaved=await flushTextDraft(true);
    const photoSaved=textSaved&&photoInput.files&&photoInput.files[0]?await uploadSelectedPhoto(false):textSaved;
    if(textSaved&&photoSaved){showAlert('心得草稿已儲存。','success');setSavedStatus();return true;}
    showAlert(photoUploadFailed?'文字已保留，但照片尚未上傳。':'草稿尚未同步，請檢查網路後重試。');
    return false;
  }finally{
    if(autosaveEnabled)draftBtn.disabled=false;
    draftSpinner.classList.add('d-none');
  }
}

async function submitFinal(){
  if(!confirm('正式送出後即無法修改，確定送出嗎？'))return;
  isSubmitting=true;setEditingDisabled(true);submitSpinner.classList.remove('d-none');
  let completed=false;
  try{
    if(!await flushTextDraft(true)){showAlert('最新心得尚未同步，請檢查網路後再送出。');return;}
    if(photoInput.files&&photoInput.files[0]&&!await uploadSelectedPhoto(false)){showAlert('照片尚未上傳，請重試或取消待上傳照片後再送出。');return;}
    const response=await apiCall(`/api/student/submissions/${submission.id}/reflection/submit`,{method:'POST',body:JSON.stringify({expected_revision:reflectionDraft.revision})});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){
      const conflict=reflectionDraft.conflictDetail(data);
      if(conflict)handleRevisionConflict(conflict,rawFormBody());
      else showAlert(typeof data.detail==='string'?data.detail:'送出失敗');
      return;
    }
    reflectionDraft.adopt(data);
    completed=true;autosaveEnabled=false;clearTimeout(saveTimer);clearLocalDraft();
    setSaveStatus('saved','已正式送出');
    showAlert('心得已正式送出，本次作業完成。','success');
    allowNavigation=true;setTimeout(()=>location.reload(),700);
  }catch(error){showAlert(error.message||'送出失敗，請稍後再試。');}
  finally{
    if(!completed){isSubmitting=false;if(!pendingRecovery)setEditingDisabled(false);}
    submitSpinner.classList.add('d-none');
  }
}

async function viewPhoto(){
  const response=await apiCall(`/api/student/submissions/${getView().id}/reflection/photo-url`);
  const data=await response.json().catch(()=>({}));
  if(response.ok){if(isEmbeddedDesktopPracticePage())navigateStudentPage(data.url);else window.open(data.url,'_blank','noopener');}else showAlert(data.detail||'照片無法開啟');
}

async function removePhoto(){
  if(photoUploadPromise)return;
  try{
    const response=await apiCall(`/api/student/submissions/${submission.id}/reflection/photo?expected_revision=${reflectionDraft.revision}`,{method:'DELETE'});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const conflict=reflectionDraft.conflictDetail(data);if(conflict)handleRevisionConflict(conflict,rawFormBody());else showAlert(typeof data.detail==='string'?data.detail:'照片移除失敗');return;}
    reflectionDraft.adopt(data);adoptServerUpdatedAt(data.updated_at);
    currentPhotoData={has_photo:false,photo_original_name:null};renderPhotoState();
    showAlert('照片已移除。','success');
  }catch(error){showAlert(error.message||'照片移除失敗');}
}

async function prepareToLeave(){
  const textSaved=await flushTextDraft();
  if(!textSaved&&!localBackupHealthy&&!confirm('心得尚未完成備份，現在離開可能遺失內容。仍要離開嗎？'))return false;
  let photoSaved=true;
  if(photoUploadPromise)photoSaved=await photoUploadPromise;
  else if(photoInput.files&&photoInput.files[0])photoSaved=await uploadSelectedPhoto(false);
  if(!photoSaved&&!confirm('選取的照片尚未上傳，現在離開將遺失這張照片。仍要離開嗎？'))return false;
  return true;
}

async function navigateAway(url){
  if(isSubmitting)return;
  if(!await prepareToLeave())return;
  allowNavigation=true;navigateStudentPage(url);
}

async function navigateSection(section){
  const viewParam=viewId?`?view=${viewId}`:'';
  await navigateAway(StudentWorkflow.sectionPath(assignmentId,section)+viewParam);
}

async function returnToAssignments(event){
  if(event)event.preventDefault();
  await navigateAway('/student');
}

async function logoutFromReflection(){
  if(isSubmitting||!await prepareToLeave())return;
  allowNavigation=true;await logout();
}

window.addEventListener('online',()=>{
  if(autosaveEnabled&&savedRevision<editRevision)scheduleAutosave(0);
  if(autosaveEnabled&&photoUploadFailed&&photoInput.files&&photoInput.files[0])void uploadSelectedPhoto(false);
});
window.addEventListener('offline',()=>{
  if(autosaveEnabled&&savedRevision<editRevision)setSaveStatus('error',localBackupHealthy?'連線中斷，已保存在此裝置':'無法備份，請勿離開此頁');
});
document.addEventListener('visibilitychange',()=>{
  if(document.hidden&&autosaveEnabled&&savedRevision<editRevision){clearTimeout(saveTimer);saveTimer=null;void drainSaveQueue();}
});
window.addEventListener('beforeunload',event=>{
  if(allowNavigation)return;
  const unsafeText=autosaveEnabled&&savedRevision<editRevision&&!localBackupHealthy;
  const unsafePhoto=!!(photoUploadPromise||(photoInput.files&&photoInput.files[0]));
  if(!unsafeText&&!unsafePhoto)return;
  event.preventDefault();event.returnValue='';
});
init().catch(error=>renderStudentPageLoadError(error));

Object.assign(window, {
  rawFormBody,
  formBody,
  setSaveStatus,
  formatSavedTime,
  setSavedStatus,
  adoptServerUpdatedAt,
  persistLocalDraft,
  readLocalDraft,
  clearLocalDraft,
  applyFormState,
  setEditingDisabled,
  scheduleAutosave,
  markDraftDirty,
  presentRecoveryChoice,
  handleRevisionConflict,
  saveLatestSnapshot,
  drainSaveQueue,
  flushTextDraft,
  restoreLocalDraftIfNeeded,
  finishRecoveryChoice,
  recoverLocalDraft,
  keepServerDraft,
  renderReflectionTaskGuide,
  reflectionSuggestionItems,
  renderAiSuggestionCard,
  renderQuestions,
  setLocked,
  setReflectionCardCompleted,
  renderPhotoState,
  loadPhoto,
  validateSelectedPhoto,
  uploadSelectedPhoto,
  retryPhoto,
  cancelPendingPhoto,
  loadGrade,
  rubricLevelPoints,
  studentRubricHtml,
  loadRubric,
  init,
  saveDraftManually,
  submitFinal,
  viewPhoto,
  removePhoto,
  prepareToLeave,
  navigateAway,
  navigateSection,
  returnToAssignments,
  logoutFromReflection,
});
