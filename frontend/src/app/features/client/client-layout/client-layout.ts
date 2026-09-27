import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '../../../core/auth/auth.service';

@Component({
  selector: 'app-client-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <header class="topbar">
      <a class="brand" routerLink="/app">EduAssistant</a>
      <nav>
        <a routerLink="courses" routerLinkActive="active">Mes cours</a>
        <a routerLink="chat" routerLinkActive="active">Professeur IA</a>
      </nav>
      <div class="user">
        <span class="avatar" aria-hidden="true">{{ initial() }}</span>
        <span class="name">{{ auth.currentUser()?.name }}</span>
        <button type="button" class="btn-link" (click)="logout()">Déconnexion</button>
      </div>
    </header>
    <main class="main">
      <router-outlet />
    </main>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      height: 100dvh;
    }
    .topbar {
      flex: none;
      display: flex;
      align-items: center;
      gap: 1.5rem;
      height: var(--topbar-h);
      padding: 0 1rem;
      background: var(--sidebar-bg);
      color: #fff;
    }
    .brand {
      font-weight: 700;
      font-size: 1.1rem;
      color: #fff;
      text-decoration: none;
    }
    nav {
      flex: 1;
      display: flex;
      gap: 0.25rem;
      a {
        padding: 0.4rem 0.75rem;
        border-radius: var(--radius);
        color: #cbd5e1;
        text-decoration: none;
        font-size: 0.9rem;
        &.active { background: rgba(255, 255, 255, 0.1); color: #fff; }
      }
    }
    .user {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.875rem;
      .btn-link { color: #cbd5e1; }
    }
    .avatar {
      display: grid;
      place-items: center;
      width: 2rem;
      height: 2rem;
      border-radius: 50%;
      background: var(--primary);
      font-weight: 700;
    }
    .main {
      flex: 1;
      min-height: 0;
    }
    @media (max-width: 640px) {
      .topbar { gap: 0.5rem; padding: 0 0.6rem; }
      .brand, .name { display: none; }
      nav a { padding: 0.4rem 0.6rem; font-size: 0.85rem; }
    }
  `,
})
export class ClientLayout {
  private readonly router = inject(Router);
  protected readonly auth = inject(AuthService);

  protected initial(): string {
    return (this.auth.currentUser()?.name ?? '?').charAt(0).toUpperCase();
  }

  protected logout(): void {
    this.auth.logout();
    this.router.navigate(['/login']);
  }
}
