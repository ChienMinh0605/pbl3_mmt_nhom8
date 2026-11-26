#!/usr/bin/env python3
"""Train và đánh giá mô hình từ file đặc trưng (đặc tả v0.3, mục 5 và 5.2; vẫn đọc được file v0.2).

Ví dụ:
    python train.py                                   # có người / không (label), dữ liệu trong ../data/features
    python train.py --target activity                 # trống / hoạt động / yên
    python train.py --target n_people                 # đếm 0–3 người
    python train.py --target action                   # động tác + té ngã (window 3 s, ../data/features_action)
    python train.py --feature-set rx1                 # chỉ RX1 – so với 2 RX (all)
    python train.py --feature-set rssi                # chỉ RSSI (so sánh với CSI như bài báo 2)
    python train.py --feature-set gon                 # bỏ cột từng sóng mang con (chỉ RSSI + shape_*)
    python train.py --target action --feature-set rx1+mot   # bộ gọn cho board: 25 cột mot_*/mon_* của RX1
    python train.py --target action --feature-set mot --board-chung --sau 5   # MỘT mô hình dùng chung mọi board

Các bước:
1. Đọc mọi file .csv trong thư mục đặc trưng, bỏ window không hợp lệ (valid = 0).
2. Đánh giá chéo THEO BUỔI THU: mỗi lượt để riêng một buổi làm tập kiểm tra (leave-one-session-out),
   train trên các buổi còn lại. Không chia ngẫu nhiên theo window vì sẽ cho điểm cao ảo.
3. So sánh: baseline đặt ngưỡng trên phương sai, Random Forest, Gradient Boosting, XGBoost (nếu đã cài),
   và bỏ phiếu mềm của các mô hình trên (tầng 2 trong bài báo 2).
4. Train lại mô hình được chọn trên toàn bộ dữ liệu và lưu vào ../models/ để dashboard dùng.
Mục tiêu nhiều lớp (activity, n_people, action) train với trọng số cân bằng lớp, F1 tính trung bình các lớp (macro).
5. n_people: bảng "phân vân thì chọn 1" theo τ, lưu τ mặc định vào mô hình (khoá "uu_tien_1_nguong", áp dụng bằng
   predict_uu_tien_1). action: bảng ngưỡng P(FALL) ưu tiên recall, lưu τ vào khoá "fall_nguong".
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
FEATURE_RE = re.compile(r"^(rx\d_)?((rssi|csi)_(var|mad|range|iqr)(_\d{2})?|(shape|mot|mon)_[a-z]+\d?|g6_[a-z]+_[a-z0-9]+)$")
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
    """which: một bộ hoặc nhiều bộ nối bằng "+" (lấy phần chung), ví dụ "rx1+mot"."""
    if "+" in which:
        for w in which.split("+"):
            feats = select_features(feats, w)
        return feats
    if which == "mot":                                              # bộ gọn bền với gói hỏng (features.robust_features)
        return [c for c in feats if re.search(r"(^|_)mo[tn]_", c)]
    if which == "g6":                                               # bộ gọn window 6 s (features.compact6_features)
        return [c for c in feats if re.search(r"(^|_)g6_", c)]
    if which == "bai_bao":                                          # 4 đặc trưng × RSSI + từng sóng mang con (212 cột)
        return [c for c in feats if re.search(r"(^|_)(rssi|csi)_", c)]
    if which in ("rssi", "csi"):
        return [c for c in feats if f"{which}_" in c]              # "rssi_" không chứa "csi_" nên không lẫn
    if which == "gon":                                              # bỏ 4 cột của từng sóng mang con, giữ RSSI + shape_*
        return [c for c in feats if not re.search(r"csi_[a-z]+_\d{2}$", c)]
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


def build_models(feat_names, n_class, seed=0, xgb=None):
    """xgb: dict ghi đè tham số XGBoost, vd. {"max_depth": 5} (cỡ mô hình cho board)."""
    base = {
        "rf": RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=seed),
        # max_features="sqrt": mỗi lần chia nhánh chỉ xét √(số cột) đặc trưng -> nhanh hơn nhiều với ~200 cột
        "gb": GradientBoostingClassifier(max_features="sqrt", random_state=seed),
    }
    if XGBClassifier is not None:
        base["xgb"] = XGBClassifier(**{"n_estimators": 300, "max_depth": 4, "learning_rate": 0.1, "subsample": 0.9,
                                       "colsample_bytree": 0.5,
                                       "eval_metric": "logloss" if n_class == 2 else "mlogloss", "n_jobs": -1,
                                       "random_state": seed, **(xgb or {})})
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


TAUS = (0.5, 0.6, 0.7, 0.8, 0.9)
FALL_TAUS = (0.5, 0.4, 0.3, 0.2, 0.15, 0.1)


def predict_uu_tien_1(proba, classes, tau):
    """Đếm người "phân vân thì chọn 1": chỉ đoán ≥ 2 người khi P(≥ 2) ≥ tau, còn lại lấy lớp tốt nhất trong {0, 1}.
    Vì đoán nhầm 1 người thành 2–3 làm hệ thống tắt phát hiện ngã (lỗi nguy hiểm); bỏ sót khách chỉ hiện sai số người."""
    proba, classes = np.asarray(proba, float), np.asarray(classes)
    many = classes >= 2
    lo, hi = np.where(many, -1, proba).argmax(axis=1), np.where(many, proba, -1).argmax(axis=1)
    return classes[np.where(proba[:, many].sum(axis=1) >= tau, hi, lo)]


def bang_uu_tien_1(proba, truth, classes):
    """Bảng theo tau (dòng đầu: argmax thường). Chọn tau nhỏ nhất đưa lỗi nguy hiểm ≤ 2 %, không có thì tau lớn nhất."""
    rows = []
    for tau in (None,) + TAUS:
        pred = classes[proba.argmax(axis=1)] if tau is None else predict_uu_tien_1(proba, classes, tau)
        rows.append({"tau": tau, "nguy_hiem": float(np.mean(pred[truth == 1] >= 2)),
                     "bat_dung_2": float(np.mean(pred[truth >= 2] >= 2)), "accuracy": float(np.mean(pred == truth))})
    ok = [r["tau"] for r in rows[1:] if r["nguy_hiem"] <= 0.02]
    return rows, (ok[0] if ok else TAUS[-1])


def bang_nguong_fall(proba, truth, classes, sessions, starts):
    """Bảng ngưỡng P(FALL) (dòng đầu: argmax): đoán FALL khi P(FALL) ≥ tau, còn lại lấy lớp tốt nhất khác FALL.
    Recall theo lần ngã = có ít nhất một window của lần ngã đó bị đoán FALL (cảnh báo còn bước xác nhận 10 s phía sau,
    nên chấp nhận thêm báo nhầm ở mức window). Chọn tau có F2 (recall nặng gấp 4 precision) cao nhất."""
    f = int(np.flatnonzero(classes == "FALL")[0])
    idx = np.flatnonzero(truth == "FALL")
    event = np.cumsum(np.r_[True, (sessions[idx][1:] != sessions[idx][:-1]) | (np.diff(starts[idx]) > 0.75)])
    rows = []
    for tau in (None,) + FALL_TAUS:
        pred = proba.argmax(axis=1) if tau is None else np.where(
            proba[:, f] >= tau, f, np.where(np.arange(len(classes)) == f, -1, proba).argmax(axis=1))
        hit = pred == f
        rec, pre = float(hit[idx].mean()), float((truth[hit] == "FALL").mean()) if hit.any() else 0.0
        rows.append({"tau": tau, "recall": rec, "precision": pre, "f2": 5 * rec * pre / max(4 * pre + rec, 1e-9),
                     "recall_lan_nga": float(np.mean([hit[idx][event == e].any() for e in np.unique(event)])),
                     "none_thanh_fall": int((hit & (truth == "NONE")).sum()),
                     "dong_tac_khac_thanh_fall": int((hit & (truth != "NONE") & (truth != "FALL")).sum())})
    return rows, max(rows[1:], key=lambda r: r["f2"])["tau"]


def _check_rules():
    f = ["rx1_csi_var_03", "rx1_mot_slope", "rx2_mon_b1", "rx1_shape_pos", "rx1_rssi_var", "rx1_g6_iqr_rssi"]
    assert select_features(f, "rx1+mot") == ["rx1_mot_slope"] and select_features(f, "mot") == f[1:3]
    assert select_features(f, "g6") == f[5:] and select_features(f, "bai_bao") == [f[0], f[4]]
    assert select_features(f, "rssi") == [f[4]]
    assert all(FEATURE_RE.match(c) for c in f)
    p = np.array([[0.1, 0.5, 0.25, 0.15], [0.0, 0.2, 0.7, 0.1]])
    assert list(predict_uu_tien_1(p, np.arange(4), 0.5)) == [1, 2]
    assert list(predict_uu_tien_1(p, np.arange(4), 0.9)) == [1, 1]
    c = np.array(["FALL", "NONE"])
    rows, _ = bang_nguong_fall(np.array([[0.3, 0.7], [0.6, 0.4], [0.1, 0.9]]), np.array(["FALL", "FALL", "NONE"]), c,
                               np.array(["a", "a", "a"]), np.array([0.0, 0.5, 9.0]))
    assert rows[0]["recall"] == 0.5 and rows[0]["recall_lan_nga"] == 1.0 and rows[3]["recall"] == 1.0


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
    ap.add_argument("--feature-set", default="all",
                    help="all, gon, mot, g6, bai_bao, csi, rssi, rx1, rx2 hoặc nối bằng +, vd. rx1+mot")
    ap.add_argument("--folds", type=int, default=0, help="0 = mỗi buổi thu một lượt (mặc định)")
    ap.add_argument("--final", default="best", help="mô hình lưu lại: best, nguong, rf, gb, xgb, bophieu")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cay", type=int, default=300, help="XGBoost: số vòng (mỗi vòng một cây cho mỗi lớp)")
    ap.add_argument("--sau", type=int, default=4, help="XGBoost: độ sâu tối đa của cây")
    ap.add_argument("--board-chung", action="store_true",
                    help="một mô hình cho mọi board: xếp chồng hàng của từng RX (bỏ tiền tố rxN_) → gấp đôi dữ liệu")
    args = ap.parse_args()
    _check_rules()

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
    if args.board_chung:                       # hai board đặt đối xứng, cùng loại đặc trưng → học chung một mô hình
        boards, base = sorted({c.split("_")[0] for c in cols}), sorted({c.split("_", 1)[1] for c in cols})
        if not all(re.match(r"rx\d_", c) for c in cols) or len(cols) != len(boards) * len(base):
            sys.exit("--board-chung cần cột có tiền tố rxN_ và đủ cột như nhau ở mọi board.")
        data = pd.concat([data.assign(**{c: data[f"{b}_{c}"] for c in base}) for b in boards], ignore_index=True)
        cols = base
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

    models = build_models(cols, n_class, args.seed, {"n_estimators": args.cay, "max_depth": args.sau})
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
            "simulated": bool(fmeta.get("simulated", False)), "final_model": final_key,
            "board_chung": args.board_chung, "xgb": {"n_estimators": args.cay, "max_depth": args.sau}}
    text = report(rows, per_detail, per_session, info, top)
    extra, proba = {}, cv[final_key]["proba"]                  # bảng ngưỡng tính trên xác suất đánh giá chéo
    if args.target == "n_people":
        tab, tau = bang_uu_tien_1(proba, classes[y], classes)
        extra = {"uu_tien_1_nguong": tau, "uu_tien_1_bang": tab}
        text += (f"\n\nĐếm người \"phân vân thì chọn 1\" ({NAMES[final_key]}): chỉ đoán ≥ 2 người khi P(≥2) ≥ τ, "
                 f"còn lại lấy lớp tốt nhất trong {{0, 1}}\n{'τ':>7s} {'lỗi nguy hiểm (thật 1 → ≥2)':>28s} "
                 f"{'bắt đúng ≥2':>12s} {'accuracy':>9s}\n")
        text += "\n".join(f"{'argmax' if r['tau'] is None else r['tau']:>7} {r['nguy_hiem']:28.3f} "
                          f"{r['bat_dung_2']:12.3f} {r['accuracy']:9.3f}" for r in tab)
        text += f"\nτ mặc định lưu vào mô hình (uu_tien_1_nguong): {tau}"
    elif args.target == "action" and "FALL" in classes:
        tab, tau = bang_nguong_fall(proba, classes[y], classes, groups, data["win_start"].to_numpy())
        extra = {"fall_nguong": tau, "fall_nguong_bang": tab}
        text += (f"\n\nNgưỡng P(FALL) ({NAMES[final_key]}): đoán FALL khi P(FALL) ≥ τ\n{'τ':>7s} {'recall':>7s} "
                 f"{'precision':>9s} {'F2':>6s} {'recall lần ngã':>15s} {'NONE→FALL':>10s} {'động tác khác→FALL':>19s}\n")
        text += "\n".join(f"{'argmax' if r['tau'] is None else r['tau']:>7} {r['recall']:7.3f} {r['precision']:9.3f} "
                          f"{r['f2']:6.3f} {r['recall_lan_nga']:15.3f} {r['none_thanh_fall']:10d} "
                          f"{r['dong_tac_khac_thanh_fall']:19d}" for r in tab)
        text += f"\nτ lưu vào mô hình (fall_nguong, F2 cao nhất): {tau}"
    print()
    print(text)

    res_dir = ROOT / "results" / f"{created}_{args.target}_{args.feature_set}"
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / "report.txt").write_text(text + "\n", encoding="utf-8")
    metrics = {"info": info, "models": [{k: v for k, v in r.items()} for r in rows], "per_detail": per_detail,
               "per_session": per_session, "top_features": top, "feature_meta": fmeta, **extra}
    (res_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    model_dir = ROOT / "models"
    model_dir.mkdir(exist_ok=True)
    bundle = {"model": final, "model_name": final_key, "feature_columns": cols, "feature_set": args.feature_set,
              "target": args.target, "classes": [c.item() if hasattr(c, "item") else c for c in classes],
              "spec_version": SPEC_VERSION, "feature_meta": fmeta, "trained_on_sessions": [str(s) for s in sessions],
              "cv_metrics": next(r for r in rows if r["model"] == final_key), "created": created,
              "simulated": info["simulated"], **extra}
    path = model_dir / f"model_{created}_{args.target}_{args.feature_set}_{final_key}.joblib"
    joblib.dump(bundle, path)
    joblib.dump(bundle, model_dir / f"model_latest_{args.target}.joblib")      # dashboard đọc theo mục tiêu
    if args.target == "label":
        joblib.dump(bundle, model_dir / "model_latest.joblib")
    print(f"\nĐã lưu báo cáo: {res_dir}\nĐã lưu mô hình: {path} (và model_latest.joblib)")


if __name__ == "__main__":
    main()
