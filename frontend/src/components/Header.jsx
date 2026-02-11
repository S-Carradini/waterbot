import React from 'react';
import imgAsuSunBurst from '../assets/asu-sunburst.png';
import HeaderDropdown from './HeaderDropdown';

export default function Header({ onMicClick, isListening }) {
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
        <p>Chat With Blue</p>
      </div>

      {/* Header Dropdown Menu - Home, Download, Mic */}
      <div className="header-buttons-container">
        <HeaderDropdown onMicClick={onMicClick} isListening={isListening} />
      </div>
    </header>
  );
}

