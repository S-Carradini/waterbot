import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Info } from 'lucide-react';
import LanguageToggle from './LanguageToggle';
import HowItWorksModal from './HowItWorksModal';
import AboutModal from './AboutModal';
import { uiText } from '../../i18n/uiText';
import blueCharacter from '../../assets/blue-character.png';
import '../../styles/figma.css';

export default function FigmaSplashScreen() {
  const navigate = useNavigate();
  const [lang, setLang] = useState('en');
  const [showHowItWorks, setShowHowItWorks] = useState(false);
  const [showAbout, setShowAbout] = useState(false);

  const t = uiText[lang] || uiText.en;

  return (
    <div className="figma-root">
      <div className="splash">
        {/* Top bar */}
        <div className="splash__topbar">
          <button className="wb-logo" aria-label="Waterbot">
            <span className="water">Water</span><span className="bot">bot</span>
          </button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <LanguageToggle lang={lang} onLangChange={setLang} t={t} />
            <button className="btn-icon-wb" onClick={() => setShowAbout(true)} aria-label={t.aboutTitle}>
              <Info size={20} />
            </button>
          </div>
        </div>

        {/* Center */}
        <div className="splash__center">
          <div className="splash__mascot">
            <img src={blueCharacter} alt="Blue - Waterbot mascot" />
          </div>
          <h1 className="splash__title">
            <span className="water">Water</span><span className="bot">bot</span>
          </h1>
          <p className="splash__subtitle">{t.splashSubline}</p>
          <div className="splash__actions">
            <button className="btn-primary-wb" onClick={() => navigate('/chat')}>
              {t.enterChat}
            </button>
            <button className="btn-link-wb" onClick={() => setShowHowItWorks(true)}>
              {t.howItWorks}
            </button>
          </div>
        </div>

        {/* Disclaimer */}
        <div className="splash__disclaimer">
          <p>{t.disclaimer}</p>
          <p>{t.partnerLine}</p>
        </div>
      </div>

      <HowItWorksModal
        isOpen={showHowItWorks}
        onClose={() => setShowHowItWorks(false)}
        onStart={() => { setShowHowItWorks(false); navigate('/chat'); }}
        t={t}
      />
      <AboutModal isOpen={showAbout} onClose={() => setShowAbout(false)} t={t} />
    </div>
  );
}
