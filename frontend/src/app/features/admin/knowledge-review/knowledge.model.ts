/**
 * Shape of the Knowledge Base JSON produced by the Python pipeline
 * (data/output/knowledge/*.json). Read-only input for the review UI.
 */

export type ValidationStatus = 'REVIEW_REQUIRED' | 'VALIDATED' | 'REJECTED';

export interface KnowledgeDocument {
  id: string;
  title: string;
  subject: string;
  level: string;
  country: string;
  source_pdf: string;
  total_pages: number;
}

export interface KnowledgeChapter {
  id: string;
  document_id: string;
  number: number;
  title: string;
  pdf_page_start: number;
  pdf_page_end: number;
}

export interface KnowledgeSection {
  id: string;
  chapter_id: string;
  label: string;
  title: string;
  pdf_page_start: number;
  pdf_page_end: number;
}

export interface KnowledgeSubsection {
  id: string;
  section_id: string;
  label: string;
  title: string;
  pdf_page_start: number;
  pdf_page_end: number;
}

export interface ItemSource {
  document_id: string;
  pdf_pages: number[];
  reconstructed_sources: string[];
  bloc_type: string;
  bloc_numero: string | null;
  continues_from_previous_page: boolean;
  continues_on_next_page: boolean;
}

export interface FigureLink {
  pdf_page: number;
  reconstructed_figure_id: string;
  candidate_id: string | null;
  figure_status_in_source: string;
  match_status: string;
  image_path?: string | null;
}

export interface ItemLinks {
  definitions: string[];
  theorems: string[];
  properties: string[];
  formulas: string[];
  methods: string[];
  exercises: string[];
  figures: FigureLink[];
}

export interface Question {
  label: string | null;
  text: string | null;
  sub_questions: Question[];
}

export interface QcmChoice {
  label: string;
  text: string;
  marked_correct_in_source: boolean | null;
}

export interface Correction {
  present_in_source: boolean;
  content: string | null;
}

export interface ExerciseDetails {
  statement: string | null;
  questions: Question[];
  correction: Correction | null;
  qcm_choices: QcmChoice[] | null;
}

export interface Uncertainty {
  has_uncertain_markers: boolean;
  has_gap_markers: boolean;
  uncertain_spans: unknown[];
}

export interface KnowledgeItem {
  id: string;
  type: string;
  document_id: string;
  chapter_id: string;
  section_id: string | null;
  subsection_id: string | null;
  title: string | null;
  source: ItemSource;
  original_content: string;
  proof: string | null;
  concepts: unknown[];
  links: ItemLinks | null;
  exercise_details: ExerciseDetails | null;
  extracted_from: unknown;
  uncertainty: Uncertainty;
  validation_status: ValidationStatus;
  validation_history: unknown[];
  created_at: string;
  schema_version: string;
}

export interface KnowledgeBase {
  document: KnowledgeDocument;
  chapter: KnowledgeChapter;
  sections: KnowledgeSection[];
  subsections: KnowledgeSubsection[];
  concepts: unknown[];
  items: KnowledgeItem[];
}
