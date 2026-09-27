import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { Role } from '../../../core/auth/auth.model';
import { AuthService } from '../../../core/auth/auth.service';

@Component({
  selector: 'app-login',
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected enterAs(role: Role): void {
    this.auth.login(role);
    this.router.navigateByUrl(this.auth.homeFor(role));
  }
}
