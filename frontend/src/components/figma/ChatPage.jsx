import React, { useState, useRef, useEffect } from 'react';
import AppHeader from './AppHeader';
import ChatBubble from './ChatBubble';
import FollowUpChips from './FollowUpChips';
import Composer from './Composer';
import ContextPanel from './ContextPanel';
import VoiceOverlay from './VoiceOverlay';
import AboutModal from './AboutModal';
import { uiText, getActionLabel } from '../../i18n/uiText';
import {
  sendChatMessage,
  getDetailedResponse,
  getActionItems,
  getSources,
  submitRating,
  translateMessages,
  downloadTranscript,
} from '../../services/api';
import '../../styles/figma.css';

const GREETING_REGEX = /\b(hi|hello|hey|hola|howdy|sup|yo|hiya|thanks|thank you|thx)\b/i;

const isSourcesAllowed = (messages) => {
  const lastUser = [...messages].reverse().find((m) => m.type === 'user');
  if (!lastUser) return false;
  const text = String(lastUser.content || '').trim();
  return text.length > 6 && !GREETING_REGEX.test(text);
};

export default function ChatPage() {
  const [language, setLanguage] = useState('en');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const chatRef = useRef(null);

  const t = uiText[language] || uiText.en;
  const msgIdRef = useRef(0);
  const nextId = () => `msg-${++msgIdRef.current}`;

  // Initialize with welcome message
  useEffect(() => {
    setMessages([
      { id: nextId(), type: 'intro', content: t.defaultAnswerText, messageId: null, showActions: false, disableTypewriter: true },
    ]);
  }, []);

  // Persist transcript for TranscriptPage
  useEffect(() => {
    try {
      const transcript = messages.map((m) => ({
        type: m.type,
        content: typeof m.content === 'string' ? m.content : '',
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }));
      sessionStorage.setItem('waterbot_transcript', JSON.stringify(transcript));
    } catch (_) {}
  }, [messages]);

  // Auto-scroll
  useEffect(() => {
    if (chatRef.current) {
      requestAnimationFrame(() => {
        chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' });
      });
    }
  }, [messages, isLoading]);

  const scrollToBottom = () => {
    setTimeout(() => {
      chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' });
    }, 50);
  };

  // Desktop panel auto-open
  useEffect(() => {
    const check = () => {
      if (window.innerWidth >= 1024) setPanelOpen(true);
    };
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  const handleSend = async (text) => {
    if (!text.trim()) return;
    setMessages((prev) => [
      ...prev,
      { id: nextId(), type: 'user', content: text },
      { id: nextId(), type: 'bot', content: '', messageId: null, showActions: false, disableTypewriter: true },
    ]);
    setIsLoading(true);

    try {
      const response = await sendChatMessage(text, language);
      setIsLoading(false);
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated.length - 1;
        if (updated[last]?.type === 'bot') {
          updated[last] = {
            type: 'bot', content: response.resp, messageId: response.msgID,
            showActions: true, disableTypewriter: false,
          };
        }
        return updated;
      });
    } catch (error) {
      console.error('Error sending message:', error);
      setIsLoading(false);
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated.length - 1;
        if (updated[last]?.type === 'bot') {
          updated[last] = { type: 'bot', content: t.errorGeneric, messageId: null, showActions: false, disableTypewriter: false };
        }
        return updated;
      });
    }
  };

  const handleAction = async (actionType) => {
    const buttonLabel = getActionLabel(language, actionType);

    if (actionType === 'sources' && !isSourcesAllowed(messages)) {
      setMessages((prev) => [
        ...prev,
        { id: nextId(), type: 'user', content: buttonLabel, isActionLabel: true, actionType },
        { id: nextId(), type: 'bot', content: t.sourcesWarning, messageId: null, showActions: false, disableTypewriter: true },
      ]);
      return;
    }

    setMessages((prev) => [
      ...prev,
      { id: nextId(), type: 'user', content: buttonLabel, isActionLabel: true, actionType },
      { id: nextId(), type: 'bot', content: '', messageId: null, showActions: false, disableTypewriter: true },
    ]);
    setIsLoading(true);

    try {
      let response;
      if (actionType === 'tell-me-more') response = await getDetailedResponse(language);
      else if (actionType === 'next-steps') response = await getActionItems(language);
      else if (actionType === 'sources') response = await getSources(language);
      else { setIsLoading(false); return; }

      setIsLoading(false);
      const content = response?.resp ?? t.errorGeneric;
      const msgID = response?.msgID ?? null;
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated.length - 1;
        if (updated[last]?.type === 'bot') {
          updated[last] = { type: 'bot', content, messageId: msgID, showActions: true, disableTypewriter: false };
        }
        return updated;
      });
    } catch (error) {
      console.error('Error with action:', error);
      setIsLoading(false);
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated.length - 1;
        if (updated[last]?.type === 'bot') {
          updated[last] = { type: 'bot', content: t.errorGeneric, messageId: null, showActions: false, disableTypewriter: false };
        }
        return updated;
      });
    }
  };

  const handleRating = async (messageId, reaction, userComment = null) => {
    try { await submitRating(messageId, reaction, userComment); } catch (e) { console.error('Rating error:', e); }
  };

  const handleLanguageChange = async (nextLang) => {
    if (nextLang === language) return;

    // Freeze all existing messages so typewriter doesn't replay
    const frozen = messages.map((msg) => ({ ...msg, disableTypewriter: true }));

    // Filter out old welcome message, re-label action buttons
    const filtered = frozen.filter((m) => m.type !== 'intro');
    const updatedFiltered = filtered.map((msg) => {
      if (msg.type === 'user' && msg.isActionLabel && msg.actionType) {
        return { ...msg, content: getActionLabel(nextLang, msg.actionType) };
      }
      return msg;
    });

    // Collect bot texts to translate
    const botMsgs = updatedFiltered.filter((m) => m.type === 'bot' && m.content && String(m.content).trim());
    const texts = botMsgs.map((m) => m.content);

    // Switch language + prepend new welcome message (single state update)
    const newDefault = { id: nextId(), type: 'intro', content: (uiText[nextLang] || uiText.en).defaultAnswerText, messageId: null, showActions: false, disableTypewriter: true };
    setLanguage(nextLang);
    setMessages([newDefault, ...updatedFiltered]);

    if (texts.length === 0) return;

    // Translate bot messages in background, then swap in-place
    try {
      const { translations } = await translateMessages(texts, nextLang);
      setMessages((prev) => {
        const first = prev[0];
        const rest = prev.slice(1);
        let idx = 0;
        const translated = rest.map((msg) => {
          if (msg.type === 'bot' && msg.content && String(msg.content).trim() && translations[idx] != null) {
            return { ...msg, content: translations[idx++], disableTypewriter: true };
          }
          return msg;
        });
        return [first, ...translated];
      });
    } catch (e) {
      console.error('Translation failed:', e);
    }
  };

  const handleDownload = async () => {
    try { await downloadTranscript(); } catch (e) { alert(t.downloadErrorAlert || 'Download failed.'); }
  };

  const handleVoiceTranscript = (text) => {
    if (text) handleSend(text);
  };

  return (
    <div className="figma-root">
      <div className="chat-layout">
        <ContextPanel
          isOpen={panelOpen}
          onToggle={() => setPanelOpen(!panelOpen)}
          onPromptSelect={(prompt) => {
            if (window.innerWidth < 1024) setPanelOpen(false);
            handleSend(prompt);
          }}
          t={t}
        />

        <div className="chat-main">
          <AppHeader
            language={language}
            onLangChange={handleLanguageChange}
            onVoice={() => setVoiceOpen(true)}
            onDownload={handleDownload}
            onAbout={() => setShowAbout(true)}
            t={t}
          />

          <div className="chat-messages" ref={chatRef} role="list" aria-label="Chat messages">
            <div className="chat-messages__inner">
              {messages.map((msg, index) => {
                if (msg.type === 'user') {
                  return (
                    <div key={msg.id || index} className="bubble bubble--user">
                      <div className="bubble--user__content">{msg.content}</div>
                    </div>
                  );
                }
                const isLast = index === messages.length - 1;
                return (
                  <ChatBubble
                    key={msg.id || index}
                    answerText={msg.content}
                    messageId={msg.messageId}
                    showActions={msg.showActions}
                    disableActions={isLoading || (isLast && isTyping)}
                    onRating={handleRating}
                    isLoading={isLoading && isLast && (!msg.content || String(msg.content).trim() === '')}
                    disableTypewriter={msg.disableTypewriter}
                    language={language}
                    onContentUpdate={scrollToBottom}
                    onTypingChange={isLast ? setIsTyping : undefined}
                    followUpChips={msg.showActions && isLast && !isLoading && !isTyping
                      ? <FollowUpChips onAction={handleAction} disabled={isLoading || isTyping} t={t} />
                      : null}
                  />
                );
              })}
            </div>
          </div>

          <div className="composer-area">
            <div className="composer-area__inner">
              <Composer
                onSend={handleSend}
                onVoice={() => setVoiceOpen(true)}
                disabled={isLoading || isTyping}
                t={t}
              />
            </div>
          </div>
        </div>
      </div>

      <AboutModal isOpen={showAbout} onClose={() => setShowAbout(false)} t={t} />
      <VoiceOverlay
        isOpen={voiceOpen}
        onStop={() => setVoiceOpen(false)}
        onTranscript={handleVoiceTranscript}
        language={language}
        t={t}
      />
    </div>
  );
}
