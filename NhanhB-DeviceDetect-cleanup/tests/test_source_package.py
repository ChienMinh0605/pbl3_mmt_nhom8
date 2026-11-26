from subprocess import run
from zipfile import ZipFile

from scripts.package import package_source


def test_source_archive_contains_only_the_committed_snapshot(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", "-q"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("committed source")
    run(["git", "add", "README.md"], cwd=repo, check=True)
    run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org",
         "commit", "-qm", "fixture"],
        cwd=repo,
        check=True,
    )
    readme.write_text("local edit")
    (repo / ".env.local").write_text("local fixture")
    (repo / "capture.jsonl").write_text("untracked fixture")
    (repo / "capture-link").symlink_to(repo / "capture.jsonl")
    output = tmp_path / "output" / "source.zip"

    package_source(repo, output)

    with ZipFile(output) as archive:
        assert [name for name in archive.namelist() if not name.endswith("/")] == [
            "wifi-device-sherlock/README.md"
        ]
        assert archive.read("wifi-device-sherlock/README.md") == b"committed source"
