# Which Tibber heat pump integrations can carry a bridge?

Findings from September 2026 on how each of Tibber's heating power-ups
connects, and whether a foreign heat pump could be presented to Tibber
through it. Summary: the vendor-cloud integrations cannot be bridged; the
two hub power-ups can; Ngenic Tune is a hardware bridge you can buy.

| Integration            | How Tibber connects                                   | Bridge possible? |
|------------------------|-------------------------------------------------------|------------------|
| NIBE S-series          | myUplink cloud, OAuth on your myUplink account        | No: the pump registers with NIBE's cloud using NIBE firmware and device credentials; no local protocol exists to emulate |
| NIBE F-series          | NIBE Uplink cloud                                     | No, same reason |
| CTC                    | myUplink cloud; Tibber's FAQ says smart heating is not available for CTC | No |
| Sensibo                | Sensibo cloud; infrared controller for air-to-air units | No, proprietary device and cloud |
| Mill, Adax             | vendor clouds for panel heaters                       | No |
| SmartThings            | Tibber's SmartThings app showed thermostats as Tibber "bubbles" | No, repository archived February 2023 |
| **Homey (Athom)**      | Tibber's Homey power-up imports "all connected thermostats, sensors and lights" from a Homey Pro 2023/2026 and applies Tibber's heating algorithms | **Yes**: a custom Homey app exposing the heat pump as a thermostat device (target and measured temperature); offered in all Tibber markets |
| **Futurehome**         | Tibber's Futurehome power-up imports heating devices and temperature sensors with smart heating | **Yes**: the hub speaks FIMP, an open MQTT protocol, with a Local API switch and community-built virtual thermostat devices; Norway-centric |
| **Ngenic Tune**        | Ngenic cloud; Tibber smart heating autopilot supports it | **Hardware**: sits between the outdoor sensor and the pump and manipulates the outdoor temperature reading; sold in Tibber's German store; ground-source, exhaust-air, electric boiler and district heating, air-to-water only with a separate outdoor sensor |

## Caveats for the hub route

- Tibber treats the device as a room thermostat: it nudges a set point by
  about a degree and expects a measured room temperature back. The bridge
  has to translate that set-point delta into a heating-curve offset, an SG
  Ready state or Modbus writes.
- Tibber's thermostat algorithm is tuned for fast electric heaters; the
  native NIBE integration shifts the curve using a weather forecast and is
  more sophisticated than what a thermostat detour can give back.
- Whether the Homey power-up accepts every thermostat-class device or
  filters by brand could not be confirmed from Tibber's documentation; it
  needs one test on a real Homey.

## Recommendation

1. Price shifting without Tibber's app in the loop: the bridge in this
   repository does it directly (`plan` / `run`, or `curve-plan` for
   curve shifting).
2. The heat pump inside the Tibber app: Homey Pro plus a small Homey
   thermostat app, with a matching "listen for set point" mode in this
   bridge. Futurehome's FIMP route if in Norway or already owning the hub.
3. No code at all: Ngenic Tune, if the pump uses an external outdoor
   sensor. `docs/virtual-outdoor-sensor.md` designs a self-built equivalent.

## Sources

- Tibber support, MyUplink for NIBE S-series: <https://support.tibber.com/sv/articles/6065031-myuplink-for-nibe-s-serie>
- Tibber support, FAQ Smarte Steuerung: <https://support.tibber.com/de/articles/8856145-faq-smarte-steuerung>
- Tibber store, Homey power-up: <https://tibber.com/de/powerup/homey-tibber>
- Tibber store, Ngenic power-up: <https://tibber.com/de/store/produkt/ngenic-tibber>
- Tibber store, CTC power-up: <https://tibber.com/de/store/produkt/ctc>
- Futurehome support, Tibber: <https://support.futurehome.no/hc/en-no/articles/6466774405277-Tibber>
- Futurehome FIMP API: <https://github.com/futurehomeno/fimp-api>
- Futurehome forum, virtual heat pump device: <https://forum.futurehome.io/t/virtual-device-air-conditioner-heat-pump/1231>
- Ngenic Tune compatibility: <https://ngenic.se/en/tune/compatibility/>
- Ngenic support, how Tune controls the heating: <https://en.support.ngenic.se/article/81-how-does-ngenic-tune-control-my-heating-system>
- Tibber SmartThings app (archived): <https://github.com/tibber/tibber-smartthings-app>
