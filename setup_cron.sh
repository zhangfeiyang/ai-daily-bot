#!/bin/bash
# setup_cron.sh — 设置定时任务

PROJECT_DIR="/home/zhangfy/gongzhonghao"
PYTHON="$PROJECT_DIR/.venv/bin/python"

echo "Setting up cron jobs for AI news pipeline..."
echo ""

# 清除旧的 gongzhonghao 相关任务
crontab -l 2>/dev/null | grep -v "gongzhonghao" | { cat; echo "30 7 * * * cd $PROJECT_DIR && $PYTHON main.py daily >> $PROJECT_DIR/logs/cron.log 2>&1"; echo "0 10 * * 0 cd $PROJECT_DIR && $PYTHON main.py weekly >> $PROJECT_DIR/logs/cron.log 2>&1"; } | crontab -

echo "Cron jobs installed:"
crontab -l | grep gongzhonghao
echo ""
echo "Done!"
