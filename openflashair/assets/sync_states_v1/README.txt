OpenFlashAir Sync States v1 — approved green design + red idle + seamless transition

GREEN: green/frames_32px, frames_48px, frames_64px; 24 frames at 55ms/frame.
RED: red/frames_32px, frames_48px, frames_64px; identical shapes and angles, stationary.
TRANSITIONS: transition_<size>px/angle_<nn>/step_00..08, 9 color frames at each of 24 angles. Step 00 is red; step 08 is green.

Tkinter state machine:
- Store the current orientation frame index (0..23), retaining it whenever the spinner stops.
- IDLE: display red frame at current orientation, no rotation timer.
- STARTING: hold orientation, show transition steps 00..08 (~35ms per step), then begin green rotation.
- ACTIVE: rotate green frames every 55ms.
- STOPPING: cancel rotation; hold last orientation; display steps 08..00 (~35ms per step), then hold red frame at that orientation.
- For rapid state toggles, reverse transition from the current step instead of restarting or snapping.
- Cancel all after() callbacks on window destruction. Keep strong references to PhotoImage assets.
- Reuse assets and avoid disk decoding on animation ticks. Do not couple UI animation to actual engine execution; reflect engine state only.
- The red idle icon does NOT indicate a failure; use a separate textual error status when needed.

All PNGs have transparent backgrounds. Assets only; no application source changed.
