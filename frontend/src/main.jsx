import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import App from './App'
import SplashScreen from './components/SplashScreen'
import Home from './components/Home'
import MobileChatbot from './components/MobileChatbot'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/museum" element={<SplashScreen />} />
        <Route path="/museum/chat" element={<App />} />
        <Route path="/mobile" element={<MobileChatbot />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)

