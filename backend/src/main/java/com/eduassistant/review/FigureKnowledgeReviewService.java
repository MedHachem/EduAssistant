package com.eduassistant.review;

import com.eduassistant.review.dto.ReviewUpsertRequest;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Every write path is explicitly @Transactional: derived repository
 * delete methods (deleteByChapterId(AndFigureId)) execute as
 * find-then-remove-each-entity and throw
 * TransactionRequiredException without an ambient transaction. This
 * was caught by a manual end-to-end run against a real running
 * instance, not by the (transactional-by-default) test suite -- see
 * backend/README.md.
 */
@Service
@Transactional
public class FigureKnowledgeReviewService {

    private final FigureKnowledgeReviewRepository repository;
    private final Clock clock;

    public FigureKnowledgeReviewService(FigureKnowledgeReviewRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<FigureKnowledgeReview> findByChapter(String chapterId) {
        return repository.findByChapterId(chapterId);
    }

    /**
     * Create-or-update the ONE review row for (chapterId, figureId).
     * This is the single entry point ALL of Validate / Reject / Choose-
     * another map to on the frontend -- e.g. changing "Figure 1 ->
     * Question 12" to "Figure 1 -> Question 13" is just another call
     * here with the same (chapterId, figureId) and a different
     * knowledgeItemId, updating the existing row rather than adding a
     * second one (see FigureKnowledgeReviewRepository's unique lookup +
     * the table's DB-level unique constraint as a concurrency backstop).
     */
    public FigureKnowledgeReview upsert(String chapterId, String figureId, ReviewUpsertRequest request) {
        FigureKnowledgeReview review = repository.findByChapterIdAndFigureId(chapterId, figureId)
            .orElseGet(() -> new FigureKnowledgeReview(chapterId, figureId));

        review.setStatus(request.status());
        review.setKnowledgeItemId(request.knowledgeItemId());
        review.setRelation(request.relation());
        review.setReviewedBy(request.reviewedBy());
        review.setReviewedAt(Instant.now(clock));

        return repository.save(review);
    }

    public void delete(String chapterId, String figureId) {
        repository.deleteByChapterIdAndFigureId(chapterId, figureId);
    }

    public void deleteAll(String chapterId) {
        repository.deleteByChapterId(chapterId);
    }
}
