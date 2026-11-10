"""Download author repositories at the commits used by CleanBench."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path("/opt/cleanbench/baselines/native/external")
SOURCES = {
    "adr": (
        "https://github.com/WelkinNi/Automatic-Data-Repair.git",
        "b3004a8980104ae5412b8dc39e609b2c1c8e439d",
        "adr/adr_repo",
        ["BigDansing_Holistic", "Daisy", "horizon", "Relative_Trust", "NADEEF-master"],
    ),
    "llunatic": (
        "https://github.com/donatellosantoro/Llunatic.git",
        "aea6ad3d9fb3a5999fbf374efeed6b40983b3ba9",
        "llunatic/upstream",
        ["lib"],
    ),
    "uniclean": (
        "https://github.com/qzkinhit/UniClean-bench-Result.git",
        "ccf388d0247d290ecc8c4c5c8905b9ad979a48f6",
        "uniclean/upstream",
        ["uniclean_cleaners"],
    ),
    "katara": (
        "https://github.com/mohamedyd/rein-benchmark.git",
        "b8a0727fdeb6d295eb88c702a344093a1d9096d1",
        "rein/rein-benchmark",
        ["cleaners/katara"],
    ),
    "cleanagent": (
        "https://github.com/sfu-db/CleanAgent.git",
        "66c10c2c1d141e7d63946f80a3f660e072d5bbe0",
        "cleanagent/CleanAgent",
        ["main.py"],
    ),
    "cocoon": (
        "https://github.com/Cocoon-Data-Transformation/cocoon.git",
        "410a4f710a93143bdf1d1b2c5c502cbb5a1d43dd",
        "cocoon/cocoon_repo",
        ["cocoon_data"],
    ),
}


def setup(name):
    url, commit, relative, paths = SOURCES[name]
    dest = ROOT / relative
    dest.mkdir(parents=True, exist_ok=True)

    def git(*args):
        subprocess.run(["git", "-C", str(dest), *args], check=True)

    git("init")
    git("remote", "add", "origin", url)
    git("sparse-checkout", "set", "--no-cone", *paths)
    git("fetch", "--filter=blob:none", "--depth", "1", "origin", commit)
    git("checkout", "--detach", "FETCH_HEAD")
    actual = subprocess.check_output(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != commit:
        raise ValueError("Upstream commit mismatch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="+", choices=list(SOURCES))
    for name in parser.parse_args().names:
        setup(name)
