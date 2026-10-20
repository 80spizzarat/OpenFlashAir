OpenFlashAir Sync Green v1

Contents:
- openflashair_sync_green_master.svg: scalable vector master
- frames_32px, frames_48px, frames_64px: 24 transparent RGBA PNG frames each
- animated_preview.gif: animated preview (light background, enlarged for inspection)
- static_preview.png: one transparent sample frame

Animation: 24 frames, 55 milliseconds/frame, clockwise, ~1.32 seconds per revolution.
Tkinter integration: load frames with Pillow ImageTk.PhotoImage once; hold strong references; switch the displayed frame using root.after(55, callback) while an operation is active. Stop and cancel the callback when inactive or the window closes. Never rotate or resize assets on each tick.
The files are visual assets only; they do not include application code or modify OpenFlashAir.
