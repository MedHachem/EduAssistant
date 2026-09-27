import { Component, ElementRef, afterRenderEffect, computed, inject, signal, viewChild } from '@angular/core';
import { KnowledgeBase, KnowledgeItem, ValidationStatus } from './knowledge.model';
import { STATUS_LABELS, excerpt, formatPages, normalize, shortId, typeLabel } from './knowledge-format';
import { KnowledgeService } from './knowledge.service';
import { ItemDetail } from './item-detail/item-detail';
import { MathText } from '../../../shared/math-text/math-text';
import { findInQueue } from './review-queue';
import { ReviewDecision, ReviewStateService } from './review-state.service';

interface Row {
  item: KnowledgeItem;
  status: ValidationStatus;
  shortId: string;
  type: string;
  title: string | null;
  preview: string;
  section: string;
  sectionTitle: string;
  pages: string;
  haystack: string;
}

type StatusFilter = 'ALL' | ValidationStatus;

@Component({
  selector: 'app-knowledge-review',
  imports: [ItemDetail, MathText],
  templateUrl: './knowledge-review.html',
  styleUrl: './knowledge-review.scss',
  host: { '(document:keydown)': 'onKey($event)' },
})
export class KnowledgeReview {
  private readonly knowledge = inject(KnowledgeService);
  protected readonly review = inject(ReviewStateService);

  private readonly listEl = viewChild<ElementRef<HTMLElement>>('list');
  private readonly panelEl = viewChild<ElementRef<HTMLElement>>('panel');

  protected readonly kb = signal<KnowledgeBase | null>(null);
  protected readonly loadError = signal<string | null>(null);

  protected readonly search = signal('');
  protected readonly statusFilter = signal<StatusFilter>('ALL');
  protected readonly typeFilter = signal<string>('ALL');
  /** Previous / Next only visit REVIEW_REQUIRED items when on (default). */
  protected readonly pendingOnly = signal(true);
  protected readonly raw = signal(false);
  protected readonly showSource = signal(false);
  protected readonly selectedId = signal<string | null>(null);

  protected readonly statusLabels = STATUS_LABELS;
  protected readonly typeLabel = typeLabel;
  protected readonly statusOptions: StatusFilter[] = ['ALL', 'REVIEW_REQUIRED', 'VALIDATED', 'REJECTED'];

  /** Static per-item data, computed once per load. */
  private readonly baseRows = computed(() => {
    const kb = this.kb();
    if (!kb) return [];
    const sections = new Map(kb.sections.map((s) => [s.id, s]));
    const subsections = new Map(kb.subsections.map((s) => [s.id, s]));
    return kb.items.map((item) => {
      const sec = item.section_id ? sections.get(item.section_id) : undefined;
      const sub = item.subsection_id ? subsections.get(item.subsection_id) : undefined;
      const sectionTitle = [sec?.title, sub?.title].filter(Boolean).join(' › ');
      return {
        item,
        shortId: shortId(item),
        type: typeLabel(item.type),
        title: item.title,
        preview: excerpt(item.original_content),
        section: sub?.label && sub.label !== sub.title ? sub.label : (sec?.label ?? '—'),
        sectionTitle,
        pages: formatPages(item.source.pdf_pages),
        haystack: normalize([item.id, item.title ?? '', item.original_content, sectionTitle].join(' ')),
      };
    });
  });

  /** Base rows + current review status (generated JSON overlaid with local review state). */
  protected readonly rows = computed<Row[]>(() => {
    const state = this.review.state();
    return this.baseRows().map((r) => ({
      ...r,
      status: state[r.item.id]?.status ?? r.item.validation_status,
    }));
  });

  protected readonly stats = computed(() => {
    const rows = this.rows();
    const validated = rows.filter((r) => r.status === 'VALIDATED').length;
    const rejected = rows.filter((r) => r.status === 'REJECTED').length;
    const reviewed = validated + rejected;
    const total = rows.length;
    return { total, validated, rejected, reviewed, remaining: total - reviewed, percent: total ? (100 * reviewed) / total : 0 };
  });

  protected readonly typeOptions = computed(() => {
    const counts = new Map<string, number>();
    for (const r of this.baseRows()) counts.set(r.item.type, (counts.get(r.item.type) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([type, count]) => ({ type, count }));
  });

  protected readonly filtered = computed(() => {
    const q = normalize(this.search().trim());
    const status = this.statusFilter();
    const type = this.typeFilter();
    return this.rows().filter(
      (r) =>
        (status === 'ALL' || r.status === status) &&
        (type === 'ALL' || r.item.type === type) &&
        (!q || r.haystack.includes(q)),
    );
  });

  protected readonly selected = computed(() => this.rows().find((r) => r.item.id === this.selectedId()) ?? null);

  private readonly selectedIndex = computed(() => this.filtered().findIndex((r) => r.item.id === this.selectedId()));

  protected readonly hasPrev = computed(() => this.neighbour(-1) !== -1);
  protected readonly hasNext = computed(() => this.neighbour(1) !== -1);

  constructor() {
    this.knowledge.load().subscribe({
      next: (kb) => {
        this.review.use(kb.chapter.id);
        this.kb.set(kb);
        const first = this.rows().find((r) => r.status === 'REVIEW_REQUIRED') ?? this.rows()[0];
        this.selectedId.set(first?.item.id ?? null);
      },
      error: () => this.loadError.set('Could not load /knowledge/chapter_01_continuite_limites.json.'),
    });

    // Keep the selected row visible and start each item at the top of the panel.
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

  protected decide(status: ReviewDecision): void {
    const current = this.selected();
    if (!current) return;
    // Snapshot the queue before the change: with a status filter, the item leaves the list.
    const queue = this.filtered();
    const from = queue.findIndex((r) => r.item.id === current.item.id);
    this.review.set(current.item.id, status);

    const pending = (r: Row) =>
      r.item.id !== current.item.id &&
      this.review.statusOf(r.item.id, r.item.validation_status) === 'REVIEW_REQUIRED';
    const target = findInQueue(queue, from, 1, pending, true);
    if (target !== -1) this.selectedId.set(queue[target].item.id);
  }

  protected undo(): void {
    const current = this.selected();
    if (current) this.review.clear(current.item.id);
  }

  protected resetAll(): void {
    if (confirm('Clear all local review decisions for this chapter? The generated JSON is not affected.')) {
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
    if (i !== -1) this.selectedId.set(this.filtered()[i].item.id);
  }

  private neighbour(dir: 1 | -1): number {
    const list = this.filtered();
    const from = this.selectedIndex();
    const accept = (r: Row) => !this.pendingOnly() || r.status === 'REVIEW_REQUIRED';
    // Selected item filtered out of the list → start from the edge.
    const start = from === -1 ? (dir === 1 ? -1 : list.length) : from;
    return findInQueue(list, start, dir, accept);
  }
}
