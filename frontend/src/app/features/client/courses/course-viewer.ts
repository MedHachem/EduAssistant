import { Component, computed, inject, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { switchMap, tap } from 'rxjs';
import { levelLabel } from '../../../core/documents/document-types';
import { LibraryDocument } from '../../../core/documents/document.model';
import { DocumentsApi } from '../../../core/documents/documents-api';

/** Reads a published book (PDF) with the browser's built-in viewer. */
@Component({
  selector: 'app-course-viewer',
  imports: [RouterLink],
  template: `
    <div class="viewer">
      <header class="bar">
        <a class="back" routerLink=".." aria-label="Retour à mes cours">←</a>
        <div class="info">
          @if (course(); as c) {
            <strong>{{ c.title }}</strong>
            <span>{{ c.subject }} · {{ level(c.level) }}@if (c.pageCount) { · {{ c.pageCount }} pages }</span>
          } @else if (state() === 'loading') {
            <strong>Chargement…</strong>
          }
        </div>
        @if (url(); as u) {
          <div class="actions">
            <a class="btn-ghost" routerLink="/app/chat">Demander au professeur IA</a>
            <a class="btn-ghost icon-only-sm" [href]="u" target="_blank" rel="noopener" title="Ouvrir dans un nouvel onglet">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7h-2V6.4l-9.3 9.3-1.4-1.4L17.6 5H14zM5 5h6v2H5v12h12v-6h2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" /></svg>
              <span>Ouvrir</span>
            </a>
            <a class="btn-ghost icon-only-sm" [href]="u" [attr.download]="course()?.fileName" title="Télécharger">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 4h2v8.2l3.6-3.6L18 10l-6 6-6-6 1.4-1.4 3.6 3.6zM5 18h14v2H5z" /></svg>
              <span>Télécharger</span>
            </a>
          </div>
        }
      </header>

      @if (state() === 'error') {
        <div class="message">
          <strong>Ce cours n'est pas disponible.</strong>
          <a routerLink="..">Retour à mes cours</a>
        </div>
      } @else if (safeUrl(); as src) {
        <iframe class="pdf" [src]="src" [title]="course()?.title ?? 'Cours'"></iframe>
        <p class="mobile-hint">Le PDF ne s'affiche pas ? <a [href]="url()" target="_blank" rel="noopener">Ouvre-le ici</a>.</p>
      }
    </div>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .viewer { display: flex; flex-direction: column; height: 100%; background: #525659; }
    .bar {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.55rem 1rem;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
    }
    .back {
      display: grid;
      place-items: center;
      width: 2rem;
      height: 2rem;
      border-radius: 50%;
      color: var(--text);
      font-size: 1.1rem;
      text-decoration: none;
      &:hover { background: var(--bg); }
    }
    .info {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      strong, span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
      strong { font-size: 0.95rem; }
      span { font-size: 0.75rem; color: var(--muted); }
    }
    .actions { display: flex; gap: 0.4rem; }
    .btn-ghost {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.4rem 0.75rem;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      color: var(--text);
      font-size: 0.8rem;
      text-decoration: none;
      white-space: nowrap;
      &:hover { border-color: var(--primary); color: var(--primary); }
      svg { width: 1rem; height: 1rem; fill: currentColor; }
    }
    .pdf { flex: 1; width: 100%; border: none; background: #525659; }
    .message {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.5rem;
      margin: auto;
      padding: 2rem;
      border-radius: var(--radius);
      background: var(--surface);
      a { color: var(--primary); }
    }
    .mobile-hint { display: none; }
    @media (max-width: 640px) {
      .actions a:first-child { display: none; }
      .icon-only-sm span { display: none; }
      .mobile-hint {
        display: block;
        margin: 0;
        padding: 0.5rem 1rem;
        background: var(--surface);
        font-size: 0.8rem;
        text-align: center;
        a { color: var(--primary); }
      }
    }
  `,
})
export class CourseViewer {
  private readonly api = inject(DocumentsApi);
  private readonly sanitizer = inject(DomSanitizer);

  protected readonly course = signal<LibraryDocument | null>(null);
  protected readonly url = signal<string | null>(null);
  protected readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly level = levelLabel;

  // The URL comes from our own API (SAS URL on Azure, blob: URL locally), never from user input.
  protected readonly safeUrl = computed<SafeResourceUrl | null>(() => {
    const u = this.url();
    return u ? this.sanitizer.bypassSecurityTrustResourceUrl(u) : null;
  });

  constructor() {
    const id = inject(ActivatedRoute).snapshot.paramMap.get('id')!;
    this.api
      .getCourse(id)
      .pipe(
        tap((c) => this.course.set(c)),
        switchMap(() => this.api.fileUrl(id)),
      )
      .subscribe({
        next: (u) => {
          this.url.set(u);
          this.state.set('ready');
        },
        error: () => this.state.set('error'),
      });
  }
}
