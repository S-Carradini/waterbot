import React, { useState, useRef, useEffect } from 'react';
import { Mic, Send } from 'lucide-react';

export default function Composer({ onSend, onVoice, disabled, t }) {
  const [value, setValue] = useState('');
  const inputRef = useRef(null);
  const hasText = value.trim().length > 0;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (hasText && !disabled) {
      onSend(value.trim());
      setValue('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  useEffect(() => {
    if (!disabled && inputRef.current) inputRef.current.focus();
  }, [disabled]);

  return (
    <form className={`composer${disabled ? ' composer--disabled' : ''}`} onSubmit={handleSubmit}>
      <button type="button" className="composer__btn-mic" onClick={onVoice} disabled={disabled} aria-label="Start voice input">
        <Mic size={20} />
      </button>
      <input
        ref={inputRef}
        type="text"
        className="composer__input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t.askPlaceholder}
        disabled={disabled}
        aria-label="Message input"
      />
      <button
        type="submit"
        className={`composer__btn-send${hasText && !disabled ? ' active' : ''}`}
        disabled={!hasText || disabled}
        aria-label="Send message"
      >
        <Send size={20} />
      </button>
    </form>
  );
}
