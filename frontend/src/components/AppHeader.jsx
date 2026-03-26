import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Mic, Download, Info } from 'lucide-react';
import LanguageToggle from './LanguageToggle';

export default function AppHeader({ language, onLangChange, onVoice, onDownload, t }) {
  const navigate = useNavigate();

  return (
    <header className="app-header">
      <div className="app-header__left">
        <button
          onClick={() => navigate('/')}
          className="wb-logo"
          aria-label="Waterbot home"
        >
          <span className="water">Water</span>
          <span className="bot">bot</span>
        </button>
      </div>
      <div className="app-header__right">
        <LanguageToggle lang={language} onLangChange={onLangChange} t={t} />
        <button
          className="btn-icon-wb"
          onClick={onVoice}
          aria-label={t('voiceMode')}
          title={t('voiceMode')}
        >
          <Mic size={20} />
        </button>
        <button
          className="btn-icon-wb"
          onClick={onDownload}
          aria-label={t('downloadTranscript')}
          title={t('downloadTranscript')}
        >
          <Download size={20} />
        </button>
      </div>
    </header>
  );
}
