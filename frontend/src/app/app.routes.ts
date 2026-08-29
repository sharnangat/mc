import { Routes } from '@angular/router';

import { authGuard, roleGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  { path: '', redirectTo: 'queries', pathMatch: 'full' },
  {
    path: 'auth/login',
    loadComponent: () => import('./features/auth/login/login').then((m) => m.Login),
  },
  {
    path: 'auth/register',
    loadComponent: () => import('./features/auth/register/register').then((m) => m.Register),
  },
  {
    path: 'queries',
    canActivate: [authGuard],
    loadComponent: () => import('./features/customer/query-list/query-list').then((m) => m.QueryList),
  },
  {
    path: 'queries/new',
    canActivate: [authGuard],
    loadComponent: () => import('./features/customer/query-new/query-new').then((m) => m.QueryNew),
  },
  {
    path: 'queries/:id',
    canActivate: [authGuard],
    loadComponent: () => import('./features/customer/query-detail/query-detail').then((m) => m.QueryDetailPage),
  },
  {
    path: 'chat',
    canActivate: [authGuard],
    loadComponent: () => import('./features/chat/chat-page/chat-page').then((m) => m.ChatPage),
  },
  {
    path: 'expert',
    canActivate: [roleGuard('expert', 'admin', 'superadmin')],
    loadComponent: () => import('./features/expert/review-queue/review-queue').then((m) => m.ReviewQueue),
  },
  {
    path: 'expert/:id',
    canActivate: [roleGuard('expert', 'admin', 'superadmin')],
    loadComponent: () => import('./features/expert/review-detail/review-detail').then((m) => m.ReviewDetail),
  },
  {
    path: 'admin/documents',
    canActivate: [roleGuard('admin', 'superadmin')],
    loadComponent: () => import('./features/admin/documents/documents').then((m) => m.Documents),
  },
  {
    path: 'admin/pricing',
    canActivate: [roleGuard('admin', 'superadmin')],
    loadComponent: () => import('./features/admin/pricing/pricing').then((m) => m.Pricing),
  },
  { path: '**', redirectTo: 'queries' },
];
