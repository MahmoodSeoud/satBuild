# SDR — a from-scratch primer

This file is **reference material**, not part of the active test plan. The current flatsat doesn't carry a radio, so SDR-based RF noise injection isn't on the path for the thesis. Trace-driven CSP-layer loss injection (`flatsat-test-plan.md` §3) covers the same evaluation needs without RF.

If a future flatsat revision adds a radio, or if you want to validate the trace-driven model against real RF on a separate test bench, this primer covers the basics.

---

## What an SDR is

If you've never touched RF before, here's the mental model.

**Old radios are dedicated hardware.** A traditional UHF transmitter is a chain of physical chips: an oscillator that vibrates at exactly 437.5 MHz, a mixer that combines that with your data, an amplifier, an antenna. Each block does one job; if you want to change the frequency or modulation scheme, you swap the chip. It's like a printer that only prints A4 in black ink.

**SDR (Software-Defined Radio) is a generic frontend with software brains.** The hardware does just enough to digitize a slice of the radio spectrum (RX) or to convert software-generated samples into RF (TX). Everything that traditionally happened in dedicated chips — modulation, filtering, demodulation, decoding — happens in software running on your laptop. Same hardware, completely different behaviour depending on the software flowgraph you load. Programmable everything.

## The signal chain

**Receive (RX):**
```
   antenna  ──►  low-noise amplifier  ──►  mixer  ──►  ADC  ──►  USB to laptop  ──►  software
                                            ▲
                                       local oscillator
                                       (you set its frequency)
```
The mixer down-converts the RF signal (e.g. centered at 437.5 MHz) to "baseband" (centered at 0 Hz) so the ADC can sample it. The ADC then spits out a stream of complex samples (more on that next) into your computer over USB. Software does the rest — filter, demodulate, decode, whatever.

**Transmit (TX) is a mirror image:** software generates samples → DAC → mixer up-converts to your chosen RF frequency → power amplifier → antenna.

## I/Q samples

Each sample from the ADC is a **complex number** with two parts: I (in-phase) and Q (quadrature). Together they describe both the **amplitude** and **phase** of the signal at that instant. The math involves Euler's formula and you can look it up later — the key facts:

- Each sample is two numbers (often two 8-bit ints for cheap SDRs, two 16-bit ints for nicer ones).
- The pair encodes everything about the signal at that moment.
- Software DSP operates on these I/Q streams.

## Sample rate and bandwidth

Nyquist's theorem: to capture a signal of bandwidth B, you need to sample at rate ≥ 2B. With **complex** samples (I/Q), you can capture a bandwidth equal to your sample rate. A HackRF doing 20 Msps (mega-samples per second) gives you a 20 MHz wide window into the spectrum.

For UHF amateur work the channel is maybe 25 kHz wide — even cheap SDRs have massive headroom. Power and frequency stability matter more than bandwidth.

## Common SDR models

| Model | Price | RX/TX | Frequency | Pick if... |
|---|---|---|---|---|
| **RTL-SDR** | $30 | RX only | 24-1766 MHz | Receive-only spectrum monitoring; useless for noise injection |
| **ADALM-Pluto** | $150-200 | RX+TX | 325 MHz - 3.8 GHz | Academic standard, good docs, supports 437 MHz |
| **HackRF One** | $300 | RX+TX (half-duplex) | 1 MHz - 6 GHz | Most popular hobbyist all-rounder, 8-bit ADC |
| **USRP B205mini** | $1000+ | RX+TX | 70 MHz - 6 GHz | Higher dynamic range, professional work |
| **LimeSDR Mini** | $400 | RX+TX | 10 MHz - 3.5 GHz | Full duplex if you ever want to TX and RX simultaneously |

**ADALM-Pluto** is the academic standard for this kind of work — covers 437 MHz, full TX support, ~$150. HackRF works equally well if you can borrow one. Don't buy unless needed.

## The software stack

Three layers, bottom to top:

1. **Vendor driver** — `librtlsdr`, `libhackrf`, `libiio` (Pluto), `UHD` (USRP). Talks to hardware over USB. You don't usually call these directly.
2. **Driver abstraction** — **SoapySDR**. Single API across vendors. Write code against Soapy and it works with any SDR. Recommended.
3. **DSP framework** — **GNU Radio**. De facto standard. Two ways to use:
   - **`gnuradio-companion`** — visual flowgraph editor. Drag blocks onto a canvas, connect them, generate runnable Python. Good for prototyping.
   - **GNU Radio Python API** — write the flowgraph as Python directly. Better for scripted experiments.

**Tools you'll bump into:**
- `gqrx` / `SDR#` — receive-only spectrum visualizers. Sanity check.
- `osmocom_siggen_nogui` — CLI signal generator. Simple noise injection without writing Python.
- `hackrf_transfer`, `iio_attr` — vendor CLI for one-off transmissions.

## How you'd use it for protocol testing

If you ever did want to inject RF noise into a real radio link to validate the trace-driven model:

1. **Noise source:** transmit broadband noise centered on the receiver's frequency at controlled power. Increase noise → SNR drops → BER rises → KISS frames drop.
2. **Recorder + replayer:** record a real satellite pass, replay it through a coupler.

A minimum noise generator script with GNU Radio Python is ~30 lines. The hard part isn't the script — it's the **calibration table**: building a defensible mapping from "SDR power knob N" to "frame loss rate at the receiver."

## Why we're NOT using it for this thesis

The flatsat doesn't have a radio. Trace-driven loss injection (`flatsat-test-plan.md` §3) tests the application protocol's response to packet loss without needing one — it injects loss at the CSP packet layer, which is the layer the protocol actually responds to. The radio layer is below that and not under test.

For the live-satellite acceptance test (F12), the actual flight radio is the link, and we just observe what happens — no RF injection needed.

## When this primer becomes relevant again

- **Future flatsat with a real radio.** If a later revision adds a UHF modem to the bench, RF noise injection becomes useful for validating the trace-driven model end-to-end (run the same recorded pattern through software replay AND through SDR noise; compare outcomes).
- **Modem characterization.** If the flight modem ever does something unexpected, SDR is how you reproduce that condition deliberately.
- **Other CubeSat projects.** Future students inheriting this work who do have RF on their bench.

For now: park.
