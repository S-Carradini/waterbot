import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, Mail, User } from 'lucide-react';
import AppHeader from './AppHeader';
import { uiText } from '../../i18n/uiText';
import blueCharacter from '../../assets/blue-character.png';
import '../../styles/figma.css';

export default function SettingsPage() {
  const navigate = useNavigate();
  const [language, setLanguage] = useState('en');
  const [useLocalSources, setUseLocalSources] = useState(true);
  const t = uiText[language] || uiText.en;

  const handleLangChange = (lang) => setLanguage(lang);

  return (
    <div className="figma-root" style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--wb-light-bg)' }}>
      <AppHeader
        language={language}
        onLangChange={handleLangChange}
        onVoice={() => navigate('/chat')}
        onDownload={() => navigate('/transcript')}
        onAbout={() => {}}
        t={t}
      />

      <div style={{ flex: 1, overflowY: 'auto' }}>
        <div style={{ maxWidth: 640, margin: '0 auto', padding: '24px 16px', display: 'flex', flexDirection: 'column', gap: 24 }}>

          {/* About Section */}
          <section style={{ background: 'var(--wb-white)', borderRadius: 16, boxShadow: 'var(--wb-shadow)', overflow: 'hidden', padding: '20px 24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
              <div style={{ width: 64, height: 64, flexShrink: 0 }}>
                <img src={blueCharacter} alt="Blue" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
              </div>
              <div>
                <h2 style={{ fontSize: 20, fontWeight: 600, lineHeight: '28px', color: 'var(--wb-dark)', margin: 0 }}>
                  {t.aboutTitle}
                </h2>
                <p style={{ fontSize: 14, color: 'var(--wb-muted)', margin: 0 }}>Arizona Water Chatbot</p>
              </div>
            </div>
            <p style={{ fontSize: 16, lineHeight: '24px', color: 'var(--wb-dark)', margin: 0 }}>
              {t.aboutText}
            </p>
          </section>

          {/* Settings Section */}
          <section style={{ background: 'var(--wb-white)', borderRadius: 16, boxShadow: 'var(--wb-shadow)', overflow: 'hidden' }}>
            <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--wb-border)' }}>
              <h2 style={{ fontSize: 20, fontWeight: 600, lineHeight: '28px', color: 'var(--wb-dark)', margin: 0 }}>
                {t.settingsTitle || 'Settings'}
              </h2>
            </div>
            <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Local sources toggle */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
                <p style={{ fontSize: 16, lineHeight: '24px', color: 'var(--wb-dark)', margin: 0 }}>
                  {t.useLocalSources || 'Use curated water information sources when available'}
                </p>
                <button
                  onClick={() => setUseLocalSources(!useLocalSources)}
                  role="switch"
                  aria-checked={useLocalSources}
                  style={{
                    position: 'relative', width: 44, height: 24, borderRadius: 12,
                    border: 'none', cursor: 'pointer', flexShrink: 0, padding: 0,
                    background: useLocalSources ? 'var(--wb-primary)' : 'var(--wb-border)',
                    transition: 'background 0.2s',
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 2, left: useLocalSources ? 22 : 2,
                    width: 20, height: 20, borderRadius: '50%', background: 'white',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.15)', transition: 'left 0.2s',
                  }} />
                </button>
              </div>

              {/* Default language */}
              <div>
                <p style={{ fontSize: 16, fontWeight: 600, lineHeight: '24px', color: 'var(--wb-dark)', margin: '0 0 8px' }}>
                  {t.defaultLanguage || 'Default Language'}
                </p>
                <div style={{ display: 'flex', gap: 12 }}>
                  {['en', 'es'].map((lang) => (
                    <button
                      key={lang}
                      onClick={() => handleLangChange(lang)}
                      style={{
                        flex: 1, minHeight: 44, padding: '10px 16px', borderRadius: 12,
                        fontSize: 16, fontWeight: 600, cursor: 'pointer',
                        border: `1px solid ${language === lang ? 'var(--wb-primary)' : 'var(--wb-border)'}`,
                        background: language === lang ? 'var(--wb-primary)' : 'var(--wb-white)',
                        color: language === lang ? 'var(--wb-white)' : 'var(--wb-dark)',
                        transition: 'all 0.2s',
                      }}
                    >
                      {lang === 'en' ? 'English' : 'Español'}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          {/* Privacy Note */}
          <section style={{ background: 'var(--wb-white)', borderRadius: 16, boxShadow: 'var(--wb-shadow)', overflow: 'hidden', padding: '20px 24px' }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', marginBottom: 12 }}>
              <ShieldCheck size={20} style={{ color: 'var(--wb-accent)', flexShrink: 0, marginTop: 2 }} />
              <h2 style={{ fontSize: 20, fontWeight: 600, lineHeight: '28px', color: 'var(--wb-dark)', margin: 0 }}>
                {t.privacyNote || 'Privacy Note'}
              </h2>
            </div>
            <p style={{ fontSize: 16, lineHeight: '24px', color: 'var(--wb-muted)', margin: 0 }}>
              {t.privacyText || 'Waterbot is an educational tool designed to help users explore water information. Responses may not always be perfect, so users should review sources when available.'}
            </p>
          </section>

          {/* Contact */}
          <section style={{ background: 'var(--wb-white)', borderRadius: 16, boxShadow: 'var(--wb-shadow)', overflow: 'hidden' }}>
            <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--wb-border)' }}>
              <h2 style={{ fontSize: 20, fontWeight: 600, lineHeight: '28px', color: 'var(--wb-dark)', margin: 0 }}>
                {t.contactTitle || 'Contact'}
              </h2>
            </div>
            <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 12, background: 'var(--wb-light-bg)', borderRadius: 12 }}>
                <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'rgba(23,162,219,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <User size={18} style={{ color: 'var(--wb-primary)' }} />
                </div>
                <p style={{ fontSize: 14, color: 'var(--wb-dark)', margin: 0 }}>
                  {t.contactPlaceholder1 || 'Project Lead — project@example.edu'}
                </p>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 12, background: 'var(--wb-light-bg)', borderRadius: 12 }}>
                <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'rgba(86,126,132,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <Mail size={18} style={{ color: 'var(--wb-teal)' }} />
                </div>
                <p style={{ fontSize: 14, color: 'var(--wb-dark)', margin: 0 }}>
                  {t.contactPlaceholder2 || 'Technical Support — support@example.edu'}
                </p>
              </div>
            </div>
          </section>

          {/* Return to Chat */}
          <div style={{ textAlign: 'center', paddingBottom: 16 }}>
            <button onClick={() => navigate('/chat')} className="btn-primary-wb">
              {t.returnToChat || 'Return to Chat'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
