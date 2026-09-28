export const environment = {
  production: false,
  apiUrl: '/api',
  // FastAPI (data/src/api/) -- Semantic Search / RAG Context Assembly / Gemini
  // Answer Generation, POST /api/v1/ask. A distinct prefix from apiUrl (Spring
  // Boot) because it's a separate service; proxy.conf.json routes it to a
  // different target (its own "/api/v1" entry, matched before the "/api" one).
  aiApiUrl: '/api/v1',
  // Temporary: skip real authentication until the Spring Boot auth (JWT) is ready.
  authBypass: true,
  documents: {
    // Temporary: keep the document library in the browser (localStorage + IndexedDB)
    // until the backend (Azure Blob Storage) is available.
    mock: true,
  },
  chat: {
    // WebSocket endpoint of the AI Teacher (relative paths resolve against the current host; proxied in dev).
    wsUrl: '/ws/chat',
    // Temporary: simulate the AI Teacher locally until the WebSocket API is available.
    mock: true,
  },
};
