// Google Analytics 4 for the React site.
//
// The old Jinja pages carried the Google tag inline; it was lost when the site moved to
// React. Google's usual snippet is an inline script, which our Content-Security-Policy
// blocks, so the same setup runs here from our own bundle instead. The server's CSP
// allows exactly Google's documented Analytics hosts (see application/security.py).
// GA4 records page changes in the single-page app itself (enhanced measurement).
const MEASUREMENT_ID = 'G-28W41YFR82';

export function initAnalytics() {
  if (typeof window === 'undefined' || window.gtag) return;
  window.dataLayer = window.dataLayer || [];
  window.gtag = function gtag() {
    window.dataLayer.push(arguments);
  };
  window.gtag('js', new Date());
  window.gtag('config', MEASUREMENT_ID);

  const script = document.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${MEASUREMENT_ID}`;
  document.head.appendChild(script);
}
