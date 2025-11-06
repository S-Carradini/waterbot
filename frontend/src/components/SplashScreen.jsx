import React from 'react';
import { useNavigate, Link } from 'react-router-dom';
import './SplashScreen.css';

export default function SplashScreen() {
  const navigate = useNavigate();

  // Debug: Log when SplashScreen component mounts
  React.useEffect(() => {
    console.log('SplashScreen component mounted, current path:', window.location.pathname);
  }, []);

  const handleChatWithBlue = (e) => {
    e.preventDefault();
    e.stopPropagation();
    console.log('Navigating to /waterbot');
    console.log('Current path before navigation:', window.location.pathname);
    navigate('/waterbot', { replace: true });
    console.log('Navigation called, current path after:', window.location.pathname);
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

