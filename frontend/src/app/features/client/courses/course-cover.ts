import { Component, computed, input } from '@angular/core';
import { LibraryDocument } from '../../../core/documents/document.model';

const SUBJECT_COLORS: Record<string, [string, string]> = {
  Mathématiques: ['#4f46e5', '#7c3aed'],
  Physique: ['#0e7490', '#0891b2'],
  Chimie: ['#0f766e', '#14b8a6'],
  'Sciences de la vie et de la Terre': ['#15803d', '#65a30d'],
  Informatique: ['#1d4ed8', '#0284c7'],
  Technologie: ['#475569', '#64748b'],
  Économie: ['#b45309', '#d97706'],
  Gestion: ['#a16207', '#ca8a04'],
  Philosophie: ['#7e22ce', '#a855f7'],
  Français: ['#be123c', '#e11d48'],
  Arabe: ['#9f1239', '#db2777'],
  Anglais: ['#c2410c', '#ea580c'],
};

/** Generated book cover (no cover image is uploaded yet): subject gradient + title. */
@Component({
  selector: 'app-course-cover',
  template: `
    <div class="cover" [style.background]="background()">
      <span class="subject">{{ course().subject }}</span>
      <span class="title">{{ course().title }}</span>
      @if (course().metadata['tome']; as tome) {
        <span class="tome">Tome {{ tome }}</span>
      }
    </div>
  `,
  styles: `
    :host { display: block; }
    .cover {
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      gap: 0.3rem;
      aspect-ratio: 3 / 4;
      padding: 1rem;
      border-radius: 6px 10px 10px 6px;
      color: #fff;
      overflow: hidden;
      box-shadow: inset 6px 0 0 rgba(0, 0, 0, 0.18);
    }
    .cover::before {
      content: '';
      position: absolute;
      top: -20%;
      right: -30%;
      width: 80%;
      aspect-ratio: 1;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.12);
    }
    .subject { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.85; }
    .title {
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
      font-size: 1rem;
      font-weight: 700;
      line-height: 1.25;
    }
    .tome {
      align-self: flex-start;
      padding: 0.1rem 0.5rem;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.2);
      font-size: 0.72rem;
      font-weight: 600;
    }
  `,
})
export class CourseCover {
  readonly course = input.required<LibraryDocument>();

  protected readonly background = computed(() => {
    const [a, b] = SUBJECT_COLORS[this.course().subject] ?? ['#334155', '#64748b'];
    return `linear-gradient(145deg, ${a}, ${b})`;
  });
}
