import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'

import './styles/tokens.css'
import './styles/base.css'

// 全局兜底：任何未捕获异常都不应该让页面白屏
window.addEventListener('unhandledrejection', (ev) => {
  console.error('[未处理的 Promise 异常]', ev.reason)
})

createApp(App).use(createPinia()).use(router).mount('#app')
