import React from 'react';
import { useNavigate } from 'react-router-dom';
import './SplashScreen.css';

export default function SplashScreen() {
  const navigate = useNavigate();

  const handleChatWithBlue = (e) => {
    e.preventDefault();
    e.stopPropagation();
    navigate('/museum/chat', { replace: true });
  };

  return (
    <div className="splash-screen-container">
      <header className="minimal-header"></header>
      <section className="splash-screen">
        <video autoPlay loop muted playsInline id="bg-video">
          <source src="/static/video/background.mp4" type="video/mp4" />
          Your browser does not support HTML5 video.
        </video>

        <button
          className="chat-with-blue-btn"
          onClick={handleChatWithBlue}
        >
          CHAT WITH BLUE
        </button>
      </section>
    </div>
  );
}

