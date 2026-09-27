import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { Role } from './auth.model';
import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.isAuthenticated() || inject(Router).createUrlTree(['/login']);
};

export function roleGuard(role: Role): CanActivateFn {
  return () => {
    const auth = inject(AuthService);
    const user = auth.currentUser();
    if (!user) {
      return inject(Router).createUrlTree(['/login']);
    }
    return user.role === role || inject(Router).createUrlTree([auth.homeFor(user.role)]);
  };
}
