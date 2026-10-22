/*! Triage icon helper — sprite-based, configuration-free.
 *  Usage:  el.innerHTML = triageIcon('arrow-right', 16);
 *          el.innerHTML = triageIcon('trash-2', 16, 'Delete');  // labelled
 *  Requires icons/sprite.svg to be served; set window.TRIAGE_ICONS_BASE to
 *  override the default '/icons/'. Presentation attributes are on the <svg> so
 *  the sprite works with or without core/base.css.
 */
(function () {
  if (window.triageIcon) return;
  var ATTRS = 'fill="none" stroke="currentColor" stroke-width="1.7" '
            + 'stroke-linecap="round" stroke-linejoin="round"';
  window.triageIcon = function (name, size, label) {
    var s = size || 16;
    var base = window.TRIAGE_ICONS_BASE || '/icons/';
    var a11y = label ? ' role="img" aria-label="' + String(label).replace(/"/g, '&quot;') + '"'
                     : ' aria-hidden="true"';
    return '<svg class="icon" width="' + s + '" height="' + s + '" ' + ATTRS + a11y
         + '><use href="' + base + 'sprite.svg#i-' + name + '"/></svg>';
  };
})();
