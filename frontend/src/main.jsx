import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
// New Figma design pages
import FigmaSplashScreen from './components/figma/SplashScreen'
import ChatPage from './components/figma/ChatPage'
import TranscriptPage from './components/figma/TranscriptPage'
import SettingsPage from './components/figma/SettingsPage'
// Museum (legacy) pages
import App from './App'
import SplashScreen from './components/SplashScreen'
import Home from './components/Home'
import MobileChatbot from './components/MobileChatbot'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <div className="spa-scale-wrapper">
    <BrowserRouter>
      <Routes>
        {/* New Figma design routes */}
        <Route path="/" element={<FigmaSplashScreen />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/transcript" element={<TranscriptPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        {/* Museum (legacy) routes */}
        <Route path="/museum" element={<SplashScreen />} />
        <Route path="/museum/home" element={<Home />} />
        <Route path="/museum/chat" element={<App />} />
        <Route path="/mobile" element={<MobileChatbot />} />
      </Routes>
    </BrowserRouter>
    </div>
  </React.StrictMode>,
)
