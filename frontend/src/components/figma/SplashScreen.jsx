import React, { useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Info } from 'lucide-react';
import LanguageToggle from './LanguageToggle';
import HowItWorksModal from './HowItWorksModal';
import AboutModal from './AboutModal';
import { uiText } from '../../i18n/uiText';
import blueCharacter from '../../assets/blue-character.png';
import '../../styles/figma.css';

function RainDrop({ delay, x, speed, height, width, sway }) {
  return (
    <motion.div
      style={{
        position: 'absolute',
        left: `${x}%`,
        top: -20,
        width: width,
        height: height,
        borderRadius: 9999,
        background: 'linear-gradient(180deg, rgba(23,162,219,0.0) 0%, rgba(23,162,219,0.45) 30%, rgba(23,162,219,0.75) 100%)',
        filter: width > 4 ? 'blur(0.5px)' : 'none',
      }}
      initial={{ y: -40, x: 0, opacity: 0 }}
      animate={{
        y: '110vh',
        x: [0, sway, -sway * 0.5, sway * 0.3, 0],
        opacity: [0, 0.3, 0.9, 0.9, 0],
      }}
      transition={{
        duration: speed,
        delay,
        ease: [0.25, 0.1, 0.25, 1],
        x: { duration: speed, delay, ease: 'easeInOut' },
      }}
    />
  );
}

function SplashRipple({ delay, x }) {
  return (
    <motion.div
      style={{
        position: 'absolute',
        left: `${x}%`,
        bottom: '8%',
        width: 0,
        height: 0,
        borderRadius: 9999,
        border: '2px solid rgba(23,162,219,0.4)',
      }}
      initial={{ width: 0, height: 0, opacity: 0.7 }}
      animate={{ width: 30, height: 10, opacity: 0 }}
      transition={{ duration: 0.8, delay: delay + 0.6, ease: 'easeOut' }}
    />
  );
}

export default function FigmaSplashScreen() {
  const navigate = useNavigate();
  const [lang, setLang] = useState('en');
  const [showHowItWorks, setShowHowItWorks] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const [transitioning, setTransitioning] = useState(false);

  const t = uiText[lang] || uiText.en;

  const rainDrops = useMemo(() => {
    return Array.from({ length: 150 }).map((_, i) => ({
      id: i,
      x: (i * 0.7 + (i * 17.3) % 11) % 100,
      delay: (i * 0.02) % 1.2,
      speed: 1.2 + (i % 7) * 0.2,
      height: 25 + (i % 6) * 10,
      width: 2 + (i % 4),
      sway: 4 + (i % 5) * 3,
    }));
  }, []);

  const handleEnter = useCallback(() => {
    setTransitioning(true);
    setTimeout(() => navigate('/chat'), 1800);
  }, [navigate]);

  return (
    <div className="figma-root">
      {/* Rain transition overlay */}
      <AnimatePresence>
        {transitioning && (
          <>
            {/* Rain drops layer */}
            <motion.div
              style={{
                position: 'fixed',
                inset: 0,
                zIndex: 90,
                pointerEvents: 'none',
                overflow: 'hidden',
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2 }}
            >
              {rainDrops.map((drop) => (
                <RainDrop
                  key={drop.id}
                  x={drop.x}
                  delay={drop.delay}
                  speed={drop.speed}
                  height={drop.height}
                  width={drop.width}
                  sway={drop.sway}
                />
              ))}
              {rainDrops.filter((_, i) => i % 3 === 0).map((drop) => (
                <SplashRipple key={`ripple-${drop.id}`} delay={drop.delay} x={drop.x} />
              ))}
            </motion.div>

            {/* Blue gradient overlay */}
            <motion.div
              style={{
                position: 'fixed',
                inset: 0,
                zIndex: 95,
                pointerEvents: 'none',
                background: 'linear-gradient(180deg, rgba(23,162,219,0.0) 0%, rgba(23,162,219,0.15) 50%, rgba(23,162,219,0.35) 100%)',
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.8, delay: 0.4 }}
            />

            {/* White fade-out overlay */}
            <motion.div
              style={{
                position: 'fixed',
                inset: 0,
                zIndex: 96,
                pointerEvents: 'none',
                background: '#fff',
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.6, delay: 1.1 }}
            />
          </>
        )}
      </AnimatePresence>

      <div className="splash">
        {/* Content fades out during transition */}
        <motion.div
          style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
          animate={transitioning ? { opacity: 0 } : { opacity: 1 }}
          transition={{ duration: 0.6, delay: transitioning ? 0.6 : 0 }}
        >
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
              <button
                className="btn-primary-wb"
                onClick={handleEnter}
                disabled={transitioning}
                style={transitioning ? { opacity: 0.8 } : undefined}
              >
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
        </motion.div>
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
