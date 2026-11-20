// Hand Raisers deck: one slide at a time, scaled to the window. Edit mode turns on the pens and ticks.
(function () {
  var deck = document.querySelector('[data-deck]');
  if (!deck) return;
  var canvas = deck.querySelector('[data-canvas]'), stage = deck.querySelector('[data-stage]'),
      slides = Array.from(deck.querySelectorAll('[data-slide]')),
      prev = deck.querySelector('[data-prev]'), next = deck.querySelector('[data-next]'),
      count = deck.querySelector('[data-count]'), bar = deck.querySelector('[data-progress]'),
      toggle = deck.querySelector('[data-edit-toggle]'), hint = deck.querySelector('[data-hint]'),
      modal = document.getElementById('edit-modal');
  var i = 0;
  try { i = Math.min(Math.max(parseInt(location.hash.slice(1), 10) - 1 || 0, 0), slides.length - 1); } catch (e) {}

  function scale() {
    canvas.style.setProperty('--scale', Math.min(stage.clientWidth / 1280, stage.clientHeight / 720) * 0.97);
  }
  function show(n) {
    i = Math.min(Math.max(n, 0), slides.length - 1);
    slides.forEach(function (s, k) { s.classList.toggle('is-active', k === i); });
    slides[i].scrollTop = 0;
    try { slides[i].focus({ preventScroll: true }); } catch (e) {}  // so the arrow keys scroll the slide
    count.textContent = (i + 1) + ' / ' + slides.length;
    bar.style.width = ((i + 1) / slides.length * 100) + '%';
    prev.disabled = i === 0; next.disabled = i === slides.length - 1;
    try { history.replaceState(null, '', '#' + (i + 1)); } catch (e) {}
  }

  function setEditing(on) {
    document.body.classList.toggle('is-editing', on);
    toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
    hint.textContent = on ? 'Editing: click a pen, step or tick. Changes save to the tracker.' : 'Left and right arrows change slide; scroll for more';
    try { sessionStorage.setItem('hr-edit', on ? '1' : '0'); } catch (e) {}
  }
  toggle.addEventListener('click', function () { setEditing(!document.body.classList.contains('is-editing')); });
  var saved = false;
  try { saved = sessionStorage.getItem('hr-edit') === '1'; } catch (e) {}
  setEditing(saved);

  deck.querySelectorAll('[data-goto]').forEach(function (el) {
    el.addEventListener('click', function () { show(parseInt(el.dataset.goto, 10) - 1); });
  });
  prev.addEventListener('click', function () { show(i - 1); });
  next.addEventListener('click', function () { show(i + 1); });
  document.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if ((modal && modal.open) || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || '')) return;
    // Up, down, space and page keys are left alone so they scroll the slide
    if (e.key === 'ArrowRight') { e.preventDefault(); show(i + 1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); show(i - 1); }
    else if (e.key === 'Home') show(0);
    else if (e.key === 'End') show(slides.length - 1);
  });
  // PDF: each slide prints on a page as tall as its content (1280px wide), not squeezed into a fixed 16:9 page
  var pageStyle = document.createElement('style');
  document.head.appendChild(pageStyle);
  function pageSizes() {
    var css = '';
    slides.forEach(function (s, k) {
      var h = Math.max(720, Math.ceil(s.scrollHeight) + 2);
      s.setAttribute('data-page', 'p' + k);
      css += '@page p' + k + ' { size: 1280px ' + h + 'px; margin: 0; }\n.slide[data-page="p' + k + '"] { page: p' + k + '; }\n';
    });
    pageStyle.textContent = css;
  }
  window.addEventListener('beforeprint', pageSizes);
  window.addEventListener('resize', scale);
  scale(); show(i); pageSizes();
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(pageSizes);
})();
