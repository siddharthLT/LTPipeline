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

// Dashboard: filter accounts by search text, segment and stage.
(function () {
  var form = document.getElementById('filters');
  if (!form) return;
  var q = document.getElementById('f-q'), seg = document.getElementById('f-segment'),
      stg = document.getElementById('f-stage'), clear = document.getElementById('f-clear'),
      count = document.getElementById('f-count'), empty = document.getElementById('f-empty');
  var rows = Array.from(document.querySelectorAll('tr[data-row]'));
  function apply() {
    var text = q.value.trim().toLowerCase(), shown = 0;
    rows.forEach(function (r) {
      var ok = (!text || r.dataset.text.indexOf(text) !== -1) &&
               (!seg.value || r.dataset.segment === seg.value) &&
               (stg.value === '' || r.dataset.stage === stg.value);
      r.hidden = !ok;
      var d = document.getElementById(r.dataset.row);
      if (d && !ok) d.hidden = true;
      if (ok) shown++;
    });
    empty.hidden = shown !== 0;
    count.textContent = shown + ' of ' + rows.length;
    clear.hidden = !(text || seg.value || stg.value !== '');
  }
  [q, seg, stg].forEach(function (el) { el.addEventListener('input', apply); el.addEventListener('change', apply); });
  clear.addEventListener('click', function () { q.value = ''; seg.value = ''; stg.value = ''; apply(); });
  apply();
})();

// Cmd/Ctrl+K search palette, available on every page.
(function () {
  var dlg = document.getElementById('palette');
  if (!dlg) return;
  var input = document.getElementById('palette-q'), list = document.getElementById('palette-list');
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  document.querySelectorAll('[data-kbd]').forEach(function (k) { k.textContent = isMac ? '⌘K' : 'Ctrl K'; });
  var pages = [
    {name: 'Pipeline', sub: 'Dashboard', url: '/'},
    {name: 'Usage playbook', sub: 'Page', url: '/playbook/'},
    {name: 'Scoring rules', sub: 'Page', url: '/rules/'}
  ];
  var data = null, items = [], sel = 0;
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
  function render() {
    var t = input.value.trim().toLowerCase();
    var all = (data || []).map(function (a) {
      return {name: a.name, sub: [a.domain, a.segment, a.stage + ' · ' + a.score + '%'].filter(Boolean).join(' · '), url: a.url, hay: (a.name + ' ' + a.domain + ' ' + a.segment).toLowerCase()};
    });
    if (t) {
      items = all.filter(function (a) { return a.hay.indexOf(t) !== -1; });
      items.sort(function (a, b) { return (b.name.toLowerCase().indexOf(t) === 0) - (a.name.toLowerCase().indexOf(t) === 0); });
      items = items.concat(pages.filter(function (p) { return p.name.toLowerCase().indexOf(t) !== -1; }));
    } else {
      items = pages.concat(all);
    }
    items = items.slice(0, 30);
    sel = 0;
    list.innerHTML = items.length ? items.map(function (it, i) {
      return '<li role="option" data-i="' + i + '" class="palette__item' + (i === 0 ? ' is-sel' : '') + '"><span class="palette__n">' + esc(it.name) + '</span><span class="palette__s">' + esc(it.sub) + '</span></li>';
    }).join('') : '<li class="palette__empty">' + (data ? 'No matches.' : 'Loading…') + '</li>';
  }
  function mark() {
    Array.from(list.children).forEach(function (li, i) { li.classList.toggle('is-sel', i === sel); });
    var el = list.children[sel]; if (el && el.scrollIntoView) el.scrollIntoView({block: 'nearest'});
  }
  function go(i) { if (items[i]) window.location.href = items[i].url; }
  function open() {
    if (!dlg.open) dlg.showModal();
    input.value = ''; render(); input.focus();
    if (!data) fetch(dlg.dataset.searchUrl, {credentials: 'same-origin'}).then(function (r) { return r.json(); })
      .then(function (j) { data = j.accounts; render(); }).catch(function () { data = []; render(); });
  }
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); dlg.open ? dlg.close() : open(); }
  });
  document.addEventListener('click', function (e) { if (e.target.closest('[data-open-palette]')) open(); });
  input.addEventListener('input', render);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, items.length - 1); mark(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); mark(); }
    else if (e.key === 'Enter') { e.preventDefault(); go(sel); }
  });
  list.addEventListener('click', function (e) { var li = e.target.closest('[data-i]'); if (li) go(+li.dataset.i); });
  dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
})();

// Dashboard: ARR forecast chart with a month slider.
(function () {
  var dataEl = document.getElementById('arr-data');
  if (!dataEl) return;
  var pts = JSON.parse(dataEl.textContent).points;
  var svg = document.getElementById('arr-svg'), range = document.getElementById('arr-range');
  var W = 640, H = 280, L = 56, R = 16, T = 16, B = 30;
  var max = Math.max.apply(null, pts.map(function (p) { return p.best_arr; })) || 1;
  var step = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / step) * step;
  function x(m) { return L + (W - L - R) * m / 12; }
  function y(v) { return T + (H - T - B) * (1 - v / top); }
  function money(v) { return v >= 1e6 ? '$' + (v / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M' : '$' + Math.round(v / 1000) + 'K'; }
  function line(key) { return pts.map(function (p, i) { return (i ? 'L' : 'M') + x(p.month).toFixed(1) + ' ' + y(p[key]).toFixed(1); }).join(' '); }
  var g = '';
  for (var i = 0; i <= 4; i++) {
    var v = top * i / 4;
    g += '<line class="arr__grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>' +
         '<text class="arr__axis" x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + money(v) + '</text>';
  }
  [0, 3, 6, 9, 12].forEach(function (m) {
    g += '<text class="arr__axis" x="' + x(m) + '" y="' + (H - 8) + '" text-anchor="middle">' + (m ? m + ' mo' : 'Today') + '</text>';
  });
  svg.innerHTML = g +
    '<path class="arr__best" d="' + line('best_arr') + '"/>' +
    '<path class="arr__area" d="' + line('arr') + ' L' + x(12) + ' ' + y(0) + ' L' + x(0) + ' ' + y(0) + ' Z"/>' +
    '<path class="arr__line" d="' + line('arr') + '"/>' +
    '<line class="arr__cursor" id="arr-cur" y1="' + T + '" y2="' + (H - B) + '"/>' +
    '<circle class="arr__dot" id="arr-dot" r="6"/><circle class="arr__dot arr__dot--b" id="arr-dotb" r="4"/>';
  var cur = document.getElementById('arr-cur'), dot = document.getElementById('arr-dot'), dotb = document.getElementById('arr-dotb');
  function show() {
    var p = pts[+range.value];
    cur.setAttribute('x1', x(p.month)); cur.setAttribute('x2', x(p.month));
    dot.setAttribute('cx', x(p.month)); dot.setAttribute('cy', y(p.arr));
    dotb.setAttribute('cx', x(p.month)); dotb.setAttribute('cy', y(p.best_arr));
    document.getElementById('arr-when').textContent = p.month ? p.date + ' · ' + p.month + ' month' + (p.month > 1 ? 's' : '') + ' out' : 'Today · ' + p.date;
    document.getElementById('arr-accounts').textContent = p.accounts.toFixed(1);
    document.getElementById('arr-arr').textContent = money(p.arr);
    document.getElementById('arr-users').textContent = p.users;
    document.getElementById('arr-accounts-b').textContent = 'best case ' + p.best_accounts;
    document.getElementById('arr-arr-b').textContent = 'best case ' + money(p.best_arr);
    document.getElementById('arr-users-b').textContent = 'best case ' + p.best_users;
  }
  range.addEventListener('input', show);
  show();
})();
