from streaminspector.poc import run_poc


def test_end_to_end_poc(tmp_path):
    database_path = run_poc(tmp_path)

    assert database_path.exists()
    assert database_path.stat().st_size > 0
