/** Mirrors data/schema/answer_result.schema.json / the FastAPI POST /api/v1/ask
 * response exactly (data/src/api/schemas.py::AnswerResultResponse). */

export type AnswerStatus = 'ANSWERED' | 'INSUFFICIENT_CONTEXT' | 'CONFLICTING_CONTEXT' | 'VALIDATION_FAILED';

export interface AskRequest {
  chapter_id: string;
  query: string;
}

export interface SupportingChunkRaw {
  chunk_id: string;
  chapter_id: string;
  section_id: string | null;
  subsection_id: string | null;
  pdf_pages: number[];
}

export interface GroundingRaw {
  context_chunk_count: number;
  cited_chunk_count: number;
  has_uncertain_source: boolean;
  has_review_required_source: boolean;
}

export interface ProvenanceRaw {
  chapter_id: string;
  source_chunks_hash: string | null;
}

export interface ModelMetadataRaw {
  provider: string;
  model: string;
  model_revision: string | null;
}

export interface GenerationConfigRaw {
  temperature: number;
  max_output_tokens: number;
  seed: number | null;
}

export interface GenerationMetadataRaw {
  prompt_version: string;
  generation_config: GenerationConfigRaw;
  generated_at: string;
}

export interface AnswerResultRaw {
  answer: string;
  status: AnswerStatus;
  supporting_chunks: SupportingChunkRaw[];
  warnings: string[];
  grounding: GroundingRaw;
  provenance: ProvenanceRaw;
  model_metadata: ModelMetadataRaw;
  generation_metadata: GenerationMetadataRaw;
}

export const ANSWER_STATUS_LABELS: Record<AnswerStatus, string> = {
  ANSWERED: 'Answered',
  INSUFFICIENT_CONTEXT: 'Insufficient context',
  CONFLICTING_CONTEXT: 'Conflicting context',
  VALIDATION_FAILED: 'Validation failed',
};

/** "sec-a · sub-b · p.5, 6" — null subsection/pages handled without an awkward inline template. */
export function chunkLocationLabel(chunk: SupportingChunkRaw): string {
  const parts = [chunk.section_id, chunk.subsection_id].filter((v): v is string => !!v);
  if (chunk.pdf_pages.length) parts.push(`p.${chunk.pdf_pages.join(', ')}`);
  return parts.join(' · ');
}
