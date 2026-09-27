package com.eduassistant.review;

import static org.hamcrest.Matchers.hasSize;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/** End-to-end through the real HTTP layer -- this is what the Angular
 * frontend actually calls (see figure-association.service.ts). */
@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class FigureKnowledgeReviewControllerTest {

    private static final String BASE = "/api/chapters/math-4eme-tome1-ch01/reviews";

    @Autowired
    private MockMvc mvc;

    @Test
    void validateSavesAConfirmedReview() throws Exception {
        mvc.perform(put(BASE + "/figure_001")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"status":"CONFIRMED","knowledgeItemId":"math-4eme-tome1-ch01-thm-017","relation":"illustrates"}
                    """))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("CONFIRMED"))
            .andExpect(jsonPath("$.knowledgeItemId").value("math-4eme-tome1-ch01-thm-017"))
            .andExpect(jsonPath("$.figureId").value("figure_001"))
            .andExpect(jsonPath("$.chapterId").value("math-4eme-tome1-ch01"));
    }

    @Test
    void rejectSavesARejectedReviewWithNoItem() throws Exception {
        mvc.perform(put(BASE + "/figure_002")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"status":"REJECTED"}
                    """))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("REJECTED"))
            .andExpect(jsonPath("$.knowledgeItemId").doesNotExist());
    }

    @Test
    void chooseAnotherSavesAReassignedReview() throws Exception {
        mvc.perform(put(BASE + "/figure_003")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"status":"REASSIGNED","knowledgeItemId":"it-2"}
                    """))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("REASSIGNED"));
    }

    @Test
    void missingStatusIsRejectedWithBadRequest() throws Exception {
        mvc.perform(put(BASE + "/figure_004")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
            .andExpect(status().isBadRequest());
    }

    @Test
    void getReturnsEveryPersistedReviewForTheChapter() throws Exception {
        mvc.perform(put(BASE + "/figure_005").contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"it-1\"}"));
        mvc.perform(put(BASE + "/figure_006").contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"REJECTED\"}"));

        mvc.perform(get(BASE))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$", hasSize(2)));
    }

    @Test
    void updatingTheSameFigureReplacesTheChosenItemWithoutDuplicating() throws Exception {
        mvc.perform(put(BASE + "/figure_007").contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"question-12\"}"));
        mvc.perform(put(BASE + "/figure_007").contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"question-13\"}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.knowledgeItemId").value("question-13"));

        mvc.perform(get(BASE)).andExpect(jsonPath("$", hasSize(1)));
    }

    @Test
    void deleteUndoesAReview() throws Exception {
        mvc.perform(put(BASE + "/figure_008").contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"it-1\"}"));
        mvc.perform(delete(BASE + "/figure_008")).andExpect(status().isNoContent());
        mvc.perform(get(BASE)).andExpect(jsonPath("$", hasSize(0)));
    }

    @Test
    void deleteAllResetsTheWholeChapter() throws Exception {
        mvc.perform(put(BASE + "/figure_009").contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"CONFIRMED\",\"knowledgeItemId\":\"it-1\"}"));
        mvc.perform(put(BASE + "/figure_010").contentType(MediaType.APPLICATION_JSON).content("{\"status\":\"REJECTED\"}"));

        mvc.perform(delete(BASE)).andExpect(status().isNoContent());
        mvc.perform(get(BASE)).andExpect(jsonPath("$", hasSize(0)));
    }
}
