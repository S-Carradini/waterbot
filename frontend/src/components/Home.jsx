import React from 'react';
import { useNavigate } from 'react-router-dom';
import './Home.css';

const imgAsuSunBurst = "https://www.figma.com/api/mcp/asset/737ecde3-562a-4d5e-b278-42a4b4136c3b";
const imgVector = "https://www.figma.com/api/mcp/asset/ec688a0f-e832-4d9b-a81a-a44dd074f6ab";
const imgUnion = "https://www.figma.com/api/mcp/asset/5c895428-f3b1-40b3-b532-27a6bfef4502";
const imgOriginalBlue = "https://www.figma.com/api/mcp/asset/98ac2073-514b-43a3-84ae-d49d5cbf6b86";
const imgGroup11142 = "https://www.figma.com/api/mcp/asset/dc0127b7-f4c5-41d4-975a-de6a9f180211";

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
        <div className="home-chat-text-main">
          <p className="home-chat-text-content">
            Ask me anything you want about the story of water in our state! Not sure where to start?
          </p>
        </div>
        <div className="home-chat-text-hello">
          <p>Hello! I'm Blue!</p>
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

      {/* Chat with Blue button */}
      <button
        className="home-chat-button"
        onClick={handleChatWithBlue}
        data-name="Interact with Blue"
        data-node-id="1:48"
      >
        <p>Chat with Blue</p>
      </button>

      {/* Info icon */}
      <div className="home-info-icon" data-node-id="6:276">
        <img alt="" src={imgGroup11142} />
        <p className="home-info-icon-text" data-node-id="6:280">i</p>
      </div>
      </div>
    </div>
  );
}

