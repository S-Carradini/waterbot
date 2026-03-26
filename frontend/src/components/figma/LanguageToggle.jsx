import React from 'react';

export default function LanguageToggle({ lang, onLangChange, t }) {
  return (
    <div className="lang-toggle" role="radiogroup" aria-label="Language selection">
      <button
        onClick={() => onLangChange('en')}
        role="radio"
        aria-checked={lang === 'en'}
        className={`lang-toggle__btn${lang === 'en' ? ' active' : ''}`}
      >
        {t.english}
      </button>
      <button
        onClick={() => onLangChange('es')}
        role="radio"
        aria-checked={lang === 'es'}
        className={`lang-toggle__btn${lang === 'es' ? ' active' : ''}`}
      >
        {t.spanish}
      </button>
    </div>
  );
}
