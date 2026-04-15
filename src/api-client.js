export const API_BASE = window.location.hostname === 'localhost'
  ? 'http://localhost:5051'
  : 'https://srv1334941.hstgr.cloud';

const TOKEN_STORAGE_KEY = 'aic_api_token_v1';
const BUILD_TIME_TOKEN = (import.meta.env && import.meta.env.VITE_API_TOKEN) || '';

function captureTokenFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const t = params.get('token');
    if (t) {
      localStorage.setItem(TOKEN_STORAGE_KEY, t.trim());
      params.delete('token');
      const newSearch = params.toString();
      const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : '') + window.location.hash;
      window.history.replaceState({}, '', newUrl);
      return t.trim();
    }
  } catch {}
  return null;
}

function resolveToken() {
  const fromUrl = captureTokenFromUrl();
  if (fromUrl) return fromUrl;
  try {
    const stored = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored) return stored;
  } catch {}
  return BUILD_TIME_TOKEN;
}

let CURRENT_TOKEN = resolveToken();

export function setApiToken(token) {
  CURRENT_TOKEN = (token || '').trim();
  try {
    if (CURRENT_TOKEN) localStorage.setItem(TOKEN_STORAGE_KEY, CURRENT_TOKEN);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {}
}

export function clearApiToken() { setApiToken(''); }
export function hasApiToken() { return Boolean(CURRENT_TOKEN); }

export function apiUrl(path) {
  if (/^https?:/i.test(path)) return path;
  const prefix = path.startsWith('/') ? '' : '/';
  return `${API_BASE}${prefix}${path}`;
}

export function apiFetch(path, init = {}) {
  const url = apiUrl(path);
  const headers = new Headers(init.headers || {});
  if (CURRENT_TOKEN && !headers.has('X-API-Token')) {
    headers.set('X-API-Token', CURRENT_TOKEN);
  }
  return fetch(url, { ...init, headers });
}
