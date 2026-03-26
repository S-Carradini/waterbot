import React from 'react';
import { X, MessageSquare, Droplets, BookOpen } from 'lucide-react';

export default function HowItWorksModal({ isOpen, onClose, onStart, t }) {
  if (!isOpen) return null;

  const steps = [
    { icon: MessageSquare, title: t.step1Title, desc: t.step1Desc, color: '#17A2DB' },
    { icon: Droplets, title: t.step2Title, desc: t.step2Desc, color: '#7FB4CB' },
    { icon: BookOpen, title: t.step3Title, desc: t.step3Desc, color: '#567E84' },
  ];

  return (
    <>
      <div className="modal-backdrop-wb" onClick={onClose} />
      <div className="modal-overlay-wb" role="dialog" aria-modal="true" aria-label={t.howTitle}>
        <div className="modal-card modal-card--lg" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header-wb">
            <h2>{t.howTitle}</h2>
            <button className="btn-icon-wb" onClick={onClose} aria-label={t.close}><X size={20} /></button>
          </div>
          <div className="modal-body-wb">
            {steps.map((step, i) => (
              <div key={i} className="hiw-step">
                <div className="hiw-step__icon" style={{ backgroundColor: step.color + '20', color: step.color }}>
                  <step.icon size={20} />
                </div>
                <div>
                  <div className="hiw-step__title">{i + 1}. {step.title}</div>
                  <div className="hiw-step__desc">{step.desc}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="modal-footer-wb">
            <button className="btn-primary-wb" style={{ width: '100%' }} onClick={onStart}>{t.startChat}</button>
          </div>
        </div>
      </div>
    </>
  );
}
