#!/bin/bash
# EC2 User Data script for Amazon Linux 2023
dnf update -y
dnf install -y python3.11 python3.11-pip git

# 安裝 Python packages
pip3.11 install pandas openpyxl numpy python-pptx boto3 fastapi uvicorn python-multipart python-dotenv

# Clone project
cd /home/ec2-user
git clone https://github.com/stoy95536/2026_AWS_Contest.git app
chown -R ec2-user:ec2-user app
cd app

# 建立 outputs 和 uploads 目錄
mkdir -p outputs uploads
chown -R ec2-user:ec2-user outputs uploads

# 啟動 server
nohup python3.11 app/api/server.py > /home/ec2-user/app.log 2>&1 &
