import React, { useEffect, useRef, useCallback } from 'react';
import { Mic, X } from 'lucide-react';
import blueCharacter from '../../assets/blue-character.png';

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
      <div className="voice-overlay__mascot"><img src={blueCharacter} alt="Blue" /></div>
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
