#!/usr/bin/env python3
"""
vpnspeed.py — Measure your VPN overhead from the command line.

Runs a baseline speed test (no VPN) and a VPN test back-to-back, then
reports the percent loss on download, upload, latency, and jitter.
Designed to be runnable on a cron and exit non-zero when overhead
exceeds a configurable threshold.

Usage:
    python vpnspeed.py                       # interactive single run
    python vpnspeed.py --baseline-only       # measure baseline, save to disk
    python vpnspeed.py --vpn-only            # measure with VPN active, compare
    python vpnspeed.py --max-download-loss 25 # exit 1 if >25% loss
    python vpnspeed.py --json                 # machine-readable

References:
    - Methodology: https://www.anonymflow.com/en/blog/real-world-vpn-speed-test
    - Throughput targets per use case: https://www.anonymflow.com/en/blog/vpn-speed-test
    - Public Cloudflare speed endpoint: https://speed.cloudflare.com/

License: MIT
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib import request
from urllib.error import URLError

__version__ = "0.1.0"

CACHE_DIR = Path(os.path.expanduser("~/.cache/vpnspeed"))
BASELINE_FILE = CACHE_DIR / "baseline.json"

# Cloudflare speed endpoint — free, no key, no tracking.
DOWNLOAD_BYTES = 25_000_000   # 25 MB single-shot download
UPLOAD_BYTES = 5_000_000      # 5 MB single-shot upload
LATENCY_SAMPLES = 10


@dataclass
class Measurement:
    """One measurement run (baseline or vpn)."""

    timestamp: float
    download_mbps: float
    upload_mbps: float
    latency_ms: float
    jitter_ms: float
    label: str  # "baseline" or "vpn"
    notes: str = ""


@dataclass
class Diff:
    """Comparison between baseline and vpn measurement."""

    download_loss_pct: float
    upload_loss_pct: float
    latency_increase_ms: float
    jitter_increase_ms: float
    verdict: str  # "ok", "warn", "fail"


# ---------- Measurement primitives ----------

def measure_latency_and_jitter(host: str = "https://1.1.1.1") -> tuple[float, float]:
    """Median latency + jitter (stdev) over LATENCY_SAMPLES probes."""
    samples = []
    for _ in range(LATENCY_SAMPLES):
        t0 = time.monotonic()
        try:
            req = request.Request(host, method="HEAD")
            with request.urlopen(req, timeout=4) as r:
                r.read()
            samples.append((time.monotonic() - t0) * 1000.0)
        except URLError:
            continue
        time.sleep(0.1)
    if len(samples) < 3:
        return 0.0, 0.0
    return statistics.median(samples), statistics.stdev(samples)


def measure_download(url: str = "https://speed.cloudflare.com/__down") -> float:
    """Measure download throughput in Mbps."""
    target = f"{url}?bytes={DOWNLOAD_BYTES}"
    t0 = time.monotonic()
    bytes_read = 0
    try:
        with request.urlopen(target, timeout=30) as r:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                bytes_read += len(chunk)
    except URLError:
        return 0.0
    elapsed = time.monotonic() - t0
    if elapsed <= 0:
        return 0.0
    return (bytes_read * 8) / elapsed / 1_000_000


def measure_upload(url: str = "https://speed.cloudflare.com/__up") -> float:
    """Measure upload throughput in Mbps."""
    payload = b"x" * UPLOAD_BYTES
    t0 = time.monotonic()
    try:
        req = request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/octet-stream")
        with request.urlopen(req, timeout=30) as r:
            r.read()
    except URLError:
        return 0.0
    elapsed = time.monotonic() - t0
    if elapsed <= 0:
        return 0.0
    return (len(payload) * 8) / elapsed / 1_000_000


def run_measurement(label: str) -> Measurement:
    """Run a complete probe and return a Measurement."""
    print(f"[{label}] Measuring latency / jitter…", file=sys.stderr)
    lat, jit = measure_latency_and_jitter()
    print(f"[{label}] Measuring download…", file=sys.stderr)
    dl = measure_download()
    print(f"[{label}] Measuring upload…", file=sys.stderr)
    ul = measure_upload()
    return Measurement(
        timestamp=time.time(),
        download_mbps=round(dl, 2),
        upload_mbps=round(ul, 2),
        latency_ms=round(lat, 2),
        jitter_ms=round(jit, 2),
        label=label,
    )


# ---------- Persistence ----------

def save_baseline(m: Measurement) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(asdict(m), indent=2))


def load_baseline() -> Optional[Measurement]:
    if not BASELINE_FILE.exists():
        return None
    data = json.loads(BASELINE_FILE.read_text())
    return Measurement(**data)


# ---------- Comparison ----------

def compute_diff(baseline: Measurement, vpn: Measurement) -> Diff:
    dl_loss = pct_loss(baseline.download_mbps, vpn.download_mbps)
    ul_loss = pct_loss(baseline.upload_mbps, vpn.upload_mbps)
    lat_inc = vpn.latency_ms - baseline.latency_ms
    jit_inc = vpn.jitter_ms - baseline.jitter_ms

    if dl_loss > 40 or ul_loss > 40 or lat_inc > 100:
        verdict = "fail"
    elif dl_loss > 25 or ul_loss > 25 or lat_inc > 50:
        verdict = "warn"
    else:
        verdict = "ok"

    return Diff(
        download_loss_pct=round(dl_loss, 1),
        upload_loss_pct=round(ul_loss, 1),
        latency_increase_ms=round(lat_inc, 1),
        jitter_increase_ms=round(jit_inc, 1),
        verdict=verdict,
    )


def pct_loss(baseline: float, vpn: float) -> float:
    if baseline <= 0:
        return 0.0
    return max(0.0, (baseline - vpn) / baseline * 100.0)


# ---------- Reporting ----------

def format_human(baseline: Measurement, vpn: Measurement, diff: Diff) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(" VPN SPEED TESTER — by AnonymFlow.com")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"{'':22} {'Baseline':>14} {'VPN':>14}")
    lines.append(f"{'Download (Mbps)':22} {baseline.download_mbps:>14.2f} {vpn.download_mbps:>14.2f}")
    lines.append(f"{'Upload (Mbps)':22} {baseline.upload_mbps:>14.2f} {vpn.upload_mbps:>14.2f}")
    lines.append(f"{'Latency (ms median)':22} {baseline.latency_ms:>14.1f} {vpn.latency_ms:>14.1f}")
    lines.append(f"{'Jitter (ms stdev)':22} {baseline.jitter_ms:>14.1f} {vpn.jitter_ms:>14.1f}")
    lines.append("")
    lines.append(f"Download loss:    {diff.download_loss_pct:.1f}%")
    lines.append(f"Upload loss:      {diff.upload_loss_pct:.1f}%")
    lines.append(f"Latency increase: +{diff.latency_increase_ms:.1f} ms")
    lines.append(f"Jitter increase:  +{diff.jitter_increase_ms:.1f} ms")
    lines.append("")
    flag = {"ok": "✅ ok", "warn": "⚠️  warn", "fail": "❌ fail"}[diff.verdict]
    lines.append(f"Verdict: {flag}")
    lines.append("")
    lines.append("Throughput targets per use case (reference):")
    lines.append("  Netflix 4K   : 25 Mbps   |   BBC iPlayer 4K : 24 Mbps")
    lines.append("  DAZN sport 4K: 50 Mbps   |   Netflix HD     :  5 Mbps")
    lines.append("")
    lines.append("Reference methodology + per-VPN comparison:")
    lines.append("  https://www.anonymflow.com/en/blog/real-world-vpn-speed-test")
    lines.append("=" * 60)
    return "\n".join(lines)


# ---------- CLI ----------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vpnspeed",
        description="Measure VPN overhead on download / upload / latency / jitter.",
        epilog="Methodology: https://www.anonymflow.com/en/blog/real-world-vpn-speed-test",
    )
    parser.add_argument("--baseline-only", action="store_true",
                       help="Measure with VPN OFF, persist as baseline, then exit.")
    parser.add_argument("--vpn-only", action="store_true",
                       help="Measure with VPN ON and compare to stored baseline.")
    parser.add_argument("--max-download-loss", type=float, default=None,
                       help="Exit 1 if download loss exceeds this percent.")
    parser.add_argument("--max-upload-loss", type=float, default=None,
                       help="Exit 1 if upload loss exceeds this percent.")
    parser.add_argument("--max-latency-increase", type=float, default=None,
                       help="Exit 1 if latency rises by more than this many ms.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human output.")
    parser.add_argument("--version", action="version", version=f"vpnspeed {__version__}")
    args = parser.parse_args(argv)

    if args.baseline_only:
        m = run_measurement("baseline")
        save_baseline(m)
        print(f"Baseline saved: dl={m.download_mbps} Mbps, ul={m.upload_mbps} Mbps, latency={m.latency_ms} ms")
        return 0

    if args.vpn_only:
        baseline = load_baseline()
        if not baseline:
            print("No baseline found. Run with --baseline-only first.", file=sys.stderr)
            return 2
        vpn = run_measurement("vpn")
        diff = compute_diff(baseline, vpn)
    else:
        # Single-shot back-to-back run (no VPN context awareness)
        print("Run --baseline-only with VPN OFF first, then --vpn-only with VPN ON.", file=sys.stderr)
        print("Or simply: assume current measurement is the VPN one and compare to last baseline.", file=sys.stderr)
        baseline = load_baseline()
        if not baseline:
            print("No baseline found. Run with --baseline-only first.", file=sys.stderr)
            return 2
        vpn = run_measurement("current")
        diff = compute_diff(baseline, vpn)

    if args.json:
        out = {
            "baseline": asdict(baseline),
            "current": asdict(vpn),
            "diff": asdict(diff),
        }
        print(json.dumps(out, indent=2))
    else:
        print(format_human(baseline, vpn, diff))

    # Threshold enforcement
    if args.max_download_loss is not None and diff.download_loss_pct > args.max_download_loss:
        return 1
    if args.max_upload_loss is not None and diff.upload_loss_pct > args.max_upload_loss:
        return 1
    if args.max_latency_increase is not None and diff.latency_increase_ms > args.max_latency_increase:
        return 1
    if diff.verdict == "fail":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
