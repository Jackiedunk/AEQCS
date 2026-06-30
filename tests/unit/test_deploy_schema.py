from deploy.init_db import SCHEMA_SQL


def test_doc_chunks_schema_keeps_chunks_attached_to_uploaded_docs():
    assert "doc_id BIGINT NOT NULL REFERENCES uploaded_docs(doc_id) ON DELETE CASCADE" in SCHEMA_SQL
    assert "seq INT NOT NULL" in SCHEMA_SQL
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_chunks_doc_seq" in SCHEMA_SQL
