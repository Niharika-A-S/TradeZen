/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bgPrimary: 'var(--bg-primary, #0E1116)',
        bgSecondary: 'var(--bg-secondary, #1A1F29)',
        bgTertiary: 'var(--bg-tertiary, #11161F)',
        textPrimary: 'var(--text-primary, #F9FAFB)',
        textSecondary: 'var(--text-secondary, #D1D5DB)',
        textTertiary: 'var(--text-tertiary, #9CA3AF)',
        borderDefault: 'var(--border-default, #2A313C)',
        borderStrong: 'var(--border-strong, #374151)',
        accentPrimary: 'var(--accent-primary, #3B82F6)',
        accentHover: 'var(--accent-hover, #60A5FA)',
        accentMuted: 'var(--accent-muted, #1E3A5F)',
        gain: 'var(--gain, #34D399)',
        gainDark: 'var(--gain-dark, #10B981)',
        loss: 'var(--loss, #F87171)',
        lossDark: 'var(--loss-dark, #EF4444)',
        warning: 'var(--warning, #FBBF24)',
        warningBg: 'var(--warning-bg, #3A2E0F)',
        info: 'var(--info, #60A5FA)',
        infoBg: 'var(--info-bg, #1E3A5F)',
        success: 'var(--success, #34D399)',
        successBg: 'var(--success-bg, #064E3B)',
        gridLine: 'var(--grid-line, #2A313C)',
        axisText: 'var(--axis-text, #9CA3AF)',
        chartLinePrimary: 'var(--chart-line-primary, #3B82F6)',
        chartLineSecondary: 'var(--chart-line-secondary, #93C5FD)',
        tz: {
          bg: {
            primary: '#0E1116',
            secondary: '#1A1F29',
            tertiary: '#11161F',
          },
          text: {
            primary: '#F9FAFB',
            secondary: '#D1D5DB',
            tertiary: '#9CA3AF',
          },
          border: {
            DEFAULT: '#2A313C',
            strong: '#374151',
          },
          accent: {
            DEFAULT: '#3B82F6',
            hover: '#60A5FA',
            muted: '#1E3A5F',
          },
          pnl: {
            gain: '#34D399',
            gainDark: '#10B981',
            loss: '#F87171',
            lossDark: '#EF4444',
          },
          status: {
            warning: '#FBBF24',
            warningBg: '#3A2E0F',
            info: '#60A5FA',
            infoBg: '#1E3A5F',
            success: '#34D399',
            successBg: '#064E3B',
          },
          chart: {
            grid: '#2A313C',
            axis: '#9CA3AF',
            primary: '#3B82F6',
            secondary: '#93C5FD',
          }
        }
      },
    },
  },
  plugins: [],
}
