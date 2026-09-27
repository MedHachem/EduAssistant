export interface PipelineStageInfo {
  title: string;
  description: string;
  steps: string[];
  /** Python scripts in data/src this stage will run. */
  scripts: string[];
}

/** Stages of "Build AI Pipeline" not implemented yet (Knowledge Base uses the review page). */
export const PIPELINE_STAGES: Record<'ocr' | 'imageValidation' | 'rag', PipelineStageInfo> = {
  ocr: {
    title: 'OCR',
    description: 'Turn an uploaded PDF into clean, structured text.',
    steps: [
      'Native PDF text extraction, Tesseract OCR for scanned pages',
      'Mechanical cleaning (whitespace / Unicode, no content change)',
      'Reconstruction with Claude from the page image (LaTeX, structure)',
      'Validation report and pages flagged for review',
    ],
    scripts: ['extract_pdf_text.py', 'clean_text.py', 'reconstruct.py', 'validate_reconstruction.py', 'validate_with_claude.py'],
  },
  imageValidation: {
    title: 'Image Validation',
    description: 'Detect figures, graphs and tables, and validate the crops before linking them to KnowledgeItems.',
    steps: [
      'Detect visual elements on each page',
      'Extract and refine figure candidates',
      'Automatic quality evaluation',
      'Manual review of uncertain figures',
    ],
    scripts: ['detect_visual_elements.py', 'extract_figure_candidates.py', 'refine_visual_elements.py', 'evaluate_visual_elements.py', 'prepare_review.py'],
  },
  rag: {
    title: 'RAG',
    description: 'Index validated KnowledgeItems so the AI Teacher can answer from the official content.',
    steps: ['Chunking of validated items', 'Embeddings → PostgreSQL + pgvector', 'Retrieval quality test set', 'Connection to the AI Teacher'],
    scripts: [],
  },
};
