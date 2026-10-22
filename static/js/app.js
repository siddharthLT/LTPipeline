(function () {
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  // Static dialogs (Add Account)
  document.querySelectorAll('[data-open-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var d = document.getElementById(btn.dataset.openDialog);
      if (d && !d.open) {
        d.showModal();
        var first = d.querySelector('input:not([type=hidden])');
        if (first) first.focus();
      }
    });
  });
  document.querySelectorAll('dialog').forEach(function (d) {
    d.addEventListener('click', function (e) {
      if (e.target === d || e.target.closest('[data-close-dialog]')) d.close();
    });
    if (d.hasAttribute('data-open-on-load')) {
      d.showModal();
      var bad = d.querySelector('[aria-invalid="true"]');
      if (bad) bad.focus();
    }
  });

  var bar = document.querySelector('[data-appbar]');
  if (bar) {
    var onScroll = function () { bar.dataset.scrolled = window.scrollY > 4 ? 'true' : 'false'; };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  // Edit modal: fetch the form fragment, post it back, reload on success.
  var modal = document.getElementById('edit-modal');
  var slot = modal && modal.querySelector('[data-modal-slot]');

  function post(url, body) {
    return fetch(url, {
      method: 'POST', body: body || null,
      headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'fetch' }, credentials: 'same-origin'
    });
  }
  function done(json) {
    if (json && json.anchor) location.hash = json.anchor;
    location.reload();
  }
  function openEdit(url) {
    if (!modal) return;
    fetch(url, { headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        slot.innerHTML = html;
        if (!modal.open) modal.showModal();
        var f = slot.querySelector('input:not([type=hidden]):not([type=checkbox]), textarea, select');
        if (f) f.focus();
      });
  }

  document.addEventListener('click', function (e) {
    var edit = e.target.closest('[data-edit-url]');
    if (edit) { e.preventDefault(); e.stopPropagation(); openEdit(edit.dataset.editUrl); return; }

    var toggle = e.target.closest('[data-toggle-url]');
    if (toggle) {
      post(toggle.dataset.toggleUrl).then(function (r) { return r.json(); }).then(done);
      return;
    }

    var del = e.target.closest('[data-delete-url]');
    if (del) {
      if (del.dataset.armed !== 'true') {
        del.dataset.armed = 'true';
        del.textContent = 'Click again to delete';
        return;
      }
      post(del.dataset.deleteUrl).then(function (r) { return r.json(); }).then(done);
    }
  }, true);

  if (modal) {
    modal.addEventListener('submit', function (e) {
      e.preventDefault();
      var form = e.target;
      post(form.action, new FormData(form)).then(function (r) {
        if (r.ok) return r.json().then(done);
        return r.text().then(function (html) { slot.innerHTML = html; var bad = slot.querySelector('.field-error'); if (bad) bad.scrollIntoView({ block: 'nearest' }); });
      });
    });
  }

})();

// Dashboard: expand the summary row under an account.
document.addEventListener('click', function (e) {
  var t = e.target.closest('[data-toggle-row]');
  if (!t) return;
  var row = document.getElementById(t.dataset.toggleRow);
  if (!row) return;
  var open = row.hasAttribute('hidden');
  row.toggleAttribute('hidden', !open);
  t.setAttribute('aria-expanded', open ? 'true' : 'false');
});

// Thesis page: highlight the left-nav entry for the section in view.
(function () {
  const links = Array.from(document.querySelectorAll('.toc__a'));
  if (!links.length || !('IntersectionObserver' in window)) return;
  const byId = new Map(links.map((a) => [a.getAttribute('href').slice(1), a]));
  const set = (id) => links.forEach((a) => a.classList.toggle('is-active', a === byId.get(id)));
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) set(e.target.id); });
  }, { rootMargin: '-15% 0px -70% 0px' });
  byId.forEach((_, id) => { const el = document.getElementById(id); if (el) io.observe(el); });
  set(links[0].getAttribute('href').slice(1));
})();

// Right-hand pending actions panel: collapse and remember the choice.
(function () {
  var shell = document.querySelector('[data-shell]');
  var btn = document.querySelector('[data-actionbar-toggle]');
  if (!shell || !btn) return;
  function apply(collapsed) {
    shell.classList.toggle('actions-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.setAttribute('aria-label', collapsed ? 'Expand pending actions' : 'Collapse pending actions');
  }
  try { apply(localStorage.getItem('actionsCollapsed') === '1'); } catch (e) {}
  btn.addEventListener('click', function () {
    var c = !shell.classList.contains('actions-collapsed');
    apply(c);
    try { localStorage.setItem('actionsCollapsed', c ? '1' : '0'); } catch (e) {}
  });
})();

// Login: show or hide the password so it can be checked.
document.addEventListener('click', function (e) {
  var t = e.target.closest('[data-pw-toggle]');
  if (!t) return;
  var input = t.parentElement.querySelector('input');
  if (!input) return;
  var show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  t.setAttribute('aria-pressed', show ? 'true' : 'false');
  t.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  t.querySelector('.pw__eye').hidden = show;
  t.querySelector('.pw__eye-off').hidden = !show;
  input.focus();
});
