// ── Tag Autocomplete ─────────────────────────
(function () {
    const textarea = document.getElementById('content');
    const dropdown = document.getElementById('tag-autocomplete');
    if (!textarea || !dropdown) return;

    let debounceTimer = null;
    let activeIndex = -1;

    textarea.addEventListener('input', function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => checkForTag(), 150);
    });

    textarea.addEventListener('keydown', function (e) {
        if (dropdown.hidden) return;

        const items = dropdown.querySelectorAll('.autocomplete-item');
        if (!items.length) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIndex = Math.min(activeIndex + 1, items.length - 1);
            updateActive(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIndex = Math.max(activeIndex - 1, 0);
            updateActive(items);
        } else if (e.key === 'Enter' && activeIndex >= 0) {
            e.preventDefault();
            e.stopPropagation();
            selectItem(items[activeIndex]);
        } else if (e.key === 'Escape') {
            hideDropdown();
        }
    });

    dropdown.addEventListener('click', function (e) {
        const item = e.target.closest('.autocomplete-item');
        if (item) selectItem(item);
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', function (e) {
        if (!dropdown.contains(e.target) && e.target !== textarea) {
            hideDropdown();
        }
    });

    function checkForTag() {
        const pos = textarea.selectionStart;
        const textBefore = textarea.value.substring(0, pos);

        // Look for # or @ followed by word chars at end of text-before-cursor
        const match = textBefore.match(/(?:^|[\s(])([#@])([\w-]*)$/);
        if (!match) {
            hideDropdown();
            return;
        }

        const sigil = match[1];
        const query = match[2];
        const tagType = sigil === '#' ? 'tag' : 'person';

        fetch(`/tags/autocomplete?q=${encodeURIComponent(query)}&type=${tagType}`)
            .then(r => r.text())
            .then(html => {
                if (!html.trim()) {
                    hideDropdown();
                    return;
                }
                // Parse server-rendered HTML safely via DOMParser
                // (same trust model as HTMX which is already used throughout this app)
                const doc = new DOMParser().parseFromString(html, 'text/html');
                dropdown.replaceChildren(...doc.body.childNodes);
                dropdown.hidden = false;
                activeIndex = -1;
            })
            .catch(() => hideDropdown());
    }

    function selectItem(item) {
        const name = item.dataset.name;
        const type = item.dataset.type;
        const sigil = type === 'person' ? '@' : '#';

        const pos = textarea.selectionStart;
        const textBefore = textarea.value.substring(0, pos);
        const textAfter = textarea.value.substring(pos);

        // Replace the partial tag with the full one
        const match = textBefore.match(/(?:^|[\s(])([#@])([\w-]*)$/);
        if (match) {
            const start = textBefore.length - match[1].length - match[2].length;
            const newText = textBefore.substring(0, start) + sigil + name + ' ';
            textarea.value = newText + textAfter;
            textarea.selectionStart = textarea.selectionEnd = newText.length;
        }

        hideDropdown();
        textarea.focus();
    }

    function hideDropdown() {
        dropdown.hidden = true;
        dropdown.replaceChildren();
        activeIndex = -1;
    }

    function updateActive(items) {
        items.forEach((item, i) => {
            item.classList.toggle('active', i === activeIndex);
        });
    }
})();

// ── Tag Rename (management page) ─────────────
function startRenameTag(id, currentName) {
    const row = document.getElementById('tag-' + id);
    if (!row) return;

    const nameEl = row.querySelector('.tag-name-text');
    if (!nameEl) return;

    const link = row.querySelector('.tag-row-name');
    const sigil = link.textContent.trim().charAt(0); // # or @

    // Replace name with input
    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentName;
    input.className = 'tag-rename-input';

    link.replaceWith(input);
    input.focus();
    input.select();

    function doRename() {
        const newName = input.value.trim().toLowerCase();
        if (!newName || newName === currentName) {
            cancelRename();
            return;
        }

        const formData = new FormData();
        formData.append('name', newName);

        fetch('/tags/' + id, {
            method: 'PUT',
            body: formData,
        })
            .then(r => r.text())
            .then(html => {
                // Parse server-rendered tag row HTML safely via DOMParser
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const newRow = doc.body.firstElementChild;
                if (newRow) {
                    row.replaceWith(newRow);
                }
            })
            .catch(() => cancelRename());
    }

    function cancelRename() {
        const newLink = document.createElement('a');
        newLink.href = '/tags/' + id + '/entries';
        newLink.className = 'tag-row-name';
        newLink.textContent = sigil;
        const span = document.createElement('span');
        span.className = 'tag-name-text';
        span.textContent = currentName;
        newLink.appendChild(span);
        input.replaceWith(newLink);
    }

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            doRename();
        } else if (e.key === 'Escape') {
            cancelRename();
        }
    });

    input.addEventListener('blur', function () {
        // Small delay to allow click events to fire first
        setTimeout(doRename, 100);
    });
}
