/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Riverbot theme (values are defined on .riverbot-root in styles/riverbot.css)
      colors: {
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        border: 'var(--border)',
        primary: 'var(--primary)',
      },
      fontFamily: {
        display: ['Manrope', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
