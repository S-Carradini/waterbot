import React from 'react';
import { useNavigate } from 'react-router-dom';
import './Home.css';

// Local image paths - images should be exported from Figma and placed in /public/images/
// Figma asset IDs for reference:
// - ASU Sunburst: 737ecde3-562a-4d5e-b278-42a4b4136c3b
// - Vector decoration: ec688a0f-e832-4d9b-a81a-a44dd074f6ab
// - Union chat bubble: 5c895428-f3b1-40b3-b532-27a6bfef4502
// - Original Blue character: 98ac2073-514b-43a3-84ae-d49d5cbf6b86
// - Info icon: dc0127b7-f4c5-41d4-975a-de6a9f180211
const imgAsuSunBurst = "/images/asu-sunburst.png";
const imgVector = "/images/vector-decoration.png";
const imgUnion = "/images/union-chat-bubble.png";
const imgOriginalBlue = "/images/original-blue.png";
const imgGroup11142 = "/images/info-icon.png";

export default function Home() {
  const navigate = useNavigate();

  const handleChatWithBlue = (e) => {
    e.preventDefault();
    navigate('/waterbot');
  };

  return (
    <div className="home-container" data-name="Home" data-node-id="1:2">
      <div className="home-inner">
      {/* Vector decoration */}
      <div className="home-vector" data-name="Vector" data-node-id="1:218">
        <img alt="" src={imgVector} />
      </div>

      {/* Chat bubble with text */}
      <div className="home-chat-bubble-container" data-node-id="1:8">
        <div className="home-union" data-name="Union" data-node-id="1:9">
          <img alt="" src={imgUnion} />
        </div>
      </div>

      {/* Blue character */}
      <div className="home-blue-character" data-name="Original Blue" data-node-id="1:4">
        <img alt="" src={imgOriginalBlue} />
      </div>

      {/* White header bar */}
      <div className="home-header-bar" data-node-id="1:38" />

      {/* ASU Logo */}
      <div className="home-asu-logo" data-name="ASU_SunBurst_1_RGB_MaroonGold_600ppi 1" data-node-id="1:39">
        <img alt="" src={imgAsuSunBurst} />
      </div>

      {/* Title */}
      <div className="home-title" data-node-id="106:316">
        <p>Chat With Blue</p>
      </div>

      {/* Info icon */}
      <div className="home-info-icon" data-node-id="6:276">
        <img alt="" src={imgGroup11142} />
        <p className="home-info-icon-text" data-node-id="6:280">i</p>
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

