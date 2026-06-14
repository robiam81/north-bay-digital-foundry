/* =========================================================================
   North Bay Digital Foundry — minimal progressive enhancement
   No dependencies. The page is fully functional without this script.
   ========================================================================= */
(function () {
  'use strict';

  /* --- Current year in the footer --- */
  var yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());

  /* --- Mobile nav toggle --- */
  var toggle = document.querySelector('.rail__toggle');
  var nav = document.getElementById('rail-nav');

  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
    });

    /* Close the menu after picking a section (mobile only) */
    nav.addEventListener('click', function (e) {
      if (e.target.closest('a') && nav.classList.contains('is-open')) {
        nav.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  /* --- Scroll-spy: mark the active section link --- */
  var links = Array.prototype.slice.call(
    document.querySelectorAll('.rail__nav a[href^="#"]')
  );
  var sections = links
    .map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); })
    .filter(Boolean);

  if ('IntersectionObserver' in window && sections.length) {
    var setCurrent = function (id) {
      links.forEach(function (a) {
        a.setAttribute('aria-current', a.getAttribute('href') === '#' + id ? 'true' : 'false');
      });
    };

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) setCurrent(entry.target.id);
      });
    }, { rootMargin: '-45% 0px -50% 0px', threshold: 0 });

    sections.forEach(function (s) { observer.observe(s); });
  }
})();
