(function() {
  var currentHighlight = null;
  var currentSelected = null;
  var style = document.createElement('style');
  style.textContent = [
    '.ts-inspect-highlight{outline:2px solid #4488ff!important;outline-offset:-1px!important;background:rgba(68,136,255,0.08)!important}',
    '.ts-inspect-selected{outline:3px solid #ff6644!important;outline-offset:-1px!important;background:rgba(255,102,68,0.12)!important}',
  ].join('');
  document.head.appendChild(style);

  function resolveCssPath(path) {
    if (!path) return null;
    var parts = path.split(' > ');
    var current = document.body || document.documentElement;
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      var tag = part.split(/[.#]/)[0];
      var m = part.match(/#([^.#]+)/);
      var id = m ? m[1] : null;
      var classes = [];
      var re = /\.([^.#]+)/g;
      var match;
      while ((match = re.exec(part)) !== null) classes.push(match[1]);
      var children = current.children;
      var found = null;
      for (var j = 0; j < children.length; j++) {
        var child = children[j];
        if (child.tagName.toLowerCase() !== tag) continue;
        if (id && child.id !== id) continue;
        if (classes.length > 0) {
          var allMatch = classes.every(function(c) { return child.classList.contains(c); });
          if (!allMatch) continue;
        }
        found = child;
        break;
      }
      if (!found) return null;
      current = found;
    }
    return current;
  }

  document.addEventListener('mouseover', function(e) {
    var el = e.target;
    if (el === document.body || el === document.documentElement) return;
    if (currentHighlight) currentHighlight.classList.remove('ts-inspect-highlight');
    currentHighlight = el;
    el.classList.add('ts-inspect-highlight');
    e.stopPropagation();
  }, true);

  document.addEventListener('mouseout', function(e) {
    if (currentHighlight) {
      currentHighlight.classList.remove('ts-inspect-highlight');
      currentHighlight = null;
    }
  }, true);

  var skipTags = ['script','style','meta','link','base','head'];
  var inputValues = {};

  document.addEventListener('input', function(e) {
    var el = e.target;
    var tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      inputValues[el.id || el.name || getCssPath(el)] = el.value;
      if (currentSelected && el === currentSelected) {
        console.log(JSON.stringify({ type: 'ts-value-update', value: el.value }));
      }
    }
  }, true);

  document.addEventListener('click', function(e) {
    var el = e.target;
    if (el === document.body || el === document.documentElement) return;
    if (skipTags.indexOf(el.tagName.toLowerCase()) !== -1) return;
    e.preventDefault();
    e.stopPropagation();

    if (currentSelected) currentSelected.classList.remove('ts-inspect-selected');
    if (currentHighlight) currentHighlight.classList.remove('ts-inspect-highlight');
    currentHighlight = null;
    currentSelected = el;
    el.classList.add('ts-inspect-selected');

    var inShadow = false;
    var targetEl = el;
    var root = el.getRootNode ? el.getRootNode() : document;
    if (root && root instanceof ShadowRoot) {
      inShadow = true;
      targetEl = root.host;
    }

    var path = getCssPath(targetEl);
    var tag = targetEl.tagName.toLowerCase();
    var text = (targetEl.textContent || '').trim().substring(0, 100);
    var id = targetEl.id || '';
    var cls = Array.from(targetEl.classList).join('.');

    var nameEl = targetEl;
    if (tag === 'option') nameEl = targetEl.closest('select') || targetEl;
    var accessibleName = computeAccessibleName(nameEl);

    var trackId = targetEl.id || targetEl.name || path;
    var value = (tag === 'input' || tag === 'textarea' || tag === 'select') ? (inputValues[trackId] || targetEl.value) : undefined;

    console.log(JSON.stringify({
      type: 'ts-element-click',
      cssPath: path,
      tag: tag,
      text: text,
      id: id,
      classes: cls,
      inShadowDOM: inShadow,
      value: value,
      accessibleName: accessibleName
    }));
  }, true);

  window.addEventListener('message', function(e) {
    var msg = e.data;
    if (!msg || !msg.type) return;

    if (msg.type === 'ts-highlight' && msg.cssPath) {
      if (currentHighlight) currentHighlight.classList.remove('ts-inspect-highlight');
      var el = resolveCssPath(msg.cssPath);
      if (el) {
        currentHighlight = el;
        el.classList.add('ts-inspect-highlight');
      }
      return;
    }

    if (msg.type === 'ts-clear-highlight') {
      if (currentHighlight) {
        currentHighlight.classList.remove('ts-inspect-highlight');
        currentHighlight = null;
      }
      return;
    }

    if (msg.type === 'ts-select' && msg.cssPath) {
      if (currentSelected) currentSelected.classList.remove('ts-inspect-selected');
      if (currentHighlight) currentHighlight.classList.remove('ts-inspect-highlight');
      currentHighlight = null;
      var el = resolveCssPath(msg.cssPath);
      if (el) {
        currentSelected = el;
        el.classList.add('ts-inspect-selected');
      }
      return;
    }
  });

  function cssEscape(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/["\\]/g, '\\$&');
  }

  function cleanLabelText(labelEl) {
    var clone = labelEl.cloneNode(true);
    var controls = clone.querySelectorAll('select,input,textarea,button');
    for (var i = 0; i < controls.length; i++) controls[i].remove();
    return (clone.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function computeAccessibleName(el) {
    if (!el || !el.getAttribute) return '';
    var tag = el.tagName.toLowerCase();
    var isControl = (tag === 'input' || tag === 'select' || tag === 'textarea');
    var labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy && labelledBy.trim()) {
      var ids = labelledBy.trim().split(/\s+/);
      var parts = [];
      for (var i = 0; i < ids.length; i++) {
        var n = document.getElementById(ids[i]);
        if (n) parts.push((n.textContent || '').trim());
      }
      if (parts.length) return parts.join(' ').trim();
    }
    var ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();
    var id = el.id;
    if (id) {
      var lbl = document.querySelector('label[for="' + cssEscape(id) + '"]');
      if (lbl) return cleanLabelText(lbl);
    }
    var p = el.parentElement;
    while (p && p.tagName.toLowerCase() !== 'label') p = p.parentElement;
    if (p && p.tagName.toLowerCase() === 'label') return cleanLabelText(p);
    var title = el.getAttribute('title');
    if (title && title.trim()) return title.trim();
    if (isControl) {
      var ph = el.getAttribute('placeholder');
      if (ph && ph.trim()) return ph.trim();
    }
    return '';
  }

  function getCssPath(el) {
    if (el.id) return el.tagName.toLowerCase() + '#' + el.id;
    var parts = [];
    while (el && el.nodeType === 1) {
      var selector = el.tagName.toLowerCase();
      if (el.id) { parts.unshift(selector + '#' + el.id); break; }
      var parent = el.parentElement;
      if (parent) {
        var siblings = Array.from(parent.children).filter(function(c) { return c.tagName === el.tagName; });
        if (siblings.length > 1) {
          var idx = siblings.indexOf(el) + 1;
          selector += ':nth-child(' + (Array.from(parent.children).indexOf(el) + 1) + ')';
        }
      }
      parts.unshift(selector);
      el = parent;
    }
    return parts.join(' > ');
  }
})();