#!/usr/bin/env python3
"""Train và đánh giá mô hình Empty/Occupied từ file đặc trưng (mục 5 của đặc tả v0.1).

Ví dụ:
    python train.py                                   # dữ liệu thật trong ../data/features
    python train.py --features-dir ../data/features_gia   # dữ liệu giả (tạo bằng tao_dac_trung_gia.py)
    python train.py --feature-set rssi                # chỉ dùng RSSI (so sánh với CSI như bài báo 2)

Các bước:
1. Đọc mọi file .csv trong thư mục đặc trưng, bỏ window không hợp lệ (valid = 0).
2. Đánh giá chéo THEO BUỔI THU: mỗi lượt để riêng một buổi làm tập kiểm tra (leave-one-session-out),
   train trên các buổi còn lại. Không chia ngẫu nhiên theo window vì sẽ cho điểm cao ảo.
3. So sánh: baseline đặt ngưỡng trên phương sai, Random Forest, Gradient Boosting, XGBoost (nếu đã cài),
   và bỏ phiếu mềm của các mô hình trên (tầng 2 trong bài báo 2).
4. Train lại mô hình được chọn trên toàn bộ dữ liệu và lưu vào ../models/ để dashboard dùng.
"""
import argparse
import json
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, VotingClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut

try:
    from xgboost import XGBClassifier
except ImportError:
    XGBClassifier = None

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC_VERSION = "0.2"
FEATURE_RE = re.compile(r"^(rssi|csi)_(var|mad|range|iqr)(_\d{2})?$")
REQUIRED = ["session_id", "win_start", "valid", "label_detail", "label"]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nhan import STATES as DETAIL_ORDER  # noqa: E402


# --------------------------------------------------------------------------- dữ liệu
def load_features(folder):
    files = sorted(Path(folder).glob("*.csv"))
    if not files:
        sys.exit(f"Không có file .csv nào trong {folder}")
    frames, feat_sets = [], []
    for f in files:
        df = pd.read_csv(f)
        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            sys.exit(f"{f.name} thiếu cột {missing} (xem mục 5 của đặc tả)")
        frames.append(df)
        feat_sets.append({c for c in df.columns if FEATURE_RE.match(c)})
    common = set.intersection(*feat_sets)
    dropped = set.union(*feat_sets) - common
    if dropped:
        print(f"[!] {len(dropped)} cột đặc trưng không có ở mọi file nên bị bỏ (vd. {sorted(dropped)[:3]}). "
              "Kiểm tra danh sách sóng mang con giữa các buổi thu.")
    data = pd.concat(frames, ignore_index=True)
    feats = sorted(common, key=lambda c: (not c.startswith("rssi"), c[-2:], c))
    return data, feats


def select_features(feats, which):
    if which == "rssi":
        return [c for c in feats if c.startswith("rssi_")]
    if which == "csi":
        return [c for c in feats if c.startswith("csi_")]
    return list(feats)


# --------------------------------------------------------------------------- mô hình
class VarianceThreshold(ClassifierMixin, BaseEstimator):
    """Baseline: điểm = trung bình log(1 + phương sai) của các cột *_var; chọn ngưỡng tốt nhất trên tập train."""

    def __init__(self, feature_names=None):
        self.feature_names = feature_names

    def fit(self, X, y):
        names = self.feature_names or []
        self.cols_ = [i for i, c in enumerate(names) if "_var" in c] or list(range(np.shape(X)[1]))
        s = self._score(X)
        cands = np.quantile(s, np.linspace(0.01, 0.99, 99))
        accs = [np.mean((s > t) == y) for t in cands]
        self.threshold_ = float(cands[int(np.argmax(accs))])
        self.classes_ = np.array([0, 1])
        return self

    def _score(self, X):
        return np.log1p(np.clip(np.asarray(X, dtype=float)[:, self.cols_], 0, None)).mean(axis=1)

    def predict(self, X):
        return (self._score(X) > self.threshold_).astype(int)

    def predict_proba(self, X):
        p = 1 / (1 + np.exp(-5 * (self._score(X) - self.threshold_)))
        return np.column_stack([1 - p, p])


def build_models(feat_names, seed=0):
    base = {
        "rf": RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=seed),
        # max_features="sqrt": mỗi lần chia nhánh chỉ xét √(số cột) đặc trưng -> nhanh hơn nhiều với ~200 cột
        "gb": GradientBoostingClassifier(max_features="sqrt", random_state=seed),
    }
    if XGBClassifier is not None:
        base["xgb"] = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.1, subsample=0.9,
                                    colsample_bytree=0.5, eval_metric="logloss", n_jobs=-1, random_state=seed)
    models = {"nguong": VarianceThreshold(feature_names=feat_names)}
    models.update(base)
    models["bophieu"] = VotingClassifier(list(base.items()), voting="soft")
    return models


NAMES = {"nguong": "Baseline ngưỡng phương sai", "rf": "Random Forest", "gb": "Gradient Boosting",
         "xgb": "XGBoost", "bophieu": "Bỏ phiếu mềm (RF+GB+XGB)"}


# --------------------------------------------------------------------------- đánh giá
def cross_validate(models, X, y, groups, folds):
    n_groups = len(np.unique(groups))
    splitter = LeaveOneGroupOut() if folds == 0 or folds >= n_groups else GroupKFold(n_splits=folds)
    splits = list(splitter.split(X, y, groups))
    out = {}
    for key, model in models.items():
        if key == "bophieu":
            continue
        t = time.time()
        proba = np.zeros(len(y))
        for tr, te in splits:
            m = clone(model)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m.fit(X[tr], y[tr])
            proba[te] = m.predict_proba(X[te])[:, 1]
        pred = (proba >= 0.5).astype(int) if key != "nguong" else (proba > 0.5).astype(int)
        out[key] = {"proba": proba, "pred": pred, "seconds": time.time() - t}
        print(f"  {NAMES[key]:28s} xong ({out[key]['seconds']:.1f} giây)")
    if "bophieu" in models:
        # bỏ phiếu mềm = trung bình xác suất của các mô hình thành phần, tính lại từ kết quả ở trên
        members = [k for k, _ in models["bophieu"].estimators]
        proba = np.mean([out[k]["proba"] for k in members], axis=0)
        out["bophieu"] = {"proba": proba, "pred": (proba >= 0.5).astype(int), "seconds": 0.0}
        print(f"  {NAMES['bophieu']:28s} xong (tính từ {', '.join(members)})")
    for r in out.values():
        r["fold_acc"] = [accuracy_score(y[te], r["pred"][te]) for _, te in splits]
    return out, splits


def summarize(cv, y, detail, groups, splits):
    rows, per_detail, per_session = [], {}, {}
    for key, r in cv.items():
        p = r["pred"]
        rows.append({"model": key, "accuracy": accuracy_score(y, p), "f1": f1_score(y, p),
                     "fold_mean": float(np.mean(r["fold_acc"])), "fold_std": float(np.std(r["fold_acc"])),
                     "confusion": confusion_matrix(y, p, labels=[0, 1]).tolist()})
        per_detail[key] = {d: float(np.mean(p[detail == d] == y[detail == d]))
                           for d in DETAIL_ORDER if np.any(detail == d)}
        per_session[key] = {", ".join(sorted(map(str, set(groups[te])))): float(acc)
                            for (tr, te), acc in zip(splits, r["fold_acc"])}
    return rows, per_detail, per_session


def report(rows, per_detail, per_session, info, top_features):
    L = []
    L.append(f"KẾT QUẢ TRAIN – {info['created']}")
    L.append(f"Dữ liệu: {info['features_dir']}")
    L.append(f"Bộ đặc trưng: {info['feature_set']} ({info['n_features']} cột) | window hợp lệ: {info['n_windows']} "
             f"(Empty {info['n_empty']}, Occupied {info['n_occupied']}) | số buổi thu: {info['n_sessions']}")
    L.append(f"Đánh giá: {info['cv']}")
    if info.get("simulated"):
        L.append("[!] DỮ LIỆU GIẢ: các con số dưới đây chỉ để kiểm tra code, không phải kết quả đề tài.")
    L.append("")
    L.append(f"{'Mô hình':28s} {'Accuracy':>9s} {'F1':>7s} {'TB theo lượt':>14s}   Ma trận nhầm lẫn [[TN FP][FN TP]]")
    for r in sorted(rows, key=lambda r: -r["f1"]):
        L.append(f"{NAMES[r['model']]:28s} {r['accuracy']:9.3f} {r['f1']:7.3f} "
                 f"{r['fold_mean']:8.3f} ± {r['fold_std']:.3f}   {r['confusion']}")
    L.append("")
    L.append("Tỉ lệ đoán đúng theo nhãn chi tiết (EMPTY/NEIGHBOR đúng = đoán Empty; còn lại đúng = đoán Occupied):")
    details = [d for d in DETAIL_ORDER if any(d in v for v in per_detail.values())]
    L.append(f"{'Mô hình':28s} " + " ".join(f"{d:>9s}" for d in details))
    for key, v in per_detail.items():
        L.append(f"{NAMES[key]:28s} " + " ".join(f"{v.get(d, float('nan')):9.3f}" for d in details))
    L.append("")
    best = max(rows, key=lambda r: r["f1"])["model"]
    L.append(f"Accuracy từng lượt kiểm tra, theo (các) buổi thu làm tập kiểm tra ({NAMES[best]}):")
    for s, a in per_session[best].items():
        L.append(f"  {a:.3f}  {s}")
    if top_features:
        L.append("")
        L.append("10 đặc trưng quan trọng nhất (Random Forest):")
        for c, v in top_features:
            L.append(f"  {c:16s} {v:.4f}")
    return "\n".join(L)


# --------------------------------------------------------------------------- chương trình chính
def main():
    ap = argparse.ArgumentParser(description="Train và đánh giá mô hình Empty/Occupied.")
    ap.add_argument("--features-dir", default=str(ROOT / "data" / "features"))
    ap.add_argument("--feature-set", choices=["all", "csi", "rssi"], default="all")
    ap.add_argument("--folds", type=int, default=0, help="0 = mỗi buổi thu một lượt (mặc định)")
    ap.add_argument("--final", default="best", help="mô hình lưu lại: best, nguong, rf, gb, xgb, bophieu")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    data, feats = load_features(args.features_dir)
    meta_path = Path(args.features_dir) / "feature_meta.json"
    fmeta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    n_all = len(data)
    data = data[(data["valid"] == 1) & data["label"].isin([0, 1])].reset_index(drop=True)
    cols = select_features(feats, args.feature_set)
    if not cols:
        sys.exit(f"Không có cột đặc trưng nào cho bộ '{args.feature_set}'.")
    sessions = data["session_id"].unique()
    if len(sessions) < 2:
        sys.exit("Cần ít nhất 2 buổi thu để đánh giá theo buổi.")
    if data["label"].nunique() < 2:
        sys.exit("Dữ liệu chỉ có một lớp, không train được.")

    X = data[cols].to_numpy(dtype=float)
    y = data["label"].to_numpy(dtype=int)
    groups = data["session_id"].to_numpy()
    detail = data["label_detail"].to_numpy()
    print(f"Đọc {n_all} window, dùng {len(data)} window hợp lệ từ {len(sessions)} buổi thu, {len(cols)} đặc trưng.")

    models = build_models(cols, args.seed)
    cv_name = "leave-one-session-out" if args.folds == 0 or args.folds >= len(sessions) else f"GroupKFold {args.folds} phần"
    print(f"Đánh giá chéo theo buổi thu ({cv_name}):")
    cv, splits = cross_validate(models, X, y, groups, args.folds)
    rows, per_detail, per_session = summarize(cv, y, detail, groups, splits)

    final_key = max(rows, key=lambda r: r["f1"])["model"] if args.final == "best" else args.final
    if final_key not in models:
        sys.exit(f"--final không hợp lệ: {args.final}")
    print(f"Train lại {NAMES[final_key]} trên toàn bộ dữ liệu...")
    final = clone(models[final_key])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        final.fit(X, y)
        rf_full = clone(models["rf"]).fit(X, y)
    top = sorted(zip(cols, rf_full.feature_importances_), key=lambda t: -t[1])[:10]

    created = datetime.now().strftime("%Y%m%d_%H%M%S")
    info = {"created": created, "features_dir": str(Path(args.features_dir).resolve()), "feature_set": args.feature_set,
            "n_features": len(cols), "n_windows": int(len(data)), "n_empty": int((y == 0).sum()),
            "n_occupied": int((y == 1).sum()), "n_sessions": int(len(sessions)), "cv": cv_name,
            "simulated": bool(fmeta.get("simulated", False)), "final_model": final_key}
    text = report(rows, per_detail, per_session, info, top)
    print()
    print(text)

    res_dir = ROOT / "results" / f"{created}_{args.feature_set}"
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / "report.txt").write_text(text + "\n", encoding="utf-8")
    metrics = {"info": info, "models": [{k: v for k, v in r.items()} for r in rows], "per_detail": per_detail,
               "per_session": per_session, "top_features": top, "feature_meta": fmeta}
    (res_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    model_dir = ROOT / "models"
    model_dir.mkdir(exist_ok=True)
    bundle = {"model": final, "model_name": final_key, "feature_columns": cols, "feature_set": args.feature_set,
              "spec_version": SPEC_VERSION, "feature_meta": fmeta, "trained_on_sessions": [str(s) for s in sessions],
              "cv_metrics": next(r for r in rows if r["model"] == final_key), "created": created,
              "simulated": info["simulated"]}
    path = model_dir / f"model_{created}_{args.feature_set}_{final_key}.joblib"
    joblib.dump(bundle, path)
    joblib.dump(bundle, model_dir / "model_latest.joblib")
    print(f"\nĐã lưu báo cáo: {res_dir}\nĐã lưu mô hình: {path} (và model_latest.joblib)")


if __name__ == "__main__":
    main()
