import { Injectable } from '@angular/core';

/** Binary storage used by LocalDocumentsApi (the Azure Blob container stand-in). */
export abstract class BlobStore {
  abstract put(key: string, blob: Blob): Promise<void>;
  abstract get(key: string): Promise<Blob | undefined>;
  abstract delete(key: string): Promise<void>;
}

const DB_NAME = 'edu-documents';
const STORE = 'blobs';

/** IndexedDB-backed store: PDFs survive reloads, up to the browser's storage quota. */
@Injectable()
export class IndexedDbBlobStore extends BlobStore {
  private db: Promise<IDBDatabase> | null = null;

  async put(key: string, blob: Blob): Promise<void> {
    await this.tx('readwrite', (s) => s.put(blob, key));
  }

  async get(key: string): Promise<Blob | undefined> {
    return this.tx<Blob | undefined>('readonly', (s) => s.get(key));
  }

  async delete(key: string): Promise<void> {
    await this.tx('readwrite', (s) => s.delete(key));
  }

  private open(): Promise<IDBDatabase> {
    this.db ??= new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return this.db;
  }

  private async tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest): Promise<T> {
    const db = await this.open();
    return new Promise<T>((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result as T);
      req.onerror = () => reject(req.error);
    });
  }
}

/** In-memory store (tests). */
@Injectable()
export class MemoryBlobStore extends BlobStore {
  private readonly map = new Map<string, Blob>();
  async put(key: string, blob: Blob): Promise<void> {
    this.map.set(key, blob);
  }
  async get(key: string): Promise<Blob | undefined> {
    return this.map.get(key);
  }
  async delete(key: string): Promise<void> {
    this.map.delete(key);
  }
}
