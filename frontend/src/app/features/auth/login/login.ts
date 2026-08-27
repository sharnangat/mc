import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';

import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-login',
  imports: [FormsModule, RouterLink],
  templateUrl: './login.html',
})
export class Login {
  email = '';
  password = '';
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
      .login(this.email, this.password)
      .pipe(switchMap(() => this.auth.loadCurrentUser()))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.router.navigateByUrl('/queries');
        },
        error: () => {
          this.submitting.set(false);
          this.errorMessage.set('Incorrect email or password.');
        },
      });
  }
}
