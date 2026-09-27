export type DocumentType = 'book' | 'exam' | 'test';

/** DRAFT: visible to admins only. PUBLISHED: visible to students (books appear as courses). */
export type DocumentStatus = 'DRAFT' | 'PUBLISHED';

export type MetadataValue = string | number;

/** A PDF stored in the document library (Azure Blob Storage on the backend). */
export interface LibraryDocument {
  id: string;
  type: DocumentType;
  title: string;
  subject: string;
  level: string | null;
  section: string | null;
  /** All type-specific fields (see document-types.ts). */
  metadata: Record<string, MetadataValue>;
  fileName: string;
  fileSize: number;
  pageCount: number | null;
  hasCorrection: boolean;
  status: DocumentStatus;
  uploadedAt: string;
  updatedAt: string;
}

export interface UploadDocumentRequest {
  type: DocumentType;
  file: File;
  /** Separate correction PDF (exams / tests). */
  correction?: File | null;
  metadata: Record<string, MetadataValue>;
  status: DocumentStatus;
}

export type UploadEvent =
  | { kind: 'progress'; percent: number }
  | { kind: 'done'; document: LibraryDocument };
