import React, { useState, useEffect } from 'react';
import { ThumbsUp, ThumbsDown } from 'lucide-react';
import { useTypewriter } from '../../hooks/useTypewriter';
import blueCharacter from '../../assets/blue-character.png';

export default function ChatBubble({
  answerText,
  messageId,
  showActions,
  disableActions,
  onRating,
  isLoading,
  disableTypewriter,
  language,
  onContentUpdate,
  onTypingChange,
}) {
  const [ratingSubmitted, setRatingSubmitted] = useState(false);
  const [selectedReaction, setSelectedReaction] = useState(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedbackSelection, setFeedbackSelection] = useState(null);
  const [feedbackText, setFeedbackText] = useState('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [shouldStartTyping, setShouldStartTyping] = useState(false);

  const textContent = typeof answerText === 'string' ? answerText : '';

  useEffect(() => {
    if (textContent && !disableTypewriter) {
      const timer = setTimeout(() => setShouldStartTyping(true), 100);
      return () => clearTimeout(timer);
    }
  }, [textContent, disableTypewriter]);

  const { displayedText, isTyping } = useTypewriter(
    textContent, 20, !disableTypewriter && shouldStartTyping
  );

  useEffect(() => {
    if (onTypingChange) onTypingChange(isTyping);
  }, [isTyping, onTypingChange]);

  useEffect(() => {
    if (onContentUpdate && displayedText) onContentUpdate();
  }, [displayedText]);

  const handleThumbsUp = () => {
    if (ratingSubmitted || !messageId) return;
    setSelectedReaction(1);
    setRatingSubmitted(true);
    onRating(messageId, 1);
  };

  const handleThumbsDown = () => {
    if (ratingSubmitted || !messageId) return;
    setSelectedReaction(0);
    setRatingSubmitted(true);
    setShowFeedback(true);
    onRating(messageId, 0);
  };

  const handleFeedbackSubmit = () => {
    const comment = feedbackSelection === 'other' ? feedbackText : feedbackSelection;
    if (comment && messageId) onRating(messageId, null, comment);
    setFeedbackSubmitted(true);
    setShowFeedback(false);
  };

  const renderedContent = disableTypewriter ? textContent : displayedText;

  const feedbackLabels = language === 'es'
    ? { title: '\u00bfQu\u00e9 no te gust\u00f3?', fi: 'Incorrecto', gr: 'Respuesta gen\u00e9rica', ra: 'Se neg\u00f3 a responder', other: 'Otro', more: 'Cu\u00e9ntanos m\u00e1s...', submit: 'Enviar', thanks: 'Gracias por tus comentarios.' }
    : { title: 'What did you not like?', fi: 'Factually incorrect', gr: 'Generic response', ra: 'Refused to answer', other: 'Other', more: 'Tell us more...', submit: 'Submit', thanks: 'Thanks for your feedback.' };

  if (isLoading) {
    return (
      <div className="bubble bubble--bot">
        <div className="bubble--bot__avatar"><img src={blueCharacter} alt="Blue" /></div>
        <div className="typing-indicator__dots">
          <span className="typing-indicator__dot" />
          <span className="typing-indicator__dot" />
          <span className="typing-indicator__dot" />
        </div>
      </div>
    );
  }

  return (
    <div className="bubble bubble--bot" role="listitem">
      <div className="bubble--bot__avatar"><img src={blueCharacter} alt="Blue" /></div>
      <div className="bubble--bot__content">
        <div className="bubble--bot__text" dangerouslySetInnerHTML={{ __html: renderedContent }} />

        {messageId != null && !isTyping && !isLoading && (
          <div className="reactions-bar">
            {!ratingSubmitted ? (
              <>
                <button className="reaction-btn" onClick={handleThumbsUp} title="I like this"><ThumbsUp size={16} /></button>
                <button className="reaction-btn" onClick={handleThumbsDown} title="Could be better"><ThumbsDown size={16} /></button>
              </>
            ) : (
              <button className="reaction-btn selected" disabled>
                {selectedReaction === 1 ? <ThumbsUp size={16} /> : null}
                {selectedReaction === 0 ? <ThumbsDown size={16} /> : null}
              </button>
            )}
          </div>
        )}

        {showFeedback && !feedbackSubmitted && (
          <div className="feedback-form">
            <p className="feedback-form__title">{feedbackLabels.title}</p>
            <div className="feedback-options">
              {[
                { key: 'fi', label: feedbackLabels.fi },
                { key: 'gr', label: feedbackLabels.gr },
                { key: 'ra', label: feedbackLabels.ra },
                { key: 'other', label: feedbackLabels.other },
              ].map(({ key, label }) => (
                <button
                  key={key}
                  className={`feedback-opt-btn${feedbackSelection === key ? ' selected' : ''}`}
                  onClick={() => setFeedbackSelection(key)}
                >{label}</button>
              ))}
            </div>
            {feedbackSelection === 'other' && (
              <textarea
                className="feedback-textarea"
                value={feedbackText}
                onChange={(e) => setFeedbackText(e.target.value)}
                placeholder={feedbackLabels.more}
              />
            )}
            <button className="btn-primary-wb btn-sm" onClick={handleFeedbackSubmit}>{feedbackLabels.submit}</button>
          </div>
        )}

        {feedbackSubmitted && (
          <div className="ty-feedback"><span className="ty-feedback__text">{feedbackLabels.thanks}</span></div>
        )}
      </div>
    </div>
  );
}
