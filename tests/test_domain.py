from traffic_tracking.domain import Detection, InferenceResult


def test_vehicle_counts_include_requested_groups() -> None:
    detections = [
        Detection(3, "motorcycle", 0.9, [0, 0, 10, 10]),
        Detection(2, "car", 0.8, [0, 0, 10, 10]),
        Detection(1, "bicycle", 0.7, [0, 0, 10, 10]),
        Detection(5, "bus", 0.6, [0, 0, 10, 10]),
        Detection(7, "truck", 0.5, [0, 0, 10, 10]),
        Detection(0, "person", 0.99, [0, 0, 10, 10]),
    ]

    assert InferenceResult(detections).counts == {
        "bicycle": 1,
        "car": 1,
        "motorcycle": 1,
        "bus": 1,
        "truck": 1,
        "other_vehicle": 3,
        "total_vehicle": 5,
    }
