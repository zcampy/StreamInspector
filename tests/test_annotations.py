from streaminspector.core.events import EventBus
from streaminspector.storage import FlowAnnotationData, StorageService


def test_annotation_defaults_and_persistence(tmp_path):
    storage = StorageService(EventBus(), tmp_path / "annotations.sqlite3")
    try:
        assert storage.get_annotation("flow-1") == FlowAnnotationData()

        storage.save_annotation(
            "flow-1",
            favorite=True,
            tags="api, error, api",
            note="  revisar respuesta  ",
        )

        assert storage.get_annotation("flow-1") == FlowAnnotationData(
            favorite=True,
            tags="api, error",
            note="revisar respuesta",
        )
        assert storage.favorite_flow_ids() == {"flow-1"}
    finally:
        storage.close()
