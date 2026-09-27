import { Injectable, signal } from '@angular/core';
import { FigureReviewDecision, FigureReviewStatus } from './figure-review.model';

export interface FigureReviewEntry {
  status: FigureReviewDecision;
  reviewed_at: string;
}

/** candidate id → local review decision */
export type FigureReviewState = Record<string, FigureReviewEntry>;

const STORAGE_PREFIX = 'edu.figure-review.v1.';

/**
 * Prototype-only review state for FIGURE candidates, kept in a SEPARATE
 * localStorage key from the knowledge-item review state
 * (edu.knowledge-review.v1.*, see ../knowledge-review/review-state.service.ts)
 * -- figure review and text review are independent decisions over
 * independent data, and must never be mixed:
 *
 *   generated visual_elements_review.json (read-only)  +  review overlay (this service, localStorage)
 *                                        ↓
 *                                    Angular UI
 *
 * One localStorage entry per chapter: `edu.figure-review.v1.<chapter_id>`.
 * The generated JSON/crops are never modified.
 */
@Injectable({ providedIn: 'root' })
export class FigureReviewStateService {
  private key: string | null = null;
  private readonly entries = signal<FigureReviewState>({});

  readonly state = this.entries.asReadonly();

  /** Switch to the review overlay of a given chapter. */
  use(chapterId: string): void {
    this.key = STORAGE_PREFIX + chapterId;
    this.entries.set(this.read());
  }

  statusOf(candidateId: string): FigureReviewStatus {
    return this.entries()[candidateId]?.status ?? 'UNREVIEWED';
  }

  set(candidateId: string, status: FigureReviewDecision): void {
    this.update((s) => ({ ...s, [candidateId]: { status, reviewed_at: new Date().toISOString() } }));
  }

  clear(candidateId: string): void {
    this.update(({ [candidateId]: _removed, ...rest }) => rest);
  }

  clearAll(): void {
    this.update(() => ({}));
  }

  private update(fn: (s: FigureReviewState) => FigureReviewState): void {
    this.entries.update(fn);
    if (this.key) {
      localStorage.setItem(this.key, JSON.stringify(this.entries()));
    }
  }

  private read(): FigureReviewState {
    if (!this.key) return {};
    try {
      return JSON.parse(localStorage.getItem(this.key) ?? '{}') as FigureReviewState;
    } catch {
      return {};
    }
  }
}
