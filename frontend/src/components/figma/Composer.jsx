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
      if (inputRef.current) {
        inputRef.current.style.height = 'auto';
        inputRef.current.style.overflowY = 'hidden';
      }
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

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const lh = parseFloat(getComputedStyle(el).lineHeight) || 24;
    const pt = parseFloat(getComputedStyle(el).paddingTop) || 0;
    const pb = parseFloat(getComputedStyle(el).paddingBottom) || 0;
    const maxH = lh * 4 + pt + pb;
    if (el.scrollHeight <= maxH) {
      el.style.height = el.scrollHeight + 'px';
      el.style.overflowY = 'hidden';
    } else {
      el.style.height = maxH + 'px';
      el.style.overflowY = 'auto';
    }
  }, [value]);

  return (
    <form className={`composer${disabled ? ' composer--disabled' : ''}`} onSubmit={handleSubmit}>
      <button type="button" className="composer__btn-mic" onClick={onVoice} disabled={disabled} aria-label="Start voice input">
        <Mic size={20} />
      </button>
      <textarea
        ref={inputRef}
        rows="1"
        className="composer__input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t.askPlaceholder}
        disabled={disabled}
        aria-label="Message input"
        style={{ resize: 'none', overflowY: 'hidden' }}
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
