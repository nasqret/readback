/* The one script of a Readback site. Without it every page still reads: the script adds the wrap switch, copying,
   the marking of a step's Lean lines, and the choice of one statement at a time in a note's reader. */
(function () {
  'use strict';
  document.documentElement.classList.add('js');
  var store = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* a private window: nothing to keep */ } }
  };
  var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function narrow() { return window.matchMedia('(max-width: 60rem)').matches; }
  function bring(el, block, atOnce) { if (el) { el.scrollIntoView({ block: block || 'center', inline: 'nearest', behavior: calm || atOnce ? 'auto' : 'smooth' }); } }
  function within(pane, el, part, atOnce) {               // move a pane, and only the pane, until el stands at `part` of its height
    var top = pane.scrollTop + el.getBoundingClientRect().top - pane.getBoundingClientRect().top - pane.clientHeight * part;
    pane.scrollTo({ top: Math.max(0, top), behavior: calm || atOnce ? 'auto' : 'smooth' });
  }
  function each(list, f) { Array.prototype.forEach.call(list, f); }

  // ---- Lean text: wrapping and copying
  function setWrap(on) {
    each(document.querySelectorAll('pre.lean'), function (p) { p.classList.toggle('wrap', on); });
    each(document.querySelectorAll('[data-wrap]'), function (b) { b.setAttribute('aria-pressed', on ? 'true' : 'false'); });
  }
  setWrap(store.get('readback-wrap') === '1');
  function copy(button) {
    var pre = button.closest('figure').querySelector('pre');
    var text = Array.prototype.map.call(pre.querySelectorAll('.ln'), function (l) { return l.textContent; }).join('\n') + '\n';
    function say(ok) { var old = button.textContent; button.textContent = ok ? 'Copied' : 'Could not copy'; window.setTimeout(function () { button.textContent = old; }, 1400); }
    function byHand() {
      var t = document.createElement('textarea'), ok = false;
      t.value = text; t.setAttribute('readonly', ''); t.style.position = 'fixed'; t.style.opacity = '0';
      document.body.appendChild(t); t.select();
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      t.remove(); say(ok);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text).then(function () { say(true); }, byHand); } else { byHand(); }
  }
  document.addEventListener('click', function (e) {
    var w = e.target.closest('[data-wrap]'), c = e.target.closest('[data-copy]');
    if (w) { var on = w.getAttribute('aria-pressed') !== 'true'; setWrap(on); store.set('readback-wrap', on ? '1' : '0'); }
    if (c) { copy(c); }
  });

  // ---- a structured proof: choosing a step marks its lines in the declaration
  var two = document.querySelector('.two');
  if (two) {
    var aside = two.querySelector('aside');
    var pick = function (step, atOnce) {
      each(two.querySelectorAll('.step.on'), function (s) { s.classList.remove('on'); });
      each(aside.querySelectorAll('.ln.hl'), function (l) { l.classList.remove('hl'); });
      if (!step) { return; }
      step.classList.add('on');
      var r = step.getAttribute('data-lines').split('-').map(Number), first = null;
      for (var n = r[0]; n <= r[1]; n++) { var l = document.getElementById('L' + n); if (l) { l.classList.add('hl'); first = first || l; } }
      if (narrow()) { var own = step.querySelector('details.own'); if (own) { own.open = true; } }
      else if (first) { within(first.closest('pre'), first, 0.22, atOnce); }
      window.history.replaceState(null, '', '#' + step.id);
    };
    two.addEventListener('click', function (e) {
      var link = e.target.closest('a[data-step]');
      if (link) { e.preventDefault(); var t = document.getElementById(link.getAttribute('href').slice(1)); pick(t); bring(t); return; }
      if (e.target.closest('a, button, summary, pre')) { return; }
      var s = e.target.closest('.step'); if (s) { pick(s); }
    });
    two.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === ' ') && e.target.classList && e.target.classList.contains('step')) { e.preventDefault(); pick(e.target); }
    });
    var start = window.location.hash.indexOf('#s-') === 0 ? document.getElementById(window.location.hash.slice(1)) : null;
    if (start) { pick(start, true); bring(start, 'center', true); }
  }

  // ---- a note: one statement at a time, the page on the left and its Lean text on the right
  var reader = document.querySelector('.reader');
  if (reader) {
    var cards = {}, holder = reader.querySelector('.cards'), now = reader.querySelector('.now'), origin = 'load';
    each(reader.querySelectorAll('.card'), function (c) { cards[c.getAttribute('data-key')] = c; });
    var carriers = function (at) { return Array.prototype.filter.call(reader.querySelectorAll('[data-at]'), function (e) { return e.getAttribute('data-at') === at; }); };
    var pdfpane = reader.querySelector('.pdfpane');
    var show = function (els, atOnce) {
      var mark = els.filter(function (e) { return e.classList.contains('mark'); })[0], frame = reader.querySelector('.pdfframe');
      if (mark) { within(pdfpane, mark, 0.28, atOnce); if (narrow()) { bring(pdfpane, 'nearest', atOnce); } return; }
      var chip = els.filter(function (e) { return e.hasAttribute('data-page'); })[0];
      if (frame && chip) {                                   // a frame does not follow a changed fragment: put a new one
        var fresh = frame.cloneNode(false);
        fresh.src = frame.getAttribute('data-pdf') + '#page=' + chip.getAttribute('data-page');
        frame.parentNode.replaceChild(fresh, frame);
      }
    };
    var apply = function (at, how) {
      var els = carriers(at);
      if (!els.length) { return false; }
      var keys = (els[0].getAttribute('data-keys') || '').split(' ').filter(Boolean);
      each(reader.querySelectorAll('[data-at]'), function (e) {
        var mine = e.getAttribute('data-at') === at, theirs = (e.getAttribute('data-keys') || '').split(' ');
        e.classList.toggle('on', mine);
        e.classList.toggle('same', !mine && e.classList.contains('mark') && theirs.some(function (k) { return keys.indexOf(k) >= 0; }));
      });
      Object.keys(cards).forEach(function (k) { cards[k].hidden = keys.indexOf(k) < 0; });
      keys.forEach(function (k) { if (cards[k]) { holder.appendChild(cards[k]); } });
      now.textContent = '';
      var b = document.createElement('b'), s = document.createElement('span'), go = document.createElement('button');
      b.textContent = els[0].getAttribute('data-title') || '';
      s.className = 'dim'; s.textContent = keys.length + (keys.length === 1 ? ' declaration' : ' declarations');
      go.type = 'button'; go.textContent = 'Show in the note'; go.addEventListener('click', function () { show(els); });
      now.appendChild(b); now.appendChild(s); now.appendChild(go);
      holder.scrollTop = 0;
      if (how === 'mark' && narrow()) { bring(now, 'start'); }
      else if (how === 'chip' && !narrow()) { show(els); }
      else if (how === 'load') { show(els, true); }
      return true;
    };
    var fromHash = function () {
      var h = window.location.hash.slice(1);
      try { h = decodeURIComponent(h); } catch (e) { /* a broken address: read it as it stands */ }
      if (h.indexOf('at=') === 0) { return h.slice(3); }
      if (h.indexOf('d-') === 0) {                          // the address of a card: the first place that shows it
        var key = h.slice(2), hit = Array.prototype.filter.call(reader.querySelectorAll('[data-at]'), function (e) { return (e.getAttribute('data-keys') || '').split(' ').indexOf(key) >= 0; })[0];
        return hit ? hit.getAttribute('data-at') : null;
      }
      return null;
    };
    var go = function (at, how) {
      origin = how;
      if (window.location.hash === '#at=' + at) { apply(at, how); } else { window.location.hash = 'at=' + at; }
    };
    reader.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-at]');
      if (a) { e.preventDefault(); go(a.getAttribute('data-at'), a.classList.contains('mark') ? 'mark' : 'chip'); }
    });
    window.addEventListener('hashchange', function () { var at = fromHash(); if (at) { apply(at, origin); origin = 'load'; } });
    var first = reader.querySelector('.chips a[data-at]'), asked = fromHash();
    if (!(asked && apply(asked, 'load')) && first) { apply(first.getAttribute('data-at'), 'start'); }
  }
})();
