import { HttpClient, HttpEventType } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, filter, map } from 'rxjs';
import { environment } from '../../../environments/environment';
import { DocumentStatus, LibraryDocument, UploadDocumentRequest, UploadEvent } from './document.model';
import { DocumentsApi } from './documents-api';

/**
 * Backend contract (to be implemented by the Spring Boot API):
 *
 *   GET    /api/admin/documents                         → LibraryDocument[]
 *   POST   /api/admin/documents        multipart: file, correction?, metadata (JSON: { type, status, ...fields })
 *                                                       → LibraryDocument   (PDF stored in Azure Blob)
 *   PATCH  /api/admin/documents/{id}   { status }       → LibraryDocument
 *   DELETE /api/admin/documents/{id}                    → 204 (also deletes the blobs)
 *   GET    /api/courses                                 → LibraryDocument[]  (published books only)
 *   GET    /api/courses/{id}                            → LibraryDocument
 *   GET    /api/documents/{id}/file-url?which=file|correction → { url, expiresAt }  (read-only SAS URL)
 */
@Injectable()
export class HttpDocumentsApi extends DocumentsApi {
  private readonly http = inject(HttpClient);
  private readonly api = environment.apiUrl;

  list(): Observable<LibraryDocument[]> {
    return this.http.get<LibraryDocument[]>(`${this.api}/admin/documents`);
  }

  upload(req: UploadDocumentRequest): Observable<UploadEvent> {
    const body = new FormData();
    body.append('file', req.file, req.file.name);
    if (req.correction) body.append('correction', req.correction, req.correction.name);
    const metadata = { type: req.type, status: req.status, ...req.metadata };
    body.append('metadata', new Blob([JSON.stringify(metadata)], { type: 'application/json' }));

    return this.http
      .post<LibraryDocument>(`${this.api}/admin/documents`, body, { reportProgress: true, observe: 'events' })
      .pipe(
        filter((e) => e.type === HttpEventType.UploadProgress || e.type === HttpEventType.Response),
        map((e): UploadEvent =>
          e.type === HttpEventType.Response
            ? { kind: 'done', document: e.body! }
            : { kind: 'progress', percent: e.total ? Math.round((100 * e.loaded) / e.total) : 0 },
        ),
      );
  }

  setStatus(id: string, status: DocumentStatus): Observable<LibraryDocument> {
    return this.http.patch<LibraryDocument>(`${this.api}/admin/documents/${id}`, { status });
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.api}/admin/documents/${id}`);
  }

  listCourses(): Observable<LibraryDocument[]> {
    return this.http.get<LibraryDocument[]>(`${this.api}/courses`);
  }

  getCourse(id: string): Observable<LibraryDocument> {
    return this.http.get<LibraryDocument>(`${this.api}/courses/${id}`);
  }

  fileUrl(id: string, which: 'file' | 'correction' = 'file'): Observable<string> {
    return this.http
      .get<{ url: string; expiresAt: string }>(`${this.api}/documents/${id}/file-url`, { params: { which } })
      .pipe(map((r) => r.url));
  }
}
