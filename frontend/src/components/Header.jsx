import React from 'react';
import imgWatersimLogo from '../assets/watersim-logo.svg';
import HeaderDropdown from './HeaderDropdown';

export default function Header({ onMicClick, isListening, language = 'en' }) {
  return (
    <header className="header-unit">
      <div className="header-bar">
        <a
          href="https://watersimmersive.net/"
          target="_blank"
          rel="noopener noreferrer"
          className="header-bar-logo-link"
        >
          <img alt="WaterSimmersive" src={imgWatersimLogo} className="header-bar-logo" />
        </a>
      </div>
      <div className="header-buttons-container">
        <HeaderDropdown onMicClick={onMicClick} isListening={isListening} language={language} />
      </div>
    </header>
  );
}

