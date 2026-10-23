#!/usr/bin/env bash
# Optional: adds a "Payslip Manager" icon to your applications menu.
D="$(dirname "$(readlink -f "$0")")"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/payslip-manager.desktop" <<EOT
[Desktop Entry]
Type=Application
Name=Payslip Manager
Exec=bash -c '"$D/start.sh"; sleep 3'
Icon=$D/assets/default_logo.png
Terminal=true
Categories=Office;
EOT
echo "Done. Search for 'Payslip Manager' in your applications menu."
