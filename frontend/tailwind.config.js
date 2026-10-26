/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          900: '#0a0e27',
          800: '#111640',
          700: '#1a1f52',
          600: '#252b6a',
        },
        warm: {
          950: '#0d1117',
          900: '#131922',
          850: '#18202c',
          800: '#1f2937',
          700: '#2d3848',
          cream: '#f4eedf',
          sand: '#e6dec8',
          muted: '#a3adbf',
          gold: '#e3b23c',
          amber: '#d99b26',
          sage: '#4ead8b',
          terracotta: '#e07a5f',
        },
        accent: {
          green: '#34b38a',
          red: '#e07a5f',
          amber: '#e3b23c',
          blue: '#5b8fd9',
        }
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        serif: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', '"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        mono: ['"Space Grotesk"', '"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        heromono: ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
