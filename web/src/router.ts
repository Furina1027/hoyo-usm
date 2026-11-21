import { createRouter, createWebHashHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'overview', component: () => import('./views/OverviewView.vue') },
    { path: '/files', name: 'files', component: () => import('./views/FilesView.vue') },
    { path: '/tasks', name: 'tasks', component: () => import('./views/TasksView.vue') },
    { path: '/external', name: 'external', component: () => import('./views/ExternalView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
    { path: '/about', name: 'about', component: () => import('./views/AboutView.vue') },
    { path: '/wizard', name: 'wizard', component: () => import('./views/WizardView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
