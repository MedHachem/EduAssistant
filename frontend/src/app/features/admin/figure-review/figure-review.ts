import { Component, ElementRef, afterRenderEffect, computed, inject, signal, viewChild } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { map } from 'rxjs';
import { pageImageUrl } from '../knowledge-review/knowledge.service';
import { findInQueue } from '../knowledge-review/review-queue';
import { cropUrl, FigureReviewService, hasSeedCrop, seedCropUrl } from './figure-review.service';
import {
  FigureReviewDecision,
  FigureReviewItem,
  FigureReviewReport,
  FigureReviewStatus,
  toFigureReviewItem,
} from './figure-review.model';
import { FigureReviewStateService } from './figure-review-state.service';

/** Matches the math-4eme-tome1-ch01-* id prefix used across the pipeline (see data/src/config.py). */
const CHAPTER_ID = 'math-4eme-tome1-ch01';

/**
 * One review "round" = one generated report + crop set (see
 * data/src/prepare_review.py / prepare_review_v3.py). Each round keeps
 * a SEPARATE localStorage key so decisions from an earlier round are
 * never overwritten or mixed with a later one -- set via the route's
 * `data.round` (see app.routes.ts); defaults to round 1 if omitted.
 */
export interface FigureReviewRound {
  reviewFile: string;
  chapterIdSuffix: string;
  roundLabel: string;
}

const ROUND_1: FigureReviewRound = {
  reviewFile: 'visual_elements_review.json',
  chapterIdSuffix: '',
  roundLabel: 'Round 1 — detection candidates (V1)',
};

type StatusFilter = 'ALL' | FigureReviewStatus;
type HintFilter = 'ALL' | 'figure' | 'text_only' | 'ambiguous';
type TriFilter = 'ALL' | 'YES' | 'NO';

export const STATUS_LABELS: Record<FigureReviewStatus, string> = {
  UNREVIEWED: 'Unreviewed',
  VALIDATED: 'Validated',
  REJECTED: 'Rejected',
  NEEDS_CORRECTION: 'Needs correction',
};

const HINT_LABELS: Record<'figure' | 'text_only' | 'ambiguous', string> = {
  figure: 'Figure',
  text_only: 'Text only',
  ambiguous: 'Ambiguous',
};

@Component({
  selector: 'app-figure-review',
  templateUrl: './figure-review.html',
  styleUrl: './figure-review.scss',
  host: { '(document:keydown)': 'onKey($event)' },
})
export class FigureReview {
  private readonly figures = inject(FigureReviewService);
  protected readonly review = inject(FigureReviewStateService);
  protected readonly round = toSignal(
    inject(ActivatedRoute).data.pipe(map((d) => (d['round'] as FigureReviewRound | undefined) ?? ROUND_1)),
    { initialValue: ROUND_1 },
  );

  private readonly listEl = viewChild<ElementRef<HTMLElement>>('list');
  private readonly panelEl = viewChild<ElementRef<HTMLElement>>('panel');

  protected readonly report = signal<FigureReviewReport | null>(null);
  protected readonly loadError = signal<string | null>(null);

  protected readonly search = signal('');
  protected readonly statusFilter = signal<StatusFilter>('ALL');
  protected readonly hintFilter = signal<HintFilter>('ALL');
  protected readonly likelyTextBoxFilter = signal<TriFilter>('ALL');
  protected readonly needsReviewFilter = signal<TriFilter>('ALL');
  protected readonly pendingOnly = signal(true);
  protected readonly showSource = signal(false);
  protected readonly showSeedCompare = signal(false);
  protected readonly selectedId = signal<string | null>(null);

  protected readonly statusLabels = STATUS_LABELS;
  protected readonly hintLabels = HINT_LABELS;
  protected readonly statusOptions: StatusFilter[] = ['ALL', 'UNREVIEWED', 'VALIDATED', 'REJECTED', 'NEEDS_CORRECTION'];
  protected readonly hintOptions: HintFilter[] = ['ALL', 'figure', 'text_only', 'ambiguous'];
  protected readonly cropUrl = cropUrl;
  protected readonly seedCropUrl = seedCropUrl;
  protected readonly hasSeedCrop = hasSeedCrop;
  protected readonly pageImageUrl = pageImageUrl;

  /** Static per-candidate data (from the generated report), computed once per load. */
  private readonly baseRows = computed(() => {
    const report = this.report();
    if (!report) return [];
    return report.candidates.map((c) => toFigureReviewItem(c));
  });

  /** Base rows + current local review status. */
  protected readonly rows = computed<FigureReviewItem[]>(() => {
    const state = this.review.state();
    return this.baseRows().map((r) => ({
      ...r,
      status: state[r.candidateId]?.status ?? 'UNREVIEWED',
      reviewedAt: state[r.candidateId]?.reviewed_at,
    }));
  });

  protected readonly stats = computed(() => {
    const rows = this.rows();
    const validated = rows.filter((r) => r.status === 'VALIDATED').length;
    const rejected = rows.filter((r) => r.status === 'REJECTED').length;
    const needsCorrection = rows.filter((r) => r.status === 'NEEDS_CORRECTION').length;
    const reviewed = validated + rejected + needsCorrection;
    const total = rows.length;
    return {
      total,
      reviewed,
      unreviewed: total - reviewed,
      validated,
      rejected,
      needsCorrection,
      percent: total ? (100 * reviewed) / total : 0,
    };
  });

  protected readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    const status = this.statusFilter();
    const hint = this.hintFilter();
    const textBox = this.likelyTextBoxFilter();
    const needsReview = this.needsReviewFilter();
    return this.rows().filter(
      (r) =>
        (status === 'ALL' || r.status === status) &&
        (hint === 'ALL' || r.type === hint) &&
        (textBox === 'ALL' || (textBox === 'YES') === !!r.likelyTextBox) &&
        (needsReview === 'ALL' || (needsReview === 'YES') === !!r.needsReview) &&
        (!q || r.candidateId.toLowerCase().includes(q) || String(r.page).includes(q)),
    );
  });

  protected readonly selected = computed(() => this.rows().find((r) => r.candidateId === this.selectedId()) ?? null);

  private readonly selectedIndex = computed(() => this.filtered().findIndex((r) => r.candidateId === this.selectedId()));

  protected readonly hasPrev = computed(() => this.neighbour(-1) !== -1);
  protected readonly hasNext = computed(() => this.neighbour(1) !== -1);

  constructor() {
    const round = this.round();
    this.review.use(CHAPTER_ID + round.chapterIdSuffix);
    this.figures.load(round.reviewFile).subscribe({
      next: (report) => {
        this.report.set(report);
        const first = this.rows().find((r) => r.status === 'UNREVIEWED') ?? this.rows()[0];
        this.selectedId.set(first?.candidateId ?? null);
      },
      error: () => this.loadError.set(`Could not load /figures/${round.reviewFile}.`),
    });

    // Keep the selected row visible and start each candidate at the top of the panel.
    afterRenderEffect(() => {
      const id = this.selectedId();
      if (!id) return;
      this.listEl()?.nativeElement.querySelector(`[data-id="${id}"]`)?.scrollIntoView({ block: 'nearest' });
      this.panelEl()?.nativeElement.scrollTo({ top: 0 });
    });
  }

  protected select(id: string): void {
    this.selectedId.set(id);
  }

  protected previous(): void {
    this.go(-1);
  }

  protected next(): void {
    this.go(1);
  }

  protected decide(status: FigureReviewDecision): void {
    const current = this.selected();
    if (!current) return;
    // Snapshot the queue before the change: with a status filter, the candidate leaves the list.
    const queue = this.filtered();
    const from = queue.findIndex((r) => r.candidateId === current.candidateId);
    this.review.set(current.candidateId, status);

    const pending = (r: FigureReviewItem) =>
      r.candidateId !== current.candidateId && this.review.statusOf(r.candidateId) === 'UNREVIEWED';
    const target = findInQueue(queue, from, 1, pending, true);
    if (target !== -1) this.selectedId.set(queue[target].candidateId);
  }

  protected undo(): void {
    const current = this.selected();
    if (current) this.review.clear(current.candidateId);
  }

  protected resetAll(): void {
    if (confirm('Clear all local figure-review decisions for this chapter? The generated report/crops are not affected.')) {
      this.review.clearAll();
    }
  }

  protected setStatusFilter(value: string): void {
    this.statusFilter.set(value as StatusFilter);
  }

  protected onKey(e: KeyboardEvent): void {
    const target = e.target as HTMLElement | null;
    if (e.ctrlKey || e.metaKey || e.altKey || target?.closest('input, textarea, select')) return;
    const actions: Record<string, () => void> = {
      j: () => this.next(),
      ArrowDown: () => this.next(),
      k: () => this.previous(),
      ArrowUp: () => this.previous(),
      v: () => this.decide('VALIDATED'),
      r: () => this.decide('REJECTED'),
      c: () => this.decide('NEEDS_CORRECTION'),
      u: () => this.undo(),
    };
    const action = actions[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  }

  private go(dir: 1 | -1): void {
    const i = this.neighbour(dir);
    if (i !== -1) this.selectedId.set(this.filtered()[i].candidateId);
  }

  private neighbour(dir: 1 | -1): number {
    const list = this.filtered();
    const from = this.selectedIndex();
    const accept = (r: FigureReviewItem) => !this.pendingOnly() || r.status === 'UNREVIEWED';
    const start = from === -1 ? (dir === 1 ? -1 : list.length) : from;
    return findInQueue(list, start, dir, accept);
  }
}
