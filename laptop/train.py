#!/usr/bin/env python3
"""Train và đánh giá mô hình từ file đặc trưng (đặc tả v0.3, mục 5 và 5.2; vẫn đọc được file v0.2).

Ví dụ:
    python train.py                                   # có người / không (label), dữ liệu trong ../data/features
    python train.py --target activity                 # trống / hoạt động / yên
    python train.py --target n_people                 # đếm 0–3 người
    python train.py --target action                   # động tác + té ngã (window 3 s, ../data/features_action)
    python train.py --feature-set rx1                 # chỉ RX1 – so với 2 RX (all)
    python train.py --feature-set rssi                # chỉ RSSI (so sánh với CSI như bài báo 2)

Các bước:
1. Đọc mọi file .csv trong thư mục đặc trưng, bỏ window không hợp lệ (valid = 0).
2. Đánh giá chéo THEO BUỔI THU: mỗi lượt để riêng một buổi làm tập kiểm tra (leave-one-session-out),
   train trên các buổi còn lại. Không chia ngẫu nhiên theo window vì sẽ cho điểm cao ảo.
3. So sánh: baseline đặt ngưỡng trên phương sai, Random Forest, Gradient Boosting, XGBoost (nếu đã cài),
   và bỏ phiếu mềm của các mô hình trên (tầng 2 trong bài báo 2).
4. Train lại mô hình được chọn trên toàn bộ dữ liệu và lưu vào ../models/ để dashboard dùng.
Mục tiêu nhiều lớp (activity, n_people, action) train với trọng số cân bằng lớp, F1 tính trung bình các lớp (macro).
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
from sklearn.utils.class_weight import compute_sample_weight

try:
    from xgboost import XGBClassifier
except ImportError:
    XGBClassifier = None

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC_VERSION = "0.3"
FEATURE_RE = re.compile(r"^(rx\d_)?((rssi|csi)_(var|mad|range|iqr)(_\d{2})?|shape_(peak|ratio))$")
REQUIRED = ["session_id", "win_start", "valid"]
TARGETS = {"label": "có người", "activity": "mức hoạt động", "n_people": "số người", "action": "động tác"}


# --------------------------------------------------------------------------- dữ liệu
def load_features(folder, target):
    files = sorted(Path(folder).glob("*.csv"))
    if not files:
        sys.exit(f"Không có file .csv nào trong {folder}")
    frames, feat_sets = [], []
    for f in files:
        df = pd.read_csv(f)
        missing = [c for c in REQUIRED + [target] if c not in df.columns]
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
    if which in ("rssi", "csi"):
        return [c for c in feats if f"{which}_" in c]              # "rssi_" không chứa "csi_" nên không lẫn
    if which.startswith("rx"):
        return [c for c in feats if c.startswith(which + "_")]
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


def build_models(feat_names, n_class, seed=0):
    base = {
        "rf": RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=seed),
        # max_features="sqrt": mỗi lần chia nhánh chỉ xét √(số cột) đặc trưng -> nhanh hơn nhiều với ~200 cột
        "gb": GradientBoostingClassifier(max_features="sqrt", random_state=seed),
    }
    if XGBClassifier is not None:
        base["xgb"] = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.1, subsample=0.9,
                                    colsample_bytree=0.5, eval_metric="logloss" if n_class == 2 else "mlogloss",
                                    n_jobs=-1, random_state=seed)
    models = {"nguong": VarianceThreshold(feature_names=feat_names)} if n_class == 2 else {}   # ngưỡng: chỉ 2 lớp
    models.update(base)
    models["bophieu"] = VotingClassifier(list(base.items()), voting="soft")
    return models


NAMES = {"nguong": "Baseline ngưỡng phương sai", "rf": "Random Forest", "gb": "Gradient Boosting",
         "xgb": "XGBoost", "bophieu": "Bỏ phiếu mềm (RF+GB+XGB)"}


# --------------------------------------------------------------------------- đánh giá
def fit(model, X, y, balanced):
    """Train; balanced: trọng số mỗi lớp tỉ lệ nghịch số mẫu (lớp hiếm như FALL không bị lớp NONE lấn át)."""
    if not balanced or isinstance(model, VarianceThreshold):
        return model.fit(X, y)
    return model.fit(X, y, sample_weight=compute_sample_weight("balanced", y))


def cross_validate(models, X, y, groups, folds, n_class):
    n_groups = len(np.unique(groups))
    splitter = LeaveOneGroupOut() if folds == 0 or folds >= n_groups else GroupKFold(n_splits=folds)
    splits = list(splitter.split(X, y, groups))
    out = {}
    for key, model in models.items():
        if key == "bophieu":
            continue
        t = time.time()
        proba = np.zeros((len(y), n_class))
        for tr, te in splits:
            m = clone(model)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fit(m, X[tr], y[tr], n_class > 2)
            proba[np.ix_(te, m.classes_.astype(int))] = m.predict_proba(X[te])   # lượt train thiếu lớp vẫn đúng cột
        pred = proba.argmax(axis=1)
        out[key] = {"proba": proba, "pred": pred, "seconds": time.time() - t}
        print(f"  {NAMES[key]:28s} xong ({out[key]['seconds']:.1f} giây)")
    if "bophieu" in models:
        # bỏ phiếu mềm = trung bình xác suất của các mô hình thành phần, tính lại từ kết quả ở trên
        members = [k for k, _ in models["bophieu"].estimators]
        proba = np.mean([out[k]["proba"] for k in members], axis=0)
        out["bophieu"] = {"proba": proba, "pred": proba.argmax(axis=1), "seconds": 0.0}
        print(f"  {NAMES['bophieu']:28s} xong (tính từ {', '.join(members)})")
    for r in out.values():
        r["fold_acc"] = [accuracy_score(y[te], r["pred"][te]) for _, te in splits]
    return out, splits


def summarize(cv, y, detail, groups, splits, n_class):
    rows, per_detail, per_session = [], {}, {}
    order = sorted(set(detail), key=str)
    for key, r in cv.items():
        p = r["pred"]
        rows.append({"model": key, "accuracy": accuracy_score(y, p),
                     "f1": f1_score(y, p, average="binary" if n_class == 2 else "macro"),
                     "fold_mean": float(np.mean(r["fold_acc"])), "fold_std": float(np.std(r["fold_acc"])),
                     "confusion": confusion_matrix(y, p, labels=list(range(n_class))).tolist()})
        per_detail[key] = {str(d): float(np.mean(p[detail == d] == y[detail == d])) for d in order}
        per_session[key] = {", ".join(sorted(map(str, set(groups[te])))): float(acc)
                            for (tr, te), acc in zip(splits, r["fold_acc"])}
    return rows, per_detail, per_session


def report(rows, per_detail, per_session, info, top_features):
    L = []
    L.append(f"KẾT QUẢ TRAIN – {info['created']}")
    L.append(f"Dữ liệu: {info['features_dir']}")
    L.append(f"Mục tiêu: {info['target']} ({TARGETS[info['target']]}), các lớp {info['class_counts']}")
    L.append(f"Bộ đặc trưng: {info['feature_set']} ({info['n_features']} cột) | window hợp lệ: {info['n_windows']} "
             f"| số buổi thu: {info['n_sessions']}")
    L.append(f"Đánh giá: {info['cv']}")
    if info.get("simulated"):
        L.append("[!] DỮ LIỆU GIẢ: các con số dưới đây chỉ để kiểm tra code, không phải kết quả đề tài.")
    L.append("")
    L.append(f"{'Mô hình':28s} {'Accuracy':>9s} {'F1':>7s} {'TB theo lượt':>14s}   Ma trận nhầm lẫn (hàng: thật, cột: đoán)")
    for r in sorted(rows, key=lambda r: -r["f1"]):
        L.append(f"{NAMES[r['model']]:28s} {r['accuracy']:9.3f} {r['f1']:7.3f} "
                 f"{r['fold_mean']:8.3f} ± {r['fold_std']:.3f}   {r['confusion']}")
    L.append("")
    L.append("Tỉ lệ đoán đúng theo nhãn chi tiết:")
    details = list(next(iter(per_detail.values())))
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
    ap = argparse.ArgumentParser(description="Train và đánh giá mô hình (có người, mức hoạt động, số người, động tác).")
    ap.add_argument("--target", choices=list(TARGETS), default="label")
    ap.add_argument("--features-dir", help="mặc định ../data/features (../data/features_action nếu --target action)")
    ap.add_argument("--feature-set", choices=["all", "csi", "rssi", "rx1", "rx2"], default="all")
    ap.add_argument("--folds", type=int, default=0, help="0 = mỗi buổi thu một lượt (mặc định)")
    ap.add_argument("--final", default="best", help="mô hình lưu lại: best, nguong, rf, gb, xgb, bophieu")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    args.features_dir = args.features_dir or str(ROOT / "data" / ("features_action" if args.target == "action"
                                                                  else "features"))
    data, feats = load_features(args.features_dir, args.target)
    meta_path = Path(args.features_dir) / "feature_meta.json"
    fmeta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    n_all = len(data)
    data = data[(data["valid"] == 1) & data[args.target].notna()].reset_index(drop=True)
    if args.target == "label":
        data = data[data["label"].isin([0, 1])].reset_index(drop=True)
    data = data.dropna(subset=select_features(feats, args.feature_set)).reset_index(drop=True)
    cols = select_features(feats, args.feature_set)
    if not cols:
        sys.exit(f"Không có cột đặc trưng nào cho bộ '{args.feature_set}'.")
    sessions = data["session_id"].unique()
    if len(sessions) < 2:
        sys.exit("Cần ít nhất 2 buổi thu để đánh giá theo buổi.")
    if data[args.target].nunique() < 2:
        sys.exit("Dữ liệu chỉ có một lớp, không train được.")

    X = data[cols].to_numpy(dtype=float)
    classes, y = np.unique(data[args.target].to_numpy(), return_inverse=True)   # lớp → 0..K-1
    n_class = len(classes)
    groups = data["session_id"].to_numpy()
    detail = data["label_detail"].to_numpy() if "label_detail" in data else data[args.target].to_numpy()
    print(f"Đọc {n_all} window, dùng {len(data)} window hợp lệ từ {len(sessions)} buổi thu, {len(cols)} đặc trưng.")

    models = build_models(cols, n_class, args.seed)
    cv_name = "leave-one-session-out" if args.folds == 0 or args.folds >= len(sessions) else f"GroupKFold {args.folds} phần"
    print(f"Đánh giá chéo theo buổi thu ({cv_name}):")
    cv, splits = cross_validate(models, X, y, groups, args.folds, n_class)
    rows, per_detail, per_session = summarize(cv, y, detail, groups, splits, n_class)

    final_key = max(rows, key=lambda r: r["f1"])["model"] if args.final == "best" else args.final
    if final_key not in models:
        sys.exit(f"--final không hợp lệ: {args.final}")
    print(f"Train lại {NAMES[final_key]} trên toàn bộ dữ liệu...")
    final = clone(models[final_key])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit(final, X, y, n_class > 2)
        rf_full = fit(clone(models["rf"]), X, y, n_class > 2)
    top = sorted(zip(cols, rf_full.feature_importances_), key=lambda t: -t[1])[:10]

    created = datetime.now().strftime("%Y%m%d_%H%M%S")
    info = {"created": created, "features_dir": str(Path(args.features_dir).resolve()), "feature_set": args.feature_set,
            "target": args.target, "class_counts": {str(c): int((y == i).sum()) for i, c in enumerate(classes)},
            "n_features": len(cols), "n_windows": int(len(data)), "n_sessions": int(len(sessions)), "cv": cv_name,
            "simulated": bool(fmeta.get("simulated", False)), "final_model": final_key}
    text = report(rows, per_detail, per_session, info, top)
    print()
    print(text)

    res_dir = ROOT / "results" / f"{created}_{args.target}_{args.feature_set}"
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / "report.txt").write_text(text + "\n", encoding="utf-8")
    metrics = {"info": info, "models": [{k: v for k, v in r.items()} for r in rows], "per_detail": per_detail,
               "per_session": per_session, "top_features": top, "feature_meta": fmeta}
    (res_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    model_dir = ROOT / "models"
    model_dir.mkdir(exist_ok=True)
    bundle = {"model": final, "model_name": final_key, "feature_columns": cols, "feature_set": args.feature_set,
              "target": args.target, "classes": [c.item() if hasattr(c, "item") else c for c in classes],
              "spec_version": SPEC_VERSION, "feature_meta": fmeta, "trained_on_sessions": [str(s) for s in sessions],
              "cv_metrics": next(r for r in rows if r["model"] == final_key), "created": created,
              "simulated": info["simulated"]}
    path = model_dir / f"model_{created}_{args.target}_{args.feature_set}_{final_key}.joblib"
    joblib.dump(bundle, path)
    joblib.dump(bundle, model_dir / f"model_latest_{args.target}.joblib")      # dashboard đọc theo mục tiêu
    if args.target == "label":
        joblib.dump(bundle, model_dir / "model_latest.joblib")
    print(f"\nĐã lưu báo cáo: {res_dir}\nĐã lưu mô hình: {path} (và model_latest.joblib)")


if __name__ == "__main__":
    main()
