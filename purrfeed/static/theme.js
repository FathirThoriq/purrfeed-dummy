(() => {
  const root = document.documentElement;
  const saved = localStorage.getItem('pf-theme');
  root.dataset.theme = saved === 'dark' ? 'dark' : 'light';
  window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.addEventListener('click', () => {
        const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
        root.dataset.theme = next;
        localStorage.setItem('pf-theme', next);
        window.dispatchEvent(new Event('pf-theme'));
      });
    });
  });
})();
