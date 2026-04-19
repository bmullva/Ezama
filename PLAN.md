# Ezama Refactor Plan

## Goal

1. Move from shared Virtual/Physical tabs to per-device tabs in Node-RED flows.
2. Replace EzamaRaspiConfig's destructive flows.json wipe with surgical add/remove of nodes when dual_temp changes.
3. Update auto_config.py to create per-device tabs and use consistent pair spacing.
4. Slim down init_flows.json to a skeleton that survives indefinitely without wiping.
5. EzamaRaspiConfig.py to support reconfiguring RPi1 AND any WT32 Hub devices.

---

## Current Architecture (what exists now)

- One shared `Virtual Links` tab (hardcoded ID `0c14ff671dbe21a9`) -- all devices' dashboard UI nodes
- One shared `Physical Links` tab (hardcoded ID `c384410fdb810ed6`) -- all devices' Interpret/Loop/Increment logic
- `auto_config.py` appends to these shared tabs when any new device announces itself
- `EzamaRaspiConfig.py` wipes flows.json with `init_flows.json` whenever dual_temp changes, and only targets RPi1

**Problems:**
- One device's nodes mixed with another's -- hard to isolate, hard to surgically edit
- Wipe destroys all user wiring (switch->light connections, Filter On/Off routing)
- No space reserved for even lights when dual_temp > 0 -- converting back to single has nowhere to put them
- Hardcoded tab IDs in auto_config.py must match init_flows.json exactly
- EzamaRaspiConfig.py cannot reconfigure WT32 Hub devices

---

## New Architecture (Hybrid Approach)

### Tab structure

| Device Type | Tabs | Created by |
|---|---|---|
| RPi1 | Shared `Virtual Links`, `Physical Links` | Existing (init_flows.json or auto_config.py) |
| WT32 Hubs | Per-device `{device_id} Virtual`, `{device_id} Physical` | auto_config.py on first ping |
| Sensors | Shared `Sensors` tab | auto_config.py on first sensor ping |

RPi1 uses hardcoded shared tabs for simplicity. WT32s get isolated per-device tabs to avoid mixing. Dual-temp changes wipe only the affected WT32 tabs.

### Detection Logic

- RPi1: device_id == "RPi1" → route to shared tabs.
- WT32: device_id != "RPi1" (unique IDs) → create/route to per-device tabs.

### Dual-Temp Updates

EzamaRaspiConfig.py surgically wipes and rebuilds only the WT32's per-device tabs on changes, preserving RPi1 and other devices.

### EzamaRaspiConfig.py Changes

- Scan flows.json for WT32 tabs (labels like "{device_id} Virtual").
- Present menu of WT32 device_ids.
- For selected WT32, wipe its tabs, send MQTT `/lights/{device_id}/dual/command`, rebuild tabs.

### auto_config.py Changes

- In `process_message`: Check device_id to route (shared vs. per-device).
- Create per-device tabs for WT32s.
- Ensure no duplicates (check existing tabs/groups).

---

## Pair Spacing Rule (critical for dual<->single conversion)

Lights are always laid out in pairs (L1+L2, L3+L4, ...). Whether a pair is currently single or dual,
**both slots are always allocated** so that converting between modes only requires inserting or removing
nodes, never shifting existing ones.

### Virtual tab -- pair block layout (200px / 5 rows of 40px each)

```
y = base + 0    : L_odd  toggle button       (always present)
y = base + 40   : L_odd  brightness slider   (always present)
y = base + 80   : L_odd  temperature slider  (present if dual; EMPTY/reserved if single)
y = base + 120  : L_even toggle button       (present if single; EMPTY/reserved if dual)
y = base + 160  : L_even brightness slider   (present if single; EMPTY/reserved if dual)
```

Each pair always occupies exactly 200px regardless of current dual/single mode.

### Physical tab -- pair block layout (160px / 4 rows of 40px each)

```
y = base + 0    : L_odd  Interpret function + mqtt out    (always present)
y = base + 40   : L_odd  50ms inject + Increment function (always present)
y = base + 80   : L_even Interpret function + mqtt out    (present if single; EMPTY/reserved if dual)
y = base + 120  : L_even 50ms inject + Increment function (present if single; EMPTY/reserved if dual)
```

Each pair always occupies exactly 160px.

Switches (mqtt in nodes) remain in the left column (x ~= 90) stacked independently.

---

## File Changes

### 1. `clean/init_flows.json`

- Remove: `Virtual Links` tab node, `Physical Links` tab node
- Add: `System` tab node
- Move the ping broadcast inject+mqtt out and reporting inject+moment+mqtt out into the `System` tab
- Keep: one unwired `Filter On/Off` function node in the `System` tab
- Keep: `mqtt-broker`, `ui_base`

### 2. `auto_config.py`

**Tab management:**
- Remove constants `VIRTUAL_TAB_ID`, `PHYSICAL_TAB_ID`
- Add `get_or_create_device_tabs(flows, device_id)` -> returns `(virtual_tab_id, physical_tab_id)`
  - Searches for existing `tab` nodes named `"{device_id} Virtual"` / `"{device_id} Physical"`
  - Creates them if not found
- Add `get_or_create_sensors_tab(flows)` -> returns `sensors_tab_id`
- Route hub devices (those with `lights` in their report) to device tabs
- Route sensor-only devices to the Sensors tab

**Duplicate detection:**
- Existing check (ui_group name match or topic contains device_id) is still correct -- no change needed

**Pair spacing:**
- Rewrite `add_lights_nodes()` to lay out in pairs using 200px virtual / 160px physical allocations
- Iterate pair by pair: for each pair `(odd, even)`, calculate `y_base` and place nodes at fixed offsets
- Even light nodes are only added if not in `skipped_indices`; y positions are allocated regardless

**Sensor nodes:**
- `add_sensors_nodes()` routes to `sensors_tab_id` instead of `VIRTUAL_TAB_ID`

### 3. `EzamaRaspiConfig.py`

**Device selection:**
- On startup, scan flows.json for all configured hub devices -- any device that has a
  `{device_id} Physical` tab (post-refactor) or an Interpret node (current flows)
- Present a numbered menu of discovered devices (e.g. `1. RPi1`, `2. 00000087`)
- User selects which device to reconfigure
- All subsequent operations (MQTT topic, flows.json surgery, tab lookup) are parameterised
  by the selected `device_id`

**Remove:**
- The hardcoded `device_id = "RPi1"` assumption
- The `cp init_flows.json -> flows.json` wipe step entirely
- The `systemctl restart nodered` that followed the wipe (a restart still happens after surgical edit)

**Add: `discover_hub_devices(flows)`**
- Returns a list of device_ids that have a `{device_id} Physical` tab in flows.json
- These are the devices eligible for dual_temp reconfiguration

**Add: `read_current_dual_temp(flows, device_id)`**
- Counts `ui_slider` nodes with `"Temperature"` in their `label` belonging to the device_id ui_group
- Returns integer 0-6

**Add: `increase_dual_temp(flows, device_id, old_val, new_val)`**
- For each new dual pair being added (pairs change from highest downward):
  - Determine `odd` and `even` indices for the pair
  - **Virtual tab:** find `y_base` from the odd light's toggle button node (`name == "V{odd}"`)
    - Add temperature slider + set_temperature function at `y_base + 80`
    - Remove even light's toggle, brightness slider, set_brightness function, mqtt out
  - **Physical tab:** find `y_base` from odd light's Interpret node (`name` contains `"Interpret"` and `"L{odd}"`)
    - Remove even light's Interpret, mqtt out, 50ms inject, Increment
  - Odd light's nodes and all wiring to them are untouched

**Add: `decrease_dual_temp(flows, device_id, old_val, new_val)`**
- For each pair being converted back to single:
  - **Virtual tab:**
    - Remove temperature slider + set_temperature function at `y_base + 80`
    - Add even light's toggle at `y_base + 120`, brightness slider at `y_base + 160`
    - Wire to a new mqtt out for `L_even`
  - **Physical tab:**
    - Add even light's Interpret + mqtt out at `y_base + 80`
    - Add even light's 50ms inject + Increment at `y_base + 120`

**Revised `main()` flow:**
1. Load flows.json
2. Discover hub devices via `discover_hub_devices()`; present menu; user selects device
3. Read current dual_temp for selected device via `read_current_dual_temp()`
4. Ask for new dual_temp count (0-6)
5. If no change, exit with message
6. Show warning (wiring to even lights being converted will break); confirm with 'yes'
7. Send MQTT command to `/lights/{device_id}/dual/command`
   - For RPi1: also rewrites its own source file (handled by rpi_switch_light_mqtt2.py)
   - For WT32 Hub: persists to EEPROM (handled by the hub firmware)
   - Script does not need to know the difference -- just send the message
8. Sleep 2s for the device to process
9. Apply surgical flows.json edit
10. Write flows.json
11. `sudo systemctl restart nodered`

---

## Wiring Preservation Notes

- All wiring **to** odd lights' Interpret nodes (switches, Filter On/Off, etc.) is untouched
- All wiring **from** odd lights' Increment -> mqtt out is untouched
- Wiring to/from even-light nodes will break when that light is removed -- accepted and expected
- Surgery only touches nodes identified by device_id + light index; other devices' nodes are never modified

---

## Files to Modify

| File | Change | Status |
|---|---|---|
| `E:\Ezama\clean\init_flows.json` | Reduce to skeleton (~10 nodes) | Updated -- not yet tested |
| `E:\Ezama\auto_config.py` | Per-device tabs, pair spacing, sensors tab | Updated -- not yet tested |
| `E:\Ezama\EzamaRaspiConfig.py` | Device menu, surgical edit instead of wipe | Updated -- not yet tested |

### Known issue to fix before testing

- `EzamaRaspiConfig.py` does not back up `flows.json` before writing. Add a timestamped `cp` inside `main()` before calling `save_flows()` -- required by the project critical backup rule.

## Backed-up originals

| Backup | Original |
|---|---|
| `E:\Ezama\EzamaRaspiConfig.py.bak` | Original EzamaRaspiConfig.py |
| `E:\Ezama\auto_config.py.bak` | Original auto_config.py |
| `E:\Ezama\clean\init_flows.json.bak` | Original init_flows.json |

## Files NOT to modify

| File | Reason |
|---|---|
| `rpi_switch_light_mqtt2.py` | No structural changes needed |
| `firmware/WT32Hub1.2/WT32Hub1.2.ino` | No changes; hub uses same `/dual/command` topic |

---

## Implementation Order

1. Redesign and write new `init_flows.json` DONE
2. Rewrite `auto_config.py` (per-device tabs + pair spacing) DONE
3. Fix `EzamaRaspiConfig.py` backup issue, then test all three together
