import { KnowledgeItem, ValidationStatus } from './knowledge.model';
import { tokenize } from '../../../shared/math-text/math-text';

const TYPE_LABELS: Record<string, string> = {
  activity: 'Activity',
  exercise: 'Exercise',
  theorem: 'Theorem',
  definition: 'Definition',
  property: 'Property',
  example: 'Example',
  remark: 'Remark',
  method: 'Method',
  formula: 'Formula',
};

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type.charAt(0).toUpperCase() + type.slice(1);
}

export const STATUS_LABELS: Record<ValidationStatus, string> = {
  REVIEW_REQUIRED: 'Review required',
  VALIDATED: 'Validated',
  REJECTED: 'Rejected',
};

/** [20, 21, 22] → "20–22", [9, 11] → "9, 11" */
export function formatPages(pages: number[]): string {
  if (!pages.length) return '—';
  const contiguous = pages.every((p, i) => i === 0 || p === pages[i - 1] + 1);
  return contiguous && pages.length > 1
    ? `${pages[0]}–${pages[pages.length - 1]}`
    : pages.join(', ');
}

/** "math-4eme-tome1-ch01-act-009" → "act-009" */
export function shortId(item: KnowledgeItem): string {
  const prefix = `${item.chapter_id}-`;
  return item.id.startsWith(prefix) ? item.id.slice(prefix.length) : item.id;
}

/**
 * One-line preview for the list, used when the item has no title. Rendered
 * through <app-math-text>, so $inline$/$$display$$ delimiters are kept
 * intact -- truncation only ever shortens plain-text segments (via
 * tokenize(), the same boundaries math-text.ts renders from), so a math
 * expression is never cut in half and handed to KaTeX unterminated.
 */
export function excerpt(text: string, max = 90): string {
  const flat = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  let out = '';
  for (const seg of tokenize(flat)) {
    const piece = seg.kind === 'display' ? `$$${seg.value}$$` : seg.kind === 'inline' ? `$${seg.value}$` : seg.value;
    if (out.length + piece.length <= max) {
      out += piece;
      continue;
    }
    if (seg.kind === 'text') {
      const room = max - out.length - 1; // reserve 1 char for the ellipsis
      if (room > 0) out += piece.slice(0, room);
    }
    // A math segment that doesn't fit whole is dropped entirely, never cut mid-expression.
    return out + '…';
  }
  return out;
}

/** Lower-case, accent-insensitive form for local search. */
export function normalize(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

export function basename(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}
