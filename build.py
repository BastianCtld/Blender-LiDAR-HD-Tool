import subprocess
import sys
import zipfile
import tomllib
import re
import os
from pathlib import Path

addon_directory = Path(__file__).parent / "BlenderLiDARHD"
wheels_directory = addon_directory / "wheels"
requirements = Path(__file__).parent / "requirements-wheels.txt"
manifest_path = addon_directory / "blender_manifest.toml"

blender_python_version = "3.13"
supported_platforms = [
    "macosx_11_0_arm64",
    "manylinux_2_17_x86_64",
    "win_amd64",
]

def download_wheels():
    wheels_directory.mkdir(exist_ok=True)
    for platform in supported_platforms:
        print(f"Dowloading wheels for {platform}")
        subprocess.run([
            sys.executable, "-m", "pip", "download",
            "-r", str(requirements),
            "--only-binary=:all:",
            f"--python-version={blender_python_version}",
            "--implementation=cp",
            "--abi=cp313",
            f"--platform={platform}",
            "-d", str(wheels_directory),
            "--no-dependencies",
        ], check=True)
        
def update_manifest_wheels():
    text = manifest_path.read_text()
    wheels: list[str] = [f'  "./wheels/{wheel.name}"' for wheel in wheels_directory.glob('*.whl')]
    wheels_str = "wheels = [\n" + ",\n".join(wheels) + ",\n]"
    # regex wizardry
    text = re.sub(r"wheels = \[.*?\]", wheels_str, text, flags=re.DOTALL)
    manifest_path.write_text(text)

def build_zip():
    blender_manifest = tomllib.loads(manifest_path.read_text())
    zip_path = Path(f"lidarhd-{blender_manifest["version"]}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in [path for path in addon_directory.glob('**') if not any(part.startswith('.') for part in path.parts)]:
            if "__pycache__" in file.parts:
                continue
            zf.write(file, file.relative_to(addon_directory.parent))
    print(f"built {zip_path}")

if __name__ == "__main__":
    download_wheels()
    update_manifest_wheels()
    build_zip()
    