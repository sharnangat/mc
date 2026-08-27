import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, computed, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, of, tap } from 'rxjs';

import { API_BASE_URL } from '../config';
import { User } from '../models';

const TOKEN_KEY = 'metag_access_token';

interface TokenResponse {
  access_token: string;
  token_type: string;
}

interface RegisterRequest {
  email: string;
  password: string;
  full_name: string;
  phone?: string;
  company_name?: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly currentUserSignal = signal<User | null>(null);
  readonly currentUser = this.currentUserSignal.asReadonly();
  readonly isLoggedIn = computed(() => this.currentUserSignal() !== null);

  constructor(
    private readonly http: HttpClient,
    private readonly router: Router
  ) {}

  get token(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  login(email: string, password: string) {
    const body = new HttpParams().set('username', email).set('password', password);
    return this.http
      .post<TokenResponse>(`${API_BASE_URL}/auth/login`, body.toString(), {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })
      .pipe(
        tap((res) => {
          localStorage.setItem(TOKEN_KEY, res.access_token);
        })
      );
  }

  register(payload: RegisterRequest) {
    return this.http.post<User>(`${API_BASE_URL}/auth/register`, payload);
  }

  loadCurrentUser() {
    return this.http.get<User>(`${API_BASE_URL}/auth/me`).pipe(
      tap((user) => this.currentUserSignal.set(user))
    );
  }

  /** Resolves the current user, loading it from the API once if a token exists but hasn't been validated yet. */
  ensureUserLoaded(): Observable<User | null> {
    const existing = this.currentUserSignal();
    if (existing) return of(existing);
    if (!this.token) return of(null);

    return this.loadCurrentUser().pipe(
      catchError(() => {
        this.logout();
        return of(null);
      })
    );
  }

  logout(): void {
    localStorage.removeItem(TOKEN_KEY);
    this.currentUserSignal.set(null);
    this.router.navigate(['/login']);
  }

  hasRole(...roles: string[]): boolean {
    const user = this.currentUserSignal();
    if (!user) return false;
    return user.roles.some((r) => roles.includes(r));
  }
}
