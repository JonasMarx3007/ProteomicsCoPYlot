from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class BuildPyWithGoDatabase(_build_py):
    """Copy the GO database and its existing notice into wheels."""

    def run(self) -> None:
        super().run()
        source_dir = Path(__file__).parent / "data" / "db"
        target_dir = Path(self.build_lib) / "proteomicscopylot" / "data"
        self.mkpath(str(target_dir))
        for filename in ("all_go_terms_genes.csv", "README.md"):
            self.copy_file(str(source_dir / filename), str(target_dir / filename))


setup(cmdclass={"build_py": BuildPyWithGoDatabase})
