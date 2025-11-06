import React, { useState, useRef } from 'react';
import imgEllipse3 from '../assets/home.png';
import imgDownloadTranscript from '../assets/download-transcript.png';
import { downloadTranscript } from '../services/api';

export default function DownloadTranscript() {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const leaveTimeoutRef = useRef(null);

  const handleMouseEnter = () => {
    // Clear any pending close timeout
    if (leaveTimeoutRef.current) {
      clearTimeout(leaveTimeoutRef.current);
      leaveTimeoutRef.current = null;
    }
    setIsDropdownOpen(true);
  };

  const handleMouseLeave = () => {
    // Add a small delay before closing to prevent glitching
    leaveTimeoutRef.current = setTimeout(() => {
      setIsDropdownOpen(false);
      leaveTimeoutRef.current = null;
    }, 100);
  };

  const handleDownload = async (e) => {
    e.preventDefault();
    setIsDownloading(true);
    
    try {
      await downloadTranscript();
    } catch (error) {
      console.error('Error downloading transcript:', error);
      alert('Could not download transcript. Please try again.');
    } finally {
      setIsDownloading(false);
      setIsDropdownOpen(false);
    }
  };

  return (
    <div 
      className="download-transcript-container"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <a 
        className="download-transcript-link" 
        href="#"
        onClick={(e) => {
          e.preventDefault();
          setIsDropdownOpen(!isDropdownOpen);
        }}
      >
        {!isDropdownOpen && (
          <div className="download-transcript-hamburger">
            <i className="fas fa-bars"></i>
          </div>
        )}
      </a>
      <div className={`download-transcript-card ${isDropdownOpen ? 'dropdown-open' : 'dropdown-closed'}`}>
        {isDropdownOpen && (
          <>
            <div className="download-transcript-ellipse">
              <img alt="" src={imgEllipse3} />
            </div>
            <div 
              className="download-transcript-icon-container"
              onClick={handleDownload}
              style={{ cursor: isDownloading ? 'wait' : 'pointer' }}
            >
              <div className="download-transcript-icon-inner">
                {isDownloading ? (
                  <div style={{ color: 'white', fontSize: '14px' }}>Downloading...</div>
                ) : (
                  <img alt="Download transcript" src={imgDownloadTranscript} />
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

