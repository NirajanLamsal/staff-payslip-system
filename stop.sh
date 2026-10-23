#!/usr/bin/env bash
cd "$(dirname "$(readlink -f "$0")")" || exit 1
if [ -f .payslip.pid ] && kill -0 "$(cat .payslip.pid)" 2>/dev/null; then
  kill "$(cat .payslip.pid)" && echo "Payslip Manager stopped."
else
  echo "Payslip Manager is not running."
fi
rm -f .payslip.pid .payslip.port
