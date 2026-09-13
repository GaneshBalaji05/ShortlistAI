import unittest

from fastapi import FastAPI, HTTPException

from boolean_search import (
    BooleanSearchError,
    install_candidate_search_route,
    matches_boolean,
    parse_boolean_query,
)


JAVA = {
    "name": "Priya Menon",
    "skills": "java, spring boot, microservices, aws",
    "resume_text": "Senior Java Developer. Built Spring Boot microservices on AWS.",
    "profile_details": {"current_designation": "Java Developer"},
    "talent_pools": ["Java", "Cloud", "AWS"],
}

PYTHON_ONLY = {
    "name": "Meera Nair",
    "skills": "python, django, react, javascript, aws, rest api",
    "resume_text": "Python developer using Django, React and JavaScript on AWS.",
    "profile_details": {"current_designation": "Python Developer"},
    "talent_pools": ["Python", "Cloud", "AWS"],
}

JAVA_WITH_PYTHON = {
    "name": "Mixed Candidate",
    "skills": "java, spring boot, python",
    "resume_text": "Java and Spring Boot engineer who also uses Python.",
    "talent_pools": ["Java", "Python"],
}


class BooleanSearchTests(unittest.TestCase):
    def test_java_does_not_match_javascript(self):
        self.assertTrue(matches_boolean("Java", JAVA))
        self.assertFalse(matches_boolean("Java", PYTHON_ONLY))

    def test_quoted_phrase(self):
        self.assertTrue(matches_boolean('"Spring Boot"', JAVA))
        self.assertFalse(matches_boolean('"Spring Boot"', PYTHON_ONLY))

    def test_and_or_parentheses_not(self):
        query = 'Java AND ("Spring Boot" OR Spring) NOT Python'
        self.assertTrue(matches_boolean(query, JAVA))
        self.assertFalse(matches_boolean(query, PYTHON_ONLY))
        self.assertFalse(matches_boolean(query, JAVA_WITH_PYTHON))

    def test_or(self):
        self.assertTrue(matches_boolean("Java OR Python", JAVA))
        self.assertTrue(matches_boolean("Java OR Python", PYTHON_ONLY))

    def test_implicit_and(self):
        self.assertTrue(matches_boolean("Java Spring", JAVA))
        self.assertFalse(matches_boolean("Java Spring", PYTHON_ONLY))

    def test_all_fields_are_searchable(self):
        candidate = {"profile_details": {"preferred_location": "Chennai"}, "skills": "Java"}
        self.assertTrue(matches_boolean("Chennai AND Java", candidate))

    def test_invalid_syntax(self):
        with self.assertRaises(BooleanSearchError):
            parse_boolean_query("Java AND (")

    def test_candidate_api_route_uses_boolean_search(self):
        app = FastAPI()
        rows = [JAVA, PYTHON_ONLY, JAVA_WITH_PYTHON]

        def original_list_candidates(
            job_id=None,
            stage=None,
            q=None,
            talent_pool=None,
            min_experience=None,
            max_experience=None,
            location=None,
            notice_period=None,
        ):
            return rows

        @app.get("/api/candidates")
        def old_route(q: str | None = None):
            if not q:
                return rows
            return [row for row in rows if q.lower() in str(row).lower()]

        install_candidate_search_route(app, original_list_candidates, HTTPException)
        route = next(
            route
            for route in app.router.routes
            if getattr(route, "path", None) == "/api/candidates"
            and "GET" in (getattr(route, "methods", set()) or set())
        )

        java_results = route.endpoint(q="Java")
        self.assertEqual(
            [row["name"] for row in java_results],
            ["Priya Menon", "Mixed Candidate"],
        )

        boolean_results = route.endpoint(
            q='Java AND ("Spring Boot" OR Spring) NOT Python'
        )
        self.assertEqual([row["name"] for row in boolean_results], ["Priya Menon"])

        with self.assertRaises(HTTPException) as ctx:
            route.endpoint(q="Java AND (")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
