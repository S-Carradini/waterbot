import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Mic, Download, FileText, Settings, ArrowLeft, Info } from 'lucide-react';
import LanguageToggle from './LanguageToggle';

export default function AppHeader({ language, onLangChange, onVoice, onDownload, onAbout, t }) {
  const navigate = useNavigate();
  const location = useLocation();
  const isChat = location.pathname === '/chat';
  const isSubPage = location.pathname !== '/chat' && location.pathname !== '/';

  return (
    <header className="app-header">
      <div className="app-header__left">
        {isSubPage && (
          <button
            onClick={() => navigate('/chat')}
            className="btn-icon-wb"
            aria-label={t.backToChat}
          >
            <ArrowLeft size={20} />
          </button>
        )}
        <button onClick={() => navigate('/')} className="wb-logo" aria-label="Waterbot home">
          <span className="water">Water</span>
          <span className="bot">bot</span>
        </button>
      </div>
      <div className="app-header__right">
        <LanguageToggle lang={language} onLangChange={onLangChange} t={t} />

        {isChat && (
          <>
            <button className="btn-icon-wb" onClick={onVoice} aria-label={t.voiceMode} title={t.voiceMode}>
              <Mic size={20} />
            </button>
            <button className="btn-icon-wb" onClick={onDownload} aria-label={t.downloadTranscript} title={t.downloadTranscript}>
              <Download size={20} />
            </button>
            <button className="btn-icon-wb" onClick={() => navigate('/transcript')} aria-label="View transcript" title="View transcript">
              <FileText size={20} />
            </button>
          </>
        )}

        <button className="btn-icon-wb" onClick={() => navigate('/settings')} aria-label={t.settings} title={t.settings}>
          <Settings size={20} />
        </button>
      </div>
    </header>
  );
}
