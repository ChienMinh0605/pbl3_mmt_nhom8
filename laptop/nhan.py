"""Bộ nhãn dùng chung cho mọi script phía laptop (mục 4.4 của đặc tả, v0.2). Đổi nhãn thì chỉ sửa ở đây."""

# Trạng thái của người được giám sát. FALL là sự kiện ngắn (1–2 giây), các nhãn khác là trạng thái kéo dài.
STATES = ["EMPTY", "NEIGHBOR", "ACTIVE", "STILL", "FALL", "DOWN", "BREATH_ABN"]

# Phím ghi nhãn trên logger: phím -> (event, value)
KEYMAP = {
    "e": ("STATE", "EMPTY"), "n": ("STATE", "NEIGHBOR"),
    "a": ("STATE", "ACTIVE"), "w": ("STATE", "ACTIVE"),
    "s": ("STATE", "STILL"), "f": ("STATE", "FALL"), "d": ("STATE", "DOWN"),
    "b": ("STATE", "BREATH_ABN"), "p": ("STATE", "PAUSE"),
    "+": ("COUNT", "+1"), "=": ("COUNT", "+1"), "-": ("COUNT", "-1"),
}

# Tầng 1 – có người hay không (cột `label` trong file đặc trưng)
PRESENCE = {"EMPTY": 0, "NEIGHBOR": 0, "ACTIVE": 1, "STILL": 1, "FALL": 1, "DOWN": 1, "BREATH_ABN": 1}

# Tầng 1 – mức hoạt động (cột `activity`): 0 trống, 1 hoạt động, 2 yên. FALL không có (là sự kiện, xử lý ở tầng 2).
ACTIVITY = {"EMPTY": 0, "NEIGHBOR": 0, "ACTIVE": 1, "STILL": 2, "DOWN": 2, "BREATH_ABN": 2}

# Nhãn chỉ dài 1–2 giây theo thiết kế, không cảnh báo "đoạn nhãn quá ngắn"
SHORT_OK = {"PAUSE", "FALL"}
