/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './backend/templates/**/*.html',
    './backend/expenses/templates/**/*.html',
  ],
  theme: {
    extend: {
      colors: {
        'bg': '#f6f7f8',
        'panel': '#ffffff',
        'accent': '#ff0066',
        'muted': '#0f172a',
        'border': '#0f172a',
      },
      fontFamily: {
        'mono': ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Roboto Mono', 'monospace'],
      },
      boxShadow: {
        'brutal': '4px 4px 0 rgba(0,0,0,0.15)',
        'brutal-lg': '8px 8px 0 rgba(0,0,0,0.06)',
      },
      borderWidth: {
        '3': '3px',
        '6': '6px',
      },
    },
  },
  plugins: [],
}
