#!/usr/bin/env bash
set -euo pipefail

sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
