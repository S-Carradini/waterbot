import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Printer, Download, ArrowLeft } from 'lucide-react';
import AppHeader from './AppHeader';
import { uiText } from '../../i18n/uiText';
import { downloadTranscript } from '../../services/api';
import blueCharacter from '../../assets/blue-character.png';
import '../../styles/figma.css';

export default function TranscriptPage() {
  const navigate = useNavigate();
  const [language, setLanguage] = useState('en');
  const t = uiText[language] || uiText.en;

  const today = new Date().toLocaleDateString(language === 'es' ? 'es-ES' : 'en-US', {
    year: 'numeric', month: 'long', day: 'numeric',
  });

  // Pull messages from sessionStorage if ChatPage stores them, otherwise show empty
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem('waterbot_transcript');
      if (stored) setMessages(JSON.parse(stored));
    } catch (_) {}
  }, []);

  const handlePrint = () => window.print();
  const handleDownload = async () => {
    try { await downloadTranscript(); } catch (e) { alert(t.downloadErrorAlert); }
  };

  return (
    <div className="figma-root" style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--wb-light-bg)' }}>
      <AppHeader
        language={language}
        onLangChange={setLanguage}
        onVoice={() => navigate('/chat')}
        onDownload={handleDownload}
        onAbout={() => {}}
        t={t}
      />

      <div style={{ flex: 1, overflowY: 'auto' }}>
        <div style={{ maxWidth: 768, margin: '0 auto', padding: '24px 16px' }}>
          {/* Printable card */}
          <div style={{ background: 'var(--wb-white)', borderRadius: 16, boxShadow: 'var(--wb-shadow)', overflow: 'hidden' }}>
            {/* Header */}
            <div style={{ padding: '24px 32px', borderBottom: '1px solid var(--wb-border)' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                <div>
                  <h1 style={{ fontSize: 28, fontWeight: 600, lineHeight: '36px', color: 'var(--wb-dark)', margin: '0 0 4px' }}>
                    {t.transcriptTitle || 'Waterbot Transcript'}
                  </h1>
                  <p style={{ fontSize: 14, color: 'var(--wb-muted)', margin: '0 0 4px' }}>
                    {t.transcriptSubtitle || 'Arizona Water Chatbot conversation'}
                  </p>
                  <div style={{ display: 'flex', gap: 16, fontSize: 14, color: 'var(--wb-muted)' }}>
                    <span>{t.transcriptDate || 'Date'}: {today}</span>
                    <span>{t.transcriptLanguage || 'Language'}: {language === 'en' ? 'English' : 'Español'}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }} className="print-hidden">
                  <button onClick={handlePrint} className="btn-outline-transcript">
                    <Printer size={18} /> {t.print || 'Print'}
                  </button>
                  <button onClick={handleDownload} className="btn-primary-wb" style={{ minHeight: 44, padding: '8px 16px', fontSize: 14, gap: 8, display: 'flex', alignItems: 'center' }}>
                    <Download size={18} /> {t.download}
                  </button>
                </div>
              </div>
            </div>

            {/* Messages */}
            <div style={{ padding: '24px 32px' }}>
              {messages.length === 0 ? (
                <p style={{ color: 'var(--wb-muted)', textAlign: 'center', padding: 40 }}>
                  No transcript messages yet. Start a chat to see your conversation here.
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                  {messages.map((msg, i) => (
                    <div key={i} style={{ display: 'flex', gap: 12 }}>
                      <div style={{ flexShrink: 0, width: 32, paddingTop: 2 }}>
                        {msg.type === 'bot' ? (
                          <div style={{ width: 28, height: 28, borderRadius: '50%', overflow: 'hidden', background: 'var(--wb-light-bg)', padding: 2 }}>
                            <img src={blueCharacter} alt="Blue" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                          </div>
                        ) : (
                          <div style={{ width: 28, height: 28, borderRadius: '50%', background: 'var(--wb-light-bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 600, color: 'var(--wb-muted)' }}>
                            You
                          </div>
                        )}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
                          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--wb-dark)' }}>
                            {msg.type === 'bot' ? 'Waterbot' : 'You'}
                          </span>
                          {msg.time && <span style={{ fontSize: 12, color: 'var(--wb-muted)' }}>{msg.time}</span>}
                        </div>
                        <p style={{ fontSize: 16, lineHeight: '24px', color: 'var(--wb-dark)', margin: 0 }}
                          dangerouslySetInnerHTML={{ __html: typeof msg.content === 'string' ? msg.content : '' }} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Back button */}
          <div style={{ marginTop: 24, textAlign: 'center' }} className="print-hidden">
            <button onClick={() => navigate('/chat')} className="btn-link-wb" style={{ gap: 8, display: 'inline-flex', alignItems: 'center' }}>
              <ArrowLeft size={16} /> {t.backToChat}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        .btn-outline-transcript {
          min-height: 44px; padding: 8px 16px; display: flex; align-items: center; gap: 8px;
          border: 1px solid var(--wb-primary); color: var(--wb-primary); background: none;
          border-radius: var(--wb-radius); font-size: 14px; font-weight: 600; cursor: pointer;
        }
        .btn-outline-transcript:hover { background: rgba(23,162,219,0.05); }
        @media print { .print-hidden { display: none !important; } }
      `}</style>
    </div>
  );
}
