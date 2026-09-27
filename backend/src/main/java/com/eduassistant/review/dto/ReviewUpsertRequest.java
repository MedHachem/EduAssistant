package com.eduassistant.review.dto;

import com.eduassistant.review.ReviewStatus;
import jakarta.validation.constraints.NotNull;

/**
 * Body for PUT /api/chapters/{chapterId}/reviews/{figureId}.
 * chapterId/figureId come from the URL path, not the body, so the two
 * can never disagree with each other.
 */
public record ReviewUpsertRequest(
    @NotNull(message = "status is required") ReviewStatus status,
    String knowledgeItemId,
    String relation,
    String reviewedBy
) {
}
