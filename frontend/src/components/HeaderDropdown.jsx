import React, { useState, useRef, useEffect } from 'react';
import imgEllipse3 from '../assets/home.png';
import imgDownloadTranscript from '../assets/download-transcript.png';
import { downloadTranscript } from '../services/api';
import { uiText } from '../i18n/uiText';

export default function HeaderDropdown({ onMicClick, isListening, language = 'en' }) {
  const [isDownloading, setIsDownloading] = useState(false);
  const dropdownRef = useRef(null);
  const t = uiText[language] || uiText.en;

  const handleDownload = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDownloading(true);
    
    try {
      await downloadTranscript();
    } catch (error) {
      console.error('Error downloading transcript:', error);
      alert(t.downloadErrorAlert);
    } finally {
      setIsDownloading(false);
    }
  };

  const handleHome = (e) => {
    e.preventDefault();
    e.stopPropagation();
    window.location.href = '/';
  };

  const handleMic = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (onMicClick) {
      onMicClick();
    }
  };

  return (
    <div className="header-dropdown" ref={dropdownRef}>
      <div className="header-dropdown-menu">
        <button 
          className="header-dropdown-item"
          onClick={handleHome}
          aria-label={t.ariaHome}
        >
          <img alt={t.ariaHome} src={imgEllipse3} />
        </button>
        
        <button 
          className="header-dropdown-item header-dropdown-download"
          onClick={handleDownload}
          disabled={isDownloading}
          aria-label={t.ariaDownloadTranscript}
        >
          {isDownloading ? (
            <div className="loading-spinner"></div>
          ) : (
            <img alt={t.ariaDownloadTranscript} src={imgDownloadTranscript} />
          )}
        </button>
        
        <button 
          className={`header-dropdown-item ${isListening ? 'recording' : ''}`}
          onClick={handleMic}
          aria-label={isListening ? t.ariaStopRecording : t.ariaMicrophone}
        >
          <i className={`fas fa-microphone ${isListening ? 'recording' : ''}`}></i>
        </button>
      </div>
    </div>
  );
}

