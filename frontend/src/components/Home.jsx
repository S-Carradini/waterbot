import React from 'react';
import { useNavigate } from 'react-router-dom';
import './Home.css';

// Local image paths - images should be exported from Figma and placed in /public/images/
const imgWatersimLogo = "/images/watersim-logo.svg";
const imgVector = "/images/vector-decoration.png";
const imgUnion = "/images/union-chat-bubble.png";
const imgOriginalBlue = "/images/original-blue.png";

export default function Home() {
  const navigate = useNavigate();

  const handleChatWithBlue = (e) => {
    e.preventDefault();
    navigate('/museum/chat');
  };

  return (
    <div className="home-container" data-name="Home" data-node-id="1:2">
      <div className="home-inner">
      {/* Vector decoration */}
      <div className="home-vector" data-name="Vector" data-node-id="1:218">
        <img alt="" src={imgVector} />
      </div>

      {/* Chat bubble */}
      <div className="home-chat-bubble-container" data-node-id="1:8">
        <div className="home-union" data-name="Union" data-node-id="1:9">
          <img alt="" src={imgUnion} />
        </div>
      </div>

      {/* Blue character */}
      <div className="home-blue-character" data-name="Original Blue" data-node-id="1:4">
        <img alt="" src={imgOriginalBlue} />
      </div>

      {/* Header row: pill-shaped white bar with WaterSimmersive logo (Figma: Updated Waterbot UI 282:34) */}
      <div className="home-header-row">
        <div className="home-header-bar" data-node-id="1:38">
          <a
            href="https://watersimmersive.net/"
            target="_blank"
            rel="noopener noreferrer"
            className="home-header-bar-logo-link"
          >
            <img alt="WaterSimmersive" src={imgWatersimLogo} className="home-header-bar-logo" />
          </a>
        </div>
      </div>
      </div>
      
      {/* Chat with Blue button - outside home-inner for fixed positioning */}
      <button
        className="home-chat-button"
        onClick={handleChatWithBlue}
        data-name="Interact with Blue"
        data-node-id="1:48"
      >
        CHAT WITH BLUE
      </button>
    </div>
  );
}

