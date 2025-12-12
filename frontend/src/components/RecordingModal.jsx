import React from 'react';
import './RecordingModal.css';

export default function RecordingModal({ isVisible, onClose }) {
  if (!isVisible) return null;

  return (
    <div className="recording-modal-overlay" onClick={onClose}>
      <div className="recording-modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="recording-modal-animation">
          <div className="recording-modal-button">
            <i className="fas fa-microphone"></i>
          </div>
          <div className="recording-modal-rings">
            <div className="recording-modal-ring ring-1"></div>
            <div className="recording-modal-ring ring-2"></div>
            <div className="recording-modal-ring ring-3"></div>
            <div className="recording-modal-ring ring-4"></div>
          </div>
        </div>
        <p className="recording-modal-text">Recording...</p>
        <button className="recording-modal-close" onClick={onClose}>
          Stop Recording
        </button>
      </div>
    </div>
  );
}
