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
      }
    }
  },
  plugins: []
};
