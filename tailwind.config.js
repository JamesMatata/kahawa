/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        cream: {
          50: '#FFFBF5',
          100: '#FFF6EB',
          200: '#FDECD3',
        },
        caramel: {
          400: '#F0A868',
          500: '#E8914A',
          600: '#D97706',
          700: '#B45309',
        },
        espresso: {
          700: '#4A3428',
          800: '#2C1A12',
          900: '#1A0F0A',
        },
        latte: '#F5D9B8',
        ink: {
          850: '#12141A',
          900: '#0B0D12',
          950: '#07080C',
        },
      },
      fontFamily: {
        display: ['"Fredoka"', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        xl: '0.5rem',
        '2xl': '0.625rem',
        '3xl': '0.75rem',
      },
    },
  },
  plugins: [],
};
