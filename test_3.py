import streamlit as st
from supabase import create_client, Client
import yfinance as yf
import re

# 1. ページ設定（必ず最初に！）
st.set_page_config(page_title="クリエイター管理プラットフォーム", layout="wide", page_icon="🎧")

# --- パスワード保護機能 ---
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # セキュリティのため入力値を消す
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # 初回表示
        st.text_input("パスワードを入力してください", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # パスワードが間違っている場合
        st.text_input("パスワードを入力してください", type="password", on_change=password_entered, key="password")
        st.error("😕 パスワードが違います")
        return False
    else:
        # パスワード正解
        return True

if not check_password():
    st.stop() # 正解するまでこれ以降のコードを実行しない

# --- 設定 ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_connection():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# プレビューリンク変換 (YouTube/Drive)
def format_preview_link(url):
    if not url: return ""
    if "drive.google.com" in url:
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/file/d/{file_id}/preview"
    if "youtube.com" in url or "youtu.be" in url:
        v_id = None
        if "v=" in url: v_id = url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url: v_id = url.split("youtu.be/")[1].split("?")[0]
        elif "live/" in url: v_id = url.split("live/")[1].split("?")[0]
        elif "shorts/" in url: v_id = url.split("shorts/")[1].split("?")[0]
        if v_id: return f"https://www.youtube.com/embed/{v_id}"
    return url

supabase = init_connection()

@st.cache_data(ttl=3600)
def get_all_rates():
    try:
        tickers = {"USD": "JPY=X", "EUR": "EURJPY=X", "CNY": "CNYJPY=X"}
        rates = {"JPY": 1.0}
        for code, ticker in tickers.items():
            t = yf.Ticker(ticker)
            rates[code] = t.history(period="1d")['Close'].iloc[-1]
        return rates
    except:
        return {"USD": 154.0, "JPY": 1.0, "EUR": 165.0, "CNY": 21.0}

rates = get_all_rates()

def convert_currency(amount, from_cur, to_cur):
    if from_cur == to_cur: return amount
    jpy_val = amount * rates[from_cur]
    return jpy_val / rates[to_cur]

def load_data():
    return supabase.table("creators").select("*").execute().data

def get_sns_icon(url, label):
    u = url.lower()
    if "instagram" in u: return "📸"
    if "twitter" in u or "x.com" in u: return "𝕏"
    if "linkedin" in u: return "🔗"
    if "spotify" in u: return "🔊"
    if "reel" in label.lower(): return "🎬"
    return "🔗"

SNS_LABELS = ["Instagram", "X (Twitter)", "LinkedIn", "Spotify", "Reel / Portfolio", "Other"]
CURRENCIES = ["USD", "JPY", "EUR", "CNY"]
ROLE_OPTIONS = ["作曲", "アレンジ", "演奏", "エンジニア", "作詞", "ボーカル"]

# --- メイン UI ---
st.title("🎧 クリエイター管理プラットフォーム")

# セクター切り替え
sector = st.radio("セクター選択", ["Music Related", "Video Related"], horizontal=True)
category_map = {"Music Related": "music", "Video Related": "video"}
current_cat = category_map[sector]

# 全データとカテゴリー別データの準備
all_data = load_data()
data = [r for r in all_data if r.get("category", "music") == current_cat]

# 自動学習用リスト
all_roles_db = sorted(list(set(r for row in all_data for r in (row.get("roles") or []))))
all_tags_db = sorted(list(set(g for row in all_data for g in (row.get("genre_tags") or []))))
all_inst_db = sorted(list(set(i for row in all_data for i in (row.get("instruments") or []))))

# --- サイドバー ---
st.sidebar.title("🔍 Search & Sorting")
search_q = st.sidebar.text_input("キーワード検索", placeholder="名前・楽器・メモ・案件名...", key="main_search")

# 音楽/映像モードによるサイドバー出し分け
if current_cat == "music":
    st.sidebar.markdown("### 💱 Market Rate")
    rate_target = st.sidebar.selectbox("レート確認 (1単位 = ? JPY)", ["USD", "EUR", "CNY"], index=0, key="rate_sel")
    st.sidebar.metric(label=f"{rate_target} / JPY", value=f"¥{rates[rate_target]:.2f}")
    st.sidebar.markdown("---")
    display_cur = st.sidebar.selectbox("表示通貨を切り替え", CURRENCIES, index=1, key="cur_sel")
    sort_options = ["お気に入り優先", "価格が安い順", "価格が高い順", "登録日が新しい順", "仕事回数が多い順"]
else:
    display_cur = "JPY" # 映像はJPY固定
    sort_options = ["お気に入り優先", "登録日が新しい順", "仕事回数が多い順"]

sort_option = st.sidebar.selectbox("並び替え", sort_options, key="sort_sel")

st.sidebar.markdown("---")
fav_only = st.sidebar.checkbox("⭐ お気に入りのみ", key="fav_check")
sel_roles = st.sidebar.multiselect("役割フィルター", all_roles_db, key="role_filter")
sel_tags = st.sidebar.multiselect("タグフィルター", all_tags_db, key="tag_filter")
sel_inst = st.sidebar.multiselect("楽器フィルター", sorted(all_inst_db), key="inst_filter")

# 🐾 予算の双方向同期ロジック (Musicのみ)
f_min, f_max = 0, 999999999
if current_cat == "music":
    st.sidebar.markdown("---")
    st.sidebar.write(f"予算フィルター ({display_cur})")
    max_limit = 2000000 if display_cur == "JPY" else 20000
    
    if "b_slider" not in st.session_state or st.session_state.get("last_cur") != display_cur:
        st.session_state.b_slider = (0, max_limit)
        st.session_state.b_min_str = "0"
        st.session_state.b_max_str = f"{max_limit:,}"
        st.session_state.last_cur = display_cur

    def on_slider_change():
        st.session_state.b_min_str = f"{st.session_state.b_slider[0]:,}"
        st.session_state.b_max_str = f"{st.session_state.b_slider[1]:,}"

    def on_str_change():
        try:
            low = int(st.session_state.b_min_str.replace(',', ''))
            high = int(st.session_state.b_max_str.replace(',', ''))
            low, high = min(low, high), max(low, high)
            st.session_state.b_slider = (low, high)
            st.session_state.b_min_str, st.session_state.b_max_str = f"{low:,}", f"{high:,}"
        except: pass

    st.sidebar.slider("スライダー", 0, max_limit, key="b_slider", on_change=on_slider_change)
    c_min, c_max = st.sidebar.columns(2)
    c_min.text_input("最小", key="b_min_str", on_change=on_str_change)
    c_max.text_input("最大", key="b_max_str", on_change=on_str_change)
    f_min, f_max = st.session_state.b_slider

# フィルタリング
filtered = data
if search_q:
    q = search_q.lower()
    filtered = [r for r in filtered if q in r["name"].lower() or q in (r.get("notes") or "").lower() or q in (r.get("email") or "").lower() or q in (r.get("tel") or "").lower() or any(q in str(i).lower() for i in (r.get("instruments") or [])) or any(q in str(h.get("project", "")).lower() for h in (r.get("work_history") or []))]
if fav_only: filtered = [r for r in filtered if r.get("is_favorite")]
if sel_roles: filtered = [r for r in filtered if set(sel_roles).intersection(set(r.get("roles") or []))]
if sel_tags: filtered = [r for r in filtered if set(sel_tags).intersection(set(r.get("genre_tags") or []))]
if sel_inst: filtered = [r for r in filtered if set(sel_inst).intersection(set(r.get("instruments") or []))]
if current_cat == "music":
    filtered = [r for r in filtered if (convert_currency(r.get("budget_min", 0), r.get("currency", "USD"), display_cur) <= f_max) and (convert_currency(r.get("budget_max", 0), r.get("currency", "USD"), display_cur) >= f_min)]

# ソート
if sort_option == "価格が安い順" and current_cat == "music": filtered.sort(key=lambda x: convert_currency(x.get("budget_min", 0), x.get("currency", "USD"), "USD"))
elif sort_option == "価格が高い順" and current_cat == "music": filtered.sort(key=lambda x: convert_currency(x.get("budget_max", 0), x.get("currency", "USD"), "USD"), reverse=True)
elif sort_option == "仕事回数が多い順": filtered.sort(key=lambda x: len(x.get("work_history") or []), reverse=True)
elif sort_option == "登録日が新しい順": filtered.sort(key=lambda x: x.get("id", 0), reverse=True)
else: filtered.sort(key=lambda x: (x.get("is_favorite", False), x.get("name")), reverse=True)

# --- タブ ---
tab_view, tab_add, tab_proj = st.tabs(["📋 リスト表示", "➕ 個別登録", "🎬 プロジェクト一括登録"])

with tab_add:
    st.subheader(f"新規登録 ({sector})")
    with st.form("add_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            n_name = st.text_input("名前（必須）")
            n_email = st.text_input("メールアドレス")
            n_tel = st.text_input("電話番号")
            n_roles_sel = st.multiselect("役割を選択", ROLE_OPTIONS + all_roles_db)
            n_roles_new = st.text_input("新しい役割を追加")
            if current_cat == "music":
                n_inst_sel = st.multiselect("既存の楽器を選択", all_inst_db)
                n_inst_new = st.text_input("新しい楽器を追加")
            else: n_inst_sel, n_inst_new = [], ""
            n_cur = st.selectbox("通貨", CURRENCIES)
            n_min_s = st.text_input("最小予算", value="0")
            n_max_s = st.text_input("最大予算", value="0")
        with c2:
            n_tags = st.text_input("タグ（カンマ区切り）")
            n_notes = st.text_area("メモ")
            n_sns = [st.text_input(L, key=f"n_sns_{L}") for L in SNS_LABELS]
        
        if st.form_submit_button("登録"):
            if n_name:
                n_min = int(n_min_s.replace(',', '')) if n_min_s.replace(',', '').isdigit() else 0
                n_max = int(n_max_s.replace(',', '')) if n_max_s.replace(',', '').isdigit() else 0
                f_roles = list(set(n_roles_sel + ([r.strip() for r in n_roles_new.split(",")] if n_roles_new else [])))
                f_inst = list(set(n_inst_sel + ([i.strip() for i in n_inst_new.split(",")] if n_inst_new else [])))
                supabase.table("creators").insert({
                    "name": n_name, "email": n_email, "tel": n_tel, "roles": f_roles, "instruments": f_inst, 
                    "budget_min": n_min, "budget_max": n_max, "currency": n_cur, "sns_urls": n_sns, 
                    "notes": n_notes, "genre_tags": [g.strip() for g in n_tags.split(",")] if n_tags else [],
                    "category": current_cat
                }).execute()
                st.rerun()

with tab_view:
    for row in filtered:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 4, 1.5])
            with c1:
                f_icon = "⭐" if row.get("is_favorite") else "☆"
                if st.button(f_icon, key=f"fav_{row['id']}"):
                    supabase.table("creators").update({"is_favorite": not row.get("is_favorite")}).eq("id", row["id"]).execute()
                    st.rerun()
                st.markdown(f"**{row['name']}**")
                contact_info = []
                if row.get("email"): contact_info.append(f"✉️ {row['email']}")
                if row.get("tel"): contact_info.append(f"📞 {row['tel']}")
                if contact_info: st.caption("  ".join(contact_info))
                roles, insts = row.get("roles") or [], sorted(row.get("instruments") or [])
                txt = " / ".join(roles) + (f" ({', '.join(insts)})" if insts else "")
                st.caption(txt)
                if row.get("genre_tags"): st.caption(" ".join([f"#{t}" for t in row["genre_tags"]]))
            with c2:
                if current_cat == "music":
                    o_min, o_max, o_cur = row.get("budget_min", 0), row.get("budget_max", 0), row.get("currency", "USD")
                    st.markdown(f"💰 **{display_cur} {convert_currency(o_min, o_cur, display_cur):,.0f} ~ {convert_currency(o_max, o_cur, display_cur):,.0f}**")
                    st.caption(f"Original: {o_cur} {o_min:,} ~ {o_max:,}")
                else: st.write("---")
            with c3:
                urls = row.get("sns_urls") or []
                cols = st.columns(3)
                for i, L in enumerate(SNS_LABELS):
                    if i < len(urls) and urls[i]:
                        cols[i % 3].link_button(f"{get_sns_icon(urls[i], L)} {L[:3]}", urls[i], use_container_width=True)
            with c4:
                m_c, d_c, e_c = st.columns(3)
                if row.get("notes"): m_c.popover("📝").write(row["notes"])
                with d_c.popover("📑"):
                    history = row.get("work_history") or []
                    with st.expander("＋ 履歴追加"):
                        h_date = st.date_input("日付", key=f"hd_{row['id']}")
                        h_proj = st.text_input("案件", key=f"hp_{row['id']}")
                        h_prod = st.text_input("担当P", key=f"hpr_{row['id']}")
                        h_link = st.text_input("Link", key=f"hl_{row['id']}")
                        if st.button("保存", key=f"hsv_{row['id']}"):
                            history.append({"date": str(h_date), "project": h_proj, "producer": h_prod, "link": h_link})
                            supabase.table("creators").update({"work_history": history}).eq("id", row["id"]).execute()
                            st.rerun()
                    rh = list(reversed(history))
                    for idx, item in enumerate(rh):
                        if idx == 3: st.markdown("---")
                        st.markdown(f"**{item['date']} | {item['project']}**")
                        if item.get("producer"): st.caption(f"P: {item['producer']}")
                        if item.get("link"):
                            emb = format_preview_link(item["link"])
                            if "embed" in emb or "preview" in emb: st.iframe(emb, height=240)
                            cl1, cl2 = st.columns([4, 1])
                            cl1.link_button("🔗 動画を開く", item["link"], use_container_width=True)
                            if cl2.button("🗑️", key=f"dh_{row['id']}_{idx}"):
                                history.remove(item); supabase.table("creators").update({"work_history": history}).eq("id", row["id"]).execute(); st.rerun()
                with e_c.popover("⚙️"):
                    e_name = st.text_input("名前", row["name"], key=f"en_{row['id']}")
                    e_email = st.text_input("メールアドレス", row.get("email", ""), key=f"ee_{row['id']}")
                    e_tel = st.text_input("電話番号", row.get("tel", ""), key=f"etel_{row['id']}")
                    e_roles = st.multiselect("役割", ROLE_OPTIONS + all_roles_db, row.get("roles") or [], key=f"er_{row['id']}")
                    e_inst = st.multiselect("楽器", all_inst_db, row.get("instruments") or [], key=f"ei_{row['id']}") if current_cat=="music" else []
                    e_tags = st.text_input("タグ", ", ".join(row.get("genre_tags") or []), key=f"etag_{row['id']}")
                    e_cur = st.selectbox("通貨", CURRENCIES, CURRENCIES.index(row.get("currency", "USD")), key=f"ec_{row['id']}")
                    e_min_s = st.text_input("最小予算", value=f"{int(row.get('budget_min', 0)):,}", key=f"emi_s_{row['id']}")
                    e_max_s = st.text_input("最大予算", value=f"{int(row.get('budget_max', 0)):,}", key=f"ema_s_{row['id']}")
                    e_sns = [st.text_input(L, (row.get("sns_urls") or [""]*6)[i] if i < len(row.get("sns_urls") or []) else "", key=f"es_{row['id']}_{i}") for i, L in enumerate(SNS_LABELS)]
                    e_notes = st.text_area("メモ", row.get("notes") or "", key=f"ent_{row['id']}")
                    if st.button("更新を反映", key=f"upd_{row['id']}", use_container_width=True):
                        e_min = int(e_min_s.replace(',', '')) if e_min_s.replace(',', '').isdigit() else 0
                        e_max = int(e_max_s.replace(',', '')) if e_max_s.replace(',', '').isdigit() else 0
                        supabase.table("creators").update({
                            "name": e_name, "email": e_email, "tel": e_tel, "roles": e_roles, "instruments": e_inst, 
                            "budget_min": e_min, "budget_max": e_max, "currency": e_cur, "sns_urls": e_sns, 
                            "notes": e_notes, "genre_tags": [t.strip() for t in e_tags.split(",")] if e_tags else [],
                            "category": current_cat
                        }).eq("id", row["id"]).execute()
                        st.rerun()
                    st.markdown("---")
                    if st.button("🚨 完全に削除", key=f"del_{row['id']}", use_container_width=True):
                        supabase.table("creators").delete().eq("id", row["id"]).execute(); st.rerun()

with tab_proj:
    st.subheader("🎬 プロジェクト一括登録")
    st.info("全カテゴリー（Music/Video）からメンバーを選んで一括登録します。")
    col_p1, col_p2 = st.columns(2)
    p_name = col_p1.text_input("案件名", key="bulk_pname")
    p_link = col_p2.text_input("Link (Drive/YouTube)", key="bulk_plink")
    p_date = col_p1.date_input("実施日", key="bulk_pdate")
    p_prod = col_p2.text_input("担当プロデューサー", key="bulk_pprod")
    st.markdown("---")
    st.write("👥 参加メンバーを選択（全リストから検索）")
    s_col1, s_col2 = st.columns([2, 1])
    p_search = s_col1.text_input("名前・楽器・役割で検索", placeholder="例: 佐藤, Piano...", key="p_search_bulk")
    p_tags_sel = s_col2.multiselect("タグで絞り込み", all_tags_db, key="p_tag_filter_bulk")
    p_candidates = [r for r in all_data if (not p_search or (p_search.lower() in r['name'].lower() or any(p_search.lower() in str(i).lower() for i in (r.get('instruments') or [])) or any(p_search.lower() in str(ro).lower() for ro in (r.get('roles') or [])))) and (not p_tags_sel or set(p_tags_sel).intersection(set(r.get('genre_tags') or [])))]
    selected_ids = []
    if p_candidates:
        st.write(f"該当候補: {len(p_candidates)}名")
        cols = st.columns(4)
        for i, cand in enumerate(p_candidates):
            icon = "🎹" if cand.get("category") == "music" else "🎬"
            if cols[i % 4].checkbox(f"{icon} {cand['name']}", key=f"sel_{cand['id']}"): selected_ids.append(cand['id'])
    if st.button("🚀 選択したメンバーに一括登録", use_container_width=True):
        if p_name and selected_ids:
            new_item = {"date": str(p_date), "project": p_name, "link": p_link, "producer": p_prod}
            for cid in selected_ids:
                tc = next(item for item in all_data if item["id"] == cid)
                h = tc.get("work_history") or []; h.append(new_item)
                supabase.table("creators").update({"work_history": h}).eq("id", cid).execute()
            st.success(f"「{p_name}」を登録しました！"); st.rerun()
