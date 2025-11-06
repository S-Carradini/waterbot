import React, { useState, useRef, useEffect } from 'react';
import './App.css';
import Header from './components/Header';
import ChatBubble from './components/ChatBubble';
import InputWrapper from './components/InputWrapper';
import { sendChatMessage, getDetailedResponse, getActionItems, getSources, submitRating } from './services/api';
import imgPolygon2 from './assets/polygon-2.png';

const DEFAULT_ANSWER_TEXT = (
  <>
    For those engaging in vigorous exercise or spending <br />
    extended time outdoors, drinks with added electrolytes <br />
    can help replace minerals lost through sweat.
    <br />
    <br />
    Choosing a hydration drink depends on your activity level <br />
    and personal needs, but water is always a healthy and <br />
    reliable choice.
    <br />
    <br />
    I would love to tell you more! Just click the buttons below <br />
    or ask a follow-up question.
    <br />
    <br />
  </>
);

export default function App() {
  const [messages, setMessages] = useState([
    { type: 'bot', content: DEFAULT_ANSWER_TEXT, messageId: null, showActions: true }
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const chatColumnRef = useRef(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (chatColumnRef.current) {
      // Use requestAnimationFrame to ensure DOM is updated before scrolling
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

  const handleSendMessage = async (userQuery) => {
    if (!userQuery.trim()) return;

    // Display user message in chat column
    setMessages(prev => [...prev, { type: 'user', content: userQuery }]);
    
    // Add bot response with empty content immediately to show loading
    setMessages(prev => [...prev, {
      type: 'bot',
      content: '',
      messageId: null,
      showActions: false
    }]);
    
    setIsLoading(true);

    try {
      const response = await sendChatMessage(userQuery);
      
      // Update with actual response immediately
      setIsLoading(false);
      setMessages(prev => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (updated[lastIndex]?.type === 'bot') {
          updated[lastIndex] = {
            type: 'bot',
            content: response.resp,
            messageId: response.msgID,
            showActions: true
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
            showActions: false
          };
        }
        return updated;
      });
    }
  };

  const handleActionButton = async (actionType) => {
    // Map action types to user-friendly button labels
    const actionLabels = {
      'tell-me-more': 'Tell Me More',
      'next-steps': 'Next Steps',
      'sources': 'Sources'
    };
    
    const buttonLabel = actionLabels[actionType] || actionType;
    
    // Add user query message showing which button was pressed
    setMessages(prev => [...prev, {
      type: 'user',
      content: buttonLabel
    }]);
    
    // Add bot response with empty content immediately to show loading
    setMessages(prev => [...prev, {
      type: 'bot',
      content: '',
      messageId: null,
      showActions: false
    }]);
    
    setIsLoading(true);
    
    try {
      let response;
      switch (actionType) {
        case 'tell-me-more':
          response = await getDetailedResponse();
          break;
        case 'next-steps':
          response = await getActionItems();
          break;
        case 'sources':
          response = await getSources();
          break;
        default:
          setIsLoading(false);
          return;
      }

      // Update with actual response immediately
      setIsLoading(false);
      setMessages(prev => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (updated[lastIndex]?.type === 'bot') {
          updated[lastIndex] = {
            type: 'bot',
            content: response.resp,
            messageId: response.msgID,
            showActions: true
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
            showActions: false
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

  return (
    <div className="desktop-container">
      <Header />

      {/* Chat Column Container */}
      <div className="chat-column" ref={chatColumnRef}>
        {messages.map((message, index) => {
          if (message.type === 'bot') {
            return (
              <ChatBubble
                key={index}
                answerText={message.content}
                messageId={message.messageId}
                showActions={message.showActions}
                onActionButton={handleActionButton}
                onRating={handleRating}
                isLoading={isLoading && index === messages.length - 1 && message.type === 'bot' && (!message.content || (typeof message.content === 'string' && message.content.trim() === ''))}
              />
            );
          } else if (message.type === 'user') {
            return (
              <div key={index} className="user-query">
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

      <InputWrapper onSendMessage={handleSendMessage} isLoading={isLoading} />
    </div>
  );
}

