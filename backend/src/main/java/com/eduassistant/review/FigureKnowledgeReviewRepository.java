package com.eduassistant.review;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface FigureKnowledgeReviewRepository extends JpaRepository<FigureKnowledgeReview, Long> {

    Optional<FigureKnowledgeReview> findByChapterIdAndFigureId(String chapterId, String figureId);

    List<FigureKnowledgeReview> findByChapterId(String chapterId);

    void deleteByChapterIdAndFigureId(String chapterId, String figureId);

    void deleteByChapterId(String chapterId);
}
