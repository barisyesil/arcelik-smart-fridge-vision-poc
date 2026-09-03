"""Docker olmadan tekrarlanabilir Lambda deployment paketleri oluşturur.

API paketi yalnızca proje kaynak kodunu taşır. Extractor paketi aynı kaynak
koduna ek olarak CPython 3.12 / Linux ARM64 wheel'lerini içerir. Kaynak dağıtım
(sdist) kabul edilmez; uygun wheel yoksa build açıkça başarısız olur.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

INFRA_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = INFRA_DIR.parent
SOURCE_DIR = REPO_ROOT / "src"
LOCK_FILE = INFRA_DIR / "requirements-lambda.lock"
BUILD_ROOT = INFRA_DIR / "build"
API_PACKAGE = BUILD_ROOT / "fridge-api"
EXTRACTOR_PACKAGE = BUILD_ROOT / "fridge-extractor"

MAX_UNZIPPED_BYTES = 240 * 1024 * 1024  # Lambda sınırı 250 MB; 10 MB güvenlik payı.


def _reset_build_root() -> None:
    """Yalnızca doğrulanmış `infra/build` hedefini temizle."""
    if BUILD_ROOT.parent != INFRA_DIR or BUILD_ROOT.name != "build":
        raise RuntimeError(f"Güvensiz build hedefi: {BUILD_ROOT}")
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    BUILD_ROOT.mkdir()


def _copy_source(destination: Path) -> None:
    shutil.copytree(SOURCE_DIR, destination, dirs_exist_ok=True)


def _install_extractor_dependencies() -> None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-compile",
        "--platform",
        "manylinux_2_34_aarch64",
        "--platform",
        "manylinux_2_28_aarch64",
        "--platform",
        "manylinux2014_aarch64",
        "--implementation",
        "cp",
        "--python-version",
        "3.12",
        "--abi",
        "cp312",
        "--abi",
        "abi3",
        "--abi",
        "none",
        "--only-binary=:all:",
        "--require-hashes",
        "--target",
        str(EXTRACTOR_PACKAGE),
        "-r",
        str(LOCK_FILE),
    ]
    subprocess.run(command, cwd=REPO_ROOT, check=True)

    # `pip --target` Windows'ta paketlerin CLI entry point'leri için .exe
    # launcher'ları üretir. Lambda bu yardımcı komutları kullanmaz; yalnızca
    # Python modüllerini import eder. Yanlış platform dosyalarını deployment
    # paketine taşımamak için entry point dizinini tamamen kaldır.
    scripts_dir = EXTRACTOR_PACKAGE / "bin"
    if scripts_dir.exists():
        shutil.rmtree(scripts_dir)


def _package_size(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def _validate_package(path: Path, *, extractor: bool) -> int:
    required = [
        path / "handlers" / "inventory_api.py",
        path / "handlers" / "extractor.py",
        path / "core" / "shelf_life.json",
    ]
    if extractor:
        required.extend(
            [
                path / "google" / "genai" / "__init__.py",
                path / "pydantic_core",
                path / "cryptography",
            ]
        )

    missing = [str(item.relative_to(path)) for item in required if not item.exists()]
    if missing:
        raise RuntimeError(f"Paket dosyaları eksik ({path.name}): {missing}")

    forbidden_markers = ("win_amd64", "x86_64", ".dll", ".exe", ".pyd")
    forbidden = [
        str(file.relative_to(path))
        for file in path.rglob("*")
        if file.is_file() and any(marker in file.name.lower() for marker in forbidden_markers)
    ]
    if forbidden:
        raise RuntimeError(f"Yanlış platform dosyaları ({path.name}): {forbidden}")

    size = _package_size(path)
    if size > MAX_UNZIPPED_BYTES:
        raise RuntimeError(
            f"{path.name} paketi güvenli boyut sınırını aşıyor: {size / 1024 / 1024:.1f} MB"
        )
    return size


def main() -> None:
    _reset_build_root()

    _copy_source(API_PACKAGE)
    _install_extractor_dependencies()
    _copy_source(EXTRACTOR_PACKAGE)

    api_size = _validate_package(API_PACKAGE, extractor=False)
    extractor_size = _validate_package(EXTRACTOR_PACKAGE, extractor=True)
    print(f"fridge-api: {api_size / 1024 / 1024:.1f} MB")
    print(f"fridge-extractor: {extractor_size / 1024 / 1024:.1f} MB")
    print("Lambda paketleri Linux ARM64 / Python 3.12 için hazır.")


if __name__ == "__main__":
    main()
