import React, { useState, useRef, useEffect } from 'react';
import '../App.css';
import Header from './Header';
import ChatBubble from './ChatBubble';
import InputWrapper from './InputWrapper';
import MobileOnlyGuard from './MobileOnlyGuard';
import { sendChatMessage, getDetailedResponse, getActionItems, getSources, submitRating, translateMessages } from '../services/api';
import imgPolygon2 from '../assets/polygon-2.png';
import { useMobileDetection } from '../hooks/useMobileDetection';
import { uiText, getActionLabel } from '../i18n/uiText';

const buildDefaultMessage = (language) => ({
  type: 'intro',
  content: (uiText[language] || uiText.en).defaultAnswerText,
  messageId: null,
  showActions: false,
  disableTypewriter: true,
});

const createBotPlaceholder = () => ({
  type: 'bot',
  content: '',
  messageId: null,
  showActions: false,
  disableTypewriter: false,
});

const GREETING_REGEX = /\b(hi|hello|hey|hola|howdy|sup|yo|hiya|thanks|thank you|thx)\b/i;

const isSourcesAllowed = (messages) => {
  const lastUser = [...messages].reverse().find(m => m.type === 'user');
  if (!lastUser) return false;
  const text = String(lastUser.content || '').trim();
  if (!text) return false;
  if (text.length <= 6) return false;
  return !GREETING_REGEX.test(text);
};

export default function MobileChatbot() {
  const isMobile = useMobileDetection();
  const [language, setLanguage] = useState('en');
  const [messages, setMessages] = useState([buildDefaultMessage('en')]);
  const [isLoading, setIsLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const chatColumnRef = useRef(null);
  const inputWrapperRef = useRef(null);

  // Redirect to desktop version if not on mobile
  useEffect(() => {
    if (!isMobile && window.innerWidth > 768) {
      // Optionally redirect to desktop version
      // window.location.href = '/waterbot';
      console.log('Desktop detected - consider redirecting to desktop version');
    }
  }, [isMobile]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (chatColumnRef.current) {
      requestAnimationFrame(() => {
        if (chatColumnRef.current) {
          chatColumnRef.current.scrollTo({
            top: chatColumnRef.current.scrollHeight,
            behavior: 'smooth'
          });
        }
      });
    }
  }, [messages, isLoading]);

  const scrollToBottom = () => {
    if (chatColumnRef.current) {
      setTimeout(() => {
        if (chatColumnRef.current) {
          chatColumnRef.current.scrollTo({
            top: chatColumnRef.current.scrollHeight,
            behavior: 'smooth'
          });
        }
      }, 50);
    }
  };

  const handleSendMessage = async (userQuery) => {
    if (!userQuery.trim()) return;

    setMessages(prev => [
      ...prev,
      { type: 'user', content: userQuery },
      createBotPlaceholder(),
    ]);
    
    setIsLoading(true);

    try {
      const response = await sendChatMessage(userQuery, language);
      
      setIsLoading(false);
      setMessages(prev => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (updated[lastIndex]?.type === 'bot') {
          updated[lastIndex] = {
            type: 'bot',
            content: response.resp,
            messageId: response.msgID,
            showActions: true,
            disableTypewriter: false,
          };
        }
        return updated;
      });
    } catch (error) {
      console.error('Error sending message:', error);
      setIsLoading(false);
      setMessages(prev => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (updated[lastIndex]?.type === 'bot') {
          updated[lastIndex] = {
            type: 'bot',
            content: (uiText[language] || uiText.en).errorGeneric,
            messageId: null,
            showActions: false,
            disableTypewriter: false,
          };
        }
        return updated;
      });
    }
  };

  const handleActionButton = async (actionType) => {
    const t = uiText[language] || uiText.en;
    const buttonLabel = getActionLabel(language, actionType);

    if (actionType === 'sources' && !isSourcesAllowed(messages)) {
      setMessages(prev => [
        ...prev,
        { type: 'user', content: buttonLabel, isActionLabel: true, actionType },
        { type: 'bot', content: t.sourcesWarning, messageId: null, showActions: false, disableTypewriter: true },
      ]);
      return;
    }
    
    setMessages(prev => [
      ...prev,
      { type: 'user', content: buttonLabel, isActionLabel: true, actionType },
      createBotPlaceholder(),
    ]);
    
    setIsLoading(true);
    
    try {
      let response;
      switch (actionType) {
        case 'tell-me-more':
          response = await getDetailedResponse(language);
          break;
        case 'next-steps':
          response = await getActionItems(language);
          break;
        case 'sources':
          response = await getSources(language);
          break;
        default:
          setIsLoading(false);
          return;
      }

      setIsLoading(false);
      setMessages(prev => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (updated[lastIndex]?.type === 'bot') {
          updated[lastIndex] = {
            type: 'bot',
            content: response.resp,
            messageId: response.msgID,
            showActions: true,
            disableTypewriter: false,
          };
        }
        return updated;
      });
    } catch (error) {
      console.error('Error with action button:', error);
      setIsLoading(false);
      setMessages(prev => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (updated[lastIndex]?.type === 'bot') {
          updated[lastIndex] = {
            type: 'bot',
            content: (uiText[language] || uiText.en).errorGeneric,
            messageId: null,
            showActions: false,
            disableTypewriter: false,
          };
        }
        return updated;
      });
    }
  };

  const handleRating = async (messageId, reaction, userComment = null) => {
    try {
      await submitRating(messageId, reaction, userComment);
    } catch (error) {
      console.error('Error submitting rating:', error);
    }
  };

  const handleLanguageChange = async (nextLanguage) => {
    if (nextLanguage === language) return;
    const filtered = messages.filter(msg => msg.type !== 'intro');
    const botMessagesToTranslate = filtered.filter(
      m => m.type === 'bot' && m.content && String(m.content).trim()
    );
    const textsToTranslate = botMessagesToTranslate.map(m => m.content);

    // Re-label action-button user messages for new language
    const updatedFiltered = filtered.map(msg => {
      if (msg.type === 'user' && msg.isActionLabel && msg.actionType) {
        return { ...msg, content: getActionLabel(nextLanguage, msg.actionType) };
      }
      return msg;
    });

    // Switch language and static UI immediately (optimistic update)
    setLanguage(nextLanguage);
    setMessages([buildDefaultMessage(nextLanguage), ...updatedFiltered]);

    if (textsToTranslate.length === 0) return;

    // Translate bot messages in background and update when done
    try {
      const { translations } = await translateMessages(textsToTranslate, nextLanguage);
      setMessages(prev => {
        const intro = prev.find(m => m.type === 'intro');
        const rest = prev.filter(m => m.type !== 'intro');
        let idx = 0;
        const withTranslatedBots = rest.map(msg => {
          if (msg.type === 'bot' && msg.content && String(msg.content).trim() && translations[idx] != null) {
            return { ...msg, content: translations[idx++] };
          }
          return msg;
        });
        return intro ? [intro, ...withTranslatedBots] : withTranslatedBots;
      });
    } catch (err) {
      console.error('Translation failed, bot messages remain in previous language:', err);
    }
  };

  const handleMicClick = () => {
    if (inputWrapperRef.current) {
      inputWrapperRef.current.click();
    }
  };

  return (
    <MobileOnlyGuard>
      <div className="desktop-container mobile-chatbot-container">
        <Header onMicClick={handleMicClick} isListening={isListening} language={language} />

      {/* Chat Column Container */}
      <div className="chat-column mobile-chat-column" ref={chatColumnRef}>
        {messages.map((message, index) => {
          if (message.type === 'bot' || message.type === 'intro') {
            return (
              <ChatBubble
                key={index}
                answerText={message.content}
                messageId={message.messageId}
                showActions={message.showActions}
                onActionButton={handleActionButton}
                onRating={handleRating}
                isLoading={isLoading && index === messages.length - 1 && message.type === 'bot' && (!message.content || (typeof message.content === 'string' && message.content.trim() === ''))}
                disableTypewriter={message.disableTypewriter}
                language={language}
                onContentUpdate={scrollToBottom}
                onTypingChange={index === messages.length - 1 ? setIsTyping : undefined}
              />
            );
          } else if (message.type === 'user') {
            return (
              <div key={index} className="user-query mobile-user-query">
                <div className="question-text">
                  <p>{message.content}</p>
                </div>
                <div className="polygon-2-container">
                  <div className="polygon-2-wrapper">
                    <div className="polygon-2">
                      <img alt="" src={imgPolygon2} />
                    </div>
                  </div>
                </div>
              </div>
            );
          }
          return null;
        })}
      </div>

      <InputWrapper 
        ref={inputWrapperRef}
        onSendMessage={handleSendMessage} 
        isLoading={isLoading || isTyping}
        language={language}
        onLanguageChange={handleLanguageChange}
        onListeningChange={setIsListening}
      />
      </div>
    </MobileOnlyGuard>
  );
}

