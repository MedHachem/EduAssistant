# AI Education — MVP

Assistant pédagogique IA (RAG) pour élèves. Cas pilote unique : 4ème année secondaire (Tunisie),
Mathématiques Tome 1, chapitre "Continuité et limites".

## Stack

- **Frontend** : Angular
- **Backend** : Spring Boot / Java 17 / Spring Security / JWT
- **DB** : PostgreSQL + pgvector
- **Service IA/RAG** : Python (FastAPI)
- **LLM** : API Claude

```
Frontend → Spring Boot API → PostgreSQL
                           → AI/RAG service (Python) → PostgreSQL+pgvector → Claude API
```

## Structure

```
ai-education/
├── backend/            (Spring Boot)
├── ai-service/         (Python : app/, ingestion/)
├── data/               (manuels sources, ex. math-4eme-tome1/source.pdf)
├── frontend/           (Angular)
├── docker-compose.yml  (Postgres + pgvector)
├── .env.example
└── README.md
```

## Setup

1. Copier `.env.example` vers `.env` et remplir les valeurs (jamais commiter `.env`).
2. Lancer PostgreSQL+pgvector : `docker compose up -d db` (à partir de la Phase 2).

## Avancement (phases du MVP)

- [x] 1. Init repo
- [ ] 2. PostgreSQL + pgvector (docker-compose)
- [ ] 3. Pipeline Python : PDF → extraction → pages.json
- [ ] 4. Nettoyage du texte
- [ ] 5. Parsing structurel
- [ ] 6. Chunking
- [ ] 7. Embeddings → pgvector
- [ ] 8. Test de la recherche vectorielle (10 questions)
- [ ] 9. Service RAG
- [ ] 10. Connexion Claude
- [ ] 11. POST /api/ai/ask
- [ ] 12. Interface chat (Angular)
- [ ] 13. Exercices
- [ ] 14. Indices
- [ ] 15. Corrections
- [ ] 16. QCM
- [ ] 17. Notation
- [ ] 18. Progression + recommandations (règles simples)
- [ ] 19. Gamification
- [ ] 20. Tests end-to-end
