/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './core/templates/**/*.html',
  ],
  theme: {
    extend: {
      colors: {},
      borderRadius: {
        DEFAULT: '0.125rem',
        lg: '0.25rem',
        xl: '0.5rem',
        full: '0.75rem',
      },
      spacing: {
        'margin-mobile': '16px',
        'unit': '4px',
        'gutter': '24px',
        'margin-desktop': '32px',
        'container-max': '1440px',
      },
      fontFamily: {
        'body-lg': ['Inter'],
        'body-md': ['Inter'],
        'title-lg': ['Inter'],
        'display-lg': ['Inter'],
        'label-md': ['Inter'],
        'headline-lg-mobile': ['Inter'],
        'headline-md': ['Inter'],
        'headline-lg': ['Inter'],
        'data-mono': ['Inter'],
      },
      fontSize: {
        'body-lg': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'body-md': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'title-lg': ['20px', { lineHeight: '28px', fontWeight: '600' }],
        'label-md': ['12px', { lineHeight: '16px', letterSpacing: '0.05em', fontWeight: '500' }],
        'headline-lg-mobile': ['24px', { lineHeight: '32px', fontWeight: '600' }],
        'headline-md': ['24px', { lineHeight: '32px', fontWeight: '600' }],
        'headline-lg': ['32px', { lineHeight: '40px', letterSpacing: '-0.01em', fontWeight: '600' }],
        'data-mono': ['14px', { lineHeight: '20px', letterSpacing: '0.01em', fontWeight: '600' }],
      },
    },
  },
  plugins: [],
}