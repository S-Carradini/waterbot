import { useState, useEffect, useRef } from 'react';

/**
 * Custom hook for typewriter effect
 * @param {string} text - The text to type out
 * @param {number} speed - Speed in milliseconds between characters (default: 20)
 * @param {boolean} start - Whether to start typing immediately
 */
export function useTypewriter(text, speed = 20, start = true) {
  const [displayedText, setDisplayedText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const intervalRef = useRef(null);
  const partsRef = useRef([]);
  const partIndexRef = useRef(0);
  const charIndexRef = useRef(0);

  useEffect(() => {
    if (!text || !start) {
      setDisplayedText('');
      setIsTyping(false);
      return;
    }

    // Clean the text first - remove any undefined strings and ensure it's a valid string
    const cleanText = String(text || '').replace(/undefined/g, '').trim();
    
    if (!cleanText) {
      setDisplayedText('');
      setIsTyping(false);
      return;
    }
    
    // Split by HTML tags and text content
    partsRef.current = cleanText.split(/(<[^>]*>)/g).filter(Boolean);
    partIndexRef.current = 0;
    charIndexRef.current = 0;
    setDisplayedText('');
    setIsTyping(true);

    intervalRef.current = setInterval(() => {
      if (partIndexRef.current >= partsRef.current.length) {
        clearInterval(intervalRef.current);
        setIsTyping(false);
        return;
      }

      const currentPart = partsRef.current[partIndexRef.current];

      // If it's an HTML tag, add it immediately
      if (currentPart && currentPart.match(/^<[^>]*>$/)) {
        setDisplayedText(prev => prev + currentPart);
        partIndexRef.current++;
        charIndexRef.current = 0;
      } else if (currentPart) {
        // If it's text content, add character by character
        if (charIndexRef.current < currentPart.length) {
          const char = currentPart[charIndexRef.current];
          if (char !== undefined && char !== null) {
            setDisplayedText(prev => prev + char);
          }
          charIndexRef.current++;
        } else {
          // Move to next part
          partIndexRef.current++;
          charIndexRef.current = 0;
        }
      } else {
        // Skip empty or undefined parts
        partIndexRef.current++;
        charIndexRef.current = 0;
      }
    }, speed);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [text, speed, start]);

  return { displayedText, isTyping };
}

