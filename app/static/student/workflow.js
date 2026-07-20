(function () {
  'use strict';
  let metadata = null;
  let contractModule = null;
  const fallbackSections = ['job-profile', 'writing', 'shadowing', 'roleplay', 'report', 'reflection']
    .map((path, index) => ({ id: index + 1, path }));
  const modulePromise = import('/static/js/workflow-contract.mjs?v=1').then(module => {
    contractModule = module;
    return module;
  });
  const readyPromise = modulePromise
    .then(module => module.loadWorkflowMetadata())
    .catch(() => ({ version: 0, sections: fallbackSections, stages: [], limits: {} }))
    .then(value => { metadata = value; return value; });

  function assignmentPath({ assignmentId, stage, completed, hasJobProfile }) {
    const base = `/student/assignment/${assignmentId}`;
    if (completed) return `${base}/reflection`;
    if (Number(stage) >= 8) return `${base}/reflection`;
    if (Number(stage) >= 6) return `${base}/roleplay`;
    if (Number(stage) >= 5) return `${base}/shadowing`;
    if (Number(stage) <= 1 || !hasJobProfile) return `${base}/job-profile`;
    return `${base}/writing`;
  }

  function activeSection(stage, currentSection = 0) {
    const value = Number(stage);
    if (value <= 1) return 1;
    if (value <= 4) return 2;
    if (value === 5) return 3;
    if (value === 6 || value === 7) return 4;
    if (value === 8) return 6;
    return 6;
  }

  function sectionPath(assignmentId, section) {
    if (!metadata) throw new Error('Workflow metadata has not loaded yet');
    const item = metadata.sections.find(candidate => Number(candidate.id) === Number(section));
    if (!item) throw new Error(`Unknown workflow section: ${section}`);
    return `/student/assignment/${assignmentId}/${item.path}`;
  }

  function stageLabel(stage) {
    const item = metadata?.stages?.find(candidate => Number(candidate.number) === Number(stage));
    return item?.label || `第 ${Number(stage)} 階段`;
  }

  function sectionLabel(section) {
    const item = metadata?.sections?.find(candidate => Number(candidate.id) === Number(section));
    return item?.label || `第 ${Number(section)} 區段`;
  }

  function dateStatus(assignment, now) {
    if (!contractModule) return { state: 'open', text: '日期載入中', disabled: false };
    return contractModule.assignmentDateStatus(assignment, now);
  }

  window.StudentWorkflow = Object.freeze({
    assignmentPath,
    activeSection,
    sectionPath,
    stageLabel,
    sectionLabel,
    dateStatus,
    ready: () => readyPromise,
    metadata: () => metadata,
  });
})();
