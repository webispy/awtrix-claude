# The sensors, and the one flash that would reach them

Status: **not started.** The enabling change is a firmware write, which on a TC001 means two
minutes of the buzzer, so it waits until there is a reason to flash anyway.

## What is already there

`buildDeviceStateJson` in the firmware builds `lightLevel`, `temperature`, `humidity`,
`pressureHpa`, `batteryPercent` and the rest today. They reach MQTT and HTTP and stop there:
`ApiRouter.cpp` routes `cmd/*` over the serial channel and nothing else, so the cable can tell the
panel what to show and cannot ask it anything.

One read topic on that channel is the whole enabling change. Everything above it - `pixelwire`
exposing a reading, the plugin drawing one - is host-side work with no flash in it.

Wiring an external sensor is not a flash either: `pinI2cSda` and `pinI2cScl` are runtime settings,
so `cmd/settings` and a reboot does it. Whether the TC001's onboard SHT30 binds to the SHT31 driver
is a claim to verify on the device before designing anything on top of it.

## What to spend it on first

Not a chatbot answering "what is the humidity". Ambient light driving the panel's own brightness,
which is the one that improves what gets looked at every day - and which would settle the
brightness question left open in [session-discovery.md](session-discovery.md) by making it a curve
instead of a constant.

## Ordering it against a flash

The panel beeps for the whole of a USB flash and there is no way to silence it from software - see
[Build and flash](../README.md#build-and-flash). Prefer OTA, which needs no download mode and
therefore no beep, and batch this with whatever else wants writing.
