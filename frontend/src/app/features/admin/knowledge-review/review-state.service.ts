import { Injectable, signal } from '@angular/core';
import { ValidationStatus } from './knowledge.model';

export type ReviewDecision = Exclude<ValidationStatus, 'REVIEW_REQUIRED'>;

export interface ReviewEntry {
  status: ReviewDecision;
  reviewed_at: string;
}

/** item id → local review decision */
export type ReviewState = Record<string, ReviewEntry>;

const STORAGE_PREFIX = 'edu.knowledge-review.v1.';

/**
 * Prototype-only review state, kept SEPARATE from the generated KnowledgeItems:
 *
 *   generated KnowledgeItem (read-only JSON)  +  review overlay (this service, localStorage)
 *                                  ↓
 *                              Angular UI
 *
 * One localStorage entry per chapter: `edu.knowledge-review.v1.<chapter_id>`.
 * The generated JSON file is never modified.
 */
@Injectable({ providedIn: 'root' })
export class ReviewStateService {
  private key: string | null = null;
  private readonly entries = signal<ReviewState>({});

  readonly state = this.entries.asReadonly();

  /** Switch to the review overlay of a given chapter. */
  use(chapterId: string): void {
    this.key = STORAGE_PREFIX + chapterId;
    this.entries.set(this.read());
  }

  statusOf(itemId: string, generated: ValidationStatus): ValidationStatus {
    return this.entries()[itemId]?.status ?? generated;
  }

  set(itemId: string, status: ReviewDecision): void {
    this.update((s) => ({ ...s, [itemId]: { status, reviewed_at: new Date().toISOString() } }));
  }

  clear(itemId: string): void {
    this.update(({ [itemId]: _removed, ...rest }) => rest);
  }

  clearAll(): void {
    this.update(() => ({}));
  }

  private update(fn: (s: ReviewState) => ReviewState): void {
    this.entries.update(fn);
    if (this.key) {
      localStorage.setItem(this.key, JSON.stringify(this.entries()));
    }
  }

  private read(): ReviewState {
    if (!this.key) return {};
    try {
      return JSON.parse(localStorage.getItem(this.key) ?? '{}') as ReviewState;
    } catch {
      return {};
    }
  }
}
