import React, { useState } from 'react';
import imgEllipse3 from '../assets/home.png';
import imgDownloadTranscript from '../assets/download-transcript.png';
import { downloadTranscript } from '../services/api';

export default function DownloadTranscript() {
  const [isDownloading, setIsDownloading] = useState(false);

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
    }
  };

  const handleHome = () => {
    // Navigate to home or refresh
    window.location.href = '/';
  };

  return (
    <div className="download-transcript-container">
      <div 
        className="download-transcript-ellipse"
        onClick={handleHome}
        style={{ cursor: 'pointer' }}
      >
        <img alt="Home" src={imgEllipse3} />
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
    </div>
  );
}

