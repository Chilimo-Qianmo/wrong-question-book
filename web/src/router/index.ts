import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

// 采用 hash 模式：后端以静态资源方式挂载 web/dist，没有 SPA 回退路由，
// hash 模式下刷新任意页面都不会 404，且与相对 base 兼容。
const routes: RouteRecordRaw[] = [
  { path: '/', name: 'source', component: () => import('@/views/SourceView.vue'), meta: { title: '① 选择来源' } },
  { path: '/review', name: 'review', component: () => import('@/views/ReviewView.vue'), meta: { title: '② 题目核对' } },
  { path: '/images', name: 'images', component: () => import('@/views/ImagesView.vue'), meta: { title: '③ 题目配图' } },
  { path: '/generate', name: 'generate', component: () => import('@/views/GenerateView.vue'), meta: { title: '④ 生成' } },
  { path: '/merge', name: 'merge', component: () => import('@/views/MergeView.vue'), meta: { title: '⑤ 合并' } },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '⑥ 设置' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
