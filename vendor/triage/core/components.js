/*! Triage components.js — behaviour for the 0.6 component layer.
 *  Data-attribute driven, dependency-free, singleton-guarded. Every component
 *  degrades to its plain markup without JS.
 *
 *  [data-tabs]             tablist/tabpanel with roving focus
 *  [data-combobox]         filterable listbox; add data-multi for multi-select
 *  [data-datepicker]       input + generated month grid (ISO value, locale-aware)
 *  [data-cmd]              command palette; [data-cmd-open] buttons, cmd/ctrl+K
 *  [data-slider]           range + value readout
 *  [data-drop]             dropzone + file list (dispatches triage:files)
 *  [data-notif]            notification panel; [data-notif-read] marks all read
 *  [data-sort-table]       click-to-sort columns (.th-sort buttons)
 *  [data-pager-num]        numbered pagination demo bindings
 */
(function () {
  'use strict';

  /* ---------------------------------------------------------------- tabs */
  function initTabs(root) {
    var tablist = root.querySelector('.tablist, [role="tablist"]');
    if (!tablist || tablist.__triageTabs) return;
    tablist.__triageTabs = 1;
    var tabs = [].slice.call(tablist.querySelectorAll('.tab, [role="tab"]'));
    var panels = tabs.map(function (t) {
      var id = t.getAttribute('aria-controls');
      return id ? document.getElementById(id) : null;
    });
    tablist.setAttribute('role', 'tablist');
    function select(i) {
      tabs.forEach(function (t, j) {
        var on = i === j;
        t.setAttribute('role', 'tab');
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.setAttribute('tabindex', on ? '0' : '-1');
        if (panels[j]) panels[j].hidden = !on;
      });
    }
    tabs.forEach(function (t, i) {
      if (!t.getAttribute('aria-controls') && panels[i]) t.setAttribute('aria-controls', panels[i].id);
      t.addEventListener('click', function () { select(i); });
      t.addEventListener('keydown', function (e) {
        var k = e.key, n = null;
        if (k === 'ArrowRight' || k === 'ArrowDown') n = (i + 1) % tabs.length;
        if (k === 'ArrowLeft' || k === 'ArrowUp') n = (i - 1 + tabs.length) % tabs.length;
        if (k === 'Home') n = 0;
        if (k === 'End') n = tabs.length - 1;
        if (n !== null) { e.preventDefault(); select(n); tabs[n].focus(); }
      });
    });
    select(Math.max(0, tabs.findIndex(function (t) { return t.getAttribute('aria-selected') === 'true'; })));
  }

  /* ------------------------------------------------------------ combobox */
  function initCombo(root) {
    if (root.__triageCb) return;
    root.__triageCb = 1;
    var input = root.querySelector('.cb-input, input');
    var list = root.querySelector('.cb-list, [role="listbox"]');
    if (!input || !list) return;
    var multi = root.hasAttribute('data-multi');
    var chips = root.querySelector('.cb-chips');
    var mirror = root.querySelector('[data-mirror]');
    var opts = [].slice.call(list.querySelectorAll('.cb-opt, [role="option"]'));
    var active = -1;
    var chosen = [];

    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-autocomplete', 'list');
    list.setAttribute('role', 'listbox');
    if (multi) list.setAttribute('aria-multiselectable', 'true');

    function syncMirror() {
      if (mirror) mirror.value = chosen.join(',');
    }
    function open(on) {
      root.classList.toggle('open', on);
      input.setAttribute('aria-expanded', on ? 'true' : 'false');
      if (!on) { active = -1; input.removeAttribute('aria-activedescendant'); }
    }
    function visible() {
      return opts.filter(function (o) { return !o.hidden; });
    }
    function highlight(i) {
      var v = visible();
      if (!v.length) { active = -1; return; }
      active = Math.max(0, Math.min(v.length - 1, i));
      v.forEach(function (o, j) { o.setAttribute('aria-selected', j === active ? 'true' : 'false'); });
      var o = v[active];
      if (!o.id) o.id = (root.id || 'cb') + '-opt-' + opts.indexOf(o);
      input.setAttribute('aria-activedescendant', o.id);
      o.scrollIntoView({ block: 'nearest' });
    }
    function filter(q) {
      q = (q || '').trim().toLowerCase();
      opts.forEach(function (o) {
        var hit = !q || o.textContent.toLowerCase().indexOf(q) !== -1;
        o.hidden = !hit;
        if (multi) {
          var val = o.getAttribute('data-value') || o.textContent.trim();
          o.setAttribute('aria-selected', chosen.indexOf(val) !== -1 ? 'true' : 'false');
        }
      });
      var none = root.querySelector('.cb-empty');
      if (none) none.hidden = visible().length > 0;
    }
    function renderChips() {
      if (!chips) return;
      chips.innerHTML = '';
      chosen.forEach(function (val) {
        var chip = document.createElement('span');
        chip.className = 'chip active';
        chip.textContent = val;
        var rm = document.createElement('button');
        rm.type = 'button';
        rm.setAttribute('aria-label', 'Remove ' + val);
        rm.textContent = '×';
        rm.addEventListener('click', function () {
          chosen = chosen.filter(function (v) { return v !== val; });
          renderChips(); syncMirror();
        });
        chip.appendChild(rm);
        chips.appendChild(chip);
      });
    }
    function pick(opt) {
      if (!opt) return;
      var val = opt.getAttribute('data-value') || opt.textContent.trim();
      if (multi) {
        if (chosen.indexOf(val) === -1) chosen.push(val);
        renderChips(); syncMirror();
        input.value = '';
        filter('');
        input.focus();
      } else {
        input.value = val;
        root.dispatchEvent(new CustomEvent('triage:select', { bubbles: true, detail: { value: val } }));
        open(false);
      }
    }

    input.addEventListener('focus', function () { filter(input.value); open(true); });
    input.addEventListener('input', function () { filter(input.value); open(true); highlight(0); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); open(true); highlight(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); highlight(active - 1); }
      else if (e.key === 'Enter') { e.preventDefault(); pick(visible()[active]); }
      else if (e.key === 'Escape') { open(false); }
      else if (e.key === 'Backspace' && multi && input.value === '' && chosen.length) {
        chosen.pop(); renderChips(); syncMirror();
      }
    });
    list.addEventListener('mousedown', function (e) {
      var o = e.target.closest('.cb-opt, [role="option"]');
      if (!o) return;
      e.preventDefault();
      if (multi) { pick(o); } else { pick(o); }
    });
    document.addEventListener('click', function (e) {
      if (!root.contains(e.target)) open(false);
    });
    renderChips(); syncMirror();
  }

  /* ----------------------------------------------------------- datepicker */
  function initDatepicker(root) {
    if (root.__triageDp) return;
    root.__triageDp = 1;
    var input = root.querySelector('.dp-input, input');
    var pop = root.querySelector('.dp-pop');
    if (!input || !pop) return;
    var min = root.getAttribute('data-min');
    var max = root.getAttribute('data-max');
    var today = new Date();
    var view = today;
    var focusDate = null;
    var suppressOpen = false;
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('inputmode', 'numeric');
    input.setAttribute('aria-haspopup', 'dialog');
    input.setAttribute('aria-expanded', 'false');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Choose date');

    function iso(d) {
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }
    function parse(v) {
      var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v || '');
      return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
    }
    function enabled(d) {
      var v = iso(d);
      return !((min && v < min) || (max && v > max));
    }
    function fullLabel(d) {
      return new Intl.DateTimeFormat(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }).format(d);
    }
    function inView(d) { return !!d && d.getFullYear() === view.getFullYear() && d.getMonth() === view.getMonth(); }
    function dayBtns() { return [].slice.call(pop.querySelectorAll('.dp-d')); }
    function findBtn(d) {
      var v = d && iso(d), out = null;
      dayBtns().forEach(function (b) { if (!b.disabled && b.getAttribute('data-v') === v) out = b; });
      return out;
    }
    /* nearest enabled date from `from` moving by `delta` days (skips disabled);
       calendar arithmetic keeps this correct across DST transitions */
    function step(from, delta) {
      for (var i = 1; i <= 60; i++) {
        var d = new Date(from.getFullYear(), from.getMonth(), from.getDate() + delta * i);
        if (enabled(d)) return d;
      }
      return null;
    }
    /* the date itself if enabled, else the nearest enabled date in `delta` direction */
    function nearest(date, delta) {
      return enabled(date) ? date : step(date, delta);
    }
    function restoreFocus() {
      suppressOpen = true;
      input.focus();
      suppressOpen = false;
    }
    function defaultFocus() {
      var sel = parse(input.value), i;
      if (inView(sel) && enabled(sel)) return sel;
      if (inView(today) && enabled(today)) return today;
      var btns = dayBtns();
      for (i = 0; i < btns.length; i++) {
        if (!btns[i].disabled && !btns[i].classList.contains('out')) return parse(btns[i].getAttribute('data-v'));
      }
      for (i = 0; i < btns.length; i++) {
        if (!btns[i].disabled) return parse(btns[i].getAttribute('data-v'));
      }
      return null;
    }
    /* exactly one day cell carries tabindex=0 (roving tabindex) */
    function applyRoving() {
      if (!focusDate || !inView(focusDate) || !enabled(focusDate)) focusDate = defaultFocus();
      var target = focusDate ? iso(focusDate) : null;
      dayBtns().forEach(function (b) {
        b.setAttribute('tabindex', (!b.disabled && b.getAttribute('data-v') === target) ? '0' : '-1');
      });
    }
    function render() {
      var y = view.getFullYear(), m = view.getMonth();
      var first = new Date(y, m, 1);
      var start = (first.getDay() + 6) % 7;               /* monday-first */
      var monthLabel = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(first);
      var monthId = (root.id || 'dp') + '-month';
      var dows = [];
      /* 2024-01-01 is a Monday; step calendar-wise (DST-safe) for each narrow name */
      for (var i = 0; i < 7; i++) {
        dows.push(new Intl.DateTimeFormat(undefined, { weekday: 'narrow' }).format(new Date(2024, 0, 1 + i)));
      }
      var html = '<div class="dp-head"><button type="button" class="dp-nav" data-prev aria-label="Previous month">‹</button>'
               + '<span class="dp-month" id="' + monthId + '" aria-live="polite">' + monthLabel + '</span>'
               + '<button type="button" class="dp-nav" data-next aria-label="Next month">›</button></div>'
               + '<div class="dp-grid">' + dows.map(function (d) { return '<span class="dp-dow" aria-hidden="true">' + d + '</span>'; }).join('');
      for (var n = 0; n < 42; n++) {
        var d = new Date(y, m, 1 - start + n);            /* calendar arithmetic (DST-safe) */
        var v = iso(d);
        var cls = 'dp-d' + (d.getMonth() !== m ? ' out' : '') + (input.value === v ? ' sel' : '');
        var dis = !enabled(d);
        html += '<button type="button" class="' + cls + '" data-v="' + v + '"'
              + (dis ? ' disabled' : ' tabindex="-1"')
              + (v === iso(today) ? ' aria-current="date"' : '')
              + ' aria-label="' + fullLabel(d).replace(/"/g, '&quot;') + '">' + d.getDate() + '</button>';
      }
      pop.innerHTML = html + '</div>';
      applyRoving();
    }
    function moveTo(date, doFocus) {
      if (!date) return;
      focusDate = date;
      if (!inView(date)) view = new Date(date.getFullYear(), date.getMonth(), 1);
      render();
      if (doFocus) { var b = findBtn(focusDate); if (b) b.focus(); }
    }
    function weekStart(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7)); }
    function weekEnd(d) { var s = weekStart(d); return new Date(s.getFullYear(), s.getMonth(), s.getDate() + 6); }
    function shiftMonth(delta) {
      var base = focusDate || parse(input.value) || today;
      var y = view.getFullYear(), m = view.getMonth() + delta;
      var last = new Date(y, m + 1, 0).getDate();
      moveTo(new Date(y, m, Math.min(base.getDate(), last)), true);
    }
    function open(on) {
      root.classList.toggle('open', on);
      input.setAttribute('aria-expanded', on ? 'true' : 'false');
      if (on) {
        var cur = parse(input.value);
        if (cur) view = new Date(cur.getFullYear(), cur.getMonth(), 1);
        focusDate = null;
        render();
      }
    }
    input.addEventListener('focus', function () { if (!suppressOpen) open(true); });
    input.addEventListener('click', function () { open(true); });
    input.addEventListener('keydown', function (e) { if (e.key === 'Escape') open(false); });
    pop.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); open(false); restoreFocus(); return; }
      var cur = focusDate || parse(input.value) || today;
      var next = null;
      if (e.key === 'ArrowLeft') next = step(cur, -1);
      else if (e.key === 'ArrowRight') next = step(cur, 1);
      else if (e.key === 'ArrowUp') next = step(cur, -7);
      else if (e.key === 'ArrowDown') next = step(cur, 7);
      else if (e.key === 'Home') next = nearest(weekStart(cur), 1);
      else if (e.key === 'End') next = nearest(weekEnd(cur), -1);
      else if (e.key === 'PageUp') { e.preventDefault(); shiftMonth(-1); return; }
      else if (e.key === 'PageDown') { e.preventDefault(); shiftMonth(1); return; }
      else return;
      if (next) { e.preventDefault(); moveTo(next, true); }
    });
    pop.addEventListener('click', function (e) {
      var nav = e.target.closest('.dp-nav');
      if (nav) {
        var dir = nav.hasAttribute('data-next') ? 'data-next' : 'data-prev';
        view = new Date(view.getFullYear(), view.getMonth() + (nav.hasAttribute('data-next') ? 1 : -1), 1);
        render();
        var nb = pop.querySelector('.dp-nav[' + dir + ']');
        if (nb) nb.focus();
        return;
      }
      var day = e.target.closest('.dp-d');
      if (!day || day.disabled) return;
      input.value = day.getAttribute('data-v');
      root.dispatchEvent(new CustomEvent('triage:select', { bubbles: true, detail: { value: input.value } }));
      open(false);
      restoreFocus();
    });
    document.addEventListener('click', function (e) {
      /* render() replaces pop.innerHTML, so by the document listener e.target may
         be detached; composedPath() is captured at dispatch and still knows the
         click originated inside root. The contains() branch is a legacy
         best-effort path for engines without composedPath() and is known to miss
         detached targets there — a documented limitation, not an equivalent. */
      var path = e.composedPath ? e.composedPath() : null;
      var inside = path ? path.indexOf(root) !== -1 : (e.target && root.contains(e.target));
      if (!inside) open(false);
    });
  }

  /* ------------------------------------------------------- command palette */
  function initCommandPalette(dlg) {
    if (dlg.__triageCmd) return;
    dlg.__triageCmd = 1;
    var input = dlg.querySelector('.cmd-input');
    var items = [].slice.call(dlg.querySelectorAll('.cmd-item'));
    var active = -1;

    function open() { if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', ''); input.value = ''; filter(''); highlight(0); input.focus(); }
    function close() { if (typeof dlg.close === 'function') dlg.close(); else dlg.removeAttribute('open'); }
    function filter(q) {
      q = (q || '').trim().toLowerCase();
      var shown = 0;
      items.forEach(function (it) {
        var hit = !q || it.textContent.toLowerCase().indexOf(q) !== -1;
        it.hidden = !hit;
        if (hit) shown++;
      });
      var empty = dlg.querySelector('.cmd-empty');
      if (empty) empty.hidden = shown > 0;
      highlight(0);
    }
    function visible() { return items.filter(function (i) { return !i.hidden; }); }
    function highlight(i) {
      var v = visible();
      active = v.length ? Math.max(0, Math.min(v.length - 1, i)) : -1;
      v.forEach(function (it, j) { it.setAttribute('aria-selected', j === active ? 'true' : 'false'); });
      if (v[active]) v[active].scrollIntoView({ block: 'nearest' });
    }
    function run(it) {
      it = it || visible()[active];
      if (!it) return;
      close();
      var href = it.getAttribute('data-href');
      if (href) { location.href = href; return; }
      if (it.dataset.cmdAction) {
        var target = document.querySelector(it.dataset.cmdAction);
        if (target) target.click();
      }
      dlg.dispatchEvent(new CustomEvent('triage:cmd', { bubbles: true, detail: { item: it } }));
    }
    input.addEventListener('input', function () { filter(input.value); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); highlight(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); highlight(active - 1); }
      else if (e.key === 'Enter') { e.preventDefault(); run(); }
    });
    dlg.addEventListener('click', function (e) {
      var it = e.target.closest('.cmd-item');
      if (it) { e.preventDefault(); run(it); }
      else if (e.target === dlg) close();
    });
    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); open(); }
    });
    document.querySelectorAll('[data-cmd-open]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); open(); });
    });
  }

  /* --------------------------------------------------------------- slider */
  function initSlider(root) {
    var input = root.querySelector('input[type="range"]');
    var out = root.querySelector('.slider-val, output');
    if (!input || !out || input.__triageSl) return;
    input.__triageSl = 1;
    var suffix = root.getAttribute('data-suffix') || '';
    function sync() { out.textContent = input.value + suffix; }
    input.addEventListener('input', sync);
    sync();
  }

  /* ------------------------------------------------------------- dropzone */
  function renderFiles(root) {
    var list = root.querySelector('.up-list');
    if (!list) return;
    var input = root.querySelector('input[type="file"]');
    var files = input && input.files ? [].slice.call(input.files) : [];
    list.innerHTML = '';
    files.forEach(function (f, i) {
      var row = document.createElement('div');
      row.className = 'up-row';
      row.innerHTML = '<span class="up-name">' + f.name.replace(/[<>&]/g, '') + '</span>'
                    + '<span class="up-size">' + (f.size > 1048576 ? (f.size / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(f.size / 1024)) + ' KB') + '</span>';
      var rm = document.createElement('button');
      rm.type = 'button'; rm.className = 'up-rm'; rm.textContent = '×';
      rm.setAttribute('aria-label', 'Remove ' + f.name);
      row.appendChild(rm);
      list.appendChild(row);
    });
    root.dispatchEvent(new CustomEvent('triage:files', { bubbles: true, detail: { files: files } }));
  }
  function initDrop(root) {
    if (root.__triageDrop) return;
    root.__triageDrop = 1;
    var zone = root.querySelector('.drop');
    var input = root.querySelector('input[type="file"]');
    if (!zone || !input) return;
    input.hidden = true;
    zone.tabIndex = 0;
    zone.setAttribute('role', 'button');
    zone.addEventListener('click', function () { input.click(); });
    zone.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    ['dragenter', 'dragover'].forEach(function (t) {
      zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (t) {
      zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.remove('over'); });
    });
    zone.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files.length) { input.files = e.dataTransfer.files; renderFiles(root); }
    });
    input.addEventListener('change', function () { renderFiles(root); });
  }

  /* --------------------------------------------------------- notifications */
  function initNotif(root) {
    if (root.__triageNotif) return;
    root.__triageNotif = 1;
    function refresh() {
      var unread = root.querySelectorAll('.notif-item.unread').length;
      var dot = root.querySelector('.notif-dot');
      if (dot) dot.hidden = unread === 0;
    }
    root.addEventListener('click', function (e) {
      var item = e.target.closest('.notif-item');
      if (item) { item.classList.remove('unread'); refresh(); }
      var all = e.target.closest('[data-notif-read]');
      if (all) {
        e.preventDefault();
        root.querySelectorAll('.notif-item.unread').forEach(function (i) { i.classList.remove('unread'); });
        refresh();
      }
    });
    refresh();
  }

  /* ------------------------------------------------------------ sort table */
  function initSortTable(tbl) {
    if (tbl.__triageSort) return;
    tbl.__triageSort = 1;
    tbl.querySelectorAll('.th-sort').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var th = btn.closest('th');
        var idx = [].indexOf.call(th.parentNode.children, th);
        var dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
        tbl.querySelectorAll('th[aria-sort]').forEach(function (o) { if (o !== th) o.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
        var body = tbl.tBodies[0];
        var rows = [].slice.call(body.rows).filter(function (r) { return r.cells.length; });
        rows.sort(function (a, b) {
          var av = (a.cells[idx].getAttribute('data-value') || a.cells[idx].textContent).trim();
          var bv = (b.cells[idx].getAttribute('data-value') || b.cells[idx].textContent).trim();
          var an = parseFloat(av), bn = parseFloat(bv);
          var cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv, undefined, { numeric: true });
          return cmp * dir;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  }

  function init() {
    document.querySelectorAll('[data-tabs]').forEach(initTabs);
    document.querySelectorAll('[data-combobox]').forEach(initCombo);
    document.querySelectorAll('[data-datepicker]').forEach(initDatepicker);
    document.querySelectorAll('.dlg.cmd').forEach(initCommandPalette);
    document.querySelectorAll('[data-slider]').forEach(initSlider);
    document.querySelectorAll('[data-drop]').forEach(initDrop);
    document.querySelectorAll('[data-notif]').forEach(initNotif);
    document.querySelectorAll('[data-sort-table]').forEach(initSortTable);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  document.addEventListener('turbo:load', init);
})();
