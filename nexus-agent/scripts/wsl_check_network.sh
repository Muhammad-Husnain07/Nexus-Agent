#!/bin/bash
echo "=== Network Debug ==="
echo "WSL IP:"
hostname -I 2>/dev/null || ip addr show eth0 2>/dev/null | grep "inet " | awk '{print $2}'
echo "Default gateway:"
ip route show default 2>/dev/null | awk '{print $3}'
echo "Resolv.conf:"
cat /etc/resolv.conf 2>/dev/null
echo "Trying host.docker.internal:"
curl -s --max-time 5 http://host.docker.internal:11434/api/tags 2>&1 | head -2
echo "Trying gateway:"
GW=$(ip route show default 2>/dev/null | awk '{print $3}')
if [ -n "$GW" ]; then
  curl -s --max-time 5 http://$GW:11434/api/tags 2>&1 | head -2
fi
echo "=== Done ==="
