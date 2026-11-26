# mo_hinh.bin, du_lieu_thu.bin do laptop/xuat_board.py tạo; nhúng vào flash, đọc qua _binary_*_start / _end
idf_component_register(SRCS "main.c" "kiem_tra.c" "dac_trung.c" "mo_hinh.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_timer esp_system heap
                       EMBED_FILES "mo_hinh.bin" "du_lieu_thu.bin")
