let metadataPromise;

export async function loadWorkflowMetadata(fetchImpl = fetch) {
  if (!metadataPromise) {
    metadataPromise = fetchImpl('/api/workflow/metadata', { credentials: 'same-origin' })
      .then(response => {
        if (!response.ok) throw new Error(`workflow_metadata_${response.status}`);
        return response.json();
      })
      .then(metadata => Object.freeze(metadata))
      .catch(error => {
        metadataPromise = undefined;
        throw error;
      });
  }
  return metadataPromise;
}

export function stageLabel(metadata, stage) {
  const item = metadata?.stages?.find(candidate => Number(candidate.number) === Number(stage));
  return item?.label || `第 ${Number(stage)} 階段`;
}

export function sectionPath(metadata, assignmentId, section) {
  const item = metadata?.sections?.find(candidate => Number(candidate.id) === Number(section));
  if (!item) throw new Error(`Unknown workflow section: ${section}`);
  return `/student/assignment/${Number(assignmentId)}/${item.path}`;
}

function taipeiDateKey(value) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(value);
}

function dayDistance(from, to) {
  const [fy, fm, fd] = taipeiDateKey(from).split('-').map(Number);
  const [ty, tm, td] = taipeiDateKey(to).split('-').map(Number);
  return Math.round((Date.UTC(ty, tm - 1, td) - Date.UTC(fy, fm - 1, fd)) / 86400000);
}

export function assignmentDateStatus(assignment, now = new Date()) {
  if (assignment.start_date) {
    const start = new Date(assignment.start_date);
    if (now < start) {
      const days = dayDistance(now, start);
      return {
        state: 'pending',
        text: days === 0 ? '今天開放' : `開放於 ${start.toLocaleString('zh-TW')}`,
        disabled: true,
      };
    }
  }
  if (!assignment.due_date) return { state: 'open', text: '無截止日期', disabled: false };
  const due = new Date(assignment.due_date);
  if (now > due) {
    if (assignment.late_deadline) {
      const late = new Date(assignment.late_deadline);
      if (now < late) {
        const days = dayDistance(now, late);
        return {
          state: 'late',
          text: days === 0 ? '補繳今天截止' : `補繳截止剩 ${days} 天`,
          disabled: false,
          lateDeadline: assignment.late_deadline,
        };
      }
    }
    const days = Math.max(0, -dayDistance(now, due));
    return { state: 'overdue', text: days === 0 ? '今天已截止' : `已截止 ${days} 天`, disabled: true };
  }
  const days = dayDistance(now, due);
  if (days === 0) return { state: 'open', text: '今天截止', disabled: false };
  if (days <= 3) return { state: 'open', text: `剩 ${days} 天截止`, disabled: false };
  return { state: 'open', text: `截止：${due.toLocaleDateString('zh-TW')}`, disabled: false };
}
