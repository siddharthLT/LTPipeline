(function () {
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  document.addEventListener('click', function (e) {
    var open = e.target.closest('[data-ot-open]');
    if (open) { var d = document.getElementById(open.dataset.otOpen); if (d && d.showModal) d.showModal(); return; }
    if (e.target.closest('[data-ot-close]')) { var dlg = e.target.closest('dialog'); if (dlg) dlg.close(); return; }
    var copy = e.target.closest('[data-ot-copy]');
    if (copy) {
      var text = copy.parentNode.querySelector('pre').textContent;
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () {
        copy.textContent = 'Copied'; setTimeout(function () { copy.textContent = 'Copy'; }, 1500);
      }, function () {});
      return;
    }
    var tick = e.target.closest('.ot__tick');
    if (!tick) return;
    var on = tick.getAttribute('aria-pressed') !== 'true';
    tick.setAttribute('aria-pressed', on ? 'true' : 'false');
    tick.closest('td').classList.toggle('is-done', on);
    var key = tick.closest('tr').dataset.person + ':' + tick.dataset.step;
    if (on === (tick.dataset.saved === '1')) delete pending[key];
    else pending[key] = { person: tick.closest('tr').dataset.person, step: tick.dataset.step, on: on };
    refresh();
  });

  var pending = {}, bar = document.querySelector('[data-ot-bar]');
  document.querySelectorAll('.ot__tick').forEach(function (t) { t.dataset.saved = t.getAttribute('aria-pressed') === 'true' ? '1' : '0'; });
  function refresh() {
    if (!bar) return;
    var n = Object.keys(pending).length;
    bar.hidden = !n;
    bar.querySelector('[data-ot-n]').textContent = n + (n === 1 ? ' change' : ' changes');
  }
  if (bar) {
    var table = document.querySelector('[data-ot-table]');
    bar.querySelector('[data-ot-save]').addEventListener('click', function (e) {
      var btn = e.currentTarget;
      btn.disabled = true; btn.textContent = 'Saving…';
      var body = new URLSearchParams({ changes: JSON.stringify(Object.keys(pending).map(function (k) { return pending[k]; })), csrfmiddlewaretoken: csrf });
      fetch(table.dataset.url, { method: 'POST', body: body, headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); pending = {}; window.location.reload(); })
        .catch(function () { alert('Could not save the ticks. Try again.'); btn.disabled = false; btn.textContent = 'Update'; });
    });
    bar.querySelector('[data-ot-discard]').addEventListener('click', function () { pending = {}; window.location.reload(); });
    window.addEventListener('beforeunload', function (e) { if (Object.keys(pending).length) { e.preventDefault(); e.returnValue = ''; } });
  }

  // the subject line only applies to email steps
  function syncKind(sel) {
    var form = sel.closest('form'), sub = form.querySelector('[data-ot-subject]');
    if (sub) sub.hidden = sel.value !== 'email';
  }
  document.querySelectorAll('[data-ot-kind]').forEach(function (sel) {
    syncKind(sel);
    sel.addEventListener('change', function () { syncKind(sel); });
  });
})();
