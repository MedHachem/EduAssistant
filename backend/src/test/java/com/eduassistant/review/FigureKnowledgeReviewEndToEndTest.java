package com.eduassistant.review;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.SpringBootTest.WebEnvironment;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

/**
 * Deliberately NOT @Transactional (unlike the other two test classes):
 * a test-managed transaction silently supplies the ambient transaction
 * that repository.deleteByChapterId(...) needs, which would have
 * masked the real "no EntityManager transaction available" bug this
 * class caught during manual end-to-end verification against a real
 * running instance (see backend/README.md). This class exercises the
 * app exactly the way the real Angular frontend and a real restart
 * would: real HTTP, real (non-test) transaction boundaries.
 *
 * Also serves as the "complete flow with Chapter 1 data" check from
 * the task brief -- 19 figures, mixed decisions, restore, update,
 * reset -- using realistic (not hardcoded-in-production-code) IDs.
 */
@SpringBootTest(webEnvironment = WebEnvironment.RANDOM_PORT)
class FigureKnowledgeReviewEndToEndTest {

    private static final String CHAPTER = "math-4eme-tome1-ch01";

    @Autowired
    private TestRestTemplate rest;

    @Autowired
    private FigureKnowledgeReviewRepository repository;

    @AfterEach
    void cleanUp() {
        repository.deleteAll();
    }

    private String base() {
        return "/api/chapters/" + CHAPTER + "/reviews";
    }

    @Test
    void deleteAllWorksAgainstARealRunningInstanceNotJustAWrappedTestTransaction() {
        put("figure_001", "{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"it-1\"}");

        ResponseEntity<Void> response = rest.exchange(base(), HttpMethod.DELETE, null, Void.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
        assertThat(get()).isEmpty();
    }

    @Test
    void deleteOneWorksAgainstARealRunningInstance() {
        put("figure_001", "{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"it-1\"}");

        ResponseEntity<Void> response = rest.exchange(base() + "/figure_001", HttpMethod.DELETE, null, Void.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
        assertThat(get()).isEmpty();
    }

    @Test
    void nineteenChapter1FiguresCanBeReviewedRestoredUpdatedAndReset() {
        // 13 VALIDATED-shaped figures confirmed as-is, 6 NEEDS_CORRECTION-shaped
        // figures reviewed with a mix of confirm/reject/reassign -- mirrors the
        // real Chapter 1 figure count from data/output/final_figures/index.json,
        // using synthetic item ids (this test owns its own fixture data, not
        // production code).
        for (int i = 1; i <= 13; i++) {
            put(String.format("figure_%03d", i), String.format(
                "{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"item-%d\",\"relation\":\"illustrates\"}", i));
        }
        put("figure_014", "{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"item-14\"}");
        put("figure_015", "{\"status\":\"REJECTED\"}");
        put("figure_016", "{\"status\":\"REASSIGNED\",\"knowledgeItemId\":\"item-16-alt\"}");
        put("figure_017", "{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"item-17\"}");
        put("figure_018", "{\"status\":\"REJECTED\"}");
        put("figure_019", "{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"item-19\"}");

        // "Browser refresh": GET restores every decision.
        List<Object> restored = get();
        assertThat(restored).hasSize(19);

        // Admin changes their mind on figure_019 -> a different item; must update, not duplicate.
        put("figure_019", "{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"item-19-corrected\"}");
        assertThat(get()).hasSize(19);

        long confirmed = repository.findByChapterId(CHAPTER).stream()
            .filter(r -> r.getStatus() == ReviewStatus.CONFIRMED).count();
        long rejected = repository.findByChapterId(CHAPTER).stream()
            .filter(r -> r.getStatus() == ReviewStatus.REJECTED).count();
        long reassigned = repository.findByChapterId(CHAPTER).stream()
            .filter(r -> r.getStatus() == ReviewStatus.REASSIGNED).count();
        assertThat(confirmed).isEqualTo(16); // figures 001-013, 014, 017, 019
        assertThat(rejected).isEqualTo(2); // figures 015, 018
        assertThat(reassigned).isEqualTo(1); // figure 016

        assertThat(repository.findByChapterIdAndFigureId(CHAPTER, "figure_019").orElseThrow().getKnowledgeItemId())
            .isEqualTo("item-19-corrected");
    }

    private void put(String figureId, String body) {
        rest.put(base() + "/" + figureId, jsonEntity(body));
    }

    private org.springframework.http.HttpEntity<String> jsonEntity(String body) {
        var headers = new org.springframework.http.HttpHeaders();
        headers.setContentType(org.springframework.http.MediaType.APPLICATION_JSON);
        return new org.springframework.http.HttpEntity<>(body, headers);
    }

    @SuppressWarnings("unchecked")
    private List<Object> get() {
        return rest.getForObject(base(), List.class);
    }
}
