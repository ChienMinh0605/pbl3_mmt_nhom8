"""Bộ nhãn dùng chung cho mọi script phía laptop (mục 4.4 của đặc tả, v0.3). Đổi nhãn thì chỉ sửa ở đây."""

# Trạng thái của người được giám sát: kéo dài từ lúc bấm tới lần bấm trạng thái tiếp theo.
STATES = ["EMPTY", "NEIGHBOR", "ACTIVE", "STILL", "DOWN", "BREATH_ABN"]

# Động tác: sự kiện ngắn, không đổi trạng thái. Đoạn động tác = [t + ACTION_WINDOW[0], t + ACTION_WINDOW[1]] giây,
# t = lúc bấm (bấm lúc bắt đầu động tác).
ACTIONS = ["FALL", "SIT_DOWN", "STAND_UP", "LIE_DOWN", "PICK_UP"]
ACTION_WINDOW = (-0.5, 2.5)
POSTURE_AFTER = {"FALL": "nằm", "SIT_DOWN": "ngồi", "STAND_UP": "đứng", "LIE_DOWN": "nằm", "PICK_UP": "đứng"}

# Phím ghi nhãn trên logger: phím -> (event, value). R (nhịp thở) và T (ghi chú) cần gõ thêm nên xử lý riêng.
KEYMAP = {
    "e": ("STATE", "EMPTY"), "n": ("STATE", "NEIGHBOR"),
    "a": ("STATE", "ACTIVE"), "w": ("STATE", "ACTIVE"),
    "s": ("STATE", "STILL"), "d": ("STATE", "DOWN"),
    "b": ("STATE", "BREATH_ABN"), "p": ("STATE", "PAUSE"),
    "f": ("ACTION", "FALL"), "g": ("ACTION", "SIT_DOWN"), "u": ("ACTION", "STAND_UP"),
    "l": ("ACTION", "LIE_DOWN"), "c": ("ACTION", "PICK_UP"),
    "+": ("COUNT", "+1"), "=": ("COUNT", "+1"), "-": ("COUNT", "-1"),
}

# Có người hay không (cột `label` trong file đặc trưng)
PRESENCE = {"EMPTY": 0, "NEIGHBOR": 0, "ACTIVE": 1, "STILL": 1, "DOWN": 1, "BREATH_ABN": 1}

# Mức hoạt động (cột `activity`): 0 trống, 1 hoạt động, 2 yên
ACTIVITY = {"EMPTY": 0, "NEIGHBOR": 0, "ACTIVE": 1, "STILL": 2, "DOWN": 2, "BREATH_ABN": 2}

# Trạng thái có thể rất ngắn theo thiết kế, không cảnh báo "đoạn nhãn quá ngắn"
SHORT_OK = {"PAUSE"}
