from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class BuildPyWithGoDatabase(_build_py):
    """Copy the GO database and its notice into wheels.

    The wheel carries only the GO table, so it gets the notice written for that
    file alone; the repository README describes resources the wheel does not ship.
    """

    def run(self) -> None:
        super().run()
        source_dir = Path(__file__).parent / "data" / "db"
        target_dir = Path(self.build_lib) / "proteomicscopylot" / "data"
        self.mkpath(str(target_dir))
        self.copy_file(str(source_dir / "all_go_terms_genes.csv"), str(target_dir / "all_go_terms_genes.csv"))
        self.copy_file(str(source_dir / "PACKAGED_README.md"), str(target_dir / "README.md"))


setup(cmdclass={"build_py": BuildPyWithGoDatabase})
