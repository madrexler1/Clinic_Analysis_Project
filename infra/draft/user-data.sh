#!/bin/bash
###############################################################################
# Smartemis draft env — first-boot bootstrap.
#   1. install runtime + tooling
#   2. clone the public repo
#   3. install python deps + generate synthetic data
#   4. fetch basic-auth creds from Secrets Manager → htpasswd
#   5. self-signed TLS cert for the public IP
#   6. nginx (TLS + basic auth + reverse proxy → uvicorn)
#   7. systemd unit for uvicorn — survives reboots
#
# All output goes to /var/log/cloud-init-output.log on the instance.
# Tail it from your laptop with the `tail_bootstrap_log` Terraform output.
###############################################################################
set -euxo pipefail

AWS_REGION="${aws_region}"
BEDROCK_MODEL_ID="${bedrock_model_id}"
REPO_URL="${repo_url}"
REPO_REF="${repo_ref}"
SECRET_ID="${basic_auth_secret}"

APP_DIR="/opt/smartemis"
APP_USER="ec2-user"

# ---- 1. OS packages ---------------------------------------------------------
dnf update -y
dnf install -y git nginx httpd-tools openssl python3.11 python3.11-pip jq

# ---- 2. Clone repo ----------------------------------------------------------
rm -rf "$APP_DIR"
git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$APP_DIR"

# ---- 3. Python deps + synthetic data ---------------------------------------
python3.11 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -e "$APP_DIR"

# Generate synthetic CSV. Repo's relative default path needs cwd=$APP_DIR.
(cd "$APP_DIR" && "$APP_DIR/.venv/bin/python" -m synthetic_data.generate \
    --invoices 2000 --clinics 12)

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ---- 4. Basic-auth secret → htpasswd ---------------------------------------
SECRET_JSON=$(aws secretsmanager get-secret-value \
    --region "$AWS_REGION" \
    --secret-id "$SECRET_ID" \
    --query SecretString --output text)

BA_USER=$(echo "$SECRET_JSON" | jq -r .username)
BA_PASS=$(echo "$SECRET_JSON" | jq -r .password)

htpasswd -bc /etc/nginx/.htpasswd "$BA_USER" "$BA_PASS"
chmod 640 /etc/nginx/.htpasswd
chown root:nginx /etc/nginx/.htpasswd

# ---- 5. Self-signed TLS for the public IP ----------------------------------
PUBLIC_IP=$(curl -sf -H "X-aws-ec2-metadata-token: $(curl -sf -X PUT 'http://169.254.169.254/latest/api/token' -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" http://169.254.169.254/latest/meta-data/public-ipv4)
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/smartemis.key \
    -out    /etc/nginx/ssl/smartemis.crt \
    -subj "/CN=smartemis-draft" \
    -addext "subjectAltName=IP:$${PUBLIC_IP}"
chmod 600 /etc/nginx/ssl/smartemis.key

# ---- 6. nginx config -------------------------------------------------------
# AL2023's default /etc/nginx/nginx.conf includes an inline server{} on :80.
# Replace the whole file with a minimal http{} that only loads conf.d/*.conf,
# so our smartemis.conf is the single source of truth for server blocks.
cat > /etc/nginx/nginx.conf <<'NGINX_MAIN'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" "$http_user_agent"';
    access_log /var/log/nginx/access.log main;
    sendfile on;
    keepalive_timeout 65;
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    include /etc/nginx/conf.d/*.conf;
}
NGINX_MAIN

cat > /etc/nginx/conf.d/smartemis.conf <<'NGINX'
server {
    listen 80 default_server;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl default_server;
    server_name _;

    ssl_certificate     /etc/nginx/ssl/smartemis.crt;
    ssl_certificate_key /etc/nginx/ssl/smartemis.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    auth_basic           "Smartemis (draft env)";
    auth_basic_user_file /etc/nginx/.htpasswd;

    # PDF generation can take ~30-60s; bump timeouts so the proxy waits.
    proxy_read_timeout 180s;
    proxy_send_timeout 180s;
    client_max_body_size 25m;

    # Live token streaming (POST /api/reports/stream): nginx must NOT buffer
    # the upstream response, or the UI sees the whole report in one chunk.
    proxy_buffering    off;
    proxy_cache        off;
    proxy_http_version 1.1;
    gzip               off;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_set_header   Connection        "";
    }
}
NGINX

nginx -t

# ---- 7. systemd unit for uvicorn -------------------------------------------
cat > /etc/systemd/system/smartemis.service <<UNIT
[Unit]
Description=Smartemis FastAPI app
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/uvicorn smartemis.api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
User=$APP_USER
Environment=AWS_REGION=$AWS_REGION
Environment=SMARTEMIS_BEDROCK_MODEL_ID=$BEDROCK_MODEL_ID
Environment=SMARTEMIS_ENV=draft
Environment=SMARTEMIS_LOG_LEVEL=INFO
Environment=SMARTEMIS_PSEUDO_SALT=draft-env-rotate-me-in-prod

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now smartemis.service
systemctl enable --now nginx

echo "=================================================="
echo "Smartemis draft env bootstrap complete."
echo "Public URL: https://$${PUBLIC_IP}/"
echo "=================================================="
