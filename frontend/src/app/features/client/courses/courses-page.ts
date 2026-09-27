import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { levelLabel } from '../../../core/documents/document-types';
import { LibraryDocument } from '../../../core/documents/document.model';
import { DocumentsApi } from '../../../core/documents/documents-api';
import { CourseCover } from './course-cover';

/** Student catalog: published official books, shown as courses. */
@Component({
  selector: 'app-courses-page',
  imports: [RouterLink, CourseCover],
  template: `
    <div class="page">
      <header class="head">
        <div>
          <h1>Mes cours</h1>
          <p>Les manuels officiels de ton programme.</p>
        </div>
        <input type="search" placeholder="Rechercher un cours…" [value]="search()" (input)="search.set($any($event.target).value)" aria-label="Rechercher" />
      </header>

      @if (subjects().length > 1) {
        <div class="chips" role="group" aria-label="Matières">
          <button type="button" [class.on]="!subject()" (click)="subject.set(null)">Toutes</button>
          @for (s of subjects(); track s) {
            <button type="button" [class.on]="subject() === s" (click)="subject.set(s)">{{ s }}</button>
          }
        </div>
      }

      @if (state() === 'loading') {
        <p class="muted">Chargement…</p>
      } @else if (state() === 'error') {
        <p class="empty">Impossible de charger les cours pour le moment.</p>
      } @else if (!courses().length) {
        <div class="empty">
          <strong>Aucun cours disponible pour l'instant.</strong>
          <span>Les manuels publiés par ton établissement apparaîtront ici.</span>
        </div>
      } @else {
        <div class="grid">
          @for (c of filtered(); track c.id) {
            <a class="course" [routerLink]="c.id">
              <app-course-cover [course]="c" />
              <span class="c-title">{{ c.title }}</span>
              <span class="c-meta">
                {{ level(c.level) }}@if (c.section) { · {{ c.section }} }@if (c.pageCount) { · {{ c.pageCount }} pages }
              </span>
            </a>
          } @empty {
            <p class="muted">Aucun cours ne correspond à ta recherche.</p>
          }
        </div>
      }
    </div>
  `,
  styles: `
    :host { display: block; height: 100%; overflow-y: auto; background: var(--bg); }
    .page { max-width: 1200px; margin: 0 auto; padding: 1.5rem 1rem 2rem; }
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 1rem;
      h1 { margin: 0; font-size: 1.5rem; }
      p { margin: 0.2rem 0 0; color: var(--muted); }
      input {
        width: min(20rem, 100%);
        padding: 0.55rem 0.8rem;
        border: 1px solid var(--border);
        border-radius: 999px;
        background: var(--surface);
        font: inherit;
        font-size: 0.9rem;
      }
    }
    .chips {
      display: flex;
      gap: 0.4rem;
      margin-bottom: 1.25rem;
      overflow-x: auto;
      padding-bottom: 0.25rem;
      button {
        flex: none;
        padding: 0.35rem 0.85rem;
        border: 1px solid var(--border);
        border-radius: 999px;
        background: var(--surface);
        font: inherit;
        font-size: 0.85rem;
        cursor: pointer;
        &.on { background: var(--primary); border-color: var(--primary); color: #fff; }
      }
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 1.5rem 1.25rem;
    }
    .course {
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      color: inherit;
      text-decoration: none;
      app-course-cover { transition: transform 0.15s, box-shadow 0.15s; border-radius: 10px; }
      &:hover app-course-cover, &:focus-visible app-course-cover { transform: translateY(-3px); box-shadow: 0 10px 24px rgba(15, 23, 42, 0.18); }
    }
    .c-title { margin-top: 0.3rem; font-weight: 600; font-size: 0.9rem; line-height: 1.3; }
    .c-meta { font-size: 0.78rem; color: var(--muted); }
    .muted { color: var(--muted); }
    .empty {
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
      padding: 3rem 1rem;
      text-align: center;
      color: var(--muted);
      strong { color: var(--text); }
    }
    @media (max-width: 640px) {
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem 0.75rem; }
      .page { padding-top: 1rem; }
    }
  `,
})
export class CoursesPage {
  private readonly api = inject(DocumentsApi);

  protected readonly courses = signal<LibraryDocument[]>([]);
  protected readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly search = signal('');
  protected readonly subject = signal<string | null>(null);
  protected readonly level = levelLabel;

  protected readonly subjects = computed(() => [...new Set(this.courses().map((c) => c.subject))].sort());

  protected readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    return this.courses().filter(
      (c) => (!this.subject() || c.subject === this.subject()) && (!q || `${c.title} ${c.subject}`.toLowerCase().includes(q)),
    );
  });

  constructor() {
    this.api.listCourses().subscribe({
      next: (list) => {
        this.courses.set([...list].sort((a, b) => a.subject.localeCompare(b.subject) || a.title.localeCompare(b.title)));
        this.state.set('ready');
      },
      error: () => this.state.set('error'),
    });
  }
}
