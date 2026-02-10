import React, { useState, useRef, useEffect } from 'react';
import '../App.css';
import Header from './Header';
import ChatBubble from './ChatBubble';
import InputWrapper from './InputWrapper';
import MobileOnlyGuard from './MobileOnlyGuard';
import { sendChatMessage, getDetailedResponse, getActionItems, getSources, submitRating, translateMessages } from '../services/api';
import imgPolygon2 from '../assets/polygon-2.png';
import { useMobileDetection } from '../hooks/useMobileDetection';

const DEFAULT_ANSWER_TEXT = {
  en: `For those engaging in vigorous exercise or spending extended time outdoors, drinks with added electrolytes can help replace minerals lost through sweat.

Choosing a hydration drink depends on your activity level and personal needs, but water is always a healthy and reliable choice.

I would love to tell you more! Just click the buttons below or ask a follow-up question.`,
  es: `Para quienes realizan ejercicio intenso o pasan mucho tiempo al aire libre, las bebidas con electrolitos ayudan a reponer los minerales perdidos con el sudor.

Elegir una bebida hidratante depende de tu nivel de actividad y tus necesidades personales, pero el agua siempre es una opción saludable y confiable.

¡Me encantaría contarte más! Solo haz clic en los botones de abajo o haz una pregunta de seguimiento.`,
};

const ACTION_BUTTON_LABELS = {
  en: {
    'tell-me-more': 'Tell Me More',
    'next-steps': 'Next Steps',
    sources: 'Sources',
  },
  es: {
    'tell-me-more': 'Cuéntame más',
    'next-steps': 'Próximos pasos',
    sources: 'Fuentes',
  },
};

const buildDefaultMessage = (language) => ({
  type: 'intro',
  content: DEFAULT_ANSWER_TEXT[language],
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
            content: 'Sorry, I encountered an error. Please try again.',
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
    const actionLabels = ACTION_BUTTON_LABELS[language] || ACTION_BUTTON_LABELS.en;
    const buttonLabel = actionLabels[actionType] || actionType;
    
    setMessages(prev => [
      ...prev,
      { type: 'user', content: buttonLabel },
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
            content: 'Sorry, I encountered an error. Please try again.',
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

    if (textsToTranslate.length === 0) {
      setLanguage(nextLanguage);
      setMessages([buildDefaultMessage(nextLanguage), ...filtered]);
      return;
    }

    try {
      const { translations } = await translateMessages(textsToTranslate, nextLanguage);
      let idx = 0;
      const updatedFiltered = filtered.map(msg => {
        if (msg.type === 'bot' && msg.content && String(msg.content).trim() && translations[idx] != null) {
          return { ...msg, content: translations[idx++] };
        }
        return msg;
      });
      setLanguage(nextLanguage);
      setMessages([buildDefaultMessage(nextLanguage), ...updatedFiltered]);
    } catch (err) {
      console.error('Translation failed, switching language without translating messages:', err);
      setLanguage(nextLanguage);
      setMessages([buildDefaultMessage(nextLanguage), ...filtered]);
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
        <Header onMicClick={handleMicClick} isListening={isListening} />

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

