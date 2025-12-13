# Hardware and Environment Setup for this project 
## Your environment will have to be edited but this is a guideline of what I did
### For this guide I will use
* username = your_username for the Pi
* usergroup = username's usergroup on the pi
* PC_PROJECT_DIR = Where your project lives on the PC
### Step 1 - Setup router and IP addresses (example)
* Allocate the IPs for devices on your home router
- 192.168.1.143 -> Shelly Pro 3EM
- 192.168.1.144 -> Raspberry Pi Zero 2W
* edit C:\Windows\System32\drivers\etc\hosts
* add 
    - 192.168.1.144 raspberry
    - 192.168.1.143 shelly
### Step 2 - Setup the Raspberry Pi out of the box
* From Windows Powershell ssh into Pi
    - You may need to connect to the Pi via monitor/kbd/mse and enable ssh unless you create a custom image
* Update the OS
```bash
sudo apt update
sudo apt upgrade -y
sudo apt autoremove -y
sudo systemctl set-default multi-user.target 
sudo reboot

sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    rsync \
    ca-certificates
sudo mkdir -p /mnt/power
```
### Step 3 - Setup the python envrionment
* start a python virtual environment
    - Going forward, you should be in the venv (noted by the prompt)
```bash
mkdir -p ~/shelly_logger
cd ~/shelly_logger
python3 -m venv venv
source venv/bin/activate
(venv) pip install --upgrade pip
(venv) pip install \
    requests \
    pandas \
    pyarrow \
    python-dotenv

(venv) pip install \
    numpy \
    fastparquet
```
* Verify the environment
```bash
(venv) python - << 'EOF'
import requests, pandas, pyarrow, dotenv
print("All imports OK")
EOF

(venv) nano .env

SHELLY_IP=192.168.1.143
OUTDIR=/mnt/power
INTERVAL_SECONDS=1
FLUSH_SECONDS=60
TIMEOUT_SECONDS=5
```
* Bring over shelly_logger.py from the Project Directory
 ```bash
 scp {PC_PROJECT_DIR}\src\shelly_logger.py {username}@raspberry:/home/{username}/shelly_logger/
 ```
### Step 4 - (Optional) Setup USB-SSD
#### I used a USB SSD to hold the data and not tax the SD card
* GET THE DATA OFF IF YOU WANT IT!
* Setup the disk for use
* find the unmounted disk (Assume sda going forward)
```
lsblk -f
```
* Repartition and make a new FS (may take a while)
```bash
sudo wipefs -a /dev/sda
sudo fdisk /dev/sda
sudo mkfs.ext4 -L power_data /dev/sda1

sudo mount /dev/sda1 /mnt/power
sudo chown -R {username}:{usergroup} /mnt/power
```
* Setup USB SSD to mount across reboots
    - Get the UUID
    - edit /etc/fstab
    - add line for the new disk
    - Test
```bash
sudo blkid /dev/sda1
sudo nano etc/fstab
```
UUID=xxxx-xxxx-xxxx-xxxx  /mnt/power  ext4  defaults,noatime,nofail  0  2
```bash
sudo umount /mnt/power
sudo mount -a
df -h | grep /mnt/power
```
#### Step 4 - Setup a service for the logger and cron job to monitor disk space
```bash
sudo nano /etc/systemd/system/shelly-logger.service

[Unit]
Description=Shelly Pro 3EM Energy Logger
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/mnt/power

[Service]
Type=simple
User={username}
WorkingDirectory=/home/{username}/shelly_logger
EnvironmentFile=/home/{username}/shelly_logger/.env
ExecStart=/home/{username}/shelly_logger/venv/bin/python /home/{username}/shelly_logger/shelly_logger.py
Restart=always
RestartSec=5
Nice=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```
* Run it and check status
```bash
sudo systemctl daemon-reload
sudo systemctl enable shelly-logger
sudo systemctl start shelly-logger
sudo systemctl status shelly-logger
```
```bash
crontab -e

Add: 
0 3 * * * find /mnt/power -type f -name "*.parquet" -mtime +30 -delete
0 3 * * * find /mnt/power -type f -name "*.parquet" -mtime +30 -print -delete >> /home/{username}/purge.log 2>&1
```
#### Step 5 - Verify it works
* Reboot
```bash
sudo reboot
```
* Check that files are writing to /mnt/power/
* Wait at least 60s for the flush and check tha the file is growing