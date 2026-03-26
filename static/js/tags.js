(function () {
  'use strict';

  const textarea = document.getElementById('entry-input');
  const dropdown = document.getElementById('tag-autocomplete');
  let highlightedIndex = -1;
  let suggestions = [];
  let debounceTimer = null;

  // --- Suggestion fetching ---
  function fetchSuggestions(query) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      if (query.length < 1) {
        hideDropdown();
        return;
      }
      try {
        const resp = await fetch(`/api/tags/suggestions?q=${encodeURIComponent(query)}`);
        if (!resp.ok) {
          hideDropdown();
          return;
        }
        suggestions = await resp.json();
        renderDropdown();
      } catch {
        hideDropdown();
      }
    }, 200);
  }

  // --- Rendering ---
  function clearDropdownChildren() {
    while (dropdown.firstChild) {
      dropdown.removeChild(dropdown.firstChild);
    }
  }

  function renderDropdown() {
    if (suggestions.length === 0) {
      hideDropdown();
      return;
    }
    clearDropdownChildren();
    suggestions.forEach((tag, i) => {
      const item = document.createElement('div');
      // Use textContent (not innerHTML) to avoid XSS — tag names are plain text
      item.textContent = tag;
      item.className = 'autocomplete-item' + (i === highlightedIndex ? ' active' : '');
      item.setAttribute('role', 'option');
      item.dataset.index = i;
      dropdown.appendChild(item);
    });
    dropdown.hidden = false;
  }

  function hideDropdown() {
    dropdown.hidden = true;
    clearDropdownChildren();
    highlightedIndex = -1;
    suggestions = [];
  }

  function selectTag(tagName) {
    // Replace the #partial typed so far with the full tag name
    const value = textarea.value;
    const cursorPos = textarea.selectionStart;
    const beforeCursor = value.substring(0, cursorPos);
    const afterCursor = value.substring(cursorPos);
    const hashIndex = beforeCursor.lastIndexOf('#');
    if (hashIndex !== -1) {
      textarea.value =
        beforeCursor.substring(0, hashIndex) + '#' + tagName + ' ' + afterCursor;
      textarea.selectionStart = textarea.selectionEnd = hashIndex + tagName.length + 2;
    }
    hideDropdown();
    textarea.focus();
  }

  // --- Keyboard navigation (on textarea) ---
  // NOTE: The inline onkeydown attribute fires first.
  // When dropdown is visible, dropdown.hidden === false so the inline
  // guard does nothing — this addEventListener handler then runs and
  // handles the keystroke, calling selectTag or hideDropdown as needed.
  textarea.addEventListener('keydown', function (e) {
    if (dropdown.hidden) return; // Let inline handler deal with it

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      highlightedIndex = Math.min(highlightedIndex + 1, suggestions.length - 1);
      renderDropdown();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      highlightedIndex = Math.max(highlightedIndex - 1, 0);
      renderDropdown();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      if (highlightedIndex >= 0 && highlightedIndex < suggestions.length) {
        selectTag(suggestions[highlightedIndex]);
      } else {
        hideDropdown();
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      hideDropdown();
    }
  });

  // --- Input monitoring for # trigger ---
  textarea.addEventListener('input', function () {
    const value = this.value;
    const cursorPos = this.selectionStart;
    const beforeCursor = value.substring(0, cursorPos);
    const hashIndex = beforeCursor.lastIndexOf('#');
    if (hashIndex !== -1 && !beforeCursor.substring(hashIndex).includes(' ')) {
      const query = beforeCursor.substring(hashIndex + 1);
      if (query.length > 0) {
        fetchSuggestions(query);
        return;
      }
    }
    hideDropdown();
  });

  // --- MOUSEDOWN (not click!) for touch device compatibility ---
  // Using mousedown with preventDefault() prevents textarea from losing focus,
  // which would otherwise fire blur before the click event registers.
  dropdown.addEventListener('mousedown', function (e) {
    const item = e.target.closest('.autocomplete-item');
    if (item) {
      e.preventDefault(); // Prevents textarea blur before we can read selectionStart
      const idx = parseInt(item.dataset.index, 10);
      if (idx >= 0 && idx < suggestions.length) {
        selectTag(suggestions[idx]);
      }
    }
  });
})();
