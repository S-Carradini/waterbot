// Shared, persisted UI language so the choice made on one page (splash,
// settings, chat) carries over to the others instead of resetting to English.

const STORAGE_KEY = 'waterbot_language';
const SUPPORTED = ['en', 'es'];

export function getStoredLanguage() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (SUPPORTED.includes(value)) return value;
  } catch (_) {
    // storage unavailable (private mode etc.)
  }
  return 'en';
}

export function storeLanguage(lang) {
  if (!SUPPORTED.includes(lang)) return;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch (_) {
    // ignore
  }
}
