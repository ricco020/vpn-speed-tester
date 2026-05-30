# vpnspeed — VPN overhead benchmark CLI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](#)

Measure how much **download, upload, latency, and jitter** your VPN
actually costs you. No web UI, no telemetry. Two commands, one cron
job, exit-code thresholds. Built to be put in `/usr/local/bin/` and
forgotten.

```text
============================================================
 VPN SPEED TESTER — by AnonymFlow.com
============================================================

                       Baseline            VPN
Download (Mbps)          512.40         436.81
Upload (Mbps)            204.13         182.74
Latency (ms median)        8.4           24.7
Jitter (ms stdev)          1.2            3.5

Download loss:    14.7%
Upload loss:      10.5%
Latency increase: +16.3 ms
Jitter increase:  +2.3 ms

Verdict: ✅ ok

Throughput targets per use case (reference):
  Netflix 4K   : 25 Mbps   |   BBC iPlayer 4K : 24 Mbps
  DAZN sport 4K: 50 Mbps   |   Netflix HD     :  5 Mbps
============================================================
```

## Why this tool exists

Speed comparisons between VPNs are usually one of two things: a single
screenshot from speedtest.net (one run, no methodology), or a glossy
graph from a VPN provider's affiliate page (cherry-picked server,
cherry-picked moment).

This CLI does the boring honest thing:

1. Measure your **real** connection with the VPN off — save it as
   baseline.
2. Turn the VPN on, measure again.
3. Report download / upload / latency / jitter **deltas in percent**.
4. Exit 1 if the deltas exceed thresholds you set.

It's the same protocol the [95-session VPN streaming
study](https://www.anonymflow.com/en/blog/study-vpn-streaming-2026-95-test-sessions)
distilled to a single Python file you can run on a Raspberry Pi.

The full write-up of the methodology — including why median+stdev are
the only honest numbers for VPN latency, why upload often suffers
more than download on WireGuard, and why "test once at 9pm" is
useless — is here:

**[Real-world VPN speed test methodology — AnonymFlow](https://www.anonymflow.com/en/blog/real-world-vpn-speed-test)**

## Install

No PyPI dependency — clone and run:

```bash
git clone https://github.com/<your-org>/vpn-speed-tester
cd vpn-speed-tester
python3 vpnspeed.py --version
```

Requires Python 3.8+. Tested on Linux, macOS, Windows 10/11.

## Usage

### One-time setup

```bash
# Disconnect your VPN, then:
python3 vpnspeed.py --baseline-only
# → saves a baseline to ~/.cache/vpnspeed/baseline.json
```

### Daily check

```bash
# Connect your VPN, then:
python3 vpnspeed.py --vpn-only
# → measures current connection, compares to baseline
```

### In a cron job

```bash
# Every hour, alert when download loss exceeds 30%
0 * * * * /usr/bin/python3 /opt/vpn-speed-tester/vpnspeed.py --vpn-only \
   --max-download-loss 30 || /usr/local/bin/alert.sh
```

### Machine-readable

```bash
python3 vpnspeed.py --vpn-only --json | jq '.diff.download_loss_pct'
```

### Threshold flags

| Flag | Effect |
|------|--------|
| `--max-download-loss N` | Exit 1 if download loss > N% |
| `--max-upload-loss N`   | Exit 1 if upload loss > N% |
| `--max-latency-increase N` | Exit 1 if latency rises by more than N ms |

If you set none, the verdict heuristic kicks in:

| Verdict | Condition (any) |
|---------|-----------------|
| `ok`    | DL loss ≤ 25%, UL loss ≤ 25%, latency +50 ms or less |
| `warn`  | 25% < DL loss ≤ 40%, or 25% < UL loss ≤ 40%, or +50 to +100 ms latency |
| `fail`  | DL or UL loss > 40%, or latency +100 ms or more |

A `fail` verdict also returns exit code 1.

## How it works

- **Download** : single-shot 25 MB fetch from
  `https://speed.cloudflare.com/__down`. The URL is rate-stable and
  rejects keep-alive caches, so each run hits the network.
- **Upload** : single-shot 5 MB POST to
  `https://speed.cloudflare.com/__up`. Same logic.
- **Latency** : median of 10 HEAD requests to `https://1.1.1.1`.
  Why HEAD: response body would dwarf round-trip time. Why median:
  it filters out the one spurious 250 ms outlier per run.
- **Jitter** : standard deviation of the same 10 samples.
  Stdev > median means your link is flapping — and a streaming
  player will notice before a benchmark does.
- **Verdict** is built from a handful of hard-coded thresholds that
  mirror what the [95-session study](https://www.anonymflow.com/en/blog/study-vpn-streaming-2026-95-test-sessions)
  ended up flagging as "good enough for 4K streaming". Adjust to taste.

## Privacy

Only network endpoints touched during a run:

| Endpoint              | Purpose          |
|-----------------------|------------------|
| `speed.cloudflare.com`| Throughput probe |
| `1.1.1.1` (HTTPS HEAD)| Latency probe    |

No data sent to AnonymFlow servers. No cookies, no analytics.
The script is 270 lines, auditable in under 10 minutes.

## Limitations

- Cloudflare's speed endpoint terminates at the Cloudflare edge
  nearest to you — so your "download" measurement is the throughput
  *to that edge*, not to a Sydney CDN. For most VPN-overhead
  comparisons this is fine; for "is my VPN saturating the long
  haul?" it isn't.
- The 25 MB download size is set conservatively to keep cron jobs
  light. On gigabit connections, increase `DOWNLOAD_BYTES` to
  100_000_000 for a more accurate steady-state measurement.
- If your VPN server has lower upstream bandwidth than your real
  ISP egress, the upload number will simply reflect the VPN cap.
  That's correct.

## Companion resources

- [Real-world VPN speed test methodology](https://www.anonymflow.com/en/blog/real-world-vpn-speed-test) — primary reference, methodology + per-VPN numbers
- [Throughput requirements per streaming service](https://www.anonymflow.com/en/blog/vpn-speed-test) — what's "good enough" for Netflix 4K, DAZN live, etc.
- [95-session VPN streaming study](https://www.anonymflow.com/en/blog/study-vpn-streaming-2026-95-test-sessions) — the underlying dataset, downloadable CSV
- [VPN security audit (9 tests)](https://www.anonymflow.com/en/blog/complete-vpn-security-audit) — broader check battery
- [DNS leak detector CLI](https://github.com/your-org/dns-leak-detector-cli) — sister tool, DNS-side
- [WebRTC leak detector](https://github.com/your-org/webrtc-leak-detector) — sister tool, browser-side

## License

[MIT](LICENSE) — do whatever you want, including commercial use.

---

*Built and maintained by the team behind [AnonymFlow](https://www.anonymflow.com) — independent VPN / privacy tooling and research. Full [methodology](https://www.anonymflow.com/en/methodology) and the [95-session VPN streaming study](https://www.anonymflow.com/en/blog/study-vpn-streaming-2026-95-test-sessions) for the reference data this CLI was distilled from.*
