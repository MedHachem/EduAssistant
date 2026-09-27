import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { FigureAssociationDecision, FigureAssociationReviewStatus } from './figure-association.model';

export interface FigureAssociationReviewEntry {
  status: FigureAssociationDecision;
  /** null when REJECTED (admin says no knowledge item relates to this figure). */
  chosen_item_id: string | null;
  reviewed_at: string;
}

/** figure id → local review decision */
export type FigureAssociationReviewState = Record<string, FigureAssociationReviewEntry>;

interface ReviewApiRow {
  chapterId: string;
  figureId: string;
  knowledgeItemId: string | null;
  relation: string | null;
  status: FigureAssociationDecision;
  reviewedAt: string;
  reviewedBy: string | null;
}

/**
 * Review state for figure <-> knowledge ASSOCIATIONS, backed by the
 * Spring Boot API (`backend/`, package com.eduassistant.review) --
 * see backend/README.md. This used to be a localStorage-only
 * prototype (like the sibling figure-review/knowledge-review state
 * services still are); it is now backed by
 * GET/PUT/DELETE /api/chapters/{chapterId}/reviews, and localStorage
 * is no longer used at all -- the server is the single source of
 * truth, restored on every `use(chapterId)` call (component mount /
 * page reopen) rather than read from the browser.
 *
 * The public method surface (use/statusOf/chosenItemIdOf/confirm/
 * reassign/reject/clear/clearAll/state) is UNCHANGED from the
 * localStorage version on purpose, so figure-association.ts and its
 * template did not need to change to move off localStorage.
 *
 * Writes update the in-memory signal immediately (so the UI stays
 * responsive) and fire the corresponding HTTP call in the background;
 * a failed call is logged, not silently swallowed, but does not roll
 * back the optimistic UI update -- keeping this simple was a
 * deliberate choice for this first backend (see backend/README.md);
 * a retry/reconciliation strategy is future work.
 */
@Injectable({ providedIn: 'root' })
export class FigureAssociationStateService {
  private readonly http = inject(HttpClient);
  private chapterId: string | null = null;
  private readonly entries = signal<FigureAssociationReviewState>({});

  readonly state = this.entries.asReadonly();

  /** Switch to (and load) the review overlay of a given chapter. */
  use(chapterId: string): void {
    this.chapterId = chapterId;
    this.entries.set({});
    this.http.get<ReviewApiRow[]>(`/api/chapters/${chapterId}/reviews`).subscribe({
      next: (rows) => {
        const next: FigureAssociationReviewState = {};
        for (const row of rows) {
          next[row.figureId] = {
            status: row.status,
            chosen_item_id: row.knowledgeItemId,
            reviewed_at: row.reviewedAt,
          };
        }
        this.entries.set(next);
      },
      error: (err) => console.error('Could not load saved reviews from the backend.', err),
    });
  }

  statusOf(figureId: string): FigureAssociationReviewStatus {
    return this.entries()[figureId]?.status ?? 'PENDING';
  }

  chosenItemIdOf(figureId: string, fallback: string | null): string | null {
    const entry = this.entries()[figureId];
    return entry ? entry.chosen_item_id : fallback;
  }

  /** Admin accepts the currently chosen item (the algorithm's own top
   * pick, or a previously reassigned one) as correct. */
  confirm(figureId: string, itemId: string, relation: string | null = null): void {
    this.upsert(figureId, 'CONFIRMED', itemId, relation);
  }

  /** Admin picks a DIFFERENT candidate than the algorithm's top pick. */
  reassign(figureId: string, itemId: string, relation: string | null = null): void {
    this.upsert(figureId, 'REASSIGNED', itemId, relation);
  }

  /** Admin says no knowledge item actually relates to this figure. */
  reject(figureId: string): void {
    this.upsert(figureId, 'REJECTED', null, null);
  }

  clear(figureId: string): void {
    const chapterId = this.chapterId;
    if (!chapterId) return;
    this.entries.update(({ [figureId]: _removed, ...rest }) => rest);
    this.http.delete(`/api/chapters/${chapterId}/reviews/${figureId}`).subscribe({
      error: (err) => console.error('Could not undo this review on the backend.', err),
    });
  }

  clearAll(): void {
    const chapterId = this.chapterId;
    if (!chapterId) return;
    this.entries.set({});
    this.http.delete(`/api/chapters/${chapterId}/reviews`).subscribe({
      error: (err) => console.error('Could not reset reviews on the backend.', err),
    });
  }

  private upsert(figureId: string, status: FigureAssociationDecision, chosenItemId: string | null, relation: string | null): void {
    const chapterId = this.chapterId;
    if (!chapterId) return;
    const reviewedAt = new Date().toISOString();
    this.entries.update((s) => ({ ...s, [figureId]: { status, chosen_item_id: chosenItemId, reviewed_at: reviewedAt } }));
    this.http
      .put(`/api/chapters/${chapterId}/reviews/${figureId}`, { status, knowledgeItemId: chosenItemId, relation })
      .subscribe({ error: (err) => console.error('Could not save this review on the backend.', err) });
  }
}
