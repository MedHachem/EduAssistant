package com.eduassistant.review;

import com.eduassistant.review.dto.ReviewResponse;
import com.eduassistant.review.dto.ReviewUpsertRequest;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/**
 * Chapter-generic by construction: chapterId is always a path variable,
 * never a hardcoded value -- this same controller serves Chapter 1,
 * Chapter 2, etc. without changes.
 */
@RestController
@RequestMapping("/api/chapters/{chapterId}/reviews")
public class FigureKnowledgeReviewController {

    private final FigureKnowledgeReviewService service;

    public FigureKnowledgeReviewController(FigureKnowledgeReviewService service) {
        this.service = service;
    }

    /** Restores every saved decision for this chapter -- called once when the review page opens. */
    @GetMapping
    public List<ReviewResponse> findAll(@PathVariable String chapterId) {
        return service.findByChapter(chapterId).stream().map(ReviewResponse::from).toList();
    }

    /** Validate / Reject / Choose-another all call this -- create-or-update, never duplicates. */
    @PutMapping("/{figureId}")
    public ReviewResponse upsert(
        @PathVariable String chapterId,
        @PathVariable String figureId,
        @Valid @RequestBody ReviewUpsertRequest request
    ) {
        return ReviewResponse.from(service.upsert(chapterId, figureId, request));
    }

    /** Undo. */
    @DeleteMapping("/{figureId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable String chapterId, @PathVariable String figureId) {
        service.delete(chapterId, figureId);
    }

    /** Reset all. */
    @DeleteMapping
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteAll(@PathVariable String chapterId) {
        service.deleteAll(chapterId);
    }
}
