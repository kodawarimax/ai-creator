import { apiUrl, hasApiToken } from './api-client.js';

const STATES = {
  ok: { label: 'API接続OK', state: 'ok' },
  unauth: { label: 'トークン無効/未設定', state: 'err' },
  noToken: { label: 'UI評価モード（API未接続）', state: 'warn' },
  offline: { label: 'バックエンド到達不可', state: 'err' },
  checking: { label: '接続確認中…', state: 'warn' },
};

function setStatus(key) {
  const el = document.getElementById('api-status');
  const labelEl = document.getElementById('api-status-label');
  if (!el || !labelEl) return;
  const cfg = STATES[key] || STATES.checking;
  el.removeAttribute('hidden');
  el.dataset.state = cfg.state;
  labelEl.textContent = cfg.label;
}

async function check() {
  if (!hasApiToken()) {
    setStatus('noToken');
    return;
  }
  setStatus('checking');
  try {
    const res = await fetch(apiUrl('/health'));
    if (!res.ok) return setStatus('offline');
    const data = await res.json().catch(() => ({}));
    if (data.auth_enabled === false) {
      setStatus('ok');
      return;
    }
    const probe = await fetch(apiUrl('/api/templates'), {
      headers: { 'X-API-Token': localStorage.getItem('aic_api_token_v1') || '' },
    });
    if (probe.status === 401) setStatus('unauth');
    else setStatus('ok');
  } catch {
    setStatus('offline');
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', check);
} else {
  check();
}
