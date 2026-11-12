"""
Step ML-2: Automated Dataset Sourcing & Ingestion Gate
Project: eng-4k-project-ml
Downloads NASA PCoE Battery Aging Dataset (B0005, B0006, B0007, B0018)
and validates MATLAB (.mat) structure integrity.
"""

import os
import sys
import ssl
import shutil
import zipfile
import subprocess
import urllib.request
from pathlib import Path
from scipy.io import loadmat

# Official NASA Ames Prognostics Data Repository URL
NASA_DATASET_URL = "https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip"

RAW_DIR = Path("data/raw")
TARGET_CELLS = ["B0005", "B0006", "B0007", "B0018"]
EXPECTED_INNER_ZIP = "1. BatteryAgingARC-FY08Q4.zip"


def download_with_curl_or_urllib(url: str, dest_file: Path):
    """
    Downloads file using native macOS curl to bypass macOS Python proxy resolution bugs.
    Falls back to urllib with disabled proxy handling if curl is unavailable.
    """
    print(f"Downloading master dataset from NASA S3:\n--> {url}")

    # Primary Method: Native macOS curl (bypasses SCNetworkProxies bug)
    if shutil.which("curl"):
        print("Using native macOS curl transfer engine...")
        curl_cmd = [
            "curl",
            "-fSL",
            "--progress-bar",
            "-o", str(dest_file),
            url
        ]
        result = subprocess.run(curl_cmd)
        if result.returncode == 0 and dest_file.exists() and dest_file.stat().st_size > 1024 * 1024:
            print("\n [PASS] Download completed successfully via curl.")
            return
        else:
            print("\n [WARN] curl download did not complete. Falling back to direct socket streaming...")

    # Fallback Method: urllib with ProxyHandler({}) to explicitly bypass macOS system proxies
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),  # Empty dict disables macOS proxy auto-discovery
        urllib.request.HTTPSHandler(context=ssl_ctx)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Apple Silicon)"})

    with opener.open(req) as response, open(dest_file, "wb") as out_file:
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024  # 1MB chunks

        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            out_file.write(chunk)
            downloaded += len(chunk)
            if total_size > 0:
                percent = min(100.0, downloaded * 100.0 / total_size)
                bar = "=" * int(30 * percent / 100) + "-" * (30 - int(30 * percent / 100))
                sys.stdout.write(f"\rDownloading: [{bar}] {percent:.1f}% ({downloaded / (1024*1024):.1f} MB)")
                sys.stdout.flush()

    print("\n [PASS] Direct stream completed.")


def run_ingestion():
    print("=" * 65)
    print("RUNNING STEP ML-2: DATASET SOURCING & INGESTION")
    print("=" * 65)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    temp_master_zip = RAW_DIR / "temp_nasa_master.zip"
    temp_inner_zip = RAW_DIR / EXPECTED_INNER_ZIP

    # 1. Check if all target MAT files are already extracted
    all_exist = all((RAW_DIR / f"{cell}.mat").exists() for cell in TARGET_CELLS)
    if all_exist:
        print(" [INFO] All raw target cell files already exist in data/raw/. Skipping download.")
    else:
        # Download master archive
        download_with_curl_or_urllib(NASA_DATASET_URL, temp_master_zip)

        # 2. Extract inner cohort (1. BatteryAgingARC-FY08Q4.zip)
        print(f"\nExtracting '{EXPECTED_INNER_ZIP}'...")
        try:
            with zipfile.ZipFile(temp_master_zip, 'r') as master_zip:
                matching_members = [m for m in master_zip.namelist() if EXPECTED_INNER_ZIP in m]
                if not matching_members:
                    raise FileNotFoundError(f"Could not locate {EXPECTED_INNER_ZIP} inside archive.")
                
                with master_zip.open(matching_members[0]) as src, open(temp_inner_zip, "wb") as dst:
                    dst.write(src.read())
            print(" [PASS] Sub-archive extracted successfully.")

            # 3. Extract target cell MAT files
            print("Extracting target MAT files (B0005, B0006, B0007, B0018)...")
            with zipfile.ZipFile(temp_inner_zip, 'r') as inner_zip:
                for cell in TARGET_CELLS:
                    target_file = f"{cell}.mat"
                    matches = [m for m in inner_zip.namelist() if m.endswith(target_file)]
                    if matches:
                        with inner_zip.open(matches[0]) as src_mat, open(RAW_DIR / target_file, "wb") as dst_mat:
                            dst_mat.write(src_mat.read())
                        print(f"  --> Extracted: {target_file}")
                    else:
                        raise FileNotFoundError(f"Missing {target_file} inside inner archive.")
            print(" [PASS] Target cell MAT files extracted into data/raw/.")

        except Exception as e:
            print(f"[FAIL] Extraction error: {e}")
            sys.exit(1)
        finally:
            # Clean up temporary download zips
            if temp_master_zip.exists():
                temp_master_zip.unlink()
            if temp_inner_zip.exists():
                temp_inner_zip.unlink()
            print(" [PASS] Temporary download archives cleaned up.")

    # 4. Rigorous Integrity Gate
    print("\nExecuting Data Integrity Check on Target MAT Files...")
    for cell in TARGET_CELLS:
        mat_path = RAW_DIR / f"{cell}.mat"
        assert mat_path.exists(), f"ERROR: File does not exist: {mat_path}"
        
        file_size_mb = mat_path.stat().st_size / (1024 * 1024)
        assert file_size_mb > 5.0, f"ERROR: {cell}.mat is suspiciously small ({file_size_mb:.2f} MB)."
        
        try:
            mat_data = loadmat(str(mat_path))
            assert cell in mat_data, f"ERROR: Key '{cell}' missing from {cell}.mat"
            cycles = mat_data[cell]['cycle'][0, 0][0]
            num_cycles = len(cycles)
            assert num_cycles > 100, f"ERROR: Insufficient cycles in {cell}: {num_cycles}"
            print(f" [VERIFIED] {cell}.mat | Size: {file_size_mb:.2f} MB | Operational Cycles: {num_cycles}")
        except Exception as e:
            print(f"[FAIL] Parse error on {cell}.mat: {e}")
            sys.exit(1)

    print("=" * 65)
    print("ALL ML-2 SANITY CHECKS PASSED: Raw NASA data ready for Step ML-3.")
    print("=" * 65)


if __name__ == "__main__":
    run_ingestion()