#!/bin/bash
export STATE_DB="${STATE_DB:-/root/asuan-scheduler/data/liuhai_chan.db}"
export FORCE_SANDBOX_RUN=1
cd /root/asuan-scheduler
python3 scheduler.py
