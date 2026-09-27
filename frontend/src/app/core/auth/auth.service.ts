import { Injectable, computed, signal } from '@angular/core';
import { environment } from '../../../environments/environment';
import { Role, User } from './auth.model';

const STORAGE_KEY = 'edu.user';

const MOCK_USERS: Record<Role, User> = {
  ADMIN: { id: 'admin-1', name: 'Admin', email: 'admin@eduassistant.local', role: 'ADMIN' },
  CLIENT: { id: 'client-1', name: 'Élève', email: 'eleve@eduassistant.local', role: 'CLIENT' },
};

/**
 * Auth is bypassed for now (environment.authBypass): login just picks a mock user
 * and stores it locally. Replace `login` with a call to the backend JWT endpoint later.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly user = signal<User | null>(this.restore());

  readonly currentUser = this.user.asReadonly();
  readonly isAuthenticated = computed(() => this.user() !== null);

  login(role: Role): void {
    if (!environment.authBypass) {
      throw new Error('Real authentication is not implemented yet.');
    }
    const user = MOCK_USERS[role];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    this.user.set(user);
  }

  logout(): void {
    localStorage.removeItem(STORAGE_KEY);
    this.user.set(null);
  }

  hasRole(role: Role): boolean {
    return this.user()?.role === role;
  }

  homeFor(role: Role): string {
    return role === 'ADMIN' ? '/admin' : '/app';
  }

  private restore(): User | null {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  }
}
