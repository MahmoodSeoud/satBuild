# Community Launch Posts

## 1. Show HN

**Title:** Show HN: satdeploy -- versioned deployment for CubeSats (SSH + CubeSat Space Protocol)

**Body:**

We shipped a CubeSat without being 100% sure what software was on it. After launch, we spent weeks trying to recreate the state on our flatsat. So we built satdeploy.

During development, everyone does incremental updates -- SCP a binary here, USB-drive a config there. After dozens of these, nobody knows what's actually running. Yocto gives you reproducible builds, but the moment someone patches a file on the flatsat, you've lost track.

satdeploy tracks every deployment with content hashes and git provenance. Push a file, it backs up the old version. Roll back with one command. Works over SSH for networked targets and over CubeSat Space Protocol (CSP) for air-gapped hardware on CAN bus or serial links.

It's a CLI tool: `satdeploy push controller`, `satdeploy status`, `satdeploy rollback controller`. There's a Docker-based demo that simulates a satellite so you can try it without hardware.

Built for small satellite teams (2-15 people) who do incremental updates and want to stop guessing what's deployed.

Early stage -- we use it on our own flatsat. Looking for feedback from anyone who's dealt with this problem.

Repo: https://github.com/MahmoodSeoud/satBuild
Demo video (real flatsat over CSP): [DEMO_VIDEO]

---

## 2. r/cubesat

**Title:** We built an open-source deployment tool after shipping a satellite without knowing exactly what was on it

**Body:**

This might be a familiar story: during development you do dozens of incremental updates to your flatsat. SCP a new binary, copy a config over USB, patch a library. Someone updates something and forgets to tell the team. By launch, you're not fully sure what's running where. Post-launch, you spend weeks trying to recreate the state on your ground unit.

That happened to us. So we built satdeploy -- a CLI that tracks what you deploy, when, and what git commit built it.

What it does:

- Versioned backups with SHA256 hashes on every deploy
- One-command rollback to any previous version
- Git provenance tracking (branch + commit for every deployment)
- Dependency-aware service management (stops dependents first, starts dependencies first)
- Works over SSH for networked targets
- Works over CSP (CubeSat Space Protocol) for CAN bus and serial links -- no network needed

The CSP transport uses an agent that runs on the target and handles deployment commands over libcsp. Supports ZMQ, CAN, and KISS interfaces. For ground station users, there's also a CSH APM module with native slash commands.

There's a Docker demo mode so you can try the full workflow without hardware: `pip install satdeploy && satdeploy demo start`.

This is early stage. We use it on our own DISCO-2 flatsat but have no external users yet. If your team deals with configuration drift or "what's deployed where" uncertainty, I'd genuinely like to hear how you handle it today. We're looking for feedback on whether this solves a real problem or if we're the only ones with this pain.

Repo: https://github.com/MahmoodSeoud/satBuild
30-second demo on real hardware: [DEMO_VIDEO]

---

## 3. r/embedded

**Title:** Versioned OTA deployment for embedded Linux over CAN bus (CubeSat Space Protocol)

**Body:**

I've been working on a deployment tool for embedded Linux targets that talks CubeSat Space Protocol (CSP) over CAN bus, KISS serial, or ZMQ. Sharing it because the transport and embedded side might be interesting to people here even if you're not building satellites.

The problem: we have ARM targets (Yocto-built, systemd-managed) that get frequent binary updates during development. The targets sit behind a CAN bus -- no Ethernet, no SSH. We needed a way to push files, track versions, and roll back without plugging in USB drives.

The system has three parts:

1. **Python CLI** on the ground station -- orchestrates deployments, tracks history in SQLite
2. **C agent** on the target -- listens on a CSP port for protobuf-encoded commands (DEPLOY, ROLLBACK, STATUS, VERIFY). Downloads files via DTP (a file transfer protocol built on CSP). Cross-compiled with Yocto SDK.
3. **CSH APM module** (optional) -- native slash commands for the CSH ground station shell, loaded via dlopen

The agent supports three interfaces: ZMQ (for local dev/testing), CAN (via libsocketcan), and KISS serial. Every deploy creates a backup named with a SHA256 hash prefix. The agent verifies checksums after transfer.

For targets with network access, there's also a plain SSH/SFTP transport that skips the agent entirely.

One gotcha we hit: the APM is dlopen'd into CSH and shares `csp_packet_t` structs. If your CSP version doesn't match CSH's, you get silent struct offset corruption. Took a while to track that one down.

The whole thing is open source. There's a Docker-based simulator if you want to try the workflow without hardware.

Early stage, looking for feedback -- especially from anyone doing OTA updates to embedded Linux over non-IP transports.

Repo: https://github.com/MahmoodSeoud/satBuild
Demo on real hardware over CSP: [DEMO_VIDEO]

---

## 4. r/aerospace

**Title:** Open-source tool for tracking what software is actually deployed on your satellite

**Body:**

A study of 27 CubeSat anomalies found that 19 could have been prevented with better ground testing. 48% of CubeSats fail early in their missions, and configuration/interface errors account for a significant share of those failures.

One contributing factor that doesn't get talked about much: during development, teams do dozens of incremental software updates to their flatsats and engineering models. SCP a binary, copy a file over USB, patch a library. By the time you're at launch, the gap between "what Yocto built" and "what's actually on the satellite" is unknown. Spreadsheets and Slack messages are the state of the art for tracking this.

We lived this. We shipped a CubeSat without being fully certain what was on it, then spent weeks post-launch trying to reconstruct the state on our flatsat.

So we built satdeploy -- an open-source CLI for tracked, versioned deployments to embedded Linux targets. Every file push records a SHA256 hash, timestamp, and the git commit that built the binary. You get one-command rollback to any previous version. It works over SSH for networked hardware and over CubeSat Space Protocol for CAN bus links.

This doesn't replace your build system. Yocto handles reproducible images. satdeploy handles the incremental updates that happen between images -- which, in our experience, is where configuration drift actually comes from.

This is early stage. We're a small team using it on our own hardware. No external users yet, and we're honest about that. If you work on a satellite program and have opinions about configuration management tooling, I'd like to hear how your team handles this today.

Repo: https://github.com/MahmoodSeoud/satBuild
Demo on real flatsat hardware: [DEMO_VIDEO]
