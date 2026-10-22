/*! Triage i18n.js — locale, messages, formats.
 *  Small on purpose: one locale at a time, Intl does the heavy lifting.
 *
 *  triageI18n.setLocale('ar', { greeting: 'مرحبا {name}' });
 *  triageI18n.t('greeting', { name: 'Dana' });
 *  triageI18n.number(1234.5);            // 1,234.5 / ١٬٢٣٤٫٥
 *  triageI18n.date(new Date());          // locale-formatted
 *  triageI18n.relative(-2, 'day');       // "2 days ago"
 *  triageI18n.plural(3, { one: '{n} file', other: '{n} files' });
 *  triageI18n.dir();                     // 'rtl' | 'ltr' — sets <html dir> too
 */
(function () {
  'use strict';
  if (window.triageI18n) return;
  var RTL = ['ar', 'fa', 'he', 'ur', 'ps', 'dv', 'yi'];
  var locale = (navigator.language || 'en');
  var catalogue = {};

  function base(l) { return String(l).toLowerCase().split('-')[0]; }
  function dir(l) { return RTL.indexOf(base(l || locale)) !== -1 ? 'rtl' : 'ltr'; }

  function interpolate(s, vars) {
    return s.replace(/\{(\w+)\}/g, function (m, k) { return vars && k in vars ? vars[k] : m; });
  }

  var api = {
    get locale() { return locale; },
    dir: function (l) { return dir(l); },
    setLocale: function (l, cat, opts) {
      locale = l || locale;
      if (cat) catalogue = Object.assign(catalogue, cat);
      var el = document.documentElement;
      el.lang = locale;
      el.setAttribute('dir', dir(locale));
      if (opts && opts.persist) { try { localStorage.setItem('triage_locale', locale); } catch (e) {} }
      document.dispatchEvent(new CustomEvent('triage:locale', { detail: { locale: locale, dir: dir(locale) } }));
      return api;
    },
    load: function (url) {
      return fetch(url, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('catalogue ' + r.status); return r.json(); })
        .then(function (cat) { return api.setLocale(cat.locale || locale, cat.messages || cat); });
    },
    t: function (key, vars, fallback) {
      var s = catalogue[key] || fallback || key;
      return interpolate(s, vars);
    },
    has: function (key) { return Object.prototype.hasOwnProperty.call(catalogue, key); },
    number: function (n, o) { return new Intl.NumberFormat(locale, o).format(n); },
    percent: function (n, o) { return new Intl.NumberFormat(locale, Object.assign({ style: 'percent' }, o)).format(n); },
    date: function (d, o) { return new Intl.DateTimeFormat(locale, o).format(d); },
    time: function (d, o) { return new Intl.DateTimeFormat(locale, Object.assign({ timeStyle: 'short' }, o)).format(d); },
    relative: function (n, unit, o) { return new Intl.RelativeTimeFormat(locale, Object.assign({ numeric: 'auto' }, o)).format(n, unit); },
    list: function (arr, o) { return new Intl.ListFormat(locale, o).format(arr); },
    plural: function (n, forms, vars) {
      var cat = new Intl.PluralRules(locale).select(n);
      var s = forms[cat] || forms.other || forms.one || '';
      return interpolate(s, Object.assign({ n: api.number(n) }, vars));
    }
  };
  try {
    var saved = localStorage.getItem('triage_locale');
    if (saved) locale = saved;
  } catch (e) {}
  document.documentElement.setAttribute('dir', dir(locale));
  window.triageI18n = api;
})();
