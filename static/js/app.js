(function () {
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  // Static dialogs (Add Account)
  document.querySelectorAll('[data-open-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var d = document.getElementById(btn.dataset.openDialog);
      if (d && !d.open) {
        if (btn.dataset.fillName !== undefined) {
          d.querySelector('input[name=name]').value = btn.dataset.fillName;
          d.querySelector('input[name=domain]').value = btn.dataset.fillDomain || '';
        }
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
    if (json && json.anchor && !window.HR_DECK) location.hash = json.anchor;
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
    {name: 'Pipeline', sub: 'Dashboard · ARR forecast and accounts', url: '/', hay: 'pipeline dashboard arr forecast accounts'},
    {name: 'Product usage', sub: 'Page · BioLens usage by account', url: '/usage/', hay: 'product usage biolens posthog'},
    {name: 'Health check', sub: 'Page · how filled in each account is', url: '/health-check/', hay: 'health check filled fields'},
    {name: 'Usage playbook', sub: 'Page', url: '/playbook/', hay: 'usage playbook'},
    {name: 'Scoring rules', sub: 'Page', url: '/rules/', hay: 'scoring rules score steps'}
  ];
  function norm(t) { return String(t || '').toLowerCase().replace(/[^a-z0-9]+/g, ''); }
  var data = null, items = [], sel = 0, failed = false;
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
  function render() {
    var t = input.value.trim().toLowerCase(), tn = norm(t), words = t.split(/\s+/).filter(Boolean);
    var all = (data || []).map(function (a) {
      var hay = (a.name + ' ' + a.domain + ' ' + a.segment + ' ' + (a.advisors || '')).toLowerCase();
      return {name: a.name, sub: [a.domain, a.segment, a.stage + ' · ' + a.score + '%'].filter(Boolean).join(' · '), url: a.url, hay: hay, hn: norm(hay), nn: norm(a.name)};
    });
    function hit(x) { return words.every(function (w) { return x.hay.indexOf(w) !== -1; }) || x.hn.indexOf(tn) !== -1; }
    var pg = pages.map(function (p) { p.hn = norm(p.name + ' ' + p.hay); p.nn = norm(p.name); return p; });
    if (t) {
      items = all.filter(hit);
      items.sort(function (a, b) { return (b.nn.indexOf(tn) === 0) - (a.nn.indexOf(tn) === 0); });
      var pm = pg.filter(function (p) { return p.nn.indexOf(tn) !== -1 || hit({hay: p.name.toLowerCase() + ' ' + p.hay, hn: p.hn}); });
      items = pm.concat(items);
    } else {
      items = pg.concat(all);
    }
    items = items.slice(0, 30);
    sel = 0;
    list.innerHTML = items.length ? items.map(function (it, i) {
      return '<li role="option" data-i="' + i + '" class="palette__item' + (i === 0 ? ' is-sel' : '') + '"><span class="palette__n">' + esc(it.name) + '</span><span class="palette__s">' + esc(it.sub) + '</span></li>';
    }).join('') : '<li class="palette__empty">' + (data ? 'No matches.' : failed ? 'Could not load accounts. Reload the page or log in again.' : 'Loading…') + '</li>';
  }
  function mark() {
    Array.from(list.children).forEach(function (li, i) { li.classList.toggle('is-sel', i === sel); });
    var el = list.children[sel]; if (el && el.scrollIntoView) el.scrollIntoView({block: 'nearest'});
  }
  function go(i) { if (items[i]) window.location.href = items[i].url; }
  function open() {
    failed = false;
    if (!dlg.open) dlg.showModal();
    input.value = ''; render(); input.focus();
    if (!data) fetch(dlg.dataset.searchUrl, {credentials: 'same-origin'}).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (j) { data = j.accounts; render(); }).catch(function () { data = null; failed = true; render(); });
  }
  document.addEventListener('keydown', function (e) {
    var mod = isMac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
    if (mod && !e.altKey && !e.shiftKey && ((e.key || '').toLowerCase() === 'k' || e.code === 'KeyK')) { e.preventDefault(); dlg.open ? dlg.close() : open(); }
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

// Dashboard: ARR forecast chart, stacked by tier, with a month slider.
(function () {
  var dataEl = document.getElementById('arr-data');
  if (!dataEl) return;
  var data = JSON.parse(dataEl.textContent), pts = data.points, N = data.months;
  var svg = document.getElementById('arr-svg'), range = document.getElementById('arr-range');
  var W = 640, H = 280, L = 56, R = 16, T = 16, B = 30;
  // Scale to the expected line; the best case runs off the top when it is far above.
  var max = Math.max.apply(null, pts.map(function (p) { return p.arr; })) * 1.3 || 1;
  var step = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / step) * step;
  function x(m) { return L + (W - L - R) * m / N; }
  function y(v) { return T + (H - T - B) * (1 - Math.min(v, top) / top); }
  function money(v) { return v >= 1e6 ? '$' + (v / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M' : '$' + Math.round(v / 1000) + 'K'; }
  function path(fn) { return pts.map(function (p, i) { return (i ? 'L' : 'M') + x(p.month).toFixed(1) + ' ' + y(fn(p)).toFixed(1); }).join(' '); }
  var g = '';
  for (var i = 0; i <= 4; i++) {
    var v = top * i / 4;
    g += '<line class="arr__grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>' +
         '<text class="arr__axis" x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + money(v) + '</text>';
  }
  for (var m = 0; m <= N; m += 3) {
    g += '<text class="arr__axis" x="' + x(m) + '" y="' + (H - 8) + '" text-anchor="middle">' + (m ? m + ' mo' : 'Today') + '</text>';
  }
  var area = '<path class="arr__area" d="' + path(function (p) { return p.arr; }) + ' L' + x(N) + ' ' + y(0) + ' L' + x(0) + ' ' + y(0) + ' Z"/>';
  svg.innerHTML = g +
    '<path class="arr__best" d="' + path(function (p) { return p.best_arr; }) + '"/>' + area +
    '<path class="arr__line" d="' + path(function (p) { return p.arr; }) + '"/>' +
    '<line class="arr__cursor" id="arr-cur" y1="' + T + '" y2="' + (H - B) + '"/>' +
    '<circle class="arr__dot" id="arr-dot" r="6"/><circle class="arr__dot arr__dot--b" id="arr-dotb" r="4"/>';
  var cur = document.getElementById('arr-cur'), dot = document.getElementById('arr-dot'), dotb = document.getElementById('arr-dotb');
  function show() {
    var p = pts[+range.value];
    cur.setAttribute('x1', x(p.month)); cur.setAttribute('x2', x(p.month));
    dot.setAttribute('cx', x(p.month)); dot.setAttribute('cy', y(p.arr));
    dotb.setAttribute('cx', x(p.month)); dotb.setAttribute('cy', y(p.best_arr));
    document.getElementById('arr-when').textContent = p.month ? p.date + ' \u00b7 ' + p.month + ' month' + (p.month > 1 ? 's' : '') + ' out' : 'Today \u00b7 ' + p.date;
    document.getElementById('arr-accounts').textContent = p.accounts;
    document.getElementById('arr-names').textContent = p.names.length ? p.names.join(', ') : 'None yet';
    document.getElementById('arr-signed').textContent = data.signed.length ? data.signed.join(', ') : 'None yet';
    document.getElementById('arr-arr').textContent = money(p.arr);
    document.getElementById('arr-credits').textContent = p.credits >= 1e6 ? (p.credits / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M' : Math.round(p.credits / 1000) + 'K';
    document.getElementById('arr-accounts-b').textContent = 'best case ' + p.best_accounts;
    document.getElementById('arr-arr-b').textContent = 'best case ' + money(p.best_arr);
  }
  range.addEventListener('input', show);
  show();
})();

document.addEventListener('click', function (e) {
  document.querySelectorAll('details.pop[open]').forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute('open'); });
});

// Dashboard: pick accounts, then open the Hand Raisers view in a new tab.
(function () {
  var bar = document.getElementById('hr-bar');
  if (!bar) return;
  var picks = Array.from(document.querySelectorAll('.hr-pick')), open = document.getElementById('hr-open'),
      count = document.getElementById('hr-count'), base = open.getAttribute('href');
  function update() {
    var ids = picks.filter(function (c) { return c.checked && !c.closest('tr').hidden; }).map(function (c) { return c.value; });
    bar.hidden = ids.length === 0;
    count.textContent = ids.length + ' selected';
    open.href = base + '?ids=' + ids.join(',');
  }
  picks.forEach(function (c) { c.addEventListener('change', update); });
  var form = document.getElementById('filters');
  if (form) ['input', 'change', 'click'].forEach(function (ev) { form.addEventListener(ev, update); });
  document.getElementById('hr-clear').addEventListener('click', function () { picks.forEach(function (c) { c.checked = false; }); update(); });
})();

// Pipeline table: fit a long company name in its column. Shrink the font first; if it still does not fit on
// one line, wrap to two lines at a small size (three at worst), so the whole name always shows.
(function () {
  var names = document.querySelectorAll('.gantt__co');
  if (!names.length) return;
  var ONE_MIN = 11, TWO_START = 12, TWO_MIN = 9;
  // scrollWidth is rounded, so a name 0.4px too wide still gets an ellipsis; measure the real text width
  function tooWide(el) {
    var r = document.createRange();
    r.selectNodeContents(el);
    return r.getBoundingClientRect().width > el.getBoundingClientRect().width + 0.01;
  }
  function fit(el) {
    el.style.fontSize = ''; el.classList.remove('gantt__co--wrap', 'gantt__co--wrap3');
    if (!el.clientWidth) return;  // row hidden by a filter; refits when it is shown again
    var size = parseFloat(getComputedStyle(el).fontSize);
    while (tooWide(el) && size > ONE_MIN) { size -= 0.5; el.style.fontSize = size + 'px'; }
    if (!tooWide(el)) return;
    el.classList.add('gantt__co--wrap');
    size = TWO_START; el.style.fontSize = size + 'px';
    while (el.scrollHeight > el.clientHeight + 1 && size > TWO_MIN) { size -= 0.5; el.style.fontSize = size + 'px'; }
    if (el.scrollHeight > el.clientHeight + 1) el.classList.add('gantt__co--wrap3');  // last resort: a third line, the row grows a little
  }
  function fitAll() { names.forEach(fit); }
  if (window.ResizeObserver) {
    var seen = new WeakMap();
    var ro = new ResizeObserver(function (entries) {
      entries.forEach(function (e) {
        var w = Math.round(e.contentRect.width);
        if (seen.get(e.target) !== w) { seen.set(e.target, w); fit(e.target); }
      });
    });
    names.forEach(function (el) { ro.observe(el); });
  } else {
    window.addEventListener('resize', fitAll);
  }
  fitAll();
  if (document.fonts) {
    if (document.fonts.ready) document.fonts.ready.then(fitAll);
    if (document.fonts.addEventListener) document.fonts.addEventListener('loadingdone', fitAll);  // a weight loaded late changes text widths
  }
  window.addEventListener('load', fitAll);
})();

// Page loader: the Lunartree mark over the page while a slow navigation or form post is in flight.
(function () {
  var el = document.querySelector('[data-loader]');
  if (!el) return;
  var timer, failsafe;
  function show() {
    clearTimeout(timer);
    timer = setTimeout(function () {  // quick pages never flash it
      el.hidden = false;
      requestAnimationFrame(function () { el.classList.add('is-on'); });
      failsafe = setTimeout(hide, 30000);  // downloads and cancelled loads never leave it stuck
    }, 200);
  }
  function hide() {
    clearTimeout(timer); clearTimeout(failsafe);
    el.classList.remove('is-on'); el.hidden = true;
  }
  window.addEventListener('pageshow', hide);  // also covers back/forward cache restores
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest('a[href]');
    if (!a || a.target === '_blank' || a.hasAttribute('download') || a.hasAttribute('data-edit-url')) return;
    var u;
    try { u = new URL(a.href, location.href); } catch (err) { return; }
    if (u.origin !== location.origin || !/^https?:$/.test(u.protocol)) return;
    if (u.pathname === location.pathname && u.search === location.search) return;  // same page or a #hash
    if (/\.(pdf|json|csv|xlsx?)$/i.test(u.pathname)) return;
    show();
  });
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (e.defaultPrevented || f.target === '_blank' || f.hasAttribute('data-edit-url')) return;
    show();
  });
})();

// Filter forms that apply as soon as a select or checkbox changes
document.querySelectorAll('[data-autosubmit]').forEach(function (form) {
  form.querySelectorAll('[data-change-submit]').forEach(function (el) {
    el.addEventListener('change', function () { form.requestSubmit(); });
  });
});

// Mapped universe: dropdown of matching companies while typing
(function () {
  var form = document.querySelector('[data-suggest-url]'), input = form && form.querySelector('[data-suggest]');
  if (!input) return;
  var list = document.getElementById('mu-sugg'), sel = -1, timer = null, seq = 0, items = [];
  function close() { list.hidden = true; input.setAttribute('aria-expanded', 'false'); sel = -1; }
  function pick(name) { input.value = name; form.requestSubmit(); }
  function mark() { Array.from(list.children).forEach(function (li, k) { li.classList.toggle('is-sel', k === sel); }); }
  function render(rows) {
    items = rows; list.textContent = '';
    rows.forEach(function (r) {
      var li = document.createElement('li'); li.setAttribute('role', 'option'); li.className = 'mu__opt';
      var ini = document.createElement('span'); ini.className = 'logo logo--sm';
      var i = document.createElement('span'); i.className = 'logo__ini'; i.textContent = (r.name || '?').charAt(0).toUpperCase(); ini.appendChild(i);
      if (r.logo) { var im = document.createElement('img'); im.src = r.logo; im.alt = ''; im.onerror = function () { im.remove(); }; ini.appendChild(im); }
      var t = document.createElement('span'); t.className = 'mu__opt-txt';
      var n = document.createElement('strong'); n.textContent = r.name;
      var m = document.createElement('span'); m.className = 't-meta'; m.textContent = [r.segment, r.place].filter(Boolean).join(' · ');
      t.appendChild(n); t.appendChild(m); li.appendChild(ini); li.appendChild(t);
      li.addEventListener('mousedown', function (e) { e.preventDefault(); pick(r.name); });
      list.appendChild(li);
    });
    list.hidden = !rows.length; input.setAttribute('aria-expanded', rows.length ? 'true' : 'false'); sel = -1;
  }
  input.addEventListener('input', function () {
    clearTimeout(timer);
    var v = input.value.trim();
    if (v.length < 2) { close(); return; }
    timer = setTimeout(function () {
      var params = new URLSearchParams(new FormData(form)); params.set('q', v); params.delete('logo');
      var me = ++seq;
      fetch(form.dataset.suggestUrl + '?' + params.toString(), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (me === seq) render(d.results || []); })
        .catch(close);
    }, 150);
  });
  input.addEventListener('keydown', function (e) {
    if (list.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, items.length - 1); mark(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); mark(); }
    else if (e.key === 'Enter' && sel >= 0) { e.preventDefault(); pick(items[sel].name); }
    else if (e.key === 'Escape') close();
  });
  input.addEventListener('blur', function () { setTimeout(close, 120); });
})();


// Product usage: generate a new AI summary for the current tab and stream it into the panel (no page reload)
document.querySelectorAll('[data-insights]').forEach(function (box) {
  var btn = box.querySelector('[data-insights-go]'), err = box.querySelector('[data-insights-err]'), loading = box.querySelector('[data-insights-loading]');
  var body = box.querySelector('[data-insights-body]'), meta = box.querySelector('[data-insights-meta]');
  var toggle = box.querySelector('[data-insights-toggle]'), hasOne = !toggle.hidden;
  // the summary stays folded away until someone opens it
  function open(on) {
    body.hidden = !on; toggle.setAttribute('aria-expanded', on ? 'true' : 'false');
    toggle.querySelector('span').textContent = on ? 'Collapse' : 'Expand';
    toggle.classList.toggle('is-open', on);
  }
  toggle.addEventListener('click', function () { open(body.hidden); });
  var SECTIONS = [['highlights', 'Key highlights', ' ins__box--hi'], ['insights', 'General insights', ''], ['outliers', 'Outliers', ''], ['risks', 'Risks', ' ins__box--risk']];
  var HEADS = { HEADLINE: 'headline', HIGHLIGHTS: 'highlights', INSIGHTS: 'insights', OUTLIERS: 'outliers', RISKS: 'risks' };

  function parse(text) {
    var out = { headline: '', highlights: [], insights: [], outliers: [], risks: [] }, section = null;
    text.split('\n').forEach(function (line) {
      var s = line.trim(), i = s.indexOf(':'), word = i > -1 ? s.slice(0, i).replace(/^[*# ]+|[*# ]+$/g, '').toUpperCase() : '';
      if (i > -1 && HEADS[word]) { section = HEADS[word]; if (section === 'headline') out.headline = s.slice(i + 1).trim(); return; }
      if (!s || !section) return;
      if (section === 'headline') { out.headline = (out.headline + ' ' + s).trim(); return; }
      var list = out[section];
      if (/^[-*•]/.test(s) || !list.length) list.push(s.replace(/^[-*•\s]+/, '')); else list[list.length - 1] += ' ' + s;
    });
    return out;
  }
  function render(c) {
    body.textContent = '';
    if (c.headline) { var h = document.createElement('p'); h.className = 'ins__headline'; h.textContent = c.headline; body.appendChild(h); }
    var grid = document.createElement('div'); grid.className = 'ins__grid';
    SECTIONS.forEach(function (sec) {
      if (!c[sec[0]].length) return;
      var d = document.createElement('div'); d.className = 'ins__box' + sec[2];
      var t = document.createElement('h3'); t.textContent = sec[1]; d.appendChild(t);
      var ul = document.createElement('ul');
      c[sec[0]].forEach(function (x) { var li = document.createElement('li'); li.textContent = x; ul.appendChild(li); });
      d.appendChild(ul); grid.appendChild(d);
    });
    body.appendChild(grid);
  }
  function fail(msg) { err.textContent = msg; err.hidden = false; }

  btn.addEventListener('click', function () {
    var label = btn.querySelector('span'), text = '', buf = '', started = false;
    open(true); toggle.hidden = true;  // show it as it is written
    btn.setAttribute('aria-busy', 'true'); label.textContent = 'Generating…'; err.hidden = true; loading.hidden = false;
    var form = new URLSearchParams({ tab: box.dataset.tab, days: box.dataset.days, csrfmiddlewaretoken: box.querySelector('[name=csrfmiddlewaretoken]').value });
    function handle(ev) {
      if (ev.t === 'reset') { text = ''; started = false; loading.hidden = false; body.textContent = ''; }
      else if (ev.t === 'delta') { text += ev.v; if (!started) { started = true; loading.hidden = true; body.textContent = ''; } render(parse(text)); }
      else if (ev.t === 'done') { hasOne = true; render(ev.content); meta.textContent = 'Generated just now by you for the last ' + box.dataset.days + ' days. Everyone sees this one until someone generates a new one.'; }
      else if (ev.t === 'error') fail(ev.v);
    }
    fetch(box.dataset.url, { method: 'POST', body: form, credentials: 'same-origin' }).then(function (r) {
      if (!r.ok || !r.body) return r.json().then(function (j) { fail(j.error || 'Something went wrong.'); }).catch(function () { fail('Something went wrong.'); });
      var reader = r.body.getReader(), dec = new TextDecoder();
      return (function pump() {
        return reader.read().then(function (res) {
          if (res.done) return;
          buf += dec.decode(res.value, { stream: true });
          var lines = buf.split('\n'); buf = lines.pop();
          lines.forEach(function (l) { if (l.trim()) handle(JSON.parse(l)); });
          return pump();
        });
      })();
    }).catch(function () { fail('Could not reach the server.'); }).finally(function () {
      btn.removeAttribute('aria-busy'); label.textContent = hasOne ? 'New insights' : 'Generate insights'; loading.hidden = true;
      toggle.hidden = !hasOne;
    });
  });
});

/* red dot and count of who is on BioLens right now, on the Recordings tab */
document.addEventListener('DOMContentLoaded', function () {
  var nav = document.querySelector('[data-live-url]');
  var live = nav && nav.querySelector('.live');
  if (!live) return;
  var n = live.querySelector('.live__n'), pop = live.querySelector('.live__pop');
  function ago(s) { return s < 60 ? 'just now' : Math.round(s / 60) + ' min ago'; }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }
  function poll() {
    if (document.hidden) return;
    fetch(nav.dataset.liveUrl, { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
      live.hidden = !d.count;
      n.textContent = d.count;
      pop.textContent = '';
      pop.appendChild(el('div', 'live__h', d.count + ' live now · active in the last ' + d.minutes + ' min'));
      d.people.forEach(function (p) {
        var row = el('div', 'live__row');
        row.appendChild(el('strong', '', p.who + (p.account ? ' · ' + p.account : '')));
        row.appendChild(el('span', '', p.area + ' · ' + ago(p.ago)));
        pop.appendChild(row);
      });
    }).catch(function () {});
  }
  poll();
  setInterval(poll, 30000);
  document.addEventListener('visibilitychange', poll);
});
