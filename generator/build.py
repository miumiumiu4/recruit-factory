#!/usr/bin/env python3
"""求人LP量産ジェネレーター

sites/<slug>/data.yml（正本）から _site/<slug>/ に静的HTMLを生成する。
HTMLは生成物なので直接は直さない。直すのは data.yml だけ。

使い方:
  python3 generator/build.py                 # 全社をビルド
  python3 generator/build.py --only sample   # 1社だけ
  BUILD_DATE=2027-02-01 python3 generator/build.py   # 日付を変えて鮮度判定を試す

止める（エラー）もの: 形式の誤り、用語ガード違反、指定業者からの購入（法務確認なし）
隠す（警告）もの   : 確認日が古い数字、根拠のそろわない収入例、同意のない声、事実の足りない地域版
"""
import datetime as dt
import html
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "sites"
OUT = ROOT / "_site"
TERMS = yaml.safe_load((ROOT / "generator" / "terms.yml").read_text(encoding="utf-8"))
TODAY = dt.date.fromisoformat(os.environ["BUILD_DATE"]) if os.environ.get("BUILD_DATE") else dt.date.today()
ROOT_URL = os.environ.get("ROOT_URL", "https://miumiumiu4.github.io/recruit-factory/")

E = html.escape


class Report:
    def __init__(self, slug):
        self.slug, self.errors, self.warnings, self.hidden = slug, [], [], []

    def err(self, m): self.errors.append(m)
    def warn(self, m): self.warnings.append(m)
    def hide(self, m): self.hidden.append(m)


# ------------------------------------------------------------------ 判定ヘルパー
def as_date(v):
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v))
    except Exception:
        return None


def fresh(checked, days):
    d = as_date(checked)
    return d is not None and (TODAY - d).days <= days


def jp_date(v):
    d = as_date(v)
    return f"{d.year}年{d.month}月{d.day}日" if d else ""


def yen(n):
    return f"{int(n):,}円"


def man(n):
    v = n / 10000
    return f"{v:.1f}".rstrip("0").rstrip(".") + "万円"


def need(d, path, rep):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur or cur[k] in (None, ""):
            rep.err(f"必須項目がありません：{path}")
            return None
        cur = cur[k]
    return cur


# ------------------------------------------------------------------ 部品
ICON = {
    "form": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14v16H5z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 9h8M8 13h8M8 17h5" stroke="currentColor" stroke-width="2"/></svg>',
    "line": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3C6.5 3 2 6.6 2 11c0 3.9 3.5 7.2 8.3 7.9l-.6 2.6 3.3-2.5C18 18.6 22 15.2 22 11c0-4.4-4.5-8-10-8z" fill="currentColor"/></svg>',
}


def cta(c, area="", pos="", label="面談を申し込む（無料・応募＝契約ではありません）"):
    url = c["meta"]["form_url"]
    sep = "&" if "?" in url else "?"
    href = f'{url}{sep}co={c["meta"]["slug"]}' + (f"&area={area}" if area else "")
    h = f'<a class="btn btn-main js-cta" data-pos="{E(pos)}" href="{E(href)}" target="_blank" rel="noopener">{ICON["form"]}{E(label)}</a>'
    if c["meta"].get("line_url"):
        h += f'<a class="btn btn-line js-cta" data-pos="{E(pos)}-line" href="{E(c["meta"]["line_url"])}" target="_blank" rel="noopener">{ICON["line"]}LINEで質問・応募</a>'
    return f'<div class="cta-row">{h}</div>'


def section(no, title, body, lead=""):
    lead_html = f"<p class=\"lead\">{lead}</p>" if lead else ""
    return f'<section><div class="sec-head"><span class="no">{E(no)}</span><h2>{title}</h2>{lead_html}</div>{body}</section>'


def table(rows):
    return "<table>" + "".join(f"<tr><th>{E(k)}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"


def source_tag(scope, source, checked):
    bits = [x for x in [scope and f"{scope}の数字", source, checked and f"{jp_date(checked)}確認"] if x]
    return f'<span class="src">（{E("・".join(bits))}）</span>' if bits else ""


# ------------------------------------------------------------------ 本体
def build_site(sdir: Path):
    slug = sdir.name
    rep = Report(slug)
    c = yaml.safe_load((sdir / "data.yml").read_text(encoding="utf-8"))
    m = c.get("meta", {})
    m.setdefault("slug", slug)
    if m["slug"] != slug:
        rep.err(f"meta.slug（{m['slug']}）がフォルダ名（{slug}）と違います")
    for p in ["meta.form_url", "meta.site_url", "company.brand", "company.legal_name", "company.representative",
              "company.address", "company.phone", "job.title", "job.date_posted", "job.location.region",
              "status.owner_approved_on", "pay.unit_price.min", "pay.unit_price.max", "pay.unit_price.checked",
              "costs.items", "recruit.areas", "company.entity"]:
        need(c, p, rep)
    if rep.errors:
        return rep, None
    ttl = int(m.get("review_cycle_days", 60))
    st = c.get("status", {})
    stopped = (not st.get("publish", True)) or not fresh(st.get("owner_approved_on"), ttl)
    if stopped:
        rep.warn("停止モード：publish が false か、オーナー承認日から" f"{ttl}日を過ぎています。募集枠・求人構造化データを外し、noindex にしました")
    noindex = bool(m.get("noindex")) or stopped

    # ---- 指定業者チェック（業務提供誘引販売取引に当たるおそれ）
    for it in c["costs"]["items"]:
        if it.get("vendor") not in ("自由", "指定"):
            rep.err(f"costs.items「{it.get('name')}」に vendor（自由／指定）がありません")
        if it.get("vendor") == "指定" and not c.get("legal_review", {}).get("vendor_designated_ok"):
            rep.err(f"「{it.get('name')}」は指定業者からの購入です。法務確認（legal_review.vendor_designated_ok: true）が済むまで公開できません")

    bm = c.get("business_model", {})
    for k in ["lease_offered", "vendor_referral", "referral_fee_received", "purchase_required_for_work"]:
        if k not in bm:
            rep.err(f"business_model.{k}（true/false）がありません")
    if any(bm.get(k) for k in ["lease_offered", "vendor_referral", "referral_fee_received", "purchase_required_for_work"]) and not (bm.get("tokusho_review") or {}).get("done_on"):
        rep.err("リース・業者紹介・紹介料・購入条件のどれかがあります。特商法（業務提供誘引販売取引）の確認（business_model.tokusho_review.done_on と reviewer）が済むまで公開できません")
    tr = c.get("training", {})
    if tr.get("before_contract", True):
        rep.err("研修が契約の前になっています（training.before_contract: false にし、手順を「面談→契約→研修」にしてください）")
    pd = c["pay"].get("payment_days")
    if not isinstance(pd, int) or pd > 60:
        rep.err("pay.payment_days（作業完了から支払いまでの最大日数）がないか、60日を超えています")
    for i, s0 in enumerate(c.get("steps", [])):
        if "研修" in s0.get("title", "") and not any("契約" in x.get("title", "") for x in c["steps"][:i]):
            rep.err("手順で「研修」が「契約」より前にあります")
            break

    up = c["pay"]["unit_price"]
    price_ok = fresh(up["checked"], ttl)
    if not price_ok:
        rep.hide("委託単価の確認日が古いため、単価と試算を隠しました")

    # ---- 試算
    sims = []
    for s in c["pay"].get("simulations", []):
        jobs = s["jobs_per_day"] * s["days_per_month"]
        sims.append({**s, "jobs": jobs, "lo": jobs * up["min"], "hi": jobs * up["max"]})

    # ---- 初期費用
    items = c["costs"]["items"]
    tmin = sum(i.get("min", 0) for i in items if i.get("required"))
    tmax = sum(i.get("max", 0) for i in items if i.get("required"))
    payback = math.ceil(tmax / up["min"]) if up["min"] else None

    # ---- 収入実例（根拠がそろったものだけ）
    ex_ok = []
    for ex in c["pay"].get("examples", []) or []:
        lack = [k for k in ["who", "period", "days", "jobs", "amount", "before_expense", "source", "checked", "consent_on"] if ex.get(k) in (None, "")]
        if lack:
            rep.hide(f"収入例「{ex.get('who', '?')}」は根拠項目（{', '.join(lack)}）が足りないので載せませんでした")
        elif not fresh(ex["checked"], 365):
            rep.hide(f"収入例「{ex['who']}」は確認から1年を過ぎたので載せませんでした")
        else:
            ex_ok.append(ex)

    voices = []
    for v in c.get("voices", []) or []:
        if v.get("source") == "店" and v.get("store") not in (None, slug):
            rep.err(f"声「{v.get('label')}」は別の店（{v.get('store')}）の声です。自店の声として載せられません")
        if not v.get("consent_on") or not v.get("source") or not v.get("consent_scope"):
            rep.hide(f"声「{v.get('label', '?')}」は本人同意日・同意の範囲・出所（店／グループ）のどれかがないので載せませんでした")
        else:
            voices.append(v)
    stats = []
    for s in c.get("stats", []) or []:
        if fresh(s.get("checked"), ttl):
            stats.append(s)
        else:
            rep.hide(f"実績「{s.get('label')}」は確認日が古いので隠しました")

    slots = c["recruit"].get("slots") or {}
    slots_ok = (not stopped) and slots.get("remaining") and fresh(slots.get("checked"), min(ttl, 30))
    if slots.get("remaining") and not slots_ok and not stopped:
        rep.hide("募集枠の確認から30日を過ぎたので、残り人数を隠しました")

    # ================================================================ HTML
    co = c["company"]
    rc = c["recruit"]
    w = c["work"]
    parts = []

    # ---- hero
    chips = []
    if price_ok:
        chips.append(f'1件あたり <b>{yen(up["min"])}〜{yen(up["max"])}</b>')
    chips += ["未経験から", "研修費無料", "稼働日は自分で決める", "業務委託（個人事業主）"]
    hero = f'''<div class="hero"><div class="wrap">
<span class="tag"><span class="dot"></span>{"募集状況を確認中" if stopped else "業務委託の職人を募集中"}｜{E("・".join(a["pref"] for a in rc["areas"]))}</span>
<h1><span class="catch">{E(rc.get("headline_catch", ""))}</span>{E(rc["headline"])}</h1>
<p class="sub">{E(rc["sub"])}</p>
<div class="chips">{"".join(f'<span class="chip">{x}</span>' for x in chips)}</div>
{cta(c, pos="hero")}
<p class="micro">応募しても、すぐに契約にはなりません。まずZoomで条件を聞いてから決められます。</p>
{f'<p class="slots">募集枠：あと{int(slots["remaining"])}名<span class="src">（{jp_date(slots["checked"])}時点）</span></p>' if slots_ok else ""}
{f'<figure class="hero-photo"><img src="{E(m["hero_image"])}" alt="エアコンクリーニングの作業風景" width="1200" height="700" fetchpriority="high"></figure>' if m.get("hero_image") else ""}
</div></div>'''

    # ---- 01 仕事
    curve = w.get("demand_curve") or []
    wave = ""
    if len(curve) == 12:
        bars = "".join(f'<i style="height:{int(v)}%" title="{i+1}月"></i>' for i, v in enumerate(curve))
        wave = f'<div class="band"><h3>1年の依頼の波（イメージ）</h3><div class="wave" aria-hidden="true">{bars}</div><div class="wave-labels"><span>1月</span><span>4月</span><span>7月</span><span>10月</span><span>12月</span></div><p>繁忙期は{E(w["busy"])}、落ち着くのは{E(w["slow"])}です。{E(w.get("demand_note", ""))}</p></div>'
    parts.append(section("01 仕事の中身", "どんな仕事？", f'<div class="card"><p>{E(w["description"])}</p></div>{wave}'))

    # ---- 02 応募資格
    parts.append(section("02 応募資格", "必要なのは、普通免許と「やってみたい」気持ち", '<div class="card"><ul class="check">'
                         '<li><b>普通自動車免許（AT限定可）</b></li><li><b>未経験OK</b>。年齢・学歴・職歴は問いません</li>'
                         '<li>副業から始めることもできます</li></ul><p class="note">車両や道具については「08 契約と費用」にまとめています。</p></div>'))

    # ---- 03 背景
    stat_html = "".join(f'<li><b>{E(s["label"])}：{E(s["value"])}</b>{source_tag(s.get("scope"), s.get("source"), s.get("checked"))}</li>' for s in stats)
    parts.append(section("03 募集の背景", "なぜ今、募集しているのか",
                         f'<div class="card"><p>{E(rc["reason"])}</p>{f"<ul class=check>{stat_html}</ul>" if stat_html else ""}</div>'))

    # ---- 04 報酬
    if price_ok:
        tabs = "".join(f'<button type="button" class="ptab{" on" if i == 0 else ""}" data-i="{i}">{E(s["persona"])}</button>' for i, s in enumerate(sims))
        panes = "".join(
            f'<div class="pane{" on" if i == 0 else ""}" data-i="{i}"><p class="model-tag">{E(s["label"])}</p>'
            f'<p class="model-num">月 {man(s["lo"])}〜{man(s["hi"])}</p>'
            f'<p class="calc">1日{s["jobs_per_day"]}件 × 月{s["days_per_month"]}日 ＝ {s["jobs"]}件 × 単価{yen(up["min"])}〜{yen(up["max"])}</p></div>'
            for i, s in enumerate(sims))
        sim_html = f'<div class="card"><h3>あなたの働き方だと、いくら？</h3><div class="ptabs" role="tablist">{tabs}</div>{panes}<p class="note">試算は件数×単価の計算で、収入を約束するものではありません。{E(c["pay"].get("expenses_note", ""))}閑散期（{E(w["slow"])}）は件数が減ります。</p></div>' if sims else ""
        ex_html = "".join(
            f'<div class="example"><p class="ttl">実例：{E(ex["who"])}</p>{E(ex["period"])}に{ex["days"]}日・{ex["jobs"]}件稼働して、報酬{yen(ex["amount"])}'
            f'（{"経費を引く前" if ex["before_expense"] else "経費を引いた後"}）。{source_tag("", ex["source"], ex["checked"])}</div>' for ex in ex_ok)
        pay_body = f'''<div class="card"><div class="formula"><span>1件あたり単価</span><span class="op">×</span><span>完了件数</span><span class="op">＝</span><span>報酬</span></div>
{table([("委託単価", f'{yen(up["min"])}〜{yen(up["max"])}（機種・作業内容で変わります）{source_tag("", up.get("source"), up["checked"])}'), ("支払い", E(c["pay"]["payment_terms"])), ("報酬の性質", "完全歩合。固定の金額や最低保証はありません")])}</div>
{sim_html}{ex_html}'''
    else:
        pay_body = f'<div class="card"><p>報酬は「1件あたり単価×完了件数」の完全歩合です。最新の単価は面談でご案内します。支払いは{E(c["pay"]["payment_terms"])}です。</p></div>'
    parts.append(section("04 報酬", "いくら稼げる？ 計算式ごと見せます", pay_body + cta(c, pos="pay", label="単価と案件の波を面談で聞く")))

    # ---- 05 エリア
    area_html = "".join(f'<div class="area"><h3>{E(a["pref"])}</h3><div class="pref">{"".join(f"<span>{E(x)}</span>" for x in a.get("cities", []))}</div></div>' for a in rc["areas"])
    lp_links = []
    parts.append(section("05 活動エリア", "仕事場は、あなたの地元です", f'<div class="card">{area_html}<p class="note">{E(rc.get("radius_note", ""))}担当範囲は面談で相談して決めます。</p>__LOCAL_LINKS__</div>'))

    # ---- 06 1日
    flows = ""
    for f in c.get("day_flow", []):
        lis = "".join(f'<li><span class="time">{E(s["time"])}</span><span class="tdot"></span><div><h4>{E(s["title"])}</h4><p>{E(s["text"])}</p></div></li>' for s in f["steps"])
        flows += f'<h3>{E(f["title"])}</h3><ol class="tl">{lis}</ol>'
    parts.append(section("06 1日の流れ", "1日はどう動く？", f'<div class="card">{flows}<p class="note">出社はなく、自宅から現場へ直接向かいます。稼働する日と件数は自分で決めます。</p></div>'))

    # ---- 07 契約と費用
    cost_rows = "".join(
        f'<tr><th>{E(i["name"])}{"" if i.get("required") else "（任意）"}</th><td>{yen(i.get("min", 0)) + "〜" + yen(i.get("max", 0)) if i.get("max") else "0円〜（お手持ちのもの可）"}<br><span class="src">{E(i.get("note", ""))}</span></td></tr>'
        for i in items)
    payback_html = f'<p class="payback">必須の費用は最大でも約{man(tmax)}。最低単価で計算しても<b>約{payback}件分</b>の報酬でまかなえる計算です。</p>' if (payback and price_ok) else ""
    unsuit = "／".join(E(x) for x in c.get("unsuitable", []))
    parts.append(section("07 契約と費用", "契約は「業務委託」。始める費用も全部出します",
                         f'''<div class="card">{table([("契約の形", "業務委託契約（個人事業主として案件ごとに受託）。雇用契約ではありません"), ("稼働日", "自分で決めます。決まった件数の義務はありません"), ("契約期間", E(c["work"].get("contract_period", "面談でご案内します"))), ("契約の終了", E(c["work"].get("termination", "面談でご案内します"))), ("条件の書面", "報酬額・支払期日などは契約前に書面（メール可）でお渡しします")])}</div>
<div class="card"><h3>始めるときにかかる費用（まとめ）</h3><table>{cost_rows}<tr class="total"><th>必須の合計</th><td><b>{yen(tmin)}〜{yen(tmax)}</b></td></tr></table>{payback_html}
<p class="note">{E(c["costs"].get("no_purchase_obligation", ""))}</p>{"" if any(bm.get(k) for k in ["lease_offered","vendor_referral"]) else '<p class="note">当社は道具や車両の販売・リース・業者の紹介をしていません。</p>'}</div>
{f'<div class="honest"><b>正直にお伝えすると、こんな方には向いていません：</b>{unsuit}</div>' if unsuit else ""}'''))

    # ---- 08 流れ
    steps = "".join(f'<div class="step"><span class="s-no">STEP {i+1}</span><h3>{E(s["title"])}</h3><p>{E(s["text"])}</p></div>' for i, s in enumerate(c.get("steps", [])))
    parts.append(section("08 応募から独り立ちまで", "応募したら、何が起きる？", f'<div class="steps">{steps}</div>'))

    # ---- 09 研修
    t = c.get("training", {})
    parts.append(section("09 研修", "未経験でも、独り立ちまで伴走します", '<div class="card"><ul class="check">'
                         f'<li><b>オンライン研修（{E(t["online"]["period"])}）</b>：{E(t["online"]["detail"])}</li>'
                         f'<li><b>同行研修（{E(t["ojt"]["period"])}）</b>：{E(t["ojt"]["detail"])}</li>'
                         f'<li><b>独り立ち後</b>：{E(t.get("support", ""))}</li>'
                         f'<li><b>費用</b>：{E(t.get("fee", ""))}</li>'
                         f'<li><b>時期</b>：研修は業務委託契約を結んだ後に行います。研修中の事故は{E(t.get("insurance", "面談でご案内する保険"))}で備えます</li></ul></div>' + cta(c, pos="training")))

    # ---- 10 将来
    if c.get("future"):
        parts.append(section("10 その先", "自分の店を持つ道もあります", f'<div class="card"><p>{E(c["future"])}</p><p class="note">{E(c.get("independence_fee", "独立の費用は面談でご案内します。"))}</p></div>'))

    # ---- 11 FAQ
    faq = c.get("faq", [])
    parts.append(section("11 よくある質問", "応募前によくある疑問", "".join(f'<details><summary><span class="q">Q</span>{E(f["q"])}</summary><div class="a"><p>{E(f["a"])}</p></div></details>' for f in faq)))

    # ---- 12 声
    if voices:
        vh = "".join(f'<article class="voice"><span class="area">{E(v["label"])}</span><h3>{E(v.get("title", ""))}</h3><p>{E(v["text"])}</p><span class="src">（{E(v["source"])}の職人の声・本人同意済み）</span></article>' for v in voices)
        parts.append(section("12 働く人の声", "実際に働く人の声", f'<div class="voices">{vh}</div>'))

    # ---- 13 代表
    o = c.get("owner", {})
    vals = "".join(f'<li><b>{E(v["title"])}</b>：{E(v["text"])}</li>' for v in c.get("values", []))
    img = f'<img src="{E(m["owner_image"])}" alt="代表 {E(o.get("name", ""))}" width="400" height="320" loading="lazy">' if m.get("owner_image") else ""
    parts.append(section("13 代表あいさつ", "一緒に働く人へ", f'''<div class="card owner">{img}<div class="tx"><p class="name"><span class="role">{E(co["brand"])} {E(o.get("role", "代表"))}</span><b>{E(o.get("name", co["representative"]))}</b></p>
{"".join(f"<p>{E(x)}</p>" for x in o.get("message", []))}{f'<h3>大切にしていること</h3><ul class="check">{vals}</ul>' if vals else ""}</div></div>'''))

    # ---- 申込
    booking = c["meta"].get("booking_url")
    parts.append(f'''<section id="apply"><div class="apply">{f'<p class="slots">募集枠：あと{int(slots["remaining"])}名（{jp_date(slots["checked"])}時点）</p>' if slots_ok else ""}
<h2>まずは、話を聞いてみませんか</h2><p>面談はZoomで行います。報酬の計算、始める費用、繁忙期と閑散期の波まで、隠さずお話しします。そのうえで決めてください。</p>{cta(c, pos="apply")}{f'<p><a class="booking js-cta" data-pos="booking" href="{E(booking)}" target="_blank" rel="noopener">面談日を今すぐカレンダーから選ぶ →</a></p>' if booking else ""}
<p class="mini-note">送信後、担当者から面談日程のご連絡をします。応募しても、すぐに契約にはなりません。</p></div></section>''')

    foot = f'''<footer><div class="wrap"><h3>募集を行う事業者（業務委託の発注者）</h3>{table([
        ("事業者名", E(co["legal_name"]) + (f'（{E(co["brand"])}）' if co["brand"] != co["legal_name"] else "")),
        ("代表者", E(co["representative"])), ("所在地", E(co["address"])),
        ("連絡先", f'{E(co["phone"])}（受付 {E(co.get("hours", ""))}）' + (f'／{E(co["email"])}' if co.get("email") else "")),
        ("募集する業務", "エアコンクリーニング業務の委託（お客様宅での分解洗浄）"),
        ("報酬", f'1件あたり{yen(up["min"])}〜{yen(up["max"])}の完全歩合（{E(c["pay"]["payment_terms"])}）' if price_ok else "1件単価×件数の完全歩合（最新の単価は面談でご案内）"),
        ("公式サイト", f'<a href="{E(co.get("official_site", ""))}" target="_blank" rel="noopener">{E(co.get("official_site", ""))}</a>' if co.get("official_site") else "—"),
        ("所属", E(co.get("group", ""))),
        ("ページ制作", "ありがとうグループ本部（募集・契約の当事者は上記の事業者です）"),
        ("掲載内容の確認日", jp_date(st.get("owner_approved_on")))])}
<p class="copy">© {E(co["brand"])}</p></div></footer>'''

    # ---- 地域版（地元の事実が3つ以上ある所だけ）
    locals_ok = []
    for lp in c.get("local_pages", []) or []:
        facts = [f for f in (lp.get("local_facts") or []) if f]
        if len(facts) < 3:
            rep.hide(f"地域版「{lp.get('city')}」は地元の事実が{len(facts)}つ（3つ以上必要）なので作りませんでした")
        else:
            locals_ok.append(lp)
    links = "".join(f'<a href="area/{E(lp["slug"])}/">{E(lp["city"])}の募集ページ →</a>' for lp in locals_ok)
    body_main = "\n".join(parts).replace("__LOCAL_LINKS__", f'<div class="city-links">{links}</div>' if links else "")

    title = f'{c["job"]["title"]}の募集｜{co["brand"]}'
    desc = f'{co["brand"]}が業務委託のエアコンクリーニング職人を募集。未経験から、研修費無料。報酬は1件単価×件数の完全歩合で、始める費用・案件の波まで公開しています。'
    jsonld = None if (stopped or noindex and not m.get("sample")) else jobposting(c, body_main, ttl)

    out = OUT / slug
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    pages = {"": page(c, title, desc, m["site_url"], hero + f'<div class="wrap">{body_main}</div>' + foot, noindex, stopped, jsonld)}
    for lp in locals_ok:
        lh = f'''<div class="hero"><div class="wrap"><span class="tag"><span class="dot"></span>{E(lp["pref"])}{E(lp["city"])}｜業務委託の職人を募集中</span>
<h1>{E(lp["city"])}で働く<br>エアコンクリーニング職人</h1><p class="sub">{E(lp["lead"])}</p>{cta(c, area=lp["slug"], pos="local-hero")}</div></div>
<div class="wrap">{section("地元の事実", f'{E(lp["city"])}の募集で知っておいてほしいこと', '<div class="card"><ul class="check">' + "".join(f"<li>{E(x)}</li>" for x in lp["local_facts"]) + '</ul><div class="pref">' + "".join(f"<span>{E(n)}</span>" for n in lp.get("neighbors", [])) + "</div></div>")}
<p class="back"><a href="../../">報酬・費用・研修など、募集の全体はこちら →</a></p></div>'''
        pages[f'area/{lp["slug"]}/'] = page(c, f'{lp["city"]}の{c["job"]["title"]}の募集｜{co["brand"]}', desc, m["site_url"] + f'area/{lp["slug"]}/', lh + foot, noindex, stopped, None)

    for rel, h in pages.items():
        lint(h, rel or "トップ", rep)
        p = out / rel / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(h, encoding="utf-8")
    if (sdir / "images").exists():
        shutil.copytree(sdir / "images", out / "images")
    if not noindex:
        urls = "".join(f'<url><loc>{E(m["site_url"] + rel)}</loc><lastmod>{as_date(st["owner_approved_on"])}</lastmod></url>' for rel in pages)
        (out / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
    (out / "build-report.json").write_text(json.dumps({"slug": slug, "build_date": str(TODAY), "stopped": stopped, "noindex": noindex,
                                                        "errors": rep.errors, "warnings": rep.warnings, "hidden": rep.hidden,
                                                        "pages": list(pages)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep, {"slug": slug, "brand": co["brand"], "noindex": noindex, "stopped": stopped, "sample": bool(m.get("sample"))}


def jobposting(c, body, ttl):
    co, j, st = c["company"], c["job"], c["status"]
    valid = as_date(st["owner_approved_on"]) + dt.timedelta(days=ttl)
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", "", body)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n", html.unescape(text)).strip()
    loc = j["location"]
    return {
        "@context": "https://schema.org/", "@type": "JobPosting",
        "title": j["title"], "description": "<p>" + E(text).replace("\n", "<br>") + "</p>",
        "identifier": {"@type": "PropertyValue", "name": co["legal_name"], "value": j.get("identifier", c["meta"]["slug"])},
        "datePosted": str(as_date(j["date_posted"])), "validThrough": f"{valid}T23:59:59+09:00",
        "employmentType": "CONTRACTOR",
        "hiringOrganization": {"@type": "Organization", "name": co["legal_name"], "sameAs": co.get("official_site", "")},
        "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressCountry": "JP",
                                                       "addressRegion": loc.get("region", ""), "addressLocality": loc.get("locality", ""),
                                                       "postalCode": str(loc.get("postal_code", "")), "streetAddress": str(loc.get("street", ""))}},
        "directApply": False,
    }


def lint(h, where, rep):
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", h)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    for a in TERMS.get("allow", []):
        text = text.replace(a, "")
    for word, alt in (TERMS.get("error") or {}).items():
        if word in text:
            i = text.find(word)
            rep.err(f"[{where}] 使わない言葉「{word}」→「{alt}」：…{text[max(0, i-15):i+15].strip()}…")
    for word, alt in (TERMS.get("warn") or {}).items():
        if word in text:
            rep.warn(f"[{where}] 注意する言葉「{word}」：{alt}")


def page(c, title, desc, url, body, noindex, stopped, jsonld):
    m = c["meta"]
    th = m.get("theme", {})
    css = (ROOT / "generator" / "style.css").read_text(encoding="utf-8")
    css = css.replace("#0a8fc2", th.get("main", "#0a8fc2")).replace("#ef6414", th.get("accent", "#ef6414"))
    banner = ""
    if m.get("sample"):
        banner += '<div class="sample-band">これは架空のサンプル会社で作った見本ページです。実在の会社・募集ではありません。</div>'
    if stopped:
        banner += '<div class="stop-band">ただいま募集状況を確認中です。最新の状況は面談でご案内します。</div>'
    ga = ""
    if m.get("ga4_id"):
        ga = f'<script async src="https://www.googletagmanager.com/gtag/js?id={E(m["ga4_id"])}"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}gtag("js",new Date());gtag("config","{E(m["ga4_id"])}");</script>'
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{E(title)}</title><meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(url)}">{'<meta name="robots" content="noindex">' if noindex else ""}
<meta property="og:type" content="website"><meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{E(url)}">
{f'<meta property="og:image" content="{E(m["site_url"] + m["hero_image"])}">' if m.get("hero_image") else ""}
<style>{css}</style>{ga}{ld}</head><body>
{banner}<header class="topbar"><div class="wrap"><span class="logo">{E(m.get("logo_text", c["company"]["brand"]))}</span><span class="sub">業務委託の職人募集</span></div></header>
<main>{body}</main>
<div class="fixedbar">{cta(c, pos="fixed", label="面談を申し込む（無料）")}</div>
<script>{TRACK_JS}</script></body></html>'''


TRACK_JS = r"""
(function(){var q=new URLSearchParams(location.search),keep=['utm_source','utm_medium','utm_campaign','src'];
document.querySelectorAll('.js-cta').forEach(function(a){try{var u=new URL(a.href);keep.forEach(function(k){if(q.get(k))u.searchParams.set(k,q.get(k))});a.href=u.toString()}catch(e){}
a.addEventListener('click',function(){if(window.gtag)gtag('event','cta_click',{position:a.dataset.pos})})});
document.querySelectorAll('.ptab').forEach(function(b){b.addEventListener('click',function(){var i=b.dataset.i;
document.querySelectorAll('.ptab').forEach(function(x){x.classList.toggle('on',x.dataset.i===i)});
document.querySelectorAll('.pane').forEach(function(x){x.classList.toggle('on',x.dataset.i===i)});
if(window.gtag)gtag('event','persona_select',{persona:b.textContent})})})})();
"""


def main():
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    OUT.mkdir(exist_ok=True)
    built, failed = [], False
    for sdir in sorted(p for p in SITES.iterdir() if (p / "data.yml").exists()):
        if only and sdir.name != only:
            continue
        rep, info = build_site(sdir)
        print(f"\n■ {rep.slug}")
        for x in rep.errors:
            print("  ✖ " + x)
        for x in rep.warnings:
            print("  ! " + x)
        for x in rep.hidden:
            print("  - " + x)
        if rep.errors:
            failed = True
            shutil.rmtree(OUT / rep.slug, ignore_errors=True)
        elif info:
            built.append(info)
            print("  ✔ 生成しました")
    if not only:
        lis = "".join(f'<li><a href="{E(b["slug"])}/">{E(b["brand"])}</a>{"（見本）" if b["sample"] else ""}{"（停止中）" if b["stopped"] else ""}</li>' for b in built)
        (OUT / "index.html").write_text(f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="robots" content="noindex"><meta name="viewport" content="width=device-width,initial-scale=1"><title>求人LP一覧</title></head><body style="font-family:sans-serif;max-width:640px;margin:40px auto;padding:0 16px"><h1>求人LP一覧</h1><ul>{lis}</ul><p><a href="https://github.com/miumiumiu4/recruit-factory">仕組みの説明（GitHub）</a></p></body></html>', encoding="utf-8")
        maps = "".join(f'<sitemap><loc>{ROOT_URL}{b["slug"]}/sitemap.xml</loc></sitemap>' for b in built if not b["noindex"])
        (OUT / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{maps}</sitemapindex>', encoding="utf-8")
        (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {ROOT_URL}sitemap.xml\n", encoding="utf-8")
        (OUT / ".nojekyll").write_text("", encoding="utf-8")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
