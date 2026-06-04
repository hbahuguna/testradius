from testsquad_shared.models import HealthResponse

def test_shared_model_import():
    health = HealthResponse(status="online", service="test")
    assert health.status == "online"
    assert health.service == "test"
