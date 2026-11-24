const studentHomeNativeFetch = window.fetch.bind(window);
const StudentApiClientReady = import('/static/js/api-client.mjs');
window.StudentApiClientReady = StudentApiClientReady;
window.StudentApiNativeFetch = studentHomeNativeFetch;
window.fetch = (url, options = {}) => {
  const sameOrigin = typeof url === 'string'
    && (url.startsWith('/') || url.startsWith(window.location.origin));
  if (!sameOrigin) return studentHomeNativeFetch(url, options);
  return StudentApiClientReady.then(({ apiRequest }) => apiRequest(url, options, studentHomeNativeFetch));
};
