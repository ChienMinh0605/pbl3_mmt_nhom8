#!/usr/bin/env python3
"""Huấn luyện + đánh giá mô hình nhánh A từ các file đặc trưng (mục 5).
(Phần chính thức là việc của Chiến – script này để Tiên tự kiểm tra file đặc trưng có dùng được không.)

  py python/train.py                                       # data/features → models/model_a.joblib
  py python/train.py --features data_mo_phong/features --out models/model_mo_phong.joblib
  py python/train.py --chi-csi                             # bỏ 4 đặc trưng RSSI

- Chỉ dùng window valid = 1.
- Chia train/test THEO BUỔI THU (GroupKFold theo session_id).
- So với cách đơn giản: đặt ngưỡng trên phương sai CSI trung bình.
"""
import argparse
import glob
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, VotingClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold


def make_model():
    est = [("rf", RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=0)),
           ("gb", GradientBoostingClassifier(random_state=0))]
    try:
        from xgboost import XGBClassifier
        est.append(("xgb", XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.1,
                                         eval_metric="logloss", random_state=0)))
    except ImportError:
        print("  (chưa cài xgboost → chỉ bỏ phiếu RF + GB)")
    return VotingClassifier(est, voting="soft")


def fit_threshold(s, y):
    best_c, best = None, -1
    for c in np.quantile(s, np.linspace(0.01, 0.99, 99)):
        acc = ((s > c).astype(int) == y).mean()
        if acc > best:
            best_c, best = c, acc
    return best_c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features")
    ap.add_argument("--out", default="models/model_a.joblib")
    ap.add_argument("--chi-csi", action="store_true", help="không dùng đặc trưng RSSI")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.features, "*.csv")))
    if not files:
        sys.exit(f"Không thấy file đặc trưng trong {a.features}. Chạy features.py trước.")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    n_all = len(df)
    df = df[df["valid"] == 1].dropna()
    cols = [c for c in df.columns if c.startswith("csi_") or (c.startswith("rssi_") and not a.chi_csi)]
    X, y, g, det = df[cols].to_numpy(), df["label"].to_numpy(int), df["session_id"].to_numpy(), df["label_detail"].to_numpy()
    sessions = np.unique(g)
    print(f"{n_all} window, dùng {len(df)} window hợp lệ, {len(sessions)} buổi, {len(cols)} đặc trưng")
    print("Số window theo nhãn:", df.groupby("label_detail").size().to_dict())
    if len(sessions) < 2 or len(np.unique(y)) < 2:
        sys.exit("Cần ít nhất 2 buổi thu và đủ cả nhãn 0 lẫn 1.")

    var_cols = [i for i, c in enumerate(cols) if c.startswith("csi_var_")]
    s_base = np.log(X[:, var_cols] + 1e-6).mean(axis=1)
    pred, pred_b = np.zeros_like(y), np.zeros_like(y)
    for i, (tr, te) in enumerate(GroupKFold(n_splits=min(5, len(sessions))).split(X, y, g)):
        m = make_model().fit(X[tr], y[tr])
        pred[te] = m.predict(X[te])
        pred_b[te] = (s_base[te] > fit_threshold(s_base[tr], y[tr])).astype(int)
        print(f"  fold {i + 1}: test {sorted(map(str, set(g[te])))}  acc={accuracy_score(y[te], pred[te]):.3f}")

    print("\n=== Kết quả (cross-validation theo buổi thu) ===")
    print(f"Mô hình bỏ phiếu : accuracy={accuracy_score(y, pred):.3f}  F1={f1_score(y, pred):.3f}")
    print(f"Ngưỡng phương sai: accuracy={accuracy_score(y, pred_b):.3f}  F1={f1_score(y, pred_b):.3f}")
    print("Ma trận nhầm lẫn (hàng = thật Empty/Occupied, cột = dự đoán):")
    print(confusion_matrix(y, pred))
    print("\nAccuracy theo nhãn chi tiết:")
    for d in sorted(set(det)):
        mk = det == d
        print(f"  {d:9s} n={mk.sum():5d}  mô hình={accuracy_score(y[mk], pred[mk]):.3f}"
              f"  ngưỡng={accuracy_score(y[mk], pred_b[mk]):.3f}")

    model = make_model().fit(X, y)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    joblib.dump({"model": model, "feature_columns": cols}, a.out)
    print(f"\nĐã lưu mô hình (huấn luyện trên toàn bộ dữ liệu): {a.out}")


if __name__ == "__main__":
    main()
