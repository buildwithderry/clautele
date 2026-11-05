#!/usr/bin/env bash
# Pasang Clautele langsung di host (tanpa Docker) sebagai systemd *user* service.
# PERINGATAN: Claude Code akan punya akses sepenuh akun Linux ini, bukan sandbox.
# Skrip ini tidak memakai sudo dan tidak mengubah paket sistem.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'GAGAL: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || die "python3 tidak ditemukan."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Butuh Python 3.10+."
command -v claude >/dev/null || die "Claude Code belum terpasang / tidak ada di PATH (https://claude.com/claude-code)."
command -v systemctl >/dev/null || die "systemd tidak ditemukan; jalankan manual: .venv/bin/python -m clautele"

say "Menyiapkan virtualenv (.venv)"
if [ ! -x .venv/bin/python ]; then
  if ! python3 -m venv .venv 2>/dev/null; then
    echo "python3-venv tidak ada; memakai venv tanpa pip + get-pip.py resmi (bootstrap.pypa.io)."
    echo "Alternatif: sudo apt install python3-venv, lalu jalankan ulang skrip ini."
    rm -rf .venv
    python3 -m venv --without-pip .venv
    tmp="$(mktemp -d)"
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$tmp/get-pip.py"
    .venv/bin/python "$tmp/get-pip.py" --quiet
    rm -rf "$tmp"
  fi
fi
.venv/bin/python -m pip install --quiet -r requirements.txt

command -v ffmpeg >/dev/null || echo "Catatan: ffmpeg tidak ditemukan; fitur video nonaktif. Opsional: sudo apt install ffmpeg fonts-dejavu-core"

say "Memeriksa .env"
if [ ! -f .env ]; then
  cp .env.example .env && chmod 600 .env
  die ".env dibuat dari .env.example. Isi TELEGRAM_BOT_TOKEN dan ALLOWED_USER_IDS, lalu jalankan ulang."
fi
for key in TELEGRAM_BOT_TOKEN ALLOWED_USER_IDS TOTP_SECRET; do
  grep -Eq "^${key}=.+" .env || die "$key belum diisi di .env$( [ "$key" = TOTP_SECRET ] && echo " (2FA WAJIB di mode host: jalankan di terminal pribadi  .venv/bin/python -m clautele.totp )")"
done
grep -Eq '^CLAUDE_WORKDIR=.+' .env || echo "Catatan: CLAUDE_WORKDIR kosong -> memakai ./workspace. Isi mis. CLAUDE_WORKDIR=$HOME/apps untuk akses lebih luas."

say "Memasang service systemd (user)"
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" deploy/clautele.service.template > "$unit_dir/clautele.service"
systemctl --user daemon-reload

if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx clautele; then
  echo "Container Docker 'clautele' masih jalan. Dua instance dengan token yang sama saling bentrok (Telegram 409)."
  echo "Hentikan dulu:  docker compose stop clautele"
  die "Hentikan container lalu jalankan ulang skrip."
fi

systemctl --user enable --now clautele.service
if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
  loginctl enable-linger "$USER" 2>/dev/null \
    || echo "Agar service tetap hidup setelah logout, jalankan:  sudo loginctl enable-linger $USER"
fi

say "Selesai"
echo "Status : systemctl --user status clautele"
echo "Log    : journalctl --user -u clautele -f"
echo "Stop   : systemctl --user disable --now clautele"
