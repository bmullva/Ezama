# Ezama System Test Plan

## Prerequisites
- Pi is running (`rpi_switch_light_mqtt2.py` started, MQTT broker up)
- C409B3 (WT32Hub) is online at 192.168.99.181
- Node-RED is running with flows configured via `auto_config.py`
- A terminal open for MQTT monitoring: `mosquitto_sub -h 192.168.99.1 -t /system/reporting`

---

## 1. Hardware: Light Toggle (RPi1 + C409B3)

**Steps:**
1. Press any physical button wired to a light

**Expected:**
- Light toggles on/off with each press
- MQTT shows command on `/lights/{device_id}/L{n}/command`
- Node-RED UI toggle button reflects state

---

## 2. Hardware: Brightness Dim/Brighten (RPi1 + C409B3)

**Steps:**
1. With a light ON, hold the dim button
2. Hold the brighten button

**Expected:**
- Dim: light visibly decreases in brightness, stops at minimum (~5%)
- Brighten: light increases, stops at maximum (100%)
- Direction is correct (dim = darker, brighten = brighter)

---

## 3. Hardware: Temperature (dual_temp lights only)

**Steps:**
1. Identify a dual_temp pair (e.g. L11/L12 when dual_temp=1)
2. With L11 ON, hold the cool button
3. Hold the heat button

**Expected (Ben's Kelvin convention):**
- Cool (6500K direction): light shifts warmer-looking / more blue-white
- Heat (2700K direction): light shifts cooler-looking / more amber
- The even light (L12) does NOT respond independently -- it tracks L11

---

## 4. Firmware: MAC-Derived Device ID (C409B3)

**Steps:**
1. `mosquitto_sub -h 192.168.99.1 -t /system/reporting`
2. Wait for C409B3 to report (up to 30s)

**Expected:**
```json
{"device_id": "C409B3", "version": "1.2.1", ...}
```
- `device_id` matches last 6 hex digits of WT32Hub MAC
- `version` is `1.2.1`

---

## 5. Node-RED: Per-Device Tabs (auto_config.py)

**Steps:**
1. Open Node-RED editor in browser
2. Check canvas tabs

**Expected:**
- Tabs named `C409B3 Virtual` and `C409B3 Physical` exist
- RPi1 nodes are on `Virtual Links` and `Physical Links` tabs (shared, hardcoded IDs)
- No mixing between devices on same tab

---

## 6. EzamaRaspiConfig: Surgical Light Reset (increasing dual_temp)

**Steps:**
1. Note current dual_temp (e.g. 1 = L11/L12 paired)
2. Run `python3 /home/pi/Ezama/EzamaRaspiConfig.py`, select C409B3
3. Change dual_temp from 1 -> 2 (adds L9/L10 as a second dual pair)
4. Confirm with `yes`
5. Open Node-RED editor

**Expected:**
- Only L9/L10 pair changed: L10 nodes removed, temperature slider added to L9
- L11/L12 pair: completely untouched
- L1-L8: completely untouched
- S14 wire (was -> L10 Interpret) pruned cleanly -- no dangling dashed lines in editor

---

## 7. EzamaRaspiConfig: Surgical Light Reset (decreasing dual_temp)

**Steps:**
1. Run EzamaRaspiConfig.py again, change dual_temp from 2 -> 1
2. Open Node-RED editor

**Expected:**
- L9/L10 pair reverted: L10 toggle + brightness slider restored, temp slider removed from L9
- L11/L12 pair: still untouched
- S14 can be re-wired to L10 Interpret node (it exists again)

---

## 8. EzamaRaspiConfig: dual_temp Persisted After Reboot

**Steps:**
1. After setting dual_temp=2 via EzamaRaspiConfig.py, reboot C409B3
2. `mosquitto_sub -h 192.168.99.1 -t /system/reporting`

**Expected:**
```json
{"device_id": "C409B3", "dual_temp": 2, ...}
```
- Value survives reboot (stored in EEPROM)

---

## 9. Stability: Multi-Device Independence

**Steps:**
1. Trigger any EzamaRaspiConfig change on C409B3
2. Check RPi1 `Virtual Links` and `Physical Links` tabs in Node-RED

**Expected:**
- RPi1 tabs completely unchanged
- RPi1 lights continue to respond physically
