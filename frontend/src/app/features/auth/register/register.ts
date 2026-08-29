import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';

import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-register',
  imports: [FormsModule, RouterLink],
  templateUrl: './register.html',
})
export class Register {
  email = '';
  password = '';
  fullName = '';
  phone = '';
  companyName = '';
  readonly submitting = signal(false);
  readonly errorMessage = signal<string | null>(null);

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router
  ) {}

  submit(): void {
    this.errorMessage.set(null);
    this.submitting.set(true);

    this.auth
      .register({
        email: this.email,
        password: this.password,
        full_name: this.fullName,
        phone: this.phone || undefined,
        company_name: this.companyName || undefined,
      })
      .subscribe({
        next: () => this.router.navigateByUrl('/auth/login'),
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.errorMessage.set(err.status === 409 ? 'That email is already registered.' : 'Registration failed.');
        },
      });
  }
}
