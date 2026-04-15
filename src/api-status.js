import { apiUrl, hasApiToken, setApiToken, clearApiToken } from './api-client.js';

const STATES = {
  ok: { label: 'AI機能 ON', state: 'ok' },
  unauth: { label: 'パスワード再入力が必要', state: 'err' },
  noToken: { label: 'UI評価モード（クリックで接続）', state: 'warn' },
  offline: { label: 'バックエンド到達不可', state: 'err' },
  checking: { label: '接続確認中…', state: 'warn' },
};

const TOKEN_STORAGE_KEY = 'aic_api_token_v1';

const $ = (id) => document.getElementById(id);

function setStatus(key) {
  const el = $('api-status');
  const labelEl = $('api-status-label');
  if (!el || !labelEl) return;
  const cfg = STATES[key] || STATES.checking;
  el.removeAttribute('hidden');
  el.dataset.state = cfg.state;
  labelEl.textContent = cfg.label;
}

async function probeAuth() {
  if (!hasApiToken()) return setStatus('noToken');
  setStatus('checking');
  try {
    const res = await fetch(apiUrl('/health'));
    if (!res.ok) return setStatus('offline');
    const data = await res.json().catch(() => ({}));
    if (data.auth_enabled === false) return setStatus('ok');
    const probe = await fetch(apiUrl('/api/templates'), {
      headers: { 'X-API-Token': localStorage.getItem(TOKEN_STORAGE_KEY) || '' },
    });
    if (probe.status === 401) return setStatus('unauth');
    return setStatus('ok');
  } catch {
    return setStatus('offline');
  }
}

function openModal() {
  const modal = $('pwd-modal');
  if (!modal) return;
  modal.removeAttribute('hidden');
  $('pwd-error').hidden = true;
  $('pwd-input').value = '';
  $('pwd-input').focus();
  $('pwd-logout').hidden = !hasApiToken();
}

function closeModal() {
  $('pwd-modal')?.setAttribute('hidden', '');
}

async function trySubmit(password) {
  const errEl = $('pwd-error');
  errEl.hidden = true;
  if (!password) {
    errEl.textContent = 'パスワードを入力してください';
    errEl.hidden = false;
    return;
  }
  setApiToken(password);
  try {
    const health = await fetch(apiUrl('/health'));
    if (!health.ok) throw new Error('offline');
    const data = await health.json().catch(() => ({}));
    if (data.auth_enabled === false) {
      // Backend in dev mode — accept anything
      closeModal();
      probeAuth();
      return;
    }
    const probe = await fetch(apiUrl('/api/templates'), {
      headers: { 'X-API-Token': password },
    });
    if (probe.status === 401) {
      clearApiToken();
      errEl.textContent = 'パスワードが違います';
      errEl.hidden = false;
      return;
    }
    closeModal();
    probeAuth();
  } catch {
    clearApiToken();
    errEl.textContent = 'サーバーに接続できません。後でもう一度お試しください';
    errEl.hidden = false;
  }
}

function init() {
  $('api-status')?.addEventListener('click', openModal);
  $('pwd-form')?.addEventListener('submit', (e) => {
    e.preventDefault();
    trySubmit($('pwd-input').value.trim());
  });
  document.querySelectorAll('[data-close]').forEach((el) =>
    el.addEventListener('click', closeModal)
  );
  $('pwd-logout')?.addEventListener('click', () => {
    clearApiToken();
    closeModal();
    probeAuth();
  });
  probeAuth();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
