(function() {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    function getTheme() {
        return document.documentElement.dataset.theme || 'storm';
    }

    function updateIcon() {
        btn.textContent = getTheme() === 'calm' ? '\u26C8' : '\u2600';
    }

    btn.addEventListener('click', function() {
        var next = getTheme() === 'storm' ? 'calm' : 'storm';
        document.documentElement.dataset.theme = next;
        localStorage.setItem('theme', next);
        updateIcon();
    });

    updateIcon();
})();
