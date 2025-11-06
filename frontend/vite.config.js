import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/chat_api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
      '/chat_detailed_api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
      '/chat_actionItems_api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
      '/chat_sources_api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
      '/submit_rating_api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
      '/session-transcript': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
      '/transcribe': {
        target: 'http://localhost:8010',
        changeOrigin: true,
        ws: true, // Enable WebSocket proxying
      },
      '/static': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
    },
  },
})

