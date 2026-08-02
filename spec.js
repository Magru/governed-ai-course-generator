/* ===========================================================================
   Governed AI Course Generator — shared behaviour for the specification set.

   Everything here is progressive: with the script blocked the pages still
   read, navigate and print. Nothing below writes to the document before
   DOMContentLoaded, and every animation respects prefers-reduced-motion
   through CSS rather than through branching here.
   =========================================================================== */
(function () {
  'use strict';

  var ready = function (fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  };

  var icon = function (id, cls) {
    return '<svg class="ico' + (cls ? ' ' + cls : '') + '" aria-hidden="true"><use href="#' + id + '"></use></svg>';
  };

  /* ---- section rail: highlight the section the reader is in ------------ */
  function rail() {
    var rail = document.querySelector('.rail');
    if (!rail) return;
    var links = Array.prototype.slice.call(rail.querySelectorAll('a[href^="#"]'));
    var targets = links.map(function (a) {
      return { link: a, el: document.getElementById(a.getAttribute('href').slice(1)) };
    }).filter(function (t) { return t.el; });
    if (!targets.length) return;

    var current = null;
    var apply = function (t) {
      if (t === current) return;
      current = t;
      targets.forEach(function (x) {
        var on = x === t;
        x.link.classList.toggle('active', on);
        if (on) { x.link.setAttribute('aria-current', 'true'); }
        else { x.link.removeAttribute('aria-current'); }
      });
    };

    var update = function () {
      var mid = window.innerHeight * 0.4;
      var pick = targets[0];
      for (var i = 0; i < targets.length; i++) {
        if (targets[i].el.getBoundingClientRect().top <= mid) pick = targets[i];
      }
      // at the very bottom of the page the last section wins
      if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) {
        pick = targets[targets.length - 1];
      }
      apply(pick);
    };

    // rAF-throttled, but never able to wedge: if a frame never arrives
    // (background tab, throttled timers) the age guard flushes directly.
    var queued = false;
    var lastRun = 0;
    var schedule = function () {
      var now = Date.now();
      if (queued && now - lastRun < 400) return;
      queued = true;
      window.requestAnimationFrame(function () {
        queued = false;
        lastRun = Date.now();
        update();
      });
    };

    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });
    update();
  }

  /* ---- reading progress ------------------------------------------------ */
  function progress() {
    var bar = document.querySelector('.progress');
    if (!bar) return;
    var paint = function () {
      var h = document.documentElement.scrollHeight - window.innerHeight;
      var pct = h > 0 ? Math.min(100, Math.max(0, (window.scrollY / h) * 100)) : 0;
      bar.style.width = pct.toFixed(2) + '%';
    };
    var queued = false;
    var schedule = function () {
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(function () { queued = false; paint(); });
    };
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });
    paint();
  }

  /* ---- heading anchors -------------------------------------------------
     h2 borrows its section's id; h3 gets a slug derived from its text, so a
     reader can link to a subsection rather than to the whole section. */
  function anchors() {
    var slugged = {};
    var slug = function (text) {
      var s = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'h';
      if (slugged[s]) { slugged[s] += 1; s = s + '-' + slugged[s]; } else { slugged[s] = 1; }
      return s;
    };

    var heads = document.querySelectorAll('.wrap h2, .wrap h3');
    Array.prototype.forEach.call(heads, function (h) {
      if (h.closest('.card, .layer, .phase, .callout')) return;
      var id = h.id;
      if (!id) {
        var sec = h.closest('section[id]');
        if (sec && h.tagName === 'H2' && !sec.dataset.anchored) {
          id = sec.id;
          sec.dataset.anchored = '1';
        } else {
          id = slug(h.textContent || '');
          h.id = id;
        }
      }
      var a = document.createElement('a');
      a.className = 'anchor';
      a.href = '#' + id;
      a.setAttribute('aria-label', 'Link to this section');
      a.innerHTML = icon('i-link');
      a.addEventListener('click', function (e) {
        // Copy the absolute link as well as following it — the usual reason
        // to click one of these is to paste it somewhere.
        if (navigator.clipboard) {
          e.preventDefault();
          var url = location.href.split('#')[0] + '#' + id;
          navigator.clipboard.writeText(url).then(function () {
            history.replaceState(null, '', '#' + id);
            document.getElementById(id).scrollIntoView();
            a.classList.add('copied');
            setTimeout(function () { a.classList.remove('copied'); }, 1200);
          }, function () { location.hash = id; });
        }
      });
      h.appendChild(a);
    });
  }

  /* ---- copy buttons on code listings ----------------------------------- */
  function copyButtons() {
    var blocks = document.querySelectorAll('pre, .formula, .code, .mv');
    Array.prototype.forEach.call(blocks, function (pre) {
      if (pre.classList.contains('mermaid')) return;
      if (pre.closest('.diagram')) return;
      // The io panels are two-line results, not listings worth copying.
      if (pre.closest('.io')) return;

      // Listings scroll horizontally on their own, so the button cannot live
      // inside them — it would slide off with the content. Wrap instead.
      var host = document.createElement('div');
      host.className = 'copy-host';
      pre.parentNode.insertBefore(host, pre);
      host.appendChild(pre);

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'copy-btn';
      btn.innerHTML = icon('i-copy') + '<span>copy</span>';
      btn.addEventListener('click', function () {
        var text = pre.innerText;
        var done = function () {
          btn.classList.add('done');
          btn.querySelector('span').textContent = 'copied';
          setTimeout(function () {
            btn.classList.remove('done');
            btn.querySelector('span').textContent = 'copy';
          }, 1400);
        };
        if (navigator.clipboard) {
          navigator.clipboard.writeText(text).then(done, function () {});
        }
      });
      host.appendChild(btn);
    });
  }

  /* ---- diagram zoom -----------------------------------------------------
     Mermaid renders asynchronously, so the button is attached to the panel
     and the SVG is looked up at click time rather than at load. */
  function diagramZoom() {
    var diagrams = document.querySelectorAll('.diagram');
    if (!diagrams.length) return;

    var open = function (svg) {
      var overlay = document.createElement('div');
      overlay.className = 'zoom-overlay';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.setAttribute('aria-label', 'Enlarged diagram');

      var sheet = document.createElement('div');
      sheet.className = 'zoom-sheet';
      var clone = svg.cloneNode(true);
      clone.removeAttribute('width');
      clone.removeAttribute('height');
      clone.style.width = 'min(84vw, ' + (svg.getBoundingClientRect().width * 2.1) + 'px)';
      clone.style.maxWidth = 'none';
      sheet.appendChild(clone);

      var close = document.createElement('button');
      close.type = 'button';
      close.className = 'zoom-close';
      close.innerHTML = icon('i-close') + '<span>close</span>';

      overlay.appendChild(sheet);
      overlay.appendChild(close);

      var dismiss = function () {
        overlay.remove();
        document.body.classList.remove('zoom-open');
        document.removeEventListener('keydown', onKey);
      };
      var onKey = function (e) { if (e.key === 'Escape') dismiss(); };

      overlay.addEventListener('click', function (e) {
        if (e.target === overlay || close.contains(e.target)) dismiss();
      });
      document.addEventListener('keydown', onKey);

      document.body.classList.add('zoom-open');
      document.body.appendChild(overlay);
      close.focus();
    };

    Array.prototype.forEach.call(diagrams, function (d) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'zoom-btn';
      btn.innerHTML = icon('i-expand') + '<span>enlarge</span>';
      btn.addEventListener('click', function () {
        var svg = d.querySelector('svg');
        if (svg) open(svg);
      });
      d.appendChild(btn);
    });
  }

  /* ---- back to top ----------------------------------------------------- */
  function backToTop() {
    var btn = document.querySelector('.to-top');
    if (!btn) return;
    btn.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    var toggle = function () {
      btn.classList.toggle('on', window.scrollY > window.innerHeight * 0.8);
    };
    window.addEventListener('scroll', toggle, { passive: true });
    toggle();
  }

  ready(function () {
    rail();
    progress();
    anchors();
    copyButtons();
    diagramZoom();
    backToTop();
  });
})();
