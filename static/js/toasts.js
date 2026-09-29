/**
 * Kahawa toast notifications.
 * window.showToast(message, level?) — level: success | error | warning | info
 */
(function () {
  const DEFAULT_MS = 4500;
  const MAX_VISIBLE = 5;

  function ensureHost() {
    let host = document.getElementById('kahawa-toasts');
    if (host) return host;
    host = document.createElement('div');
    host.id = 'kahawa-toasts';
    host.setAttribute('data-theme', document.body?.dataset?.toastTheme || 'light');
    host.setAttribute('aria-live', 'polite');
    host.setAttribute('aria-relevant', 'additions');
    document.body.appendChild(host);
    return host;
  }

  function normalizeLevel(level) {
    const raw = String(level || 'info').toLowerCase();
    if (raw.includes('error') || raw.includes('danger')) return 'error';
    if (raw.includes('success')) return 'success';
    if (raw.includes('warning') || raw.includes('warn')) return 'warning';
    if (raw.includes('debug')) return 'debug';
    return 'info';
  }

  function dismissToast(el, immediate) {
    if (!el || el.dataset.leaving === '1') return;
    el.dataset.leaving = '1';
    if (immediate) {
      el.remove();
      return;
    }
    el.classList.remove('is-in');
    el.classList.add('is-out');
    window.setTimeout(() => el.remove(), 280);
  }

  function showToast(message, level, opts) {
    const text = String(message || '').trim();
    if (!text) return null;

    const host = ensureHost();
    const lvl = normalizeLevel(level);
    const duration = (opts && opts.duration) != null ? opts.duration : DEFAULT_MS;

    while (host.children.length >= MAX_VISIBLE) {
      dismissToast(host.firstElementChild, true);
    }

    const el = document.createElement('div');
    el.className = `kahawa-toast kahawa-toast--${lvl}`;
    el.setAttribute('role', lvl === 'error' ? 'alert' : 'status');

    const body = document.createElement('div');
    body.className = 'kahawa-toast__body';
    body.textContent = text;

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'kahawa-toast__close';
    close.setAttribute('aria-label', 'Dismiss');
    close.innerHTML = '&times;';
    close.addEventListener('click', () => dismissToast(el));

    el.appendChild(body);
    el.appendChild(close);
    host.appendChild(el);

    requestAnimationFrame(() => {
      el.classList.add('is-in');
    });

    if (duration > 0) {
      window.setTimeout(() => dismissToast(el), duration);
    }
    return el;
  }

  function bootFromDjango() {
    const node = document.getElementById('django-toast-messages');
    if (!node) return;
    let items = [];
    try {
      items = JSON.parse(node.textContent || '[]');
    } catch (_) {
      return;
    }
    if (!Array.isArray(items) || !items.length) return;
    items.forEach((item, i) => {
      const delay = i * 80;
      window.setTimeout(() => {
        showToast(item.text || item.message || '', item.level || item.tags || 'info');
      }, delay);
    });
  }

  window.showToast = showToast;
  window.KahawaToast = { show: showToast, dismiss: dismissToast };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootFromDjango);
  } else {
    bootFromDjango();
  }
})();
