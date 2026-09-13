import math
import unittest

from final_review import (
    PIPELINE_STAGES,
    SCORING_WEIGHTS,
    _score_wrapper_factory,
    _stable_semantic_scores_factory,
    canonical_stage,
    effective_pipeline_stage,
)


class FakeLegacy:
    @staticmethod
    def normalize(text):
        return " ".join((text or "").lower().split())

    @staticmethod
    def rating(score):
        return "Strong" if score >= 75 else "Average" if score >= 55 else "Weak"


class FinalReviewTests(unittest.TestCase):
    def test_pipeline_stage_contract(self):
        self.assertEqual(
            PIPELINE_STAGES,
            ["Applied","Contacted","Interview Scheduled","L1","L2","Selected","Hired","Dropped"],
        )
        self.assertEqual(canonical_stage("Sourced"), "Applied")
        self.assertEqual(canonical_stage("Joined"), "Hired")
        self.assertEqual(canonical_stage("Rejected"), "Dropped")

    def test_effective_pipeline_stage_uses_round_progress(self):
        self.assertEqual(effective_pipeline_stage({"stage":"Screened","profile_details":{"l1_status":"Scheduled"}}), "Interview Scheduled")
        self.assertEqual(effective_pipeline_stage({"stage":"Screened","profile_details":{"l1_status":"Cleared","l2_status":"Pending Scheduling"}}), "L1")
        self.assertEqual(effective_pipeline_stage({"stage":"Screened","profile_details":{"l1_status":"Cleared","l2_status":"Cleared"}}), "L2")
        self.assertEqual(effective_pipeline_stage({"stage":"Offered","profile_details":{"l1_status":"Cleared","l2_status":"Cleared"}}), "Selected")
        self.assertEqual(effective_pipeline_stage({"stage":"Joined","profile_details":{}}), "Hired")
        self.assertEqual(effective_pipeline_stage({"stage":"Rejected","profile_details":{}}), "Dropped")

    def test_semantic_scoring_is_batch_independent(self):
        stable = _stable_semantic_scores_factory(FakeLegacy)
        jd = "Java Spring Boot microservices engineer"
        resume = "Five years building Java Spring Boot microservices"
        alone = stable(jd, [resume])[0]
        in_batch = stable(jd, ["Python Django React developer", resume, "QA Selenium engineer"])[1]
        self.assertAlmostEqual(alone, in_batch, places=12)

    def test_score_wrapper_recomputes_from_explainable_components(self):
        def base_score(_jd, _resume, _sim):
            return {
                "score": 1.0,
                "rating": "Weak",
                "semantic_fit": 80.0,
                "skill_coverage": 90.0,
                "experience_fit": 100.0,
                "recent_evidence": 50.0,
                "evidence": [],
            }

        wrapped = _score_wrapper_factory(FakeLegacy, base_score)
        result = wrapped("jd", "resume", 0.4)
        expected = round(
            80 * SCORING_WEIGHTS["semantic_fit"] / 100
            + 90 * SCORING_WEIGHTS["skill_coverage"] / 100
            + 100 * SCORING_WEIGHTS["experience_fit"] / 100
            + 50 * SCORING_WEIGHTS["recent_evidence"] / 100,
            1,
        )
        self.assertTrue(math.isclose(result["score"], expected))
        self.assertIn("weighted_components", result)
        self.assertIn("calculation", result)
        self.assertEqual(result["methodology_version"], "stable-v2")


if __name__ == "__main__":
    unittest.main()
