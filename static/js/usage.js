// Recordings tab: account playlists, length chips and sorting. Everything is already on the page, so this only shows, hides and reorders.
(function () {
  var root = document.querySelector('[data-recs]');
  if (!root) return;
  var grid = root.querySelector('[data-rec-grid]'), none = root.querySelector('[data-rec-none]'),
      count = root.querySelector('[data-rec-count]'), sortBy = root.querySelector('[data-rec-sort]'),
      cards = Array.from(grid.querySelectorAll('.rec')),
      acctChips = Array.from(root.querySelectorAll('[data-rec-acct]')),
      lenChips = Array.from(root.querySelectorAll('[data-rec-len]'));
  var acct = '';

  function off() { return lenChips.filter(function (c) { return c.getAttribute('aria-pressed') === 'false'; }).map(function (c) { return c.dataset.recLen; }); }
  function apply() {
    var hide = off(), shown = 0;
    cards.forEach(function (c) {
      var ok = (!acct || c.dataset.acct === acct) && hide.indexOf(c.dataset.len) < 0;
      c.hidden = !ok;
      if (ok) shown++;
    });
    count.textContent = shown + ' of ' + cards.length;
    none.hidden = shown > 0 || cards.length === 0;
  }
  function sort() {
    var key = sortBy.value, field = { new: 'ts', long: 'dur', active: 'active', busy: 'clicks' }[key] || 'ts';
    cards.sort(function (a, b) { return (b.dataset[field] - a.dataset[field]) || (b.dataset.ts - a.dataset.ts); })
      .forEach(function (c) { grid.appendChild(c); });
  }
  acctChips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      acct = chip.dataset.recAcct;
      acctChips.forEach(function (c) { c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'); });
      apply();
    });
  });
  lenChips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      chip.setAttribute('aria-pressed', chip.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
      apply();
    });
  });
  sortBy.addEventListener('change', sort);
  sort(); apply();
})();
