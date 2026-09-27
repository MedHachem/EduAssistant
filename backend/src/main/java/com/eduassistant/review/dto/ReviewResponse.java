package com.eduassistant.review.dto;

import com.eduassistant.review.FigureKnowledgeReview;
import com.eduassistant.review.ReviewStatus;
import java.time.Instant;

public record ReviewResponse(
    String chapterId,
    String figureId,
    String knowledgeItemId,
    String relation,
    ReviewStatus status,
    Instant reviewedAt,
    String reviewedBy
) {
    public static ReviewResponse from(FigureKnowledgeReview entity) {
        return new ReviewResponse(
            entity.getChapterId(),
            entity.getFigureId(),
            entity.getKnowledgeItemId(),
            entity.getRelation(),
            entity.getStatus(),
            entity.getReviewedAt(),
            entity.getReviewedBy()
        );
    }
}
