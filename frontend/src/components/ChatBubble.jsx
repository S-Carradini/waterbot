import React, { useState, useEffect, useRef } from 'react';
import imgBlueCharacter from '../assets/blue-character.png';
import imgPolygon1 from '../assets/polygon-1.png';
import imgThumbsUp from '../assets/thumbs-up.png';
import imgThumbsDown from '../assets/thumbs-down.png';
import { useTypewriter } from '../hooks/useTypewriter';
import { uiText } from '../i18n/uiText';

export default function ChatBubble({
  answerText,
  messageId,
  showActions = true,
  disableActions = false,
  onActionButton,
  onRating,
  isLoading = false,
  disableTypewriter = false,
  language = 'en',
  onContentUpdate,
  onTypingChange,
}) {
  const [ratingSubmitted, setRatingSubmitted] = useState(false);
  const [selectedReaction, setSelectedReaction] = useState(null);
  const [feedbackSelection, setFeedbackSelection] = useState(null);
  const [feedbackOtherText, setFeedbackOtherText] = useState('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [shouldStartTyping, setShouldStartTyping] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  
  // Convert answerText to string for typewriter effect
  const textContent = typeof answerText === 'string' 
    ? answerText 
    : (typeof answerText?.props?.children === 'string' 
        ? answerText.props.children 
        : (Array.isArray(answerText?.props?.children) 
            ? answerText.props.children.map(c => {
                if (c === undefined || c === null) return '';
                return String(c);
              }).join('')
            : String(answerText?.props?.children || '')));
  
  // Clean the text content - remove undefined strings and ensure it's valid
  const cleanTextContent = String(textContent || '').replace(/undefined/g, '');
  
  // Use typewriter effect for string content
  const isTypewriterEnabled = typeof answerText === 'string' && !disableTypewriter;

  const { displayedText, isTyping } = useTypewriter(
    isTypewriterEnabled ? cleanTextContent : '', 
    20, 
    shouldStartTyping && isTypewriterEnabled
  );

  // Start typing when component mounts or answerText changes
  useEffect(() => {
    if (cleanTextContent && isTypewriterEnabled) {
      setShouldStartTyping(false); // Reset first
      setTimeout(() => setShouldStartTyping(true), 50); // Then start after a brief delay
    }
  }, [cleanTextContent, isTypewriterEnabled]);

  // Scroll to bottom when displayedText updates during typewriter effect
  // Scroll with every line (newline character) and continuously for natural line wraps
  const scrollTimeoutRef = useRef(null);
  const lastTextRef = useRef('');
  const lastLineCountRef = useRef(0);
  
  useEffect(() => {
    if (displayedText && isTypewriterEnabled && onContentUpdate) {
      const currentText = displayedText;
      const lastText = lastTextRef.current;
      
      // Count lines (both explicit newlines and estimate natural wraps)
      const currentLineCount = (currentText.match(/\n/g) || []).length + 1;
      const lastLineCount = lastLineCountRef.current;
      
      // Check if a newline character was added (new line detected)
      const hasNewLine = currentText.length > lastText.length && 
                        currentText.slice(lastText.length).includes('\n');
      
      // Scroll on every character update to catch line wraps, but prioritize newlines
      if (currentText.length > lastText.length) {
        // Clear existing timeout
        if (scrollTimeoutRef.current) {
          clearTimeout(scrollTimeoutRef.current);
        }
        
        // Scroll immediately for newlines, or with minimal delay for regular updates
        const delay = hasNewLine || currentLineCount > lastLineCount ? 10 : 20;
        
        scrollTimeoutRef.current = setTimeout(() => {
          onContentUpdate();
          lastTextRef.current = currentText;
          lastLineCountRef.current = currentLineCount;
        }, delay);
      }
      
      return () => {
        if (scrollTimeoutRef.current) {
          clearTimeout(scrollTimeoutRef.current);
        }
      };
    }
  }, [displayedText, isTypewriterEnabled, onContentUpdate]);

  // Also scroll when answerText changes (for non-typewriter content)
  useEffect(() => {
    if (cleanTextContent && !isTypewriterEnabled && onContentUpdate) {
      const timeoutId = setTimeout(() => {
        onContentUpdate();
      }, 100);
      return () => clearTimeout(timeoutId);
    }
  }, [cleanTextContent, isTypewriterEnabled, onContentUpdate]);

  // Scroll when typing completes
  useEffect(() => {
    if (!isTyping && isTypewriterEnabled && displayedText && onContentUpdate) {
      // Final scroll when typing is complete
      const timeoutId = setTimeout(() => {
        onContentUpdate();
      }, 100);
      return () => clearTimeout(timeoutId);
    }
  }, [isTyping, isTypewriterEnabled, displayedText, onContentUpdate]);

  // Notify parent when typing state changes
  useEffect(() => {
    if (onTypingChange) {
      onTypingChange(isTyping && isTypewriterEnabled);
    }
  }, [isTyping, isTypewriterEnabled, onTypingChange]);

  const handleThumbsUp = () => {
    if (messageId != null && !ratingSubmitted) {
      setSelectedReaction(1);
      setRatingSubmitted(true);
      setFeedbackSelection(null);
      setFeedbackOtherText('');
      onRating?.(messageId, 1);
    }
  };

  const handleThumbsDown = () => {
    if (messageId != null && !ratingSubmitted) {
      setSelectedReaction(0);
      setRatingSubmitted(true);
      onRating?.(messageId, 0);
    }
  };

  const handleFeedbackClick = (value) => {
    setFeedbackSelection(value);
    if (value !== 'other') {
      setFeedbackOtherText('');
    }
    if (value !== 'other' && messageId != null) {
      const t = uiText[language] || uiText.en;
      const commentMap = {
        'factually-incorrect': t.factuallyIncorrect,
        'generic-response': t.genericResponse,
        refused: t.refusedToAnswer,
      };
      onRating?.(messageId, 0, commentMap[value] || value);
      setFeedbackSubmitted(true);
    }
  };

  const handleOtherSubmit = () => {
    const trimmed = feedbackOtherText.trim();
    if (!trimmed || messageId == null) return;
    onRating?.(messageId, 0, trimmed);
    setFeedbackSubmitted(true);
  };

  const handleActionClick = (actionType) => {
    if (disableActions || !onActionButton) return;
    onActionButton(actionType);
  };

  const stripHtml = (html) => {
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || '';
  };

  const getFemaleVoice = () => {
    const femaleNames = ['Samantha', 'Zira', 'Google US English', 'Victoria', 'Karen', 'Moira', 'Tessa', 'Fiona'];
    const pick = (voices) =>
      voices.find(v => v.lang.startsWith('en') && femaleNames.some(n => v.name.includes(n))) || null;
    return new Promise(resolve => {
      const voices = window.speechSynthesis.getVoices();
      if (voices.length) resolve(pick(voices));
      else window.speechSynthesis.onvoiceschanged = () => resolve(pick(window.speechSynthesis.getVoices()));
    });
  };

  const handleSpeak = () => {
    if (!window.speechSynthesis) return;
    if (isSpeaking) {
      window.speechSynthesis.cancel();
      setIsSpeaking(false);
      return;
    }
    const rawText = typeof answerText === 'string' ? answerText : cleanTextContent;
    const plainText = stripHtml(rawText).replace(/undefined/g, '').trim();
    if (!plainText) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(plainText);
    utterance.lang = language === 'es' ? 'es-ES' : 'en-US';
    utterance.rate = 1;
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    setIsSpeaking(true);
    getFemaleVoice().then(voice => {
      if (voice) utterance.voice = voice;
      window.speechSynthesis.speak(utterance);
    });
  };

  React.useEffect(() => {
    return () => {
      if (isSpeaking) window.speechSynthesis.cancel();
    };
  }, [isSpeaking]);

  const linkifyUrls = (text) => {
    const urlRegex = /(?<!['"=])(https?:\/\/[^\s<>"']+)/g;
    return text.replace(urlRegex, (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`);
  };

  // Parse HTML content for typewriter effect
  const createMarkup = () => {
    if (typeof answerText === 'string') {
      let cleanText = isTypewriterEnabled ? (displayedText || '&nbsp;') : (cleanTextContent || '&nbsp;');
      cleanText = cleanText.replace(/undefined/g, '');
      cleanText = linkifyUrls(cleanText);
      return { __html: cleanText };
    }
    return null;
  };

  const t = uiText[language] || uiText.en;
  const buttonLabels = t.actionLabels;

  return (
    <div className="character-chat-row">
      {/* Blue Character */}
      <div className="blue-character">
        <img alt="" src={imgBlueCharacter} />
      </div>

      {/* Content Card 1 - System Chat Bubble */}
      <div className="content-card-1" style={{ minHeight: '150px' }}>
        {/* Loading Animation - Show when loading and no content */}
        {isLoading && (!cleanTextContent || cleanTextContent.trim() === '') ? (
          <div className="loading-message-inline">
            <div className="loader"></div>
            <span>{t.loadingMessage}</span>
          </div>
        ) : (
          /* Answer Text */
          <div className="answer-text">
            {typeof answerText === 'string' ? (
              <p dangerouslySetInnerHTML={createMarkup()} />
            ) : (
              <p>{answerText}</p>
            )}
          </div>
        )}

        {/* Thumbs and Action Buttons Row - disabled while response is loading or typing */}
        {showActions && messageId != null && (
          <div className="actions-row">
            {/* Thumbs Up and Down Buttons */}
            {messageId != null && (
              <div className="thumbs-container">
                <div 
                  className={`thumbs-up ${selectedReaction === 1 ? 'selected' : ''}`}
                  onClick={handleThumbsUp}
                  style={{ cursor: ratingSubmitted ? 'default' : 'pointer', opacity: ratingSubmitted && selectedReaction !== 1 ? 0.5 : 1 }}
                >
                  <img alt="Thumbs up" src={imgThumbsUp} />
                </div>
                <div 
                  className={`thumbs-down ${selectedReaction === 0 ? 'selected' : ''}`}
                  onClick={handleThumbsDown}
                  style={{ cursor: ratingSubmitted ? 'default' : 'pointer', opacity: ratingSubmitted && selectedReaction !== 0 ? 0.5 : 1 }}
                >
                  <img alt="Thumbs down" src={imgThumbsDown} />
                </div>
              </div>
            )}

            {/* Speaker Button */}
            <button
              type="button"
              className={`tts-button ${isSpeaking ? 'tts-button--speaking' : ''}`}
              onClick={handleSpeak}
              aria-label={isSpeaking ? 'Stop reading' : 'Read aloud'}
              disabled={disableActions}
            >
              <i className={`fas ${isSpeaking ? 'fa-stop' : 'fa-volume-up'}`}></i>
            </button>

            {/* Action Buttons - disabled until response has completed */}
            <div className="buttons-container">
              <button 
                className="button-tell-me-more"
                onClick={() => handleActionClick('tell-me-more')}
                disabled={disableActions}
                aria-disabled={disableActions}
              >
                <span className="button-text-tell-me-more">{buttonLabels['tell-me-more']}</span>
              </button>
              <button 
                className="button-next-steps"
                onClick={() => handleActionClick('next-steps')}
                disabled={disableActions}
                aria-disabled={disableActions}
              >
                <span className="button-text-next-steps">{buttonLabels['next-steps']}</span>
              </button>
              <button 
                className="button-sources"
                onClick={() => handleActionClick('sources')}
                disabled={disableActions}
                aria-disabled={disableActions}
              >
                <span className="button-text-sources">{buttonLabels['sources']}</span>
              </button>
            </div>
          </div>
        )}
        {selectedReaction === 0 && (
          <div className="feedback-card-row" role="region" aria-label="Feedback">
            {feedbackSubmitted ? (
              <>
                <div className="feedback-card-icon">
                  <img
                    className="feedback-icon-image feedback-icon-image-thankyou"
                    src="/static/images/WaterDrop5.png"
                    alt=""
                    aria-hidden="true"
                  />
                </div>
                <div className="feedback-card feedback-thankyou">
                  {t.feedbackThankYou}
                </div>
              </>
            ) : (
              <>
                <div className="feedback-card-icon">
                  <img
                    className="feedback-icon-image"
                    src="/static/images/WaterDrop3.png"
                    alt=""
                    aria-hidden="true"
                  />
                </div>
                <div className="feedback-card">
                  <div className="feedback-card-title">
                    {t.feedbackTitle}
                  </div>
                  <div className="feedback-card-body">
                    <button
                      type="button"
                      className={`feedback-button ${feedbackSelection === 'factually-incorrect' ? 'selected' : ''}`}
                      onClick={() => handleFeedbackClick('factually-incorrect')}
                    >
                      {t.factuallyIncorrect}
                    </button>
                    <button
                      type="button"
                      className={`feedback-button ${feedbackSelection === 'generic-response' ? 'selected' : ''}`}
                      onClick={() => handleFeedbackClick('generic-response')}
                    >
                      {t.genericResponse}
                    </button>
                    <button
                      type="button"
                      className={`feedback-button ${feedbackSelection === 'refused' ? 'selected' : ''}`}
                      onClick={() => handleFeedbackClick('refused')}
                    >
                      {t.refusedToAnswer}
                    </button>
                    <button
                      type="button"
                      className={`feedback-button feedback-other-button ${feedbackSelection === 'other' ? 'selected' : ''}`}
                      onClick={() => handleFeedbackClick('other')}
                    >
                      {t.other}
                    </button>
                    {feedbackSelection === 'other' && (
                      <div className="feedback-other-wrapper">
                        <textarea
                          className="feedback-other-input"
                          rows={3}
                          placeholder={t.tellUsMore}
                          value={feedbackOtherText}
                          onChange={(event) => setFeedbackOtherText(event.target.value)}
                        />
                        <button
                          type="button"
                          className="feedback-submit-button"
                          onClick={handleOtherSubmit}
                          disabled={!feedbackOtherText.trim()}
                        >
                          {t.submit}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        )}
        {/* Chat Bubble Tail - Polygon 1 */}
        <div className="polygon-1-container">
          <div className="polygon-1-wrapper">
            <div className="polygon-1">
              <img alt="" src={imgPolygon1} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

