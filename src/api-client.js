export const API_BASE = window.location.hostname === 'localhost'
  ? 'http://localhost:5051'
  : 'https://srv1334941.hstgr.cloud';

const API_TOKEN = (import.meta.env && import.meta.env.VITE_API_TOKEN) || '';

export function apiUrl(path) {
  if (/^https?:/i.test(path)) return path;
  const prefix = path.startsWith('/') ? '' : '/';
  return `${API_BASE}${prefix}${path}`;
}

export function apiFetch(path, init = {}) {
  const url = apiUrl(path);
  const headers = new Headers(init.headers || {});
  if (API_TOKEN && !headers.has('X-API-Token')) {
    headers.set('X-API-Token', API_TOKEN);
  }
  return fetch(url, { ...init, headers });
}
