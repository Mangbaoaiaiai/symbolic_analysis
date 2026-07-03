from setuptools import find_packages, setup


setup(
    name="symbolicana",
    version="0.1.0",
    description="Symbolic execution, path ranking, and path equivalence verification.",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.10,<3.14",
    install_requires=[
        "angr",
        "z3-solver",
    ],
    entry_points={
        "console_scripts": [
            "symbolicana=symbolic_analysis.cli:main",
        ],
    },
)
