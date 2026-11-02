// Sanitizes bot output before it is rendered as HTML.
//
// Bot replies are model output and can be steered by prompt injection or by text
// planted in a source document, so they are never trusted as markup. Only simple
// formatting tags and http(s)/mailto/tel links survive; scripts, event handlers,
// styles, images and iframes are removed.
import DOMPurify from 'dompurify';

const ALLOWED_TAGS = [
  'p', 'br', 'b', 'strong', 'i', 'em', 'u', 'del', 's', 'code', 'pre', 'blockquote', 'hr',
  'ul', 'ol', 'li', 'a', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
];
const ALLOWED_ATTR = ['href', 'title', 'target', 'rel'];
const SAFE_LINK = /^(https?:|mailto:|tel:)/i;

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    const href = (node.getAttribute('href') || '').trim();
    if (!SAFE_LINK.test(href)) {
      node.removeAttribute('href');
    }
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

export function sanitizeHtml(html) {
  return DOMPurify.sanitize(typeof html === 'string' ? html : '', {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
  });
}

// Plain text of an HTML string, parsed in an inert document (nothing executes or loads).
export function htmlToText(html) {
  if (typeof html !== 'string' || !html) return '';
  const doc = new DOMParser().parseFromString(html, 'text/html');
  return doc.body.textContent || '';
}

export function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
