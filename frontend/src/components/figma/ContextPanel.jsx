import React from 'react';
import { PanelLeftClose, PanelLeft, Droplets, CloudRain, Landmark, Thermometer, MapPin, ShieldCheck } from 'lucide-react';

export default function ContextPanel({ isOpen, onToggle, onPromptSelect, t }) {
  const topics = [
    { key: 'topicWaterCycle', icon: Droplets, color: '#17A2DB' },
    { key: 'topicDrought', icon: CloudRain, color: '#567E84' },
    { key: 'topicGovernance', icon: Landmark, color: '#7FB4CB' },
    { key: 'topicClimate', icon: Thermometer, color: '#17A2DB' },
    { key: 'topicLocalRivers', icon: MapPin, color: '#567E84' },
  ];

  const prompts = [t.prompt1, t.prompt2, t.prompt3];

  return (
    <>
      {isOpen && <div className="panel-backdrop" onClick={onToggle} />}

      {!isOpen && (
        <button className="panel-toggle-btn" onClick={onToggle} aria-label="Open context panel">
          <PanelLeft size={18} />
        </button>
      )}

      <aside className={`context-panel${isOpen ? '' : ' closed'}`} role="complementary" aria-label="Context panel">
        <div className="context-panel__inner">
          <div className="context-panel__header">
            <h2>{t.contextPanel}</h2>
            <button className="btn-icon-wb" onClick={onToggle} aria-label="Close context panel">
              <PanelLeftClose size={18} />
            </button>
          </div>

          <div className="context-panel__topics">
            {topics.map((topic) => (
              <button
                key={topic.key}
                className="topic-chip"
                onClick={() => onPromptSelect(`Tell me about ${t[topic.key]}`)}
              >
                <topic.icon size={16} style={{ color: topic.color }} />
                {t[topic.key]}
              </button>
            ))}
          </div>

          <div className="context-panel__prompts">
            <div className="context-panel__prompts-label">{t.suggestedPrompts}</div>
            {prompts.map((prompt, i) => (
              <button key={i} className="prompt-btn" onClick={() => onPromptSelect(prompt)}>{prompt}</button>
            ))}
          </div>

          <div className="context-panel__footer">
            <div className="trust-note">
              <ShieldCheck size={16} className="trust-note__icon" />
              <span className="trust-note__text">{t.trustNote}</span>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
