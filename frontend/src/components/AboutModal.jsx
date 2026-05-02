import React from 'react';
import { X } from 'lucide-react';
import blueCharacter from '../assets/blue-character.png';

export default function AboutModal({ isOpen, onClose, t }) {
  if (!isOpen) return null;

  return (
    <>
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-overlay" role="dialog" aria-modal="true" aria-label={t('aboutTitle')}>
        <div className="modal-card" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header-wb">
            <h2>{t('aboutTitle')}</h2>
            <button className="btn-icon-wb" onClick={onClose} aria-label={t('close')}>
              <X size={20} />
            </button>
          </div>
          <div className="modal-body-wb" style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
            <div className="about-mascot">
              <img src={blueCharacter} alt="Blue mascot" />
            </div>
            <p className="about-text">{t('aboutText')}</p>
          </div>
          <div className="modal-footer-wb">
            <button className="btn-primary-wb" style={{ width: '100%' }} onClick={onClose}>
              {t('close')}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
