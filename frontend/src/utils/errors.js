/**
 * Error extraction helper for API responses and errors.
 * Ensures FastAPI 422 validation errors, arrays, and objects are converted
 * into readable strings instead of '[object Object]'.
 */
export function extractErrorMessage(data, fallback = 'Request failed') {
  if (!data) return fallback;
  if (typeof data === 'string') {
    return data === '[object Object]' ? fallback : data;
  }
  if (data instanceof Error) {
    const msg = data.message;
    return msg === '[object Object]' ? fallback : msg;
  }

  const detail = data.detail ?? data.error ?? data.message ?? data.msg;
  if (typeof detail === 'string') {
    return detail === '[object Object]' ? fallback : detail;
  }
  if (Array.isArray(detail)) {
    const joined = detail
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && item.msg) {
          const loc = Array.isArray(item.loc) ? item.loc.filter((x) => x !== 'body').join('.') : '';
          return loc ? `${loc}: ${item.msg}` : item.msg;
        }
        return JSON.stringify(item);
      })
      .filter(Boolean)
      .join('; ');
    return joined || fallback;
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

