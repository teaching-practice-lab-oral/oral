(() => {
  'use strict';

  // Styles live in /static/legal/site.css (CSP forbids script-created <style>).
  const NAV_ITEMS = [
    { href: '/legal/', label: '條款與隱私', exact: true },
    { href: '/legal/system-terms/', label: '使用者條款' },
    { href: '/legal/privacy-notice/', label: '隱私權政策' }
  ];

  const CONTACT_ITEM = {
    href: 'https://brid.pw/mailme',
    label: '聯絡我們'
  };

  const normalizePath = (value) => {
    const path = (value || '/').split('?')[0].split('#')[0];
    return path === '/' ? '/' : `${path.replace(/\/+$/, '')}/`;
  };

  const currentPath = normalizePath(window.location.pathname);

  const isActive = (item) => {
    const target = normalizePath(item.href);
    return item.exact ? currentPath === target : currentPath.startsWith(target);
  };

  const injectNavbar = () => {
    if (!document.body || document.querySelector('.docs-navbar')) return;

    const nav = document.createElement('nav');
    nav.className = 'docs-navbar';
    nav.setAttribute('aria-label', '條款與隱私導覽');

    const inner = document.createElement('div');
    inner.className = 'docs-navbar__inner';

    const brand = document.createElement('a');
    brand.className = 'docs-navbar__brand';
    brand.href = '/login';
    brand.textContent = 'AI 英語面試練習系統';
    inner.appendChild(brand);

    const links = document.createElement('div');
    links.className = 'docs-navbar__links';

    NAV_ITEMS.forEach((item) => {
      const link = document.createElement('a');
      link.className = 'docs-navbar__link';
      link.href = item.href;
      link.textContent = item.label;
      if (isActive(item)) link.setAttribute('aria-current', 'page');
      links.appendChild(link);
    });

    inner.appendChild(links);
    const currentLink = links.querySelector('[aria-current="page"]');
    if (currentLink) {
      requestAnimationFrame(() => {
        const currentLeft = currentLink.offsetLeft - links.offsetLeft;
        links.scrollLeft = Math.max(0, currentLeft - ((links.clientWidth - currentLink.clientWidth) / 2));
      });
    }

    const contact = document.createElement('a');
    contact.className = 'docs-navbar__contact';
    contact.href = CONTACT_ITEM.href;
    contact.target = '_blank';
    contact.rel = 'noopener noreferrer';
    contact.textContent = CONTACT_ITEM.label;
    contact.setAttribute('aria-label', `${CONTACT_ITEM.label}（另開新分頁）`);
    inner.appendChild(contact);

    nav.appendChild(inner);
    document.body.insertBefore(nav, document.body.firstChild);
  };

  const bindSectionSpy = () => {
    const navigation = document.querySelectorAll('[data-spy-nav] a[href^="#"],.sidebar a[href^="#"]');
    if (!navigation.length || !('IntersectionObserver' in window)) return;

    const sections = [...navigation]
      .map((link) => document.querySelector(link.getAttribute('href')))
      .filter(Boolean);

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        navigation.forEach((link) => {
          link.classList.toggle('active', link.getAttribute('href') === `#${entry.target.id}`);
        });
      });
    }, { rootMargin: '-18% 0px -66% 0px' });

    sections.forEach((section) => observer.observe(section));
  };

  injectNavbar();
  bindSectionSpy();
})();
