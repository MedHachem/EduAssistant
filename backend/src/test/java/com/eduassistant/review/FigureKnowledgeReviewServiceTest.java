package com.eduassistant.review;

import static org.assertj.core.api.Assertions.assertThat;

import com.eduassistant.review.dto.ReviewUpsertRequest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@Transactional
class FigureKnowledgeReviewServiceTest {

    private static final String CHAPTER = "math-4eme-tome1-ch01";

    @Autowired
    private FigureKnowledgeReviewService service;

    @Autowired
    private FigureKnowledgeReviewRepository repository;

    @Test
    void confirmedReviewIsPersistedWithTheChosenItem() {
        service.upsert(CHAPTER, "figure_012", new ReviewUpsertRequest(
            ReviewStatus.CONFIRMED, "math-4eme-tome1-ch01-thm-017", "illustrates", "admin@school.tn"));

        FigureKnowledgeReview saved = repository.findByChapterIdAndFigureId(CHAPTER, "figure_012").orElseThrow();
        assertThat(saved.getStatus()).isEqualTo(ReviewStatus.CONFIRMED);
        assertThat(saved.getKnowledgeItemId()).isEqualTo("math-4eme-tome1-ch01-thm-017");
        assertThat(saved.getRelation()).isEqualTo("illustrates");
        assertThat(saved.getReviewedBy()).isEqualTo("admin@school.tn");
        assertThat(saved.getReviewedAt()).isNotNull();
    }

    @Test
    void rejectedReviewHasNoKnowledgeItem() {
        service.upsert(CHAPTER, "figure_013", new ReviewUpsertRequest(ReviewStatus.REJECTED, null, null, null));

        FigureKnowledgeReview saved = repository.findByChapterIdAndFigureId(CHAPTER, "figure_013").orElseThrow();
        assertThat(saved.getStatus()).isEqualTo(ReviewStatus.REJECTED);
        assertThat(saved.getKnowledgeItemId()).isNull();
    }

    @Test
    void reassignedReviewStoresTheNewlyChosenItem() {
        service.upsert(CHAPTER, "figure_014", new ReviewUpsertRequest(
            ReviewStatus.CONFIRMED, "math-4eme-tome1-ch01-act-030", "supports", null));
        service.upsert(CHAPTER, "figure_014", new ReviewUpsertRequest(
            ReviewStatus.REASSIGNED, "math-4eme-tome1-ch01-act-031", "supports", null));

        FigureKnowledgeReview saved = repository.findByChapterIdAndFigureId(CHAPTER, "figure_014").orElseThrow();
        assertThat(saved.getStatus()).isEqualTo(ReviewStatus.REASSIGNED);
        assertThat(saved.getKnowledgeItemId()).isEqualTo("math-4eme-tome1-ch01-act-031");
    }

    @Test
    void retrievingReviewsReturnsEveryDecisionForThatChapter() {
        service.upsert(CHAPTER, "figure_001", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "it-1", null, null));
        service.upsert(CHAPTER, "figure_002", new ReviewUpsertRequest(ReviewStatus.REJECTED, null, null, null));
        service.upsert("some-other-chapter", "figure_001", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "it-x", null, null));

        var reviews = service.findByChapter(CHAPTER);

        assertThat(reviews).hasSize(2);
        assertThat(reviews).extracting(FigureKnowledgeReview::getFigureId).containsExactlyInAnyOrder("figure_001", "figure_002");
    }

    @Test
    void updatingAnExistingReviewChangesTheKnowledgeItemInPlace() {
        // "Figure 1 -> Question 12" then changed to "Figure 1 -> Question 13"
        service.upsert(CHAPTER, "figure_020", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "question-12", null, null));
        service.upsert(CHAPTER, "figure_020", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "question-13", null, null));

        FigureKnowledgeReview saved = repository.findByChapterIdAndFigureId(CHAPTER, "figure_020").orElseThrow();
        assertThat(saved.getKnowledgeItemId()).isEqualTo("question-13");
    }

    @Test
    void savingTheSameFigureTwiceNeverCreatesADuplicateRow() {
        service.upsert(CHAPTER, "figure_030", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "it-1", null, null));
        service.upsert(CHAPTER, "figure_030", new ReviewUpsertRequest(ReviewStatus.REJECTED, null, null, null));
        service.upsert(CHAPTER, "figure_030", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "it-2", null, null));

        assertThat(service.findByChapter(CHAPTER)).filteredOn(r -> r.getFigureId().equals("figure_030")).hasSize(1);
    }

    @Test
    void deletingAReviewRestoresItToPendingByRemovingTheRow() {
        service.upsert(CHAPTER, "figure_040", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "it-1", null, null));
        service.delete(CHAPTER, "figure_040");

        assertThat(repository.findByChapterIdAndFigureId(CHAPTER, "figure_040")).isEmpty();
    }

    @Test
    void deleteAllOnlyClearsTheGivenChapter() {
        service.upsert(CHAPTER, "figure_050", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "it-1", null, null));
        service.upsert("other-chapter", "figure_050", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "it-1", null, null));

        service.deleteAll(CHAPTER);

        assertThat(service.findByChapter(CHAPTER)).isEmpty();
        assertThat(service.findByChapter("other-chapter")).hasSize(1);
    }

    @Test
    void sameFigureIdInDifferentChaptersAreIndependentReviews() {
        service.upsert("chapter-a", "figure_001", new ReviewUpsertRequest(ReviewStatus.CONFIRMED, "it-a", null, null));
        service.upsert("chapter-b", "figure_001", new ReviewUpsertRequest(ReviewStatus.REJECTED, null, null, null));

        assertThat(repository.findByChapterIdAndFigureId("chapter-a", "figure_001").orElseThrow().getStatus())
            .isEqualTo(ReviewStatus.CONFIRMED);
        assertThat(repository.findByChapterIdAndFigureId("chapter-b", "figure_001").orElseThrow().getStatus())
            .isEqualTo(ReviewStatus.REJECTED);
    }
}
