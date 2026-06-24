"""
Relay Server - Trung gian giữa Main Program và ESP32 Wokwi
=============================================================
Endpoints:
  POST /provision          ← Main Program gửi token lên
  GET  /provision/<id>     ← ESP32 poll lấy token
  GET  /status             ← Xem trạng thái tất cả device
  DELETE /provision/<id>   ← Xoá token của device
"""

from flask import Flask, jsonify, request
from datetime import datetime, timedelta
import logging
import threading

# ─────────────────────────────────────
# Cấu hình
# ─────────────────────────────────────
PORT           = 5000
HOST           = "0.0.0.0"
TOKEN_TTL_MIN  = 10   # Token hết hạn sau N phút nếu chưa được lấy

# ─────────────────────────────────────
# Setup logging
# ─────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(message)s",
    datefmt= "%H:%M:%S"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ─────────────────────────────────────
# Storage: { device_id → entry }
# ─────────────────────────────────────
# entry = {
#   "token":      str,
#   "claimed":    bool,
#   "created_at": datetime,
#   "claimed_at": datetime | None
# }
store = {}
store_lock = threading.Lock()


# ═══════════════════════════════════════════════════════
# ENDPOINT 1: Main Program → gửi token vào relay
#   POST /provision
#   Body: { "device_id": "esp32-001", "token": "xxx" }
# ═══════════════════════════════════════════════════════
@app.route("/provision", methods=["POST"])
def set_token():
    data = request.get_json(silent=True)

    # Validate input
    if not data:
        return jsonify({"error": "Body phải là JSON"}), 400

    device_id = data.get("device_id", "").strip()
    token     = data.get("token", "").strip()

    if not device_id:
        return jsonify({"error": "Thiếu device_id"}), 400
    if not token:
        return jsonify({"error": "Thiếu token"}), 400

    with store_lock:
        store[device_id] = {
            "token":      token,
            "claimed":    False,
            "created_at": datetime.now(),
            "claimed_at": None
        }

    log.info(f"📥 Token mới | device={device_id} | token={token[:8]}...")
    return jsonify({
        "ok":       True,
        "device_id": device_id,
        "message":  "Token đã được lưu, chờ ESP32 lấy"
    }), 201


# ═══════════════════════════════════════════════════════
# ENDPOINT 2: ESP32 → poll lấy token của mình
#   GET /provision/<device_id>
# ═══════════════════════════════════════════════════════
@app.route("/provision/<device_id>", methods=["GET"])
def get_token(device_id):
    with store_lock:
        entry = store.get(device_id)

        # Chưa có token
        if not entry:
            log.info(f"⏳ Chờ token | device={device_id}")
            return jsonify({
                "token":  None,
                "status": "waiting",
                "message": "Chưa có token, thử lại sau"
            })

        # Kiểm tra TTL — token quá hạn
        age = datetime.now() - entry["created_at"]
        if age > timedelta(minutes=TOKEN_TTL_MIN) and not entry["claimed"]:
            del store[device_id]
            log.warning(f"⚠️ Token hết hạn | device={device_id}")
            return jsonify({
                "token":  None,
                "status": "expired",
                "message": f"Token hết hạn sau {TOKEN_TTL_MIN} phút"
            })

        # Đã được lấy rồi
        if entry["claimed"]:
            return jsonify({
                "token":  None,
                "status": "already_claimed",
                "message": "Token đã được lấy trước đó"
            })

        # ✅ Cấp token — đánh dấu claimed
        entry["claimed"]    = True
        entry["claimed_at"] = datetime.now()
        token = entry["token"]

    log.info(f"✅ Token đã cấp | device={device_id}")
    return jsonify({
        "token":  token,
        "status": "ok",
        "message": "Token hợp lệ, kết nối ThingsBoard"
    })


# ═══════════════════════════════════════════════════════
# ENDPOINT 3: Xem trạng thái tất cả device
#   GET /status
# ═══════════════════════════════════════════════════════
@app.route("/status", methods=["GET"])
def get_status():
    with store_lock:
        result = {}
        for device_id, entry in store.items():
            age_s = (datetime.now() - entry["created_at"]).seconds
            result[device_id] = {
                "token_preview": entry["token"][:8] + "...",
                "claimed":       entry["claimed"],
                "age_seconds":   age_s,
                "claimed_at":    entry["claimed_at"].isoformat()
                                 if entry["claimed_at"] else None
            }

    return jsonify({
        "total_devices": len(result),
        "devices":       result
    })


# ═══════════════════════════════════════════════════════
# ENDPOINT 4: Xoá token của device
#   DELETE /provision/<device_id>
# ═══════════════════════════════════════════════════════
@app.route("/provision/<device_id>", methods=["DELETE"])
def delete_token(device_id):
    with store_lock:
        if device_id not in store:
            return jsonify({"error": "Device không tồn tại"}), 404
        del store[device_id]

    log.info(f"🗑️  Token xoá | device={device_id}")
    return jsonify({"ok": True, "message": f"Đã xoá token của {device_id}"})


# ═══════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


# ─────────────────────────────────────
# Chạy server
# ─────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  🚀 Relay Server")
    print(f"  http://localhost:{PORT}")
    print("=" * 50)
    print(f"  POST   /provision          ← Main Program gửi token")
    print(f"  GET    /provision/<id>     ← ESP32 lấy token")
    print(f"  GET    /status             ← Xem trạng thái")
    print(f"  DELETE /provision/<id>     ← Xoá token")
    print("=" * 50)
    app.run(host=HOST, port=PORT, debug=False)