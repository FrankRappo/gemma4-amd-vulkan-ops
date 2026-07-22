#!/bin/sh
# Select the AMD COMPUTE power profile on every local DRM GPU.
set -eu

MODE=${1:-status}
DRM_ROOT=${DRM_ROOT:-/sys/class/drm}

case "$MODE" in
    enable) profile_name=COMPUTE ;;
    rollback) profile_name=BOOTUP_DEFAULT ;;
    status) profile_name= ;;
    *) echo "usage: $0 {enable|rollback|status}" >&2; exit 2 ;;
esac

found=0
for device in "$DRM_ROOT"/card*/device; do
    [ -f "$device/vendor" ] || continue
    [ "$(cat "$device/vendor")" = 0x1002 ] || continue
    profile="$device/pp_power_profile_mode"
    [ -r "$profile" ] || continue
    found=1
    if [ "$MODE" = status ]; then
        printf '%s:\n' "$device"
        sed -n '/\*:/p' "$profile"
        continue
    fi
    index=$(awk -v name="$profile_name" \
        '$2 == name || $2 == name "*:" { print $1; exit }' "$profile")
    [ -n "$index" ] || {
        echo "$device does not expose the $profile_name power profile" >&2
        exit 1
    }
    [ -w "$profile" ] || {
        echo "$profile is not writable" >&2
        exit 1
    }
    printf '%s\n' "$index" >"$profile"
    echo "$device: selected $profile_name (index $index)"
done

[ "$found" -eq 1 ] || {
    echo "no AMD DRM device with pp_power_profile_mode found under $DRM_ROOT" >&2
    exit 1
}
