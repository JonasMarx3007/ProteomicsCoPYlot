from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class BuildPyWithGoDatabase(_build_py):
    """Copy the GO databases (human, mouse) and their notice into wheels.

    The wheel carries only the GO tables, so it gets the notice written for those
    files alone; the repository README describes resources the wheel does not ship.
    """

    def run(self) -> None:
        super().run()
        source_dir = Path(__file__).parent / "data" / "db"
        target_dir = Path(self.build_lib) / "proteomicscopylot" / "data"
        self.mkpath(str(target_dir))
        for filename in ("all_go_terms_genes.csv", "all_go_terms_genes_mouse.csv"):
            self.copy_file(str(source_dir / filename), str(target_dir / filename))
        self.copy_file(str(source_dir / "PACKAGED_README.md"), str(target_dir / "README.md"))


setup(cmdclass={"build_py": BuildPyWithGoDatabase})
