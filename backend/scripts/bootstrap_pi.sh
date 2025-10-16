#!/usr/bin/env bash
set -euo pipefail

# Omnicontrol Raspberry Pi bootstrap script
# - Installs system packages
# - Creates omnicontrol user (if missing)
# - Clones/updates the repo under /home/omnicontrol/Omnicontrol
# - Sets up Python virtualenv and installs backend deps
# - Installs and enables systemd units for backend + bluetooth agent
#
# Usage (run as root on a fresh Raspberry Pi OS Lite install):
#   curl -sSL https://raw.githubusercontent.com/<your-org>/Omnicontrol/main/backend/scripts/bootstrap_pi.sh | sudo bash
# or copy this file onto the Pi and execute `sudo bash bootstrap_pi.sh`

OMNICONTROL_USER=${OMNICONTROL_USER:-omnicontrol}
REPO_URL=${REPO_URL:-https://github.com/<your-org>/Omnicontrol.git}
REPO_DIR=/home/${OMNICONTROL_USER}/Omnicontrol
BACKEND_DIR="${REPO_DIR}/backend"
VENV_DIR="${BACKEND_DIR}/.venv"

log() {
  echo "[bootstrap] $*"
}

require_root() {
  if [[ "$EUID" -ne 0 ]]; then
    echo "This script must be run as root (or with sudo)." >&2
    exit 1
  fi
}

create_user_if_needed() {
  if id "${OMNICONTROL_USER}" >/dev/null 2>&1; then
    log "User ${OMNICONTROL_USER} exists"
    return
  fi
  log "Creating user ${OMNICONTROL_USER}"
  adduser --disabled-password --gecos '' "${OMNICONTROL_USER}"
}

install_packages() {
  log "Updating apt repositories"
  apt update
  log "Installing required packages"
  DEBIAN_FRONTEND=noninteractive apt install -y \
    git python3-venv python3-pip python3-dev \
    bluez bluetooth libdbus-1-dev libglib2.0-dev \
    ffmpeg libcap2-bin jq curl \
    gcc g++ make pkg-config
}

clone_repo() {
  if [[ -d "${REPO_DIR}" ]]; then
    log "Repository already exists, fetching latest changes"
    sudo -u "${OMNICONTROL_USER}" -H bash -c "cd '${REPO_DIR}' && git fetch --all && git reset --hard origin/main"
  else
    log "Cloning repository"
    sudo -u "${OMNICONTROL_USER}" -H git clone "${REPO_URL}" "${REPO_DIR}"
  fi
}

setup_venv() {
  log "Setting up Python virtual environment"
  sudo -u "${OMNICONTROL_USER}" -H bash -c "\
    cd '${BACKEND_DIR}' && \
    python3 -m venv '${VENV_DIR}' && \
    source '${VENV_DIR}/bin/activate' && \
    pip install --upgrade pip && \
    pip install -r requirements.txt" 2>&1
}

configure_capabilities() {
  # Allow python to access Bluetooth without sudo via capabilities.
  if command -v setcap >/dev/null 2>&1; then
    if command -v ${VENV_DIR}/bin/python >/dev/null 2>&1; then
      log "Enabling bluetooth capabilities on python interpreter"
      setcap 'cap_net_raw,cap_net_admin+eip' "${VENV_DIR}/bin/python" || true
    fi
  fi
}

install_systemd_units() {
  log "Installing systemd units"
  cp "${BACKEND_DIR}/systemd/omnicontrol.service" /etc/systemd/system/omnicontrol.service
  cp "${BACKEND_DIR}/systemd/omnicontrol-agent.service" /etc/systemd/system/omnicontrol-agent.service
  systemctl daemon-reload
  systemctl enable --now omnicontrol-agent.service
  systemctl enable --now omnicontrol.service
}

main() {
  require_root
  create_user_if_needed
  install_packages
  clone_repo
  setup_venv
  configure_capabilities
  install_systemd_units
  log "Bootstrap complete. Tail logs with:"
  log "  sudo journalctl -u omnicontrol.service -f"
  log "  sudo journalctl -u omnicontrol-agent.service -f"
}

main "$@"
