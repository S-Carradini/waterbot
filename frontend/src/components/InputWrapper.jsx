import React, { useState, useRef, useEffect } from 'react';
import RecordingModal from './RecordingModal';
import { uiText } from '../i18n/uiText';

const speechLangCode = (lang) => (lang === 'es' ? 'es-ES' : 'en-US');
const SILENCE_TIMEOUT = 2000; // Stop recording after 2 seconds of silence (adjust as needed)

const InputWrapper = React.forwardRef(function InputWrapper({ onSendMessage, isLoading, language = 'en', onLanguageChange, onListeningChange }, ref) {
  const [inputValue, setInputValue] = useState('');
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef(null);
  const languageRef = useRef(language);
  const finalTranscriptRef = useRef(''); // Store accumulated final transcripts
  const silenceTimeoutRef = useRef(null); // Timeout for auto-stop on silence

  // Expose toggleListening function to parent via ref
  React.useImperativeHandle(ref, () => ({
    click: toggleListening,
  }));

  // Notify parent of listening state changes
  useEffect(() => {
    if (onListeningChange) {
      onListeningChange(isListening);
    }
  }, [isListening, onListeningChange]);

  // Initialize speech recognition
  useEffect(() => {
    // Support for Chrome, Edge, Safari (WebKit)
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true; // Enable interim results for better UX
      recognition.lang = speechLangCode(languageRef.current);
      
      // Set max alternatives for better accuracy
      if (recognition.maxAlternatives !== undefined) {
        recognition.maxAlternatives = 1;
      }

      let isCurrentlyListening = false;

      recognition.onresult = (event) => {
        let interimTranscript = '';
        let hasNewSpeech = false;
        
        // Process all results since last event
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) {
            // Add final results to accumulated transcript
            finalTranscriptRef.current += result[0].transcript + ' ';
            hasNewSpeech = true;
          } else {
            // Show interim results in real-time
            interimTranscript += result[0].transcript;
            hasNewSpeech = true;
          }
        }
        
        // Combine accumulated final text with current interim text
        const fullTranscript = finalTranscriptRef.current + interimTranscript;
        setInputValue(fullTranscript.trim());

        // Reset silence timeout when speech is detected
        if (hasNewSpeech && isCurrentlyListening) {
          // Clear existing timeout
          if (silenceTimeoutRef.current) {
            clearTimeout(silenceTimeoutRef.current);
          }
          
          // Set new timeout to auto-stop after silence
          silenceTimeoutRef.current = setTimeout(() => {
            console.log('Auto-stopping recording due to silence');
            if (isCurrentlyListening && recognitionRef.current) {
              try {
                recognitionRef.current.stop();
                if (recognitionRef.current.setIsCurrentlyListening) {
                  recognitionRef.current.setIsCurrentlyListening(false);
                }
                setIsListening(false);

                // Auto-submit the transcribed text if there's any
                // Use a small delay to ensure state is updated
                setTimeout(() => {
                  const currentTranscript = finalTranscriptRef.current.trim();
                  if (currentTranscript) {
                    console.log('Auto-submitting transcribed text:', currentTranscript);
                    onSendMessage(currentTranscript);
                    setInputValue('');
                    finalTranscriptRef.current = '';
                  }
                }, 100);
              } catch (e) {
                console.error('Error auto-stopping recognition:', e);
                setIsListening(false);
              }
            }
          }, SILENCE_TIMEOUT);
        }
      };

      recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        isCurrentlyListening = false;
        setIsListening(false);
        if (recognitionRef.current) {
          recognitionRef.current.stop();
        }
      };

      recognition.onend = () => {
        if (isCurrentlyListening) {
          try {
            recognition.start();
          } catch (e) {
            // If start fails, reset listening state
            console.warn('Recognition restart failed:', e);
            isCurrentlyListening = false;
            setIsListening(false);
          }
        }
      };
      
      recognition.onstart = () => {
        console.log('Speech recognition started');
      };

      recognitionRef.current = recognition;
      recognitionRef.current.isCurrentlyListening = () => isCurrentlyListening;
      recognitionRef.current.setIsCurrentlyListening = (value) => {
        isCurrentlyListening = value;
      };
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };

    return () => {
      // Cleanup: clear timeout and stop recognition
      if (silenceTimeoutRef.current) {
        clearTimeout(silenceTimeoutRef.current);
      }
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, []);

  useEffect(() => {
    languageRef.current = language;
    if (recognitionRef.current) {
      recognitionRef.current.lang = speechLangCode(language);
    }
  }, [language]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (inputValue.trim() && !isLoading) {
      onSendMessage(inputValue);
      setInputValue('');
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const toggleListening = () => {
    console.log('Mic button clicked, isListening:', isListening, 'recognitionRef.current:', recognitionRef.current);
    if (isListening) {
      stopListening();
    } else {
      // Show modal even if speech recognition isn't available
      // The modal will display the animation
      if (!recognitionRef.current) {
        // Still show the modal for visual feedback
        console.log('Speech recognition not available, showing modal anyway');
        setIsListening(true);
        return;
      }
      startListening();
    }
  };

  const startListening = () => {
    // Clear any existing silence timeout
    if (silenceTimeoutRef.current) {
      clearTimeout(silenceTimeoutRef.current);
      silenceTimeoutRef.current = null;
    }

    if (recognitionRef.current) {
      try {
        // Reset transcript when starting new recording
        setInputValue('');
        finalTranscriptRef.current = ''; // Reset accumulated transcript
        recognitionRef.current.start();
        if (recognitionRef.current.setIsCurrentlyListening) {
          recognitionRef.current.setIsCurrentlyListening(true);
        }
        setIsListening(true);
      } catch (e) {
        console.error('Error starting recognition:', e);
        setIsListening(false);
      }
    }
  };

  const stopListening = () => {
    // Clear silence timeout
    if (silenceTimeoutRef.current) {
      clearTimeout(silenceTimeoutRef.current);
      silenceTimeoutRef.current = null;
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
        if (recognitionRef.current.setIsCurrentlyListening) {
          recognitionRef.current.setIsCurrentlyListening(false);
        }
        setIsListening(false);

        // Auto-submit the transcribed text if there's any
        if (inputValue.trim() && !isLoading) {
          console.log('Auto-submitting transcribed text:', inputValue);
          onSendMessage(inputValue.trim());
          setInputValue('');
          finalTranscriptRef.current = ''; // Reset accumulated transcript
        }
      } catch (e) {
        console.error('Error stopping recognition:', e);
        setIsListening(false);
        
        // Still try to submit if there's text
        if (inputValue.trim() && !isLoading) {
          onSendMessage(inputValue.trim());
          setInputValue('');
          finalTranscriptRef.current = '';
        }
      }
    } else {
      // If recognition wasn't available but modal was shown, still submit if there's text
      setIsListening(false);
      if (inputValue.trim() && !isLoading) {
        onSendMessage(inputValue.trim());
        setInputValue('');
        finalTranscriptRef.current = '';
      }
    }
  };

  return (
    <div className="input-wrapper">
      {/* Text Input Box */}
      <div className="input-container">
        <form onSubmit={handleSubmit} style={{ display: 'flex', alignItems: 'center', width: '100%', height: '100%' }}>
          <input
            type="text"
            className="text-input"
            placeholder={(uiText[language] || uiText.en).inputPlaceholder}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={isLoading}
            autoComplete="off"
          />
          <button 
            type="submit" 
            className="paper-plane-icon-button"
            disabled={isLoading || !inputValue.trim()}
          >
            <i className="fas fa-paper-plane"></i>
          </button>
        </form>
      </div>
      {/* Recording Modal */}
      <RecordingModal 
        isVisible={isListening} 
        onClose={stopListening}
        transcript={inputValue}
      />
      {/* Language Toggle */}
      {onLanguageChange && (
        <button 
          type="button"
          className="language-toggle-switch"
          onClick={() => onLanguageChange(language === 'en' ? 'es' : 'en')}
          disabled={isLoading}
        >
          <div className="language-toggle-background"></div>
          <div className={`language-toggle-slider ${language === 'en' ? 'left' : 'right'}`}></div>
          <span className={`language-toggle-text language-toggle-en ${language === 'en' ? 'active' : ''}`}>
            EN
          </span>
          <span className={`language-toggle-text language-toggle-es ${language === 'es' ? 'active' : ''}`}>
            ES
          </span>
        </button>
      )}
    </div>
  );
});

export default InputWrapper;

