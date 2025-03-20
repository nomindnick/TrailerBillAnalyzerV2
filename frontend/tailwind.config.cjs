// frontend/tailwind.config.cjs
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['class'], // or just 'class'
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
    // Add the line below so that Radix UI classes & attributes don't get purged
    './node_modules/@radix-ui/**/*.{js,ts,jsx,tsx}'
  ],
  theme: {
    extend: {
      zIndex: {
        '50': '50'
      },
      colors: {
        border: 'hsl(var(--border))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))'
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))'
        }
      },
      animation: {
        'fade-in': 'fade-in 0.3s ease-in-out',
        'slide-up': 'slide-up 0.4s ease-out',
        'pulse': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-subtle': 'pulse-subtle 3s ease-in-out infinite',
        'ping-once': 'ping-once 0.8s cubic-bezier(0, 0, 0.2, 1)',
        'spin': 'spin 1s linear infinite',
        'bounce-in': 'bounce-in 0.7s ease-out',
        'shake': 'shake 0.5s cubic-bezier(.36,.07,.19,.97) both',
      },
      keyframes: {
        'shake': {
          '10%, 90%': { transform: 'translate3d(-1px, 0, 0)' },
          '20%, 80%': { transform: 'translate3d(2px, 0, 0)' },
          '30%, 50%, 70%': { transform: 'translate3d(-3px, 0, 0)' },
          '40%, 60%': { transform: 'translate3d(3px, 0, 0)' }
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' }
        },
        'slide-up': {
          '0%': { 
            opacity: '0',
            transform: 'translateY(10px)'
          },
          '100%': { 
            opacity: '1',
            transform: 'translateY(0)'
          }
        },
        'pulse': {
          '0%, 100%': { 
            opacity: '1' 
          },
          '50%': { 
            opacity: '0.5' 
          }
        },
        'pulse-subtle': {
          '0%, 100%': { 
            opacity: '1',
            transform: 'scale(1)' 
          },
          '50%': { 
            opacity: '0.95',
            transform: 'scale(0.98)' 
          }
        },
        'ping-once': {
          '0%': {
            opacity: '1',
            transform: 'scale(0.8)'
          },
          '80%': {
            opacity: '0.8',
            transform: 'scale(1.5)'
          },
          '100%': {
            opacity: '0',
            transform: 'scale(2)'
          }
        },
        'bounce-in': {
          '0%': {
            opacity: '0',
            transform: 'scale(0.8)'
          },
          '70%': {
            opacity: '1',
            transform: 'scale(1.05)'
          },
          '100%': {
            opacity: '1',
            transform: 'scale(1)'
          }
        },
        'spin': {
          '0%': { 
            transform: 'rotate(0deg)' 
          },
          '100%': { 
            transform: 'rotate(360deg)' 
          }
        }
      },
      boxShadow: {
        'md': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        'lg': '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
        'xl': '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)'
      },
      borderRadius: {
        'sm': '0.25rem',
        'md': '0.375rem',
        'lg': '0.5rem',
        'xl': '0.75rem',
        '2xl': '1rem',
      },
      transitionDuration: {
        '0': '0ms',
        '200': '200ms',
        '300': '300ms',
        '500': '500ms',
        '700': '700ms',
      },
      transitionTimingFunction: {
        'bounce': 'cubic-bezier(0.68, -0.6, 0.32, 1.6)',
      }
    }
  },
  plugins: []
};