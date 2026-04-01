import React, { useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Mic, X } from 'lucide-react';
import svgPaths from '../../imports/svg-s7e7bo9si0';

function AnimatedBlue({ isListening }) {
  return (
    <motion.div
      style={{ position: 'relative', width: 180, height: 180 }}
      animate={{
        y: isListening ? [0, -3, 0] : 0,
      }}
      transition={{
        duration: 3,
        repeat: isListening ? Infinity : 0,
        ease: 'easeInOut',
      }}
    >
      <svg
        style={{ display: 'block', width: '100%', height: '100%' }}
        fill="none"
        preserveAspectRatio="xMidYMid meet"
        viewBox="0 0 432 436"
      >
        <g filter="url(#filter0_d_voice)" id="BlueVoice">
          <g>
            <path d={svgPaths.p1fba0f80} fill="#55B7D5" stroke="#407498" strokeMiterlimit="10" strokeWidth="2" />
            <path d={svgPaths.pb8a20c0} fill="#55B7D5" stroke="#407498" strokeMiterlimit="10" strokeWidth="2" />
          </g>
          <path d={svgPaths.p202dd100} fill="#55B7D5" stroke="#407498" strokeMiterlimit="10" strokeWidth="2" />
          <path d={svgPaths.p3226d80} fill="#55B7D5" stroke="#407498" strokeMiterlimit="10" strokeWidth="2" />
          <path d={svgPaths.p10b79d80} fill="#55B7D5" stroke="#407498" strokeMiterlimit="10" strokeWidth="2" />
          <path d={svgPaths.p16c27f00} fill="#55B7D5" stroke="#407498" strokeMiterlimit="10" strokeWidth="2" />
          <g>
            {/* Eyes - blink */}
            <motion.path
              d={svgPaths.pefd9092}
              stroke="#223643" strokeMiterlimit="10" strokeWidth="3"
              animate={{ scaleY: isListening ? [1, 0.1, 1, 1, 1, 1, 0.1, 1] : 1 }}
              transition={{ duration: 2, repeat: isListening ? Infinity : 0, ease: 'easeInOut' }}
              style={{ transformOrigin: 'center' }}
            />
            <motion.path
              d={svgPaths.p32038b00}
              stroke="#223643" strokeMiterlimit="10" strokeWidth="3"
              animate={{ scaleY: isListening ? [1, 0.1, 1, 1, 1, 1, 0.1, 1] : 1 }}
              transition={{ duration: 2, repeat: isListening ? Infinity : 0, ease: 'easeInOut' }}
              style={{ transformOrigin: 'center' }}
            />
            <path d={svgPaths.p3ee1fa80} fill="#223643" />
            {/* Mouth - animated */}
            <motion.path
              d={svgPaths.p19ba8a80}
              fill="#E47E77"
              animate={{
                scaleY: isListening ? [1, 1.4, 1.1, 1.5, 1, 1.3, 1.15, 1.2, 1] : 1,
                scaleX: isListening ? [1, 0.95, 1.02, 0.93, 1, 0.96, 1.01, 0.97, 1] : 1,
              }}
              transition={{ duration: 1.2, repeat: isListening ? Infinity : 0, ease: 'easeInOut' }}
              style={{ transformOrigin: 'center' }}
            />
            {/* Eyebrows */}
            <motion.path
              d={svgPaths.p1b235200}
              fill="#223643"
              animate={{ y: isListening ? [0, -2, 0, -1, 0] : 0 }}
              transition={{ duration: 1.5, repeat: isListening ? Infinity : 0, ease: 'easeInOut' }}
              style={{ transformOrigin: 'center' }}
            />
            <motion.path
              d={svgPaths.p1228fd80}
              fill="#223643"
              animate={{ y: isListening ? [0, -2, 0, -1, 0] : 0 }}
              transition={{ duration: 1.5, repeat: isListening ? Infinity : 0, ease: 'easeInOut' }}
              style={{ transformOrigin: 'center' }}
            />
          </g>
        </g>
        <defs>
          <filter colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse" height="435.87" id="filter0_d_voice" width="431.996" x="0" y="0">
            <feFlood floodOpacity="0" result="BackgroundImageFix" />
            <feColorMatrix in="SourceAlpha" result="hardAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" />
            <feOffset dy="4" />
            <feGaussianBlur stdDeviation="2" />
            <feComposite in2="hardAlpha" operator="out" />
            <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.25 0" />
            <feBlend in2="BackgroundImageFix" mode="normal" result="effect1_dropShadow" />
            <feBlend in="SourceGraphic" in2="effect1_dropShadow" mode="normal" result="shape" />
          </filter>
        </defs>
      </svg>
    </motion.div>
  );
}

function ListeningRipples() {
  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          style={{ position: 'absolute', width: 180, height: 180 }}
          initial={{ scale: 1, opacity: 0 }}
          animate={{ scale: [1, 1.8, 2.2], opacity: [0.6, 0.3, 0] }}
          transition={{ duration: 3, repeat: Infinity, delay: i * 1, ease: 'easeOut' }}
        >
          <div style={{
            position: 'absolute', inset: 0,
            border: '4px solid #55B7D5',
            borderRadius: '50%',
            filter: 'blur(2px)',
          }} />
        </motion.div>
      ))}
    </div>
  );
}

export default function VoiceOverlay({ isOpen, onStop, onTranscript, language, t }) {
  const recognitionRef = useRef(null);
  const transcriptRef = useRef('');

  const handleStop = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.onend = null;
      try { recognitionRef.current.stop(); } catch (_) {}
      recognitionRef.current = null;
    }
    const text = transcriptRef.current.trim();
    transcriptRef.current = '';
    if (text) onTranscript(text);
    onStop();
  }, [onStop, onTranscript]);

  useEffect(() => {
    if (!isOpen) {
      if (recognitionRef.current) {
        recognitionRef.current.onend = null;
        try { recognitionRef.current.stop(); } catch (_) {}
        recognitionRef.current = null;
      }
      transcriptRef.current = '';
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert('Voice input is not supported in this browser.');
      onStop();
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = language === 'es' ? 'es-ES' : 'en-US';

    recognition.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcriptRef.current += event.results[i][0].transcript + ' ';
      }
    };
    recognition.onerror = () => handleStop();
    recognition.onend = () => {
      if (recognitionRef.current) {
        try { recognition.start(); } catch (_) {}
      }
    };

    recognitionRef.current = recognition;
    try { recognition.start(); } catch (_) {}

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.onend = null;
        try { recognitionRef.current.stop(); } catch (_) {}
        recognitionRef.current = null;
      }
    };
  }, [isOpen, language, onStop, handleStop]);

  if (!isOpen) return null;

  return (
    <div className="voice-overlay" role="dialog" aria-modal="true" aria-label={t.voiceMode}>
      <button className="voice-overlay__close" onClick={handleStop} aria-label={t.close}>
        <X size={22} />
      </button>

      <div className="voice-overlay__mascot" style={{ position: 'relative' }}>
        <ListeningRipples />
        <AnimatedBlue isListening={true} />
      </div>

      <div className="voice-overlay__status">{t.listening}</div>
      <div className="voice-overlay__waves">
        {Array.from({ length: 15 }).map((_, i) => (
          <div key={i} className="voice-wave-bar" style={{ animationDelay: `${i * 0.08}s` }} />
        ))}
      </div>
      <button className="voice-overlay__mic-btn" onClick={handleStop} aria-label={t.tapToStop}>
        <Mic size={28} />
      </button>
      <div className="voice-overlay__hint">{t.tapToStop}</div>
    </div>
  );
}
