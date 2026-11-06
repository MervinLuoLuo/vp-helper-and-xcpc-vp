#!/bin/bash
tmux ls 2>/dev/null | grep '^vp-' | cut -d: -f1 | xargs -r -n1 tmux kill-session -t

rm ~/.local/lib/vp-helper/state/vp/current.json

rm -f ~/.local/lib/vp-helper/state/vp/vp-qoj-2581-1793943575.json
rm -f ~/.local/lib/vp-helper/state/vp/vp-qoj-2581-1793943575.monitor.lock
rm -rf /~/.local/lib/vp-helper/state/vpvp-qoj-2581-1793943575.receipts
rm -f ~/.local/lib/vp-helper/state/vp/xcpc-vp.json
