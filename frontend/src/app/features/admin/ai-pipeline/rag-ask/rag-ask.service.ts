import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../../environments/environment';
import { AnswerResultRaw, AskRequest } from './rag-ask.model';

/** Calls the FastAPI /api/v1/ask endpoint (data/src/api/) -- proxied in dev
 * via proxy.conf.json's more specific "/api/v1" entry, same relative-URL
 * convention as HttpDocumentsApi's own environment.apiUrl usage. */
@Injectable({ providedIn: 'root' })
export class RagAskService {
  private readonly http = inject(HttpClient);
  private readonly api = environment.aiApiUrl;

  ask(request: AskRequest): Observable<AnswerResultRaw> {
    return this.http.post<AnswerResultRaw>(`${this.api}/ask`, request);
  }
}
