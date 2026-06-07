#!/bin/bash
# Shadow Learning - 生成 HTTPS 自签名证书
# 用于 iPad/iOS Safari 调用麦克风（getUserMedia 需 secure context）

set -e

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
CERT_FILE="$CERT_DIR/server.crt"
KEY_FILE="$CERT_DIR/server.key"

mkdir -p "$CERT_DIR"

if [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]]; then
    echo "✅ 证书已存在:"
    echo "   $CERT_FILE"
    echo "   $KEY_FILE"
    echo ""
    echo "   重新生成请先删除: rm $CERT_DIR/server.*"
    exit 0
fi

# 提取本机局域网 IP
if [[ "$OSTYPE" == "darwin"* ]]; then
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")
else
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
fi

echo "🔐 生成自签名证书（CN=$LOCAL_IP）..."

# 写 OpenSSL 配置（含 SAN）
OPENSSL_CNF=$(mktemp)
cat > "$OPENSSL_CNF" <<EOF
[req]
default_bits       = 2048
default_md         = sha256
distinguished_name = dn
req_extensions     = v3_req
prompt             = no

[dn]
CN = $LOCAL_IP

[v3_req]
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
IP.1 = 127.0.0.1
IP.2 = $LOCAL_IP
DNS.1 = localhost
EOF

# 生成私钥 + 自签名证书（有效期 825 天 = Chrome 限制上限）
openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -days 825 \
    -config "$OPENSSL_CNF" \
    -extensions v3_req 2>/dev/null

rm -f "$OPENSSL_CNF"

chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"

echo ""
echo "✅ 证书生成完成:"
echo "   证书: $CERT_FILE"
echo "   私钥: $KEY_FILE"
echo "   IP:   $LOCAL_IP"
echo ""
echo "📱 iPad/iOS 首次访问会提示'此连接不是私密连接'，需要："
echo "   1. 点击'显示详细信息'"
echo "   2. 点击'访问此网站'"
echo "   3. 确认信任自签名证书"
echo ""
echo "🔄 或在 Mac 上把证书加入钥匙串:"
echo "   sudo security add-trusted-cert -d -r trustRoot \\"
echo "       -k /Library/Keychains/System.keychain $CERT_FILE"
