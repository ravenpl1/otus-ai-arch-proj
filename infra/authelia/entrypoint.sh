#!/bin/sh
# =============================================================
# Authelia 4.37 Entrypoint
# - Generates secrets using /dev/urandom
# - Generates OIDC RSA signing key via authelia crypto
# - Patches configuration.yml with inline PEM key
# - Generates user password hashes from credentials.env
# - Starts Authelia
# =============================================================

CONFIG_TEMPLATE="/templates/configuration.yml"
CONFIG_FILE="/config/configuration.yml"
USERS_DB="/config/users_database.yml"
MARKER="/config/.credentials_initialized"

# If already initialized and config exists, just start Authelia
if [ -f "$MARKER" ] && [ -f "$CONFIG_FILE" ]; then
    if ! grep -q 'JWT_SECRET_PLACEHOLDER' "$CONFIG_FILE" 2>/dev/null; then
        echo "[entrypoint] Already initialized, starting Authelia..."
        exec authelia --config "$CONFIG_FILE"
    fi
    echo "[entrypoint] Config has placeholders — re-patching..."
fi

# Copy fresh template to writable config directory
cp "$CONFIG_TEMPLATE" "$CONFIG_FILE"

echo "[entrypoint] First start — initializing..."

# ── 1. Generate secrets ────────────────────────────────────────
echo "[entrypoint] Generating secrets..."

generate_secret() {
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

JWT_SECRET=$(generate_secret)
echo "  jwt_secret: OK"

SESSION_SECRET=$(generate_secret)
echo "  session_secret: OK"

# ── 2. Generate OIDC RSA signing key ───────────────────────────
OIDC_KEY_FILE="/config/oidc_key.pem"
echo "[entrypoint] Generating OIDC signing key (RSA)..."
authelia crypto pair rsa generate -d /config --file.private-key oidc_key.pem 2>&1
chmod 600 "$OIDC_KEY_FILE"
echo "  oidc_private_key: OK"

# ── 3. Patch configuration.yml ─────────────────────────────────
echo "[entrypoint] Patching configuration.yml..."

# Extract AUTH_HOST from AUTHELIA_URL (e.g. http://192.168.1.55:9091 → 192.168.1.55)
AUTHELIA_URL="${AUTHELIA_URL:-http://127.0.0.1:9091}"
AUTH_HOST=$(echo "$AUTHELIA_URL" | sed 's|https\?://||' | cut -d: -f1)
BACKEND_HOST="${BACKEND_HOST:-$AUTH_HOST}"
echo "  AUTH_HOST=${AUTH_HOST}  BACKEND_HOST=${BACKEND_HOST}"

# Step 1: Replace simple placeholders
awk \
    -v jwt="$JWT_SECRET" \
    -v session="$SESSION_SECRET" \
    -v auth_host="$AUTH_HOST" \
    -v backend_host="$BACKEND_HOST" '
{
    gsub(/JWT_SECRET_PLACEHOLDER/, jwt)
    gsub(/SESSION_SECRET_PLACEHOLDER/, session)
    gsub(/AUTH_HOST_PLACEHOLDER/, auth_host)
    gsub(/BACKEND_HOST_PLACEHOLDER/, backend_host)
    print
}' "$CONFIG_FILE" > "${CONFIG_FILE}.tmp" && mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"

# Step 2: Replace OIDC_KEY_PLACEHOLDER with inline PEM
awk -v keyfile="$OIDC_KEY_FILE" '
{
    if ($0 ~ /OIDC_KEY_PLACEHOLDER/) {
        printf "    issuer_private_key: |\n"
        while ((getline line < keyfile) > 0) {
            print "      " line
        }
        close(keyfile)
    } else {
        print
    }
}' "$CONFIG_FILE" > "${CONFIG_FILE}.tmp" && mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"

echo "[entrypoint] configuration.yml patched."

# ── 4. Generate user password hashes ────────────────────────────
if [ ! -f /credentials.env ]; then
    echo "[entrypoint] ERROR: /credentials.env not found!"
    exit 1
fi
. /credentials.env

hash_password() {
    result=$(authelia crypto hash generate argon2 --password "$1" 2>&1)
    hash=$(echo "$result" | sed -n 's/^.*Digest: //p' | tr -d '[:space:]')
    if [ -z "$hash" ]; then
        hash=$(echo "$result" | sed -n 's/^.*Hash: //p' | tr -d '[:space:]')
    fi
    if [ -z "$hash" ]; then
        echo "[entrypoint] ERROR: Failed to hash password." >&2
        echo "$result" >&2
        exit 1
    fi
    echo "$hash"
}

echo "[entrypoint] Hashing user passwords..."
HASH_IVAN=$(hash_password "$IVAN_PASSWORD")
echo "  ivan: OK"
HASH_MARIA=$(hash_password "$MARIA_PASSWORD")
echo "  maria: OK"
HASH_OLGA=$(hash_password "$OLGA_PASSWORD")
echo "  olga: OK"
HASH_ADMIN=$(hash_password "$ADMIN_PASSWORD")
echo "  admin: OK"

cat > "$USERS_DB" << ENDOFFILE
---
users:
  ivan:
    disabled: false
    displayname: "Иван Иванов"
    password: "${HASH_IVAN}"
    email: ivan@rfsd-rag.local
    groups:
      - users

  maria:
    disabled: false
    displayname: "Мария Петрова"
    password: "${HASH_MARIA}"
    email: maria@rfsd-rag.local
    groups:
      - data_stewards
      - users

  olga:
    disabled: false
    displayname: "Ольга Сидорова"
    password: "${HASH_OLGA}"
    email: olga@rfsd-rag.local
    groups:
      - finance
      - users

  admin:
    disabled: false
    displayname: "Администратор Системы"
    password: "${HASH_ADMIN}"
    email: admin@rfsd-rag.local
    groups:
      - admin
      - data_stewards
      - finance
      - users
ENDOFFILE

echo "[entrypoint] users_database.yml generated."

touch "$MARKER"

echo "[entrypoint] Initialization complete!"
echo "[entrypoint] Starting Authelia..."

exec authelia --config "$CONFIG_FILE"
