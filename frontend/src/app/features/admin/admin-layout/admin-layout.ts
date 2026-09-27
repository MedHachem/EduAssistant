import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '../../../core/auth/auth.service';

interface NavLink {
  path: string;
  label: string;
  /** Only active on this exact URL (parents with child links). */
  exact?: boolean;
  children?: NavLink[];
}

interface NavGroup {
  title: string | null;
  links: NavLink[];
}

@Component({
  selector: 'app-admin-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './admin-layout.html',
  styleUrl: './admin-layout.scss',
})
export class AdminLayout {
  private readonly router = inject(Router);
  protected readonly auth = inject(AuthService);

  protected readonly nav: NavGroup[] = [
    { title: null, links: [{ path: 'overview', label: 'Overview' }] },
    {
      title: 'Data Injection',
      links: [
        {
          path: 'data-injection',
          label: 'Upload',
          exact: true,
          children: [
            { path: 'data-injection/book', label: 'Official Books' },
            { path: 'data-injection/exam', label: 'Official Exams' },
            { path: 'data-injection/test', label: 'Official Tests' },
          ],
        },
      ],
    },
    {
      title: 'Build AI Pipeline',
      links: [
        { path: 'ai-pipeline/ocr', label: 'OCR' },
        {
          path: 'ai-pipeline/image-validation',
          label: 'Figure Review',
          exact: true,
          children: [
            { path: 'ai-pipeline/image-validation', label: 'Round 1 (V1)' },
            { path: 'ai-pipeline/image-validation-v3', label: 'Round 3 (V3)' },
          ],
        },
        { path: 'ai-pipeline/knowledge-base', label: 'Knowledge Base' },
        { path: 'ai-pipeline/figure-association', label: 'Figure ↔ Knowledge' },
        { path: 'ai-pipeline/rag', label: 'RAG' },
      ],
    },
  ];

  protected logout(): void {
    this.auth.logout();
    this.router.navigate(['/login']);
  }
}
