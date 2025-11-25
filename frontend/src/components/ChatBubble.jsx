import React, { useState, useEffect } from 'react';
import imgBlueCharacter from '../assets/blue-character.png';
import imgPolygon1 from '../assets/polygon-1.png';
import imgThumbsUp from '../assets/thumbs-up.png';
import imgThumbsDown from '../assets/thumbs-down.png';
import { useTypewriter } from '../hooks/useTypewriter';

export default function ChatBubble({ answerText, messageId, showActions = true, onActionButton, onRating, isLoading = false }) {
  const [ratingSubmitted, setRatingSubmitted] = useState(false);
  const [selectedReaction, setSelectedReaction] = useState(null);
  const [shouldStartTyping, setShouldStartTyping] = useState(false);
  
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
  const { displayedText, isTyping } = useTypewriter(
    typeof answerText === 'string' ? cleanTextContent : '', 
    20, 
    shouldStartTyping
  );

  // Start typing when component mounts or answerText changes
  useEffect(() => {
    if (cleanTextContent) {
      setShouldStartTyping(false); // Reset first
      setTimeout(() => setShouldStartTyping(true), 50); // Then start after a brief delay
    }
  }, [cleanTextContent]);

  const handleThumbsUp = () => {
    if (messageId && !ratingSubmitted) {
      setSelectedReaction(1);
      setRatingSubmitted(true);
      onRating?.(messageId, 1);
    }
  };

  const handleThumbsDown = () => {
    if (messageId && !ratingSubmitted) {
      setSelectedReaction(0);
      setRatingSubmitted(true);
      onRating?.(messageId, 0);
    }
  };

  const handleActionClick = (actionType) => {
    if (onActionButton) {
      onActionButton(actionType);
    }
  };

  // Parse HTML content for typewriter effect
  const createMarkup = () => {
    if (typeof answerText === 'string') {
      // Clean up the displayed text - remove any undefined strings
      let cleanText = displayedText || '&nbsp;';
      // Remove any "undefined" strings that might have been concatenated
      cleanText = cleanText.replace(/undefined/g, '');
      // Use non-breaking space to prevent collapse when empty
      return { __html: cleanText };
    }
    return null;
  };

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
            <span>Generating response...</span>
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

        {/* Thumbs and Action Buttons Row - Only show after typing is complete */}
        {showActions && !isTyping && (
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

            {/* Action Buttons */}
            <div className="buttons-container">
              <button 
                className="button-tell-me-more"
                onClick={() => handleActionClick('tell-me-more')}
              >
                <span className="button-text-tell-me-more">Tell Me More</span>
              </button>
              <button 
                className="button-next-steps"
                onClick={() => handleActionClick('next-steps')}
              >
                <span className="button-text-next-steps">Next Steps</span>
              </button>
              <button 
                className="button-sources"
                onClick={() => handleActionClick('sources')}
              >
                <span className="button-text-sources">Sources</span>
              </button>
            </div>
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

