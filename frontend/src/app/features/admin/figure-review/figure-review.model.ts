/**
 * Shape of data/output/visual_elements_review.json (prepare_review.py) --
 * read-only input for the figure review UI. One row per detected visual
 * element candidate; classification_hint/confidence/likely_text_box are
 * SOFT hints from the deterministic pipeline, never a verified label --
 * see prepare_review.py / evaluate_visual_elements.py.
 */

export type ClassificationHint = 'figure' | 'text_only' | 'ambiguous';

export type Bbox = [number, number, number, number];

export interface FigureCandidateRaw {
  candidate_id: string;
  pdf_page: number;
  type: string;
  classification_hint: ClassificationHint;
  hint_meaning: string;
  hint_explanation: string;
  confidence: number;
  refinement_uncertain: boolean;
  likely_text_box: boolean;
  seed_bbox: Bbox;
  refined_bbox: Bbox;
  bbox: Bbox;
  image_path: string | null;
  needs_review: boolean;
}

export interface FigureReviewReport {
  note: string;
  total_candidates: number;
  counts_by_hint: Record<ClassificationHint, number>;
  candidates: FigureCandidateRaw[];
}

export type FigureReviewDecision = 'VALIDATED' | 'REJECTED' | 'NEEDS_CORRECTION';
export type FigureReviewStatus = 'UNREVIEWED' | FigureReviewDecision;

/**
 * Frontend view-model, adapted from FigureCandidateRaw (camelCase, and
 * `type` surfaces classification_hint -- the raw `type` field is always
 * the literal string "candidate", not useful for display/filtering).
 */
export interface FigureReviewItem {
  candidateId: string;
  page: number;
  seedBbox?: Bbox;
  refinedBbox: Bbox;
  type?: ClassificationHint;
  confidence?: number;
  likelyTextBox?: boolean;
  needsReview?: boolean;
  cropPath: string | null;
  status: FigureReviewStatus;
  reviewedAt?: string;
}

export function toFigureReviewItem(raw: FigureCandidateRaw): Omit<FigureReviewItem, 'status' | 'reviewedAt'> {
  return {
    candidateId: raw.candidate_id,
    page: raw.pdf_page,
    seedBbox: raw.seed_bbox,
    refinedBbox: raw.refined_bbox,
    type: raw.classification_hint,
    confidence: raw.confidence,
    likelyTextBox: raw.likely_text_box,
    needsReview: raw.needs_review,
    cropPath: raw.image_path,
  };
}
