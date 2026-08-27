import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';

import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  return auth.ensureUserLoaded().pipe(map((user) => (user ? true : router.createUrlTree(['/login']))));
};

export function roleGuard(...roles: string[]): CanActivateFn {
  return () => {
    const auth = inject(AuthService);
    const router = inject(Router);

    return auth.ensureUserLoaded().pipe(
      map((user) => {
        if (!user) return router.createUrlTree(['/login']);
        if (!roles.some((r) => user.roles.includes(r))) return router.createUrlTree(['/']);
        return true;
      })
    );
  };
}
