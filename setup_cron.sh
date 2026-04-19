#!/bin/bash
# setup_cron.sh — 设置定时任务

PROJECT_DIR="/home/zhangfy/gongzhonghao"
PYTHON="$(which python3)"

echo "Setting up cron jobs for AI news pipeline..."
echo ""

# 每日 8:00 执行
(crontab -l 2>/dev/null; echo "0 8 * * * cd $PROJECT_DIR && $PYTHON main.py daily >> logs/cron.log 2>&1") | sort -u | crontab -

# 每周日 10:00 执行
(crontab -l 2>/dev/null; echo "0 10 * * 0 cd $PROJECT_DIR && $PYTHON main.py weekly >> logs/cron.log 2>&1") | sort -u | crontab -

echo "Cron jobs installed:"
crontab -l | grep gongzhonghao
echo ""
echo "Done! Use 'crontab -l' to verify."
