package com.eduassistant.review;

/**
 * Human review decision for one figure <-> knowledge item pairing.
 *
 * Reuses the EXISTING frontend vocabulary
 * (figure-association.model.ts: FigureAssociationDecision) rather than
 * inventing a new one -- see backend/README.md for why this differs
 * from the "VALIDATED/NO_MATCH" example in the original task brief.
 *
 * PENDING is intentionally NOT a value here: "no decision yet" is
 * represented by the ABSENCE of a row for (chapterId, figureId), not a
 * stored status -- see FigureKnowledgeReviewRepository.
 */
public enum ReviewStatus {
    /** The admin confirmed a knowledge item is correctly associated with the figure
     * (whether it was the algorithm's own top suggestion or one the admin picked instead). */
    CONFIRMED,
    /** The admin confirmed NO knowledge item is related to this figure. */
    REJECTED,
    /** The admin picked a different candidate than the algorithm's top suggestion,
     * but has not (yet) clicked Validate to confirm it. */
    REASSIGNED
}
