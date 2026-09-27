import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { environment } from '../environments/environment';
import { routes } from './app.routes';
import { BlobStore, IndexedDbBlobStore } from './core/documents/blob-store';
import { DocumentsApi } from './core/documents/documents-api';
import { HttpDocumentsApi } from './core/documents/http-documents-api';
import { LocalDocumentsApi } from './core/documents/local-documents-api';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // XHR backend so the PDF upload can report progress (Fetch can't).
    provideHttpClient(withXhr()),
    { provide: DocumentsApi, useClass: environment.documents.mock ? LocalDocumentsApi : HttpDocumentsApi },
    { provide: BlobStore, useClass: IndexedDbBlobStore },
  ]
};
