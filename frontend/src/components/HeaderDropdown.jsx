import React, { useState, useRef, useEffect } from 'react';
import imgEllipse3 from '../assets/home.png';
import imgDownloadTranscript from '../assets/download-transcript.png';
import { downloadTranscript } from '../services/api';

export default function HeaderDropdown({ onMicClick, isListening }) {
  const [isDownloading, setIsDownloading] = useState(false);
  const dropdownRef = useRef(null);

  const handleDownload = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDownloading(true);
    
    try {
      await downloadTranscript();
    } catch (error) {
      console.error('Error downloading transcript:', error);
      alert('Could not download transcript. Please try again.');
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
          aria-label="Home"
        >
          <img alt="Home" src={imgEllipse3} />
        </button>
        
        <button 
          className="header-dropdown-item header-dropdown-download"
          onClick={handleDownload}
          disabled={isDownloading}
          aria-label="Download transcript"
        >
          {isDownloading ? (
            <div className="loading-spinner"></div>
          ) : (
            <img alt="Download transcript" src={imgDownloadTranscript} />
          )}
        </button>
        
        <button 
          className={`header-dropdown-item ${isListening ? 'recording' : ''}`}
          onClick={handleMic}
          aria-label={isListening ? 'Stop Recording' : 'Microphone'}
        >
          <i className={`fas fa-microphone ${isListening ? 'recording' : ''}`}></i>
        </button>
      </div>
    </div>
  );
}

