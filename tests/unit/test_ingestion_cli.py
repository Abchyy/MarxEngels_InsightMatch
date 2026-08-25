from pathlib import Path

from tests.helpers import write_pdf

from marx_engels.corpus_registry.ids import expected_filename
from marx_engels.ingestion.cli import main
from marx_engels.ingestion.config import CorpusSettings


def _ten_volumes(root: Path) -> None:
    for number in range(1, 11):
        write_pdf(root / expected_filename(number), [f"v{number} p{page}" for page in range(1, 5)])


def test_verify_corpus_accepts_example_manifest(tmp_path: Path) -> None:
    assert (
        main(
            [
                "verify-corpus",
                "--manifest",
                "corpora/marx_engels_collected_works_cn/manifest.example.yaml",
                "--data-root",
                str(tmp_path / "corpus"),
                "--asset-root",
                str(tmp_path / "missing-pdfs"),
            ]
        )
        == 0
    )


def test_inventory_and_preflight_cli(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assets = tmp_path / "pdf"
    data = tmp_path / "data"
    assets.mkdir()
    _ten_volumes(assets)
    assert main(["inventory", "--asset-root", str(assets), "--data-root", str(data)]) == 0
    assert main(["preflight", "--asset-root", str(assets), "--data-root", str(data)]) == 0
    output = capsys.readouterr().out
    assert "v01" in output
    assert data.joinpath("reports", "preflight.json").is_file()
    assert data.joinpath("source_records").exists()
    assert main(["status", "--data-root", str(data), "--asset-root", str(assets)]) == 0


def test_settings_do_not_require_token_for_local_commands(tmp_path: Path) -> None:
    settings = CorpusSettings(
        pdf_asset_root=tmp_path, corpus_data_root=tmp_path / "out", mineru_api_token=None
    )
    assert settings.token_configured() is False


def test_ingest_sqlite_cli(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from tests.helpers import seed_completed_all_run
    from tests.integration.test_assemble import _work_pages

    from marx_engels.ingestion.assemble import assemble_corpus
    from marx_engels.ingestion.paths import CorpusLayout

    data = tmp_path / "data"
    seed_completed_all_run(data, volume_pages={1: _work_pages()}, chunk_size=3)
    assemble_corpus(CorpusLayout(data), extraction_run_id="run_test_all")
    sqlite = tmp_path / "corpus.db"
    assert (
        main(
            [
                "ingest-sqlite",
                "--data-root",
                str(data),
                "--sqlite",
                str(sqlite),
                "--replace",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "ingest-sqlite" in output
    assert "outbox=0" in output
    assert sqlite.is_file()
