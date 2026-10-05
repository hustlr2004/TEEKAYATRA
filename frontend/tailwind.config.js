/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        tealInk: '#0f3f3b',
        field: '#f8fafc',
        saffron: '#f59e0b',
        leaf: '#16a34a',
        river: '#2563eb'
      }
    }
  },
  plugins: []
};
