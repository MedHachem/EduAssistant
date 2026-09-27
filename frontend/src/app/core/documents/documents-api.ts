import { Observable } from 'rxjs';
import { DocumentStatus, LibraryDocument, UploadDocumentRequest, UploadEvent } from './document.model';

/**
 * Access to the document library.
 * - HttpDocumentsApi: real backend (Spring Boot → Azure Blob Storage).
 * - LocalDocumentsApi: in-browser stand-in (localStorage + IndexedDB) until the backend exists.
 * Selected by environment.documents.mock (see app.config.ts).
 */
export abstract class DocumentsApi {
  // ---- admin ----
  abstract list(): Observable<LibraryDocument[]>;
  abstract upload(req: UploadDocumentRequest): Observable<UploadEvent>;
  abstract setStatus(id: string, status: DocumentStatus): Observable<LibraryDocument>;
  abstract delete(id: string): Observable<void>;

  // ---- student ----
  /** Published books, shown to students as courses. */
  abstract listCourses(): Observable<LibraryDocument[]>;
  abstract getCourse(id: string): Observable<LibraryDocument>;

  // ---- both ----
  /**
   * URL to display / download the PDF. On Azure this is a short-lived read-only SAS URL
   * issued by the backend (the browser never holds storage credentials).
   */
  abstract fileUrl(id: string, which?: 'file' | 'correction'): Observable<string>;
}
