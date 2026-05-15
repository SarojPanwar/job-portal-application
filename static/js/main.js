/**
 * Handles: auto-dismiss alerts, form enhancements, smooth UX
 */

document.addEventListener('DOMContentLoaded', function () {

  // ── Auto-dismiss flash alerts after 4 seconds ──────────────────────
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach(alert => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    }, 4000);
  });

  // ── Animate stat numbers on homepage ────────────────────────────────
  const statNums = document.querySelectorAll('.stat-num');
  if (statNums.length && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const el = entry.target;
          const target = parseInt(el.textContent, 10);
          if (isNaN(target)) return;
          animateCount(el, 0, target, 1200);
          observer.unobserve(el);
        }
      });
    }, { threshold: 0.5 });
    statNums.forEach(el => observer.observe(el));
  }

  function animateCount(el, start, end, duration) {
    const range = end - start;
    const startTime = performance.now();
    function update(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      el.textContent = Math.round(start + range * eased);
      if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
  }

  // ── Confirm dialogs already inline via onclick; keep as-is ──────────

  // ── Highlight active nav on browse page ─────────────────────────────
  const currentPath = window.location.pathname;
  document.querySelectorAll('.nav-link').forEach(link => {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('active');
    }
  });

  // ── Character counter for cover letter textarea ──────────────────────
  const coverLetter = document.querySelector('textarea[name="cover_letter"]');
  if (coverLetter) {
    const counter = document.createElement('div');
    counter.className = 'form-text text-end';
    counter.textContent = '0 characters';
    coverLetter.parentNode.insertBefore(counter, coverLetter.nextSibling);
    coverLetter.addEventListener('input', () => {
      counter.textContent = coverLetter.value.length + ' characters';
    });
  }

  // ── Tooltip initialization ───────────────────────────────────────────
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.forEach(el => new bootstrap.Tooltip(el));

});