from app.graph.nodes.visa_worker import visa_worker
from app.models import Trip


def test_visa_worker_does_not_treat_origin_as_nationality():
    result = visa_worker(
        {
            "trip": Trip(origin="Bangladesh", destination="Thailand"),
            "research_results": {},
        },
        config={},
    )

    guidance = result["research_results"]["visa"]
    assert "travel from Bangladesh to Thailand" in guidance
    assert "does not establish passport nationality" in guidance
    assert "Bangladesh travelers" not in guidance
