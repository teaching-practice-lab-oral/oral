export class ApiError extends Error {
  constructor(message, { status = 0, detail = null, cause = null } = {}) {
    super(message, cause ? { cause } : undefined);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail || message;
  }
}

export function csrfToken(cookie = (typeof document === 'undefined' ? '' : document.cookie)) {
  const match = String(cookie || '').match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

export async function apiRequest(url, options = {}, fetchImpl = fetch) {
  const method = String(options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !headers.has('X-CSRF-Token')) {
    headers.set('X-CSRF-Token', csrfToken());
  }
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (options.body != null && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  try {
    const response = await fetchImpl(url, { ...options, method, headers, credentials: 'include' });
    if (response.status === 401 && typeof globalThis.ApiUnauthorizedHandler === 'function') {
      await globalThis.ApiUnauthorizedHandler(response.clone());
    }
    return response;
  } catch (cause) {
    throw new ApiError('目前無法連線，請稍後再試。', { cause });
  }
}

export async function requestJson(url, options = {}, fetchImpl = fetch) {
  const response = await apiRequest(url, options, fetchImpl);
  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (cause) {
      throw new ApiError('伺服器回應格式錯誤，請稍後再試。', { status: response.status, cause });
    }
  }
  if (!response.ok) {
    const detail = data && typeof data === 'object' ? data.detail : null;
    throw new ApiError(detail || `請求失敗（${response.status}）`, { status: response.status, detail });
  }
  return data;
}
