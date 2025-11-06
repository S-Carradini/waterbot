import React, { useState, useRef, useEffect } from 'react';

export default function InputWrapper({ onSendMessage, isLoading }) {
  const [inputValue, setInputValue] = useState('');
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef(null);
  const micAnimationRef = useRef(null);

  // Initialize speech recognition
  useEffect(() => {
    // Support for Chrome, Edge, Safari (WebKit)
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true; // Enable interim results for better UX
      recognition.lang = 'en-US';
      
      // Set max alternatives for better accuracy
      if (recognition.maxAlternatives !== undefined) {
        recognition.maxAlternatives = 1;
      }

      let isCurrentlyListening = false;

      recognition.onresult = (event) => {
        let transcript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) {
            transcript += result[0].transcript + ' ';
          } else {
            // Show interim results in real-time
            transcript += result[0].transcript;
          }
        }
        setInputValue(transcript.trim());
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

    // Initialize Lottie animation if available
    const initLottie = () => {
      if (window.lottie && micAnimationRef.current) {
        try {
          const animation = window.lottie.loadAnimation({
            container: micAnimationRef.current,
            renderer: 'svg',
            loop: true,
            autoplay: false,
            path: '/static/animation/mic.json',
            rendererSettings: {
              preserveAspectRatio: 'xMidYMid slice',
            },
          });
          if (micAnimationRef.current) {
            micAnimationRef.current.animation = animation;
          }
        } catch (e) {
          console.warn('Could not load mic animation:', e);
        }
      }
    };

    // Wait for Lottie to load
    if (window.lottie) {
      initLottie();
    } else {
      // Wait for script to load
      const checkLottie = setInterval(() => {
        if (window.lottie) {
          clearInterval(checkLottie);
          initLottie();
        }
      }, 100);
      
      return () => {
        clearInterval(checkLottie);
        if (recognitionRef.current) {
          recognitionRef.current.stop();
        }
      };
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, []);

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
    if (!recognitionRef.current) {
      // Check browser and provide helpful message
      const isFirefox = navigator.userAgent.toLowerCase().indexOf('firefox') > -1;
      const message = isFirefox 
        ? 'Speech recognition is not supported in Firefox. Please use Chrome, Edge, Safari, or Brave.'
        : 'Speech recognition is not supported in this browser. Please use a modern browser like Chrome, Edge, Safari, or Brave.';
      alert(message);
      console.warn('Web Speech API not supported in this browser.');
      return;
    }

    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  };

  const startListening = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.start();
        if (recognitionRef.current.setIsCurrentlyListening) {
          recognitionRef.current.setIsCurrentlyListening(true);
        }
        setIsListening(true);
        
        // Show Lottie animation if available
        if (micAnimationRef.current?.animation) {
          micAnimationRef.current.style.display = 'block';
          micAnimationRef.current.animation.play();
        }
      } catch (e) {
        console.error('Error starting recognition:', e);
        setIsListening(false);
      }
    }
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
        if (recognitionRef.current.setIsCurrentlyListening) {
          recognitionRef.current.setIsCurrentlyListening(false);
        }
        setIsListening(false);
        
        // Hide Lottie animation if available
        if (micAnimationRef.current?.animation) {
          micAnimationRef.current.style.display = 'none';
          micAnimationRef.current.animation.stop();
        }
      } catch (e) {
        console.error('Error stopping recognition:', e);
        setIsListening(false);
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
            placeholder="Type your question here"
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
      {/* Mic Icon Button */}
      <div style={{ position: 'relative' }}>
        <button 
          type="button" 
          className={`mic-icon-button ${isListening ? 'recording' : ''}`}
          onClick={toggleListening}
          disabled={!recognitionRef.current}
        >
          <i 
            className="fas fa-microphone" 
            style={{ 
              display: 'block',
              color: isListening ? 'white' : '#8c1d40',
              position: 'relative',
              zIndex: 2
            }}
          ></i>
          {isListening && (
            <div className="recording-indicator">
              <div className="recording-pulse"></div>
            </div>
          )}
          <div 
            ref={micAnimationRef}
            className="mic-animation-container"
            style={{ display: isListening ? 'block' : 'none' }}
          ></div>
        </button>
      </div>
    </div>
  );
}

