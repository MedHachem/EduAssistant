export const environment = {
  production: false,
  apiUrl: '/api',
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
