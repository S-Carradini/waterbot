import React from 'react';

export default function FollowUpChips({ onAction, disabled, t }) {
  const chips = [
    { key: 'tell-me-more', label: t.actionLabels['tell-me-more'] },
    { key: 'next-steps', label: t.actionLabels['next-steps'] },
    { key: 'sources', label: t.actionLabels.sources },
  ];

  return (
    <div className="follow-up-chips">
      {chips.map((chip) => (
        <button
          key={chip.key}
          className="chip"
          onClick={() => onAction(chip.key)}
          disabled={disabled}
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}
