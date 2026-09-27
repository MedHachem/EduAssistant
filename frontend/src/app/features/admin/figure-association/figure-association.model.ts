/**
 * Shape of data/output/<chapter_id>/associations/figure_knowledge.json
 * (associate_figures_knowledge.py) -- read-only input for the review UI.
 * See data/schema/figure_knowledge_association.md for the full design.
 */

export type AssociationDecision = 'AUTO_MATCH' | 'REVIEW_REQUIRED' | 'NO_MATCH';

/**
 * The admin-facing confidence tier for a decision. The raw score and
 * signal breakdown (same_page, reading_order_proximity, ...) are
 * algorithm internals -- never shown in the main review UI, per the
 * design brief ("the admin must never see V1/V2/V3/V4, density valley,
 * adaptive ink mask, connected components, algorithm internals").
 */
export type ConfidenceTier = 'High' | 'Medium' | 'Low';

export const CONFIDENCE_BY_DECISION: Record<AssociationDecision, ConfidenceTier> = {
  AUTO_MATCH: 'High',
  REVIEW_REQUIRED: 'Medium',
  NO_MATCH: 'Low',
};

export interface AssociationSignals {
  same_page: boolean;
  neighboring_page: boolean;
  same_section: boolean;
  same_subsection: boolean;
  reading_order_proximity: number;
}

export interface AssociationCandidateRaw {
  association_id: string;
  item_id: string;
  item_type: string;
  relation: string;
  score: number;
  signals: AssociationSignals;
}

export interface FigureAssociationRaw {
  figure_id: string;
  chapter_id: string;
  source_page: number;
  candidate_image: string;
  decision: AssociationDecision;
  review_status: string | null;
  chosen_association_id: string | null;
  chosen_item_id: string | null;
  relation: string | null;
  score: number | null;
  candidates: AssociationCandidateRaw[];
}

export interface AssociationSummary {
  total_figures: number;
  auto_match: number;
  review_required: number;
  no_match: number;
}

export interface AssociationFile {
  chapter_id: string;
  algorithm_version: string;
  generated_at: string;
  summary: AssociationSummary;
  pipeline_status: string;
  associations: FigureAssociationRaw[];
}

/** Human review decision, stored locally (see figure-association-state.service.ts). */
export type FigureAssociationDecision = 'CONFIRMED' | 'REJECTED' | 'REASSIGNED';
export type FigureAssociationReviewStatus = 'PENDING' | FigureAssociationDecision;

export const REVIEW_STATUS_LABELS: Record<FigureAssociationReviewStatus, string> = {
  PENDING: 'Pending review',
  CONFIRMED: 'Confirmed',
  REJECTED: 'Rejected',
  REASSIGNED: 'Reassigned',
};

/** One candidate item, adapted for display (title/preview resolved
 * against the knowledge base -- see figure-association.service.ts).
 * Deliberately carries NO score/confidence of its own: only the
 * overall figure-level decision (see FigureAssociationRow.confidence)
 * is shown to the admin -- ranking individual alternates by a number
 * would expose algorithm internals the brief explicitly hides. */
export interface CandidateView {
  itemId: string;
  itemType: string;
  relation: string;
  title: string;
  preview: string;
}

/** Frontend view-model for one figure's association row. */
export interface FigureAssociationRow {
  figureId: string;
  sourcePage: number;
  imagePath: string;
  decision: AssociationDecision;
  confidence: ConfidenceTier;
  candidates: CandidateView[];
  /** Effective status: human override if one exists, else derived from `decision`. */
  reviewStatus: FigureAssociationReviewStatus;
  /** Effective chosen item: human override if one exists, else the algorithm's own pick. */
  chosenItemId: string | null;
  reviewedAt?: string;
}
