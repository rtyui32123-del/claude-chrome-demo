# -*- coding: utf-8 -*-
"""
청개구리 환희 지표 (시장 심리 점수의 반대 버전, 재미용) : 한국 + 미국

실행 방법
  1) 설치 (처음 한 번만):  pip install yfinance pandas
  2) 실행:                python fear_greed.py
  3) 인터넷 없이 화면만 확인:  python fear_greed.py --demo

점수 계산 방식
  - 지표 점수: 오늘 값이 최근 2년 중 어느 위치인지 0~100점으로 환산 (낮을수록 공포)
  - 가중치: 과거 약 15년 동안 그 지표가 다른 지표들과 같은 방향을 가리킨 정도(상관계수).
            시장 분위기를 꾸준히 잘 대표한 지표일수록 가중치가 큼.
  - 종합 점수: 지표 점수의 가중평균
"""
import sys
import math
import html as html_lib
import webbrowser
from datetime import datetime
from pathlib import Path

import pandas as pd

HISTORY_PERIOD = "15y"  # 가중치 계산에 쓰는 과거 기간
LOOKBACK = 504          # 점수 비교 기간: 약 2년 (거래일 기준)
MIN_HISTORY = 150       # 점수 계산에 필요한 최소 데이터 수
MIN_CORR_ROWS = 250     # 가중치 계산에 필요한 최소 데이터 수
MIN_INDICATORS = 3      # 종합 점수를 내기 위한 최소 지표 수

BANDS = [               # (상한 점수, 이름, 색)
    (25, "매우 시무룩", "#6b7280"),
    (45, "시무룩", "#9ca3af"),
    (55, "그저 그럼", "#c9a227"),
    (75, "신남", "#f08a24"),
    (101, "환희", "#e0338a"),
]

# 구간별 표정 (화면에만 표시)
EMOJI = {"매우 시무룩": "\U0001F62D", "시무룩": "\U0001F61F", "그저 그럼": "\U0001F610",
         "신남": "\U0001F604", "환희": "\U0001F973"}

# 지표 설명 (마우스를 올리거나 클릭하면 표시)
DESCRIPTIONS = {
    "시장 모멘텀":
        "주가지수가 최근 약 6개월(125거래일) 평균보다 얼마나 위나 아래에 있는지 봅니다. "
        "평균보다 한참 아래면 사람들이 겁을 먹고 팔고 있다는 뜻(공포), 한참 위면 너도나도 사고 있다는 뜻(탐욕)입니다. "
        "내 시험 점수가 반 평균보다 높은지 낮은지 보는 것과 비슷합니다.",
    "변동성":
        "주가가 하루하루 얼마나 크게 출렁이는지 봅니다. 사람들이 불안하면 작은 뉴스에도 주가가 크게 오르내립니다. "
        "그래서 출렁임이 클수록 공포, 잔잔할수록 안정(탐욕)으로 봅니다. 최근 20거래일의 실제 움직임으로 계산합니다.",
    "변동성 (VIX)":
        "'공포 지수'라는 별명을 가진 지표입니다. 투자자들이 앞으로 한 달 동안 주가가 얼마나 출렁일 거라고 "
        "예상하는지를 숫자로 나타냅니다. 보통 20 아래면 평온, 30을 넘으면 불안이 큰 상태로 봅니다. 높을수록 공포입니다.",
    "원/달러 환율":
        "1달러를 사는 데 필요한 원화 금액입니다. 세계 시장이 불안해지면 외국인 투자자들이 한국 주식을 팔고 "
        "달러로 바꿔 나가서 환율이 오릅니다. 그래서 최근 한 달 사이 환율이 빠르게 오르면 공포, 내리면 안정으로 봅니다.",
    "안전자산 선호 (주식 대 국고채)":
        "최근 한 달 동안 주식과 국고채(나라가 발행한 채권) 중 어느 쪽 수익률이 좋았는지 비교합니다. "
        "겁이 나면 사람들은 위험한 주식을 팔고 안전한 국고채로 옮겨 갑니다. "
        "채권이 주식보다 잘 나갔다면 공포, 주식이 잘 나갔다면 탐욕입니다.",
    "안전자산 선호 (주식 대 국채)":
        "최근 한 달 동안 주식과 미국 국채(나라가 발행한 채권) 중 어느 쪽 수익률이 좋았는지 비교합니다. "
        "겁이 나면 사람들은 위험한 주식을 팔고 안전한 국채로 옮겨 갑니다. "
        "채권이 주식보다 잘 나갔다면 공포, 주식이 잘 나갔다면 탐욕입니다.",
    "위험 선호 (코스닥 대 코스피)":
        "코스닥(작고 변동이 큰 회사가 많음)과 코스피(크고 안정적인 회사가 많음) 중 최근 한 달간 어느 쪽이 더 올랐는지 봅니다. "
        "자신감이 넘치면 위험한 코스닥이 더 오르고, 겁이 나면 코스닥이 더 많이 빠지는 경향이 있습니다.",
    "정크본드 수요":
        "정크본드는 신용이 낮은 회사가 높은 이자를 주고 빌리는 돈(채권)입니다. 떼일 위험이 커서, 사람들이 겁을 먹으면 "
        "가장 먼저 팝니다. 최근 한 달간 정크본드가 안전한 국채보다 잘 나갔다면 위험을 감수하려는 분위기(탐욕), 반대면 공포입니다.",
    "시장 폭 (동일가중 대 시총가중)":
        "주가지수는 몇몇 초대형 회사가 좌우합니다. 그래서 '500개 회사를 똑같은 비중으로 담은 지수'와 "
        "'큰 회사 비중이 큰 일반 지수'를 비교합니다. 대부분의 회사가 골고루 오르면 건강한 상승(탐욕), "
        "소수만 버티고 나머지가 빠지면 불안 신호(공포)로 봅니다.",
    "52주 고점/저점 위치":
        "지난 1년 동안의 최고가와 최저가 사이에서 지금 주가가 어디쯤 있는지 봅니다. 최저가 근처면 0%, 최고가 근처면 100%입니다. "
        "바닥 근처에 있을수록 공포, 꼭대기 근처일수록 탐욕입니다.",
}

TOTAL_DESCRIPTION = (
    "재미로 만든 반대 버전입니다. 원래 '시장 심리 점수'를 거꾸로 뒤집어서(100 - 원래 점수), "
    "시장이 겁에 질릴수록 점수가 높아지고 표정이 밝아집니다. '남들이 겁낼 때 웃는 청개구리'의 시선입니다. "
    "각 지표 점수는 '오늘 값이 최근 2년 중 몇 등인지'를 100점 만점으로 바꾼 뒤 뒤집은 것이고, "
    "가중치는 원래 버전과 똑같이 과거 기록으로 정합니다."
)


def label_of(score):
    for upper, name, color in BANDS:
        if score < upper:
            return name, color
    return BANDS[-1][1], BANDS[-1][2]


# ---------------------------------------------------------------- 데이터 받기
class Market:
    """시세를 받아서 보관해 두는 창고 (같은 종목을 두 번 받지 않음)"""

    def __init__(self, demo=False):
        self.demo = demo
        self.cache = {}

    def get(self, ticker):
        if ticker not in self.cache:
            self.cache[ticker] = self._demo(ticker) if self.demo else self._download(ticker)
        return self.cache[ticker]

    @staticmethod
    def _download(ticker):
        import yfinance as yf
        s = yf.Ticker(ticker).history(period=HISTORY_PERIOD, auto_adjust=True)["Close"].dropna()
        if s.empty:
            raise ValueError(f"{ticker} 데이터 없음")
        # 시장마다 시간대가 달라서 날짜만 남김
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        return s[~s.index.duplicated(keep="last")]

    @staticmethod
    def _demo(ticker):
        import random
        rnd = random.Random(ticker)
        days = pd.bdate_range(end=datetime.today().date(), periods=1500)
        level = 20.0 if ticker == "^VIX" else 100.0
        vals = []
        for _ in days:
            if ticker == "^VIX":
                level = max(10.0, level + (18 - level) * 0.05 + rnd.gauss(0, 1.2))
            else:
                level *= 1 + rnd.gauss(0.0003, 0.011)
            vals.append(level)
        return pd.Series(vals, index=days)


# ---------------------------------------------------------------- 지표 계산
# 모든 지표는 "값이 클수록 탐욕"이 되도록 방향을 맞춘 시계열과, 오늘 값 설명 문구를 돌려준다.
def ret20(s):
    return s.pct_change(20)


def momentum(mk, idx):
    s = mk.get(idx)
    ind = s / s.rolling(125).mean() - 1
    return ind, f"125일 평균 대비 {ind.iloc[-1] * 100:+.1f}%"


def vix_level(mk, t):
    s = mk.get(t)
    return -s, f"VIX {s.iloc[-1]:.1f}"


def realized_vol(mk, idx):
    s = mk.get(idx)
    vol = s.pct_change().rolling(20).std() * math.sqrt(252) * 100
    return -vol, f"20일 변동성 연 {vol.iloc[-1]:.1f}%"


def relative_strength(mk, a, b, text):
    """a의 20일 수익률 - b의 20일 수익률 (a가 강할수록 탐욕)"""
    ind = (ret20(mk.get(a)) - ret20(mk.get(b))).dropna()
    return ind, f"{text} {ind.iloc[-1] * 100:+.1f}%p"


def fx_weakness(mk, t):
    s = mk.get(t)
    chg = ret20(s)
    return -chg, f"원/달러 {s.iloc[-1]:,.0f}원 (20일 {chg.iloc[-1] * 100:+.1f}%)"


def range_position(mk, idx):
    s = mk.get(idx)
    lo, hi = s.rolling(252).min(), s.rolling(252).max()
    ind = (s - lo) / (hi - lo) * 100
    return ind, f"52주 범위의 {ind.iloc[-1]:.0f}% 지점"


MARKETS = {
    "한국 (코스피)": [
        ("시장 모멘텀", lambda m: momentum(m, "^KS11")),
        ("변동성", lambda m: realized_vol(m, "^KS11")),
        ("원/달러 환율", lambda m: fx_weakness(m, "KRW=X")),
        ("안전자산 선호 (주식 대 국고채)", lambda m: relative_strength(m, "^KS11", "148070.KS", "주식-채권 20일")),
        ("위험 선호 (코스닥 대 코스피)", lambda m: relative_strength(m, "^KQ11", "^KS11", "코스닥-코스피 20일")),
        ("52주 고점/저점 위치", lambda m: range_position(m, "^KS11")),
    ],
    "미국 (S&P 500)": [
        ("시장 모멘텀", lambda m: momentum(m, "^GSPC")),
        ("변동성 (VIX)", lambda m: vix_level(m, "^VIX")),
        ("안전자산 선호 (주식 대 국채)", lambda m: relative_strength(m, "SPY", "TLT", "주식-국채 20일")),
        ("정크본드 수요", lambda m: relative_strength(m, "HYG", "IEF", "하이일드-국채 20일")),
        ("시장 폭 (동일가중 대 시총가중)", lambda m: relative_strength(m, "RSP", "SPY", "동일가중-시총가중 20일")),
        ("52주 고점/저점 위치", lambda m: range_position(m, "^GSPC")),
    ],
}


def score_history(ind):
    """매일의 점수: 그날 값이 직전 2년 중 몇 번째 백분위였는지 (0~100)"""
    s = ind.dropna()
    hist = (s.rolling(LOOKBACK, min_periods=MIN_HISTORY).rank(pct=True) * 100).dropna()
    if hist.empty:
        raise ValueError("과거 데이터 부족")
    return hist


def historical_weights(hists):
    """
    과거 기록으로 가중치 산출.
    지표별로 '자기 점수'와 '나머지 지표들의 평균 점수'의 상관계수를 구하고,
    그 값(음수는 0)에 비례해 가중치를 준다.
    """
    df = pd.DataFrame(hists)
    corr = {}
    for c in df.columns:
        pair = pd.concat([df[c], df.drop(columns=c).mean(axis=1)], axis=1).dropna()
        corr[c] = float(pair.corr().iloc[0, 1]) if len(pair) >= MIN_CORR_ROWS and df.shape[1] > 1 else None
    valid = [max(v, 0.0) for v in corr.values() if v is not None]
    fallback = sum(valid) / len(valid) if valid else 1.0   # 기록이 짧은 지표는 평균 가중치
    raw = {c: (max(v, 0.0) if v is not None else fallback) for c, v in corr.items()}
    total = sum(raw.values())
    if total <= 0:                                          # 전부 0이면 동일 가중
        return {c: 1 / len(raw) for c in raw}, corr
    return {c: v / total for c, v in raw.items()}, corr


def evaluate(mk):
    results = {}
    for market, indicators in MARKETS.items():
        rows, hists = [], {}
        for name, fn in indicators:
            try:
                ind, detail = fn(mk)
                hist = score_history(ind)
                hists[name] = hist
                rows.append({"name": name, "score": 100 - float(hist.iloc[-1]), "detail": detail, "error": None})
            except Exception as e:  # 지표 하나가 실패해도 나머지는 계속
                rows.append({"name": name, "score": None, "detail": "", "error": str(e)[:60]})
        weights, corr = historical_weights(hists) if hists else ({}, {})
        for r in rows:
            r["weight"] = weights.get(r["name"])
            r["corr"] = corr.get(r["name"])
        ok = [r for r in rows if r["score"] is not None]
        enough = len(ok) >= MIN_INDICATORS
        starts = [h.index[0] for h in hists.values()]
        ends = [h.index[-1] for h in hists.values()]
        results[market] = {
            "rows": rows,
            "total": sum(r["score"] * r["weight"] for r in ok) if enough else None,
            "simple": sum(r["score"] for r in ok) / len(ok) if enough else None,
            "used": len(ok),
            "date": max(ends).strftime("%Y-%m-%d") if ends else "-",
            "years": (max(ends) - min(starts)).days / 365.25 if ends else 0,
        }
    return results


# ---------------------------------------------------------------- 출력
def print_report(results, demo):
    print()
    if demo:
        print("[데모 모드] 아래 숫자는 가짜 데이터입니다. 실제 시장과 무관합니다.")
    for market, r in results.items():
        print("=" * 76)
        if r["total"] is None:
            print(f"{market} : 계산 불가 (받아온 지표 {r['used']}개)")
        else:
            name, _ = label_of(r["total"])
            print(f"{market} : {r['total']:.0f}점  [{name}]   (단순 평균 {r['simple']:.0f}점, "
                  f"기준일 {r['date']}, 가중치 산출 기간 약 {r['years']:.0f}년)")
        print("-" * 76)
        for row in r["rows"]:
            if row["score"] is None:
                print(f"  {row['name']:<28} 실패: {row['error']}")
            else:
                name, _ = label_of(row["score"])
                c = "  -  " if row["corr"] is None else f"{row['corr']:+.2f}"
                print(f"  {row['name']:<28} {row['score']:>3.0f}점 {name:<6} "
                      f"가중치 {row['weight'] * 100:>4.1f}% (상관 {c})  {row['detail']}")
    print("=" * 76)
    print("반대 버전: 0~25 매우 시무룩 / 25~45 시무룩 / 45~55 그저 그럼 / 55~75 신남 / 75~100 환희")
    print("시장 분위기를 보는 참고 지표이며, 주가 예측이나 투자 권유가 아닙니다.")


CSS = """
body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;background:#f4f5f7;color:#222;margin:0;padding:24px}
h1{font-size:22px;margin:0 0 4px} .sub{color:#666;margin:0 0 20px;font-size:13px}
.wrap{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:20px;max-width:1100px}
section{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
h2{font-size:16px;margin:0 0 12px}
.has-tip{position:relative;cursor:pointer;outline:none}
.tip{display:none;position:absolute;left:0;right:0;top:100%;z-index:10;background:#1f2430;color:#fff;
  padding:12px 14px;border-radius:8px;font-size:13px;line-height:1.65;font-weight:400;box-shadow:0 6px 18px rgba(0,0,0,.25)}
.tip b{color:#ffd479}
.has-tip:hover .tip,.has-tip:focus .tip,.has-tip.open .tip{display:block}
.info{display:inline-block;width:15px;height:15px;line-height:15px;text-align:center;border-radius:50%;
  background:#d5d8de;color:#555;font-size:10px;font-weight:700;margin-left:4px;vertical-align:1px}
.head{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.score{font-size:56px;font-weight:700;line-height:1}
.label{color:#fff;padding:6px 14px;border-radius:20px;font-weight:700}
.simple{color:#888;font-size:12px}
.face{margin-left:auto;font-size:64px;line-height:1}
.gauge{position:relative;height:12px;border-radius:6px;margin:18px 0 4px;
  background:linear-gradient(90deg,#6b7280 0 25%,#9ca3af 25% 45%,#c9a227 45% 55%,#f08a24 55% 75%,#e0338a 75% 100%)}
.pin{position:absolute;top:-5px;width:4px;height:22px;background:#111;border-radius:2px;transform:translateX(-2px)}
.scale{display:flex;justify-content:space-between;font-size:11px;color:#777;margin-bottom:14px}
.row{display:grid;grid-template-columns:1fr 34px 86px 50px;gap:8px;align-items:start;
  padding:10px 4px;border-top:1px solid #eee;font-size:13px}
.row:hover,.row.open{background:#f7f8fa}
.colhead{color:#999;font-size:11px;padding:4px;display:grid;grid-template-columns:1fr 34px 86px 50px;gap:8px}
.num{font-weight:700;text-align:right}
.w{text-align:right;color:#555}
.bar{background:#eee;border-radius:4px;height:8px;margin:6px 0 4px}
.bar div{height:8px;border-radius:4px}
small{color:#777} .fail{color:#aaa;grid-column:2 / 5} .meta{color:#888;font-size:12px;margin:12px 0 0}
.demo{background:#fff3cd;padding:10px 14px;border-radius:8px;max-width:1070px}
.note{color:#777;font-size:12px;max-width:1100px;margin-top:18px;line-height:1.6}
"""

JS = """
document.querySelectorAll('.has-tip').forEach(function(el){
  el.addEventListener('click',function(e){
    var wasOpen=el.classList.contains('open');
    document.querySelectorAll('.has-tip.open').forEach(function(o){o.classList.remove('open')});
    if(!wasOpen){el.classList.add('open')}else{el.blur()}
    e.stopPropagation();
  });
});
document.addEventListener('click',function(){
  document.querySelectorAll('.has-tip.open').forEach(function(o){o.classList.remove('open')});
});
"""


def weight_sentence(row, years):
    w = row["weight"] * 100
    if row["corr"] is None:
        return f"<b>가중치 {w:.0f}%</b>: 과거 기록이 짧아 다른 지표들의 평균 수준 가중치를 주었습니다."
    if row["corr"] <= 0:
        return (f"<b>가중치 0%</b>: 과거 약 {years:.0f}년 동안 다른 지표들과 같은 방향으로 움직이지 않아"
                f"(상관계수 {row['corr']:+.2f}) 종합 점수에는 반영하지 않습니다.")
    return (f"<b>가중치 {w:.0f}%</b>: 과거 약 {years:.0f}년 동안 다른 지표들과 같은 방향을 가리킨 정도"
            f"(상관계수 {row['corr']:+.2f}, 1에 가까울수록 시장 분위기를 잘 대표)로 정했습니다.")


def write_html(results, demo, path):
    esc = html_lib.escape
    cards = []
    for market, r in results.items():
        if r["total"] is None:
            head = '<div class="score">-</div><div class="label" style="background:#8a8a8a">계산 불가</div>'
        else:
            name, color = label_of(r["total"])
            head = (f'<div class="score" style="color:{color}">{r["total"]:.0f}</div>'
                    f'<div class="label" style="background:{color}">{name}</div>'
                    f'<div class="simple">가중평균 점수<span class="info">i</span><br>'
                    f'(단순 평균으로는 {r["simple"]:.0f}점)</div>'
                    f'<div class="face" title="{name}">{EMOJI[name]}</div>')
        rows = []
        for row in r["rows"]:
            desc = esc(DESCRIPTIONS.get(row["name"], ""))
            if row["score"] is None:
                rows.append(f'<div class="row has-tip" tabindex="0"><div>{esc(row["name"])}<span class="info">i</span></div>'
                            f'<div class="fail">데이터를 받지 못함</div><div class="tip">{desc}</div></div>')
                continue
            n, c = label_of(row["score"])
            tip = (f'{desc}<br><br><b>지금 {row["score"]:.0f}점 ({n})</b>: {esc(row["detail"])}. '
                   f'이 반대 버전에서는 시장이 겁먹을수록 점수가 높아집니다.<br>{weight_sentence(row, r["years"])}')
            rows.append(
                f'<div class="row has-tip" tabindex="0">'
                f'<div>{esc(row["name"])}<span class="info">i</span>'
                f'<div class="bar"><div style="width:{row["score"]:.0f}%;background:{c}"></div></div>'
                f'<small>{esc(row["detail"])}</small></div>'
                f'<div class="num">{row["score"]:.0f}</div>'
                f'<div style="color:{c}">{EMOJI[n]} {n}</div>'
                f'<div class="w">{row["weight"] * 100:.0f}%</div>'
                f'<div class="tip">{tip}</div></div>')
        pos = 0 if r["total"] is None else r["total"]
        cards.append(f"""
<section>
  <h2>{esc(market)}</h2>
  <div class="head has-tip" tabindex="0">{head}<div class="tip">{esc(TOTAL_DESCRIPTION)}</div></div>
  <div class="gauge"><div class="pin" style="left:{pos:.0f}%"></div></div>
  <div class="scale"><span>매우 시무룩</span><span>시무룩</span><span>그저 그럼</span><span>신남</span><span>환희</span></div>
  <div class="colhead"><div>지표 (올리거나 누르면 설명)</div><div class="num">점수</div><div>상태</div><div class="w">가중치</div></div>
  {''.join(rows)}
  <p class="meta">기준일 {r['date']} / 사용 지표 {r['used']}개 / 가중치 산출 기간 약 {r['years']:.0f}년</p>
</section>""")
    demo_note = '<p class="demo">데모 모드: 가짜 데이터입니다. 실제 시장과 무관합니다.</p>' if demo else ""
    page = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>청개구리 환희 지표</title>
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" type="image/png" href="favicon.png">
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#141a30">
<meta name="apple-mobile-web-app-title" content="환희지표">
<meta name="mobile-web-app-capable" content="yes">
<style>{CSS}</style></head><body>
<h1>청개구리 환희 지표 \U0001F438</h1>
<p class="sub">생성 시각 {datetime.now().strftime('%Y-%m-%d %H:%M')} / 재미로 만든 반대 버전: 시장이 겁낼수록 점수가 높아집니다 / 점수나 지표에 마우스를 올리거나 누르면 설명이 나옵니다</p>
{demo_note}
<div class="wrap">{''.join(cards)}</div>
<p class="note">지표 점수: 오늘 값이 최근 2년 중 어느 위치인지를 나타내는 백분위를 거꾸로 뒤집은 값(100 - 원래 점수).<br>
가중치: 과거 기록에서 각 지표가 나머지 지표들의 평균과 같은 방향으로 움직인 정도(상관계수)에 비례. 실행할 때마다 다시 계산하지만 긴 기간을 쓰므로 천천히 변합니다.<br>
종합 점수: 지표 점수의 가중평균. 재미로 만든 반대 버전이며, 점수가 높다고 사라는 뜻이 아닙니다. 시장 분위기를 보는 참고 지표이며, 주가 예측이나 투자 권유가 아닙니다.</p>
<script>{JS}</script>
</body></html>"""
    Path(path).write_text(page, encoding="utf-8")


def main():
    demo = "--demo" in sys.argv
    if not demo:
        try:
            import yfinance  # noqa: F401
        except ImportError:
            print("yfinance가 설치되어 있지 않습니다. 먼저 실행하세요:  pip install yfinance pandas")
            return
        print("시세를 받아오는 중입니다... (10~30초)")
    results = evaluate(Market(demo=demo))
    print_report(results, demo)
    if "--out" in sys.argv:      # 저장 위치 지정:  --out 폴더/파일.html
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        out = Path(__file__).resolve().parent / "시장심리_리포트.html"
    write_html(results, demo, out)
    print(f"\n리포트 저장: {out}")
    if all(r["total"] is None for r in results.values()):
        # 데이터를 전혀 못 받은 경우: 자동 게시가 빈 화면으로 덮어쓰지 않도록 실패로 종료
        sys.exit(1)
    if "--no-open" not in sys.argv:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
