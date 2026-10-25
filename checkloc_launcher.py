import subprocess
import sys
from pathlib import Path


def main() -> None:
    app_path = Path(__file__).resolve().with_name("app.py")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            *sys.argv[1:],
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
