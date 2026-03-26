(function () {
  'use strict';

  // --- Lightbox helpers ---

  function openLightbox(src, alt) {
    // Guard against duplicate overlays
    if (document.querySelector('.lightbox-overlay')) {
      return;
    }

    var overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Image lightbox');

    var img = document.createElement('img');
    img.className = 'lightbox-image';
    img.setAttribute('src', src);
    img.setAttribute('alt', alt || '');

    overlay.appendChild(img);
    document.body.appendChild(overlay);

    // Close on Escape key
    document.addEventListener('keydown', handleKeyDown);
  }

  function closeLightbox() {
    var overlay = document.querySelector('.lightbox-overlay');
    if (overlay) {
      overlay.parentNode.removeChild(overlay);
    }
    document.removeEventListener('keydown', handleKeyDown);
  }

  function handleKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeLightbox();
    }
  }

  // --- Event delegation: open lightbox on image click ---
  document.addEventListener('click', function (e) {
    var img = e.target.closest('.entry-image');
    if (img) {
      e.preventDefault();
      openLightbox(img.getAttribute('src'), img.getAttribute('alt'));
      return;
    }

    // Close when clicking overlay background (not the lightbox image itself)
    var overlay = e.target.closest('.lightbox-overlay');
    if (overlay && !e.target.closest('.lightbox-image')) {
      closeLightbox();
      return;
    }

    // Close when clicking the lightbox image directly
    var lightboxImg = e.target.closest('.lightbox-image');
    if (lightboxImg) {
      closeLightbox();
    }
  });
})();
