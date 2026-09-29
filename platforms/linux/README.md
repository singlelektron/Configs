# Linux desktop extension point

Kitty currently uses the shared configuration and detects Wayland/X11 automatically.
There is no Niri configuration yet: the audited machine runs GNOME.
Follow the shared palette and spacing in [the style guide](../../docs/style.md)
when adding desktop components.

When Niri is actually adopted, add `platforms/linux/niri/config.kdl` and an explicit
Linux-only deployment entry. Keep display names, scaling, input-device names,
autostart credentials and host-specific commands in local overrides. Test the
configuration in the real session before enabling autostart or replacing the
current desktop. Do not copy an entire desktop configuration tree into this repo.
