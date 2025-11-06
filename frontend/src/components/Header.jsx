import React from 'react';
import imgAsuSunBurst from '../assets/asu-sunburst.png';
import DownloadTranscript from './DownloadTranscript';

export default function Header() {
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

      {/* Download Transcript Button */}
      <DownloadTranscript />
    </header>
  );
}

