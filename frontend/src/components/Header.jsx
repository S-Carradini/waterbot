import React from 'react';
import imgAsuSunBurst from '../assets/asu-sunburst.png';
import HeaderDropdown from './HeaderDropdown';
import { uiText } from '../i18n/uiText';

export default function Header({ onMicClick, isListening, language = 'en' }) {
  const t = uiText[language] || uiText.en;
  return (
    <header className="header-unit">
      {/* Main White Card */}
      <div className="main-card" />

      {/* ASU Sunburst Background */}
      <div className="asu-sunburst">
        <img alt="" src={imgAsuSunBurst} />
      </div>

      {/* Title */}
      <div className="title">
        <p>{t.headerTitle}</p>
      </div>

      {/* Header Dropdown Menu - Home, Download, Mic */}
      <div className="header-buttons-container">
        <HeaderDropdown onMicClick={onMicClick} isListening={isListening} language={language} />
      </div>
    </header>
  );
}

