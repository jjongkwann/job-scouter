import type { OpenSlideConfig } from '@open-slide/core'

export default {
  base: '/slides/',
  slidesDir: '../data/application-slide-studio/slides',
  assetsDir: '../data/application-slide-studio/assets',
  build: { showSlideBrowser: true, showSlideUi: true, allowHtmlDownload: true },
} satisfies OpenSlideConfig
