/* CSP-safe action delegation. Page controllers may register named actions
 * without inline event handlers or the retired legacy action attributes.
 *
 * Markup usage:
 *   <button data-action="fnName" data-args='[1,"x"]'>
 *   data-action-change / data-action-input / data-action-keydown /
 *   data-action-focus cover the other delegated event types.
 *
 * The named global function is invoked with `this` = the element and the DOM event
 * appended as the last argument. Existing functions that take positional args simply
 * ignore the trailing event; handlers that need the event take it as their last param.
 *
 * For handlers that passed user-controlled strings (names/titles), use dedicated
 * data-* attributes encoded with escAttr() and a thin wrapper that reads dataset —
 * this avoids quote-escaping hazards inside JSON-in-attribute.
 */
const registry = new Map();

export function registerAction(name, handler) {
  if (!name || typeof handler !== 'function') throw new TypeError('Action name and handler are required');
  registry.set(name, handler);
}

window.ActionRegistry = Object.freeze({ register: registerAction });

(function installActionDelegator() {
  function run(e, attr) {
    var el = e.target.closest('[' + attr + ']');
    if (!el) return;
    var name = el.getAttribute(attr);
    var fn = registry.get(name) || window[name];
    if (typeof fn !== 'function') return;
    var args = [];
    var raw = el.getAttribute('data-args');
    if (raw) {
      try { args = JSON.parse(raw); } catch (_) { args = []; }
    }
    fn.apply(el, args.concat([e]));
  }
  document.addEventListener('click',   function (e) { run(e, 'data-action'); });
  document.addEventListener('change',  function (e) { run(e, 'data-action-change'); });
  document.addEventListener('input',   function (e) { run(e, 'data-action-input'); });
  document.addEventListener('keydown', function (e) { run(e, 'data-action-keydown'); });
  document.addEventListener('focusin', function (e) { run(e, 'data-action-focus'); });
})();

/* Attribute-safe escaper for embedding arbitrary strings in data-* attributes. */
window.escAttr = function escAttr(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

/* ---- Wrappers for handlers that referenced `this`, `event`, or raw DOM ops ---- */
window.clearReadonlyAttr = function () { this.removeAttribute('readonly'); };
window.onEnterConfirmRetake = function (e) { if (e?.key === 'Enter') window.confirmRetake?.(); };
window.handleTagKeyH = function (wrap, input, e) { window.handleTagKey?.(e, wrap, input); };
window.toggleActiveH = function (id) { window.toggleActive?.call(this, id, this.checked, this); };
window.confirmDeleteH = function () { window.confirmDelete?.(this.dataset.id, this.dataset.name); };
window.openDeleteAssignmentH = function () { window.openDeleteAssignment?.(this.dataset.id, this.dataset.title); };
window.openResetAssignmentH = function () { window.openResetAssignment?.(this.dataset.id, this.dataset.title); };
window.openDeleteUserH = function () { window.openDeleteUser?.(this.dataset.id, this.dataset.name, this.dataset.sid); };
window.openEditClassH = function () { window.openEditClass?.(this.dataset.id, this.dataset.name, this.dataset.course); };
window.openResetH = function () { window.openReset?.(this.dataset.id, this.dataset.name); };
