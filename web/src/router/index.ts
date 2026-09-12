import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useReviewStore } from '@/stores/review'
import { useUiStore } from '@/stores/ui'

// 采用 hash 模式：后端以静态资源方式挂载 web/dist，没有 SPA 回退路由，
// hash 模式下刷新任意页面都不会 404，且与相对 base 兼容。
//
// needVerified: 必须先在第②步把每一道题都勾选「已核对」并点「确认核验」，
// 否则不允许进入该页（③ 题目配图、④ 生成都依赖核对结果）。
const routes: RouteRecordRaw[] = [
  { path: '/', name: 'source', component: () => import('@/views/SourceView.vue'), meta: { title: '① 选择来源' } },
  { path: '/review', name: 'review', component: () => import('@/views/ReviewView.vue'), meta: { title: '② 题目核对' } },
  {
    path: '/images',
    name: 'images',
    component: () => import('@/views/ImagesView.vue'),
    meta: { title: '③ 题目配图', needVerified: true },
  },
  {
    path: '/generate',
    name: 'generate',
    component: () => import('@/views/GenerateView.vue'),
    meta: { title: '④ 生成', needVerified: true },
  },
  { path: '/merge', name: 'merge', component: () => import('@/views/MergeView.vue'), meta: { title: '⑤ 合并' } },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '⑥ 设置' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

/** 第②步没核对完就进 ③/④：弹提示并把页面拉回核对页 */
router.beforeEach((to) => {
  if (!to.meta.needVerified) return true
  const review = useReviewStore()
  if (review.allVerified) return true
  const ui = useUiStore()
  if (review.total > 0) {
    ui.notify(
      '还有 ' + (review.total - review.verifiedCount) + ' 题没有勾选「已核对」：' +
        '请逐题核对，全部勾选后点「确认核验」再进入下一步',
      'warn',
      6000,
    )
  } else {
    ui.notify('请先在「① 选择来源」识别试卷，并在第②步逐题核对后再进入下一步', 'warn', 6000)
  }
  return { path: '/review' }
})

export default router
