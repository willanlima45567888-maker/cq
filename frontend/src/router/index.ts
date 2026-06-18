import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import HomeView from '../views/HomeView.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: HomeView,
  },
  {
    path: '/iostat',
    name: 'iostat',
    component: () => import('../views/IostatView.vue'),
  },
  {
    path: '/ps',
    name: 'ps',
    component: () => import('../views/PsView.vue'),
  },
  {
    path: '/top',
    name: 'top',
    component: () => import('../views/TopView.vue'),
  },
  {
    path: '/netstat',
    name: 'netstat',
    component: () => import('../views/NetstatView.vue'),
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
