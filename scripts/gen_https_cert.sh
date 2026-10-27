#!/bin/bash
# Shadow Learning - 生成 HTTPS 证书(本地 CA + 服务器叶子证书)
#
# 用于 iPad/iOS Safari 调用麦克风(getUserMedia 需要 secure context)。
#
# 用法:
#   bash scripts/gen_https_cert.sh              # 首次生成(CA + 叶子)
#   bash scripts/gen_https_cert.sh --leaf-only  # 只重签叶子(换了 IP 时用,不用重装根证书)
#   bash scripts/gen_https_cert.sh --ip 10.0.0.5 # 额外把某个 IP 写进 SAN
#
# 为什么是两级(CA + 叶子):
#   根证书(certs/ca.crt)由你手动装到设备上,装一次就够;
#   叶子证书(certs/server.crt)由本地 CA 签发,换 IP 了重签就行,
#   设备上不用再动一次信任设置。
#
# 代价:每台要用麦克风的设备都得信任这个根证书 —— 这是浏览器的规矩:
# 证书链不可信 → 页面不算安全上下文 → 不给麦克风。

set -e

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
CA_CERT="$CERT_DIR/ca.crt"
CA_KEY="$CERT_DIR/ca.key"
CERT_FILE="$CERT_DIR/server.crt"
KEY_FILE="$CERT_DIR/server.key"

FORCE=0
LEAF_ONLY=0
EXTRA_IPS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE=1; shift ;;
        --leaf-only) LEAF_ONLY=1; shift ;;
        --ip) EXTRA_IPS+=("$2"); shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

mkdir -p "$CERT_DIR"

# 提取本机局域网 IP
if [[ "$OSTYPE" == "darwin"* ]]; then
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")
else
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
fi

# mDNS 名字:不受 DHCP 换 IP 影响,证书里带上它更耐用
HOST_NAME=$(hostname 2>/dev/null || echo "")

if [[ $LEAF_ONLY -eq 1 ]]; then
    if [[ ! -f "$CA_CERT" || ! -f "$CA_KEY" ]]; then
        echo "❌ 还没有根证书,先跑一次: bash scripts/gen_https_cert.sh"
        exit 1
    fi
    echo "🔄 只重签叶子证书(根证书不变,设备上不用再信任一次)"
elif [[ -f "$CERT_FILE" && -f "$KEY_FILE" && $FORCE -eq 0 ]]; then
    echo "✅ 证书已存在:"
    echo "   根证书: $CA_CERT"
    echo "   服务器证书: $CERT_FILE"
    echo ""
    echo "   重新生成整套: bash scripts/gen_https_cert.sh --force"
    echo "   只重签叶子(换了 IP): bash scripts/gen_https_cert.sh --leaf-only"
    exit 0
fi

CNF_DIR=$(mktemp -d)
trap 'rm -rf "$CNF_DIR"' EXIT

# ---- 根证书(CA)----
cat > "$CNF_DIR/ca.cnf" <<'EOF'
[req]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no
[dn]
CN = Shadow Learning Local CA
O = Shadow Learning
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
EOF

# ---- 叶子证书的 SAN----
{
    cat <<EOF
[req]
distinguished_name = dn
req_extensions = v3_req
prompt = no
[dn]
CN = $LOCAL_IP
[v3_req]
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
IP.1 = 127.0.0.1
IP.2 = $LOCAL_IP
DNS.1 = localhost
EOF
    idx=2
    for ip in "${EXTRA_IPS[@]}"; do
        idx=$((idx + 1))
        echo "IP.$idx = $ip"
    done
    if [[ -n "$HOST_NAME" ]]; then
        echo "DNS.2 = $HOST_NAME"
    fi
} > "$CNF_DIR/leaf.cnf"

if [[ $LEAF_ONLY -eq 0 ]]; then
    echo "🔐 生成根证书(CA)..."
    openssl req -x509 -nodes -newkey rsa:2048 \
        -keyout "$CA_KEY" -out "$CA_CERT" -days 3650 \
        -config "$CNF_DIR/ca.cnf" -extensions v3_ca 2>/dev/null
    chmod 600 "$CA_KEY"
    chmod 644 "$CA_CERT"
fi

echo "🔐 签发服务器证书(CN=$LOCAL_IP)..."
openssl req -new -nodes -newkey rsa:2048 \
    -keyout "$KEY_FILE" -out "$CNF_DIR/server.csr" \
    -config "$CNF_DIR/leaf.cnf" 2>/dev/null
openssl x509 -req -in "$CNF_DIR/server.csr" \
    -CA "$CA_CERT" -CAkey "$CA_KEY" -CAcreateserial \
    -out "$CERT_FILE" -days 825 -sha256 \
    -extfile "$CNF_DIR/leaf.cnf" -extensions v3_req 2>/dev/null

chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"

echo ""
echo "✅ 证书就绪:"
echo "   根证书(要装到设备上): $CA_CERT"
echo "   服务器证书(服务端自己用): $CERT_FILE"
echo "   IP:   $LOCAL_IP"
[[ -n "$HOST_NAME" ]] && echo "   名字: $HOST_NAME"
echo ""
echo "📱 信任根证书(每台要用麦克风的设备做一次):"
echo ""
echo "  【Mac】加进系统钥匙串,输一次自己的密码就行:"
echo "    sudo security add-trusted-cert -d -r trustRoot \\"
echo "        -k /Library/Keychains/System.keychain $CA_CERT"
echo ""
echo "  【iPad / iPhone】装成描述文件 + 打开信任:"
echo "    1. 把 ca.crt 传到设备上(AirDrop / 邮件 / 微信文件传输助手都行)"
echo "    2. 「设置 → 通用 → VPN 与设备管理」里安装这个描述文件"
echo "    3. 「设置 → 通用 → 关于本机 → 证书信任设置」里找到它,打开「完全信任」"
echo ""
echo "  ⚠️ 只在 Safari 里点「访问此网站」不够 —— 证书链不可信时页面不算"
echo "     安全上下文,浏览器照样不给麦克风。必须走上面的信任流程。"
echo ""
echo "🔄 换 IP 了不用重装根证书,只重签叶子: bash scripts/gen_https_cert.sh --leaf-only"
echo "   (或者用 mDNS 名字访问: https://$HOST_NAME:5002 —— 名字不变就不怕换 IP)"
