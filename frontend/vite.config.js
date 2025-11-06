import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/chat_api': {
        target: API_URL,
        changeOrigin: true,
      },
      '/chat_detailed_api': {
        target: API_URL,
        changeOrigin: true,
      },
      '/chat_actionItems_api': {
        target: API_URL,
        changeOrigin: true,
      },
      '/chat_sources_api': {
        target: API_URL,
        changeOrigin: true,
      },
      '/submit_rating_api': {
        target: API_URL,
        changeOrigin: true,
      },
      '/session-transcript': {
        target: API_URL,
        changeOrigin: true,
      },
      '/transcribe': {
        target: API_URL,
        changeOrigin: true,
        ws: true, // Enable WebSocket proxying
      },
      '/static': {
        target: API_URL,
        changeOrigin: true,
      },
    },
  },
})

