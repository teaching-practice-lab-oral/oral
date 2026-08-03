export function apiErrorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail.message === 'string' && detail.message.trim()) {
    return detail.message;
  }
  if (typeof payload?.message === 'string' && payload.message.trim()) {
    return payload.message;
  }
  return fallback;
}
