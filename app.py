import pandas as pd
import streamlit as st
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# ============================================================
# 1. CẤU HÌNH HỆ THỐNG
# ============================================================
# Hãy dán chuỗi Key gsk_... của bạn vào đây
GROQ_API_KEY = "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"
GROQ_MODEL = "gemma2-9b-it"
APP_VERSION = "v6-groq-api"

AIVEN_HOST = "mysql-3a5ef2bc-binhquytoc.a.aivencloud.com"
AIVEN_PORT = 14483
AIVEN_USER = "avnadmin"
AIVEN_PASSWORD = "AVNS_TX2oBXmTGGjXba6p7j1"
AIVEN_DATABASE = "defaultdb"

ADMIN_PASSWORD = "123456"


# ============================================================
# 2. CẤU HÌNH STREAMLIT
# ============================================================
st.set_page_config(
    page_title="Order Nhà Hàng + Groq AI",
    page_icon="🍽️",
    layout="wide"
)


# ============================================================
# 3. KẾT NỐI AIVEN MYSQL
# ============================================================
DATABASE_URL = URL.create(
    drivername="mysql+pymysql",
    username=AIVEN_USER,
    password=AIVEN_PASSWORD,
    host=AIVEN_HOST.strip(),
    port=int(AIVEN_PORT),
    database=AIVEN_DATABASE
)


@st.cache_resource
def get_db_engine():
    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"connect_timeout": 15, "ssl": {"check_hostname": False}},
        pool_size=5,
        max_overflow=5
    )


def init_db():
    engine = get_db_engine()

    sql = """
    CREATE TABLE IF NOT EXISTS orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        created_at DATETIME NOT NULL,
        table_name VARCHAR(50) NOT NULL,
        item_name VARCHAR(100) NOT NULL,
        quantity INT NOT NULL,
        total_price DECIMAL(12,2) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


db_connected = False
db_error = ""

try:
    init_db()
    db_connected = True
except Exception as e:
    db_error = str(e)


# ============================================================
# 4. MENU NHÀ HÀNG
# ============================================================
menu = {
    "Đồ ăn": {
        "Pizza Hải Sản": 150000,
        "Mì Ý Bò Bằm": 95000,
        "Burger Gà": 65000,
        "Salad Trộn": 50000,
        "Bít tết Bò Mỹ": 250000,
        "Sườn nướng BBQ": 180000,
        "Cánh gà chiên mắm": 75000,
        "Lẩu cá diêu hồng": 200000,
        "Lẩu Thái hải sản": 300000,
    },
    "Thức uống": {
        "Coca Cola": 20000,
        "Trà Đào Cam Sả": 35000,
        "Cà Phê Sữa": 25000,
        "Nước Suối": 10000,
        "Sinh tố Bơ": 45000,
        "Nước ép cam": 40000,
        "Mojito chanh dây": 55000,
        "Bia Heineken": 30000,
    },
}


# ============================================================
# 5. SESSION STATE
# ============================================================
if "order_dict" not in st.session_state:
    st.session_state.order_dict = {}

if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


# ============================================================
# 6. ĐỌC LỊCH SỬ GIAO DỊCH
# ============================================================
def load_history_from_db(show_error=True):
    if not db_connected:
        return pd.DataFrame()

    try:
        engine = get_db_engine()

        sql = text("""
            SELECT
                id,
                created_at,
                table_name,
                item_name,
                quantity,
                total_price
            FROM orders
            ORDER BY created_at DESC
        """)

        with engine.connect() as conn:
            df = pd.read_sql(sql, conn)

        if not df.empty:
            df["total_price"] = df["total_price"].astype(float)
            df.rename(
                columns={
                    "id": "ID",
                    "created_at": "Thời gian",
                    "table_name": "Bàn",
                    "item_name": "Tên món",
                    "quantity": "Số lượng",
                    "total_price": "Thành tiền",
                },
                inplace=True
            )

        return df

    except Exception as e:
        if show_error:
            st.error(f"Lỗi đọc dữ liệu Aiven MySQL: {e}")
        return pd.DataFrame()


# ============================================================
# 7. TẠO DỮ LIỆU MYSQL CHO GROQ AI
# ============================================================
def get_database_context():
    if not db_connected:
        return "DATABASE_STATUS: MySQL chưa kết nối được."

    try:
        engine = get_db_engine()

        summary_sql = text("""
            SELECT
                COUNT(*) AS total_records,
                COALESCE(SUM(quantity), 0) AS total_quantity,
                COALESCE(SUM(total_price), 0) AS total_revenue,
                COUNT(DISTINCT table_name) AS total_tables,
                COUNT(DISTINCT item_name) AS total_items
            FROM orders
        """)

        daily_sql = text("""
            SELECT
                DATE(created_at) AS order_date,
                SUM(quantity) AS quantity,
                SUM(total_price) AS revenue
            FROM orders
            GROUP BY DATE(created_at)
            ORDER BY order_date DESC
            LIMIT 30
        """)

        product_sql = text("""
            SELECT
                item_name,
                SUM(quantity) AS quantity,
                SUM(total_price) AS revenue
            FROM orders
            GROUP BY item_name
            ORDER BY quantity DESC
            LIMIT 30
        """)

        table_sql = text("""
            SELECT
                table_name,
                SUM(quantity) AS quantity,
                SUM(total_price) AS revenue
            FROM orders
            GROUP BY table_name
            ORDER BY revenue DESC
        """)

        hourly_sql = text("""
            SELECT
                HOUR(created_at) AS hour,
                SUM(quantity) AS quantity,
                SUM(total_price) AS revenue
            FROM orders
            GROUP BY HOUR(created_at)
            ORDER BY hour
        """)

        recent_sql = text("""
            SELECT
                created_at,
                table_name,
                item_name,
                quantity,
                total_price
            FROM orders
            ORDER BY created_at DESC
            LIMIT 100
        """)

        with engine.connect() as conn:
            summary = pd.read_sql(summary_sql, conn)
            daily = pd.read_sql(daily_sql, conn)
            products = pd.read_sql(product_sql, conn)
            tables = pd.read_sql(table_sql, conn)
            hourly = pd.read_sql(hourly_sql, conn)
            recent = pd.read_sql(recent_sql, conn)

        parts = [
            "=== TỔNG QUAN DATABASE ===",
            summary.to_string(index=False),
            "\n=== DOANH THU THEO NGÀY - 30 NGÀY GẦN NHẤT ===",
            daily.to_string(index=False),
            "\n=== MÓN BÁN NHIỀU ===",
            products.to_string(index=False),
            "\n=== DOANH THU THEO BÀN ===",
            tables.to_string(index=False),
            "\n=== DOANH SỐ THEO GIỜ ===",
            hourly.to_string(index=False),
            "\n=== 100 GIAO DỊCH GẦN NHẤT ===",
            recent.to_string(index=False),
        ]

        return "\n".join(parts)

    except Exception as e:
        return f"DATABASE_ERROR: {e}"


# ============================================================
# 8. GỌI GROQ AI API
# ============================================================
def ask_groq(user_question):
    if not GROQ_API_KEY or GROQ_API_KEY == "gsk_...":
        return "❌ Chưa cấu hình GROQ_API_KEY hợp lệ ở đầu file."

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        database_context = get_database_context()

        previous_messages = st.session_state.chat_history[-10:]
        history_text = ""
        for message in previous_messages:
            role = "Người dùng" if message["role"] == "user" else "AI"
            history_text += f"\n{role}: {message['content']}\n"

        system_instruction = (
            "Bạn là trợ lý AI cho hệ thống quản lý nhà hàng.\n"
            "QUY TẮC:\n"
            "1. Trả lời bằng tiếng Việt ngắn gọn, rõ ràng.\n"
            "2. Dựa vào DỮ LIỆU THỰC TẾ từ database MySQL để trả lời chính xác số liệu.\n"
            "3. Định dạng số tiền VNĐ rõ ràng (VD: 150.000 VNĐ).\n"
        )

        prompt = f"""
=== DỮ LIỆU THỰC TẾ TỪ AIVEN MYSQL ===
{database_context}

=== LỊCH SỬ HỘI THOẠI ===
{history_text}

=== CÂU HỎI HIỆN TẠI ===
{user_question}
"""

        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            model=GROQ_MODEL,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"❌ **Lỗi gọi Groq API:** `{e}`"


# ============================================================
# 9. SIDEBAR
# ============================================================
st.sidebar.title("🍽️ QUẢN LÝ NHÀ HÀNG")

page = st.sidebar.radio(
    "📋 Chọn trang hệ thống",
    [
        "🍽️ Order",
        "🔑 Admin",
        "🤖 Groq AI"
    ]
)

st.sidebar.markdown("---")

if db_connected:
    st.sidebar.success("🟢 MySQL: ĐÃ KẾT NỐI")
else:
    st.sidebar.error("🔴 MySQL: CHƯA KẾT NỐI")

st.sidebar.caption(f"Phiên bản code: {APP_VERSION}")


# ============================================================
# 10. TRANG ORDER
# ============================================================
if page == "🍽️ Order":

    st.title("🍽️ Hệ thống Order Nhà Hàng")
    st.caption("Ghi nhận order và lưu dữ liệu trực tiếp lên Aiven MySQL")

    if db_connected:
        st.success("🟢 Aiven MySQL: ĐÃ KẾT NỐI")
    else:
        st.error("🔴 Aiven MySQL: CHƯA KẾT NỐI")
        if db_error:
            st.code(db_error, language="text")

    st.markdown("---")

    col1, col2 = st.columns([1, 1.3])

    with col1:
        st.subheader("🍔 Chọn món")

        table_number = st.selectbox(
            "🪑 Chọn số bàn",
            [f"Bàn {i}" for i in range(1, 21)]
        )

        category = st.selectbox(
            "📂 Chọn loại",
            list(menu.keys())
        )

        item = st.selectbox(
            "🍽️ Chọn món",
            list(menu[category].keys())
        )

        price = menu[category][item]
        st.write(f"**Đơn giá:** {price:,.0f} VNĐ")

        quantity = st.number_input(
            "🔢 Số lượng",
            min_value=1,
            step=1,
            value=1
        )

        if st.button("➕ Thêm vào giỏ", use_container_width=True):
            if item in st.session_state.order_dict:
                st.session_state.order_dict[item]["Số lượng"] += quantity
                st.session_state.order_dict[item]["Thành tiền"] = (
                    st.session_state.order_dict[item]["Số lượng"] * price
                )
                st.session_state.order_dict[item]["Bàn"] = table_number
            else:
                st.session_state.order_dict[item] = {
                    "Bàn": table_number,
                    "Tên món": item,
                    "Đơn giá": price,
                    "Số lượng": quantity,
                    "Thành tiền": price * quantity,
                }

            st.rerun()

    with col2:
        st.subheader("🛒 Giỏ hàng hiện tại")

        if st.session_state.order_dict:
            df = pd.DataFrame.from_dict(
                st.session_state.order_dict,
                orient="index"
            )

            st.dataframe(
                df[["Bàn", "Tên món", "Đơn giá", "Số lượng", "Thành tiền"]],
                use_container_width=True,
                hide_index=True
            )

            tam_tinh = df["Thành tiền"].sum()
            giam_gia = tam_tinh * 0.05 if tam_tinh > 1_000_000 else 0
            tong_thanh_toan = tam_tinh - giam_gia

            st.write(f"**Tạm tính:** {tam_tinh:,.0f} VNĐ")
            if giam_gia > 0:
                st.write(f"**Giảm giá 5%:** -{giam_gia:,.0f} VNĐ")

            st.metric("💰 Tổng thanh toán", f"{tong_thanh_toan:,.0f} VNĐ")

            st.markdown("---")

            col_btn1, col_btn2 = st.columns(2)

            with col_btn1:
                if st.button("💳 Thanh toán", use_container_width=True):
                    if not db_connected:
                        st.error("Không thể thanh toán vì MySQL chưa kết nối.")
                    else:
                        now_time = datetime.now()
                        records = [
                            {
                                "created_at": now_time,
                                "table_name": row["Bàn"],
                                "item_name": row["Tên món"],
                                "quantity": int(row["Số lượng"]),
                                "total_price": float(row["Thành tiền"]),
                            }
                            for row in st.session_state.order_dict.values()
                        ]

                        try:
                            engine = get_db_engine()
                            df_to_save = pd.DataFrame(records)
                            df_to_save.to_sql(
                                "orders",
                                engine,
                                if_exists="append",
                                index=False
                            )

                            st.session_state.order_dict = {}
                            st.success("✅ Thanh toán thành công!")
                            st.rerun()

                        except Exception as e:
                            st.error(f"❌ Lỗi lưu dữ liệu: {e}")

            with col_btn2:
                if st.button("🗑️ Xóa toàn bộ giỏ", use_container_width=True):
                    st.session_state.order_dict = {}
                    st.rerun()
        else:
            st.info("🛒 Giỏ hàng đang trống. Hãy chọn món bên trái để lên đơn.")


# ============================================================
# 11. TRANG ADMIN
# ============================================================
elif page == "🔑 Admin":

    st.title("🔑 Trang Quản Trị & Phân Tích Doanh Thu")

    if not st.session_state.admin_logged_in:
        with st.form("admin_login_form"):
            password = st.text_input("🔐 Nhập mật khẩu quản trị", type="password")
            login_submitted = st.form_submit_button("🔑 Đăng nhập")

            if login_submitted:
                if password == ADMIN_PASSWORD:
                    st.session_state.admin_logged_in = True
                    st.rerun()
                else:
                    st.error("❌ Mật khẩu không chính xác!")

        st.warning("Vui lòng nhập mật khẩu quản trị.")
        st.stop()

    col_header_title, col_header_btn = st.columns([4, 1])

    with col_header_title:
        st.success("🟢 Xác thực quyền Quản trị viên thành công!")

    with col_header_btn:
        if st.button("🔒 Đăng xuất"):
            st.session_state.admin_logged_in = False
            st.rerun()

    tab1, tab2, tab3 = st.tabs(
        [
            "📋 Danh sách thực đơn",
            "💰 Doanh thu & Nhật ký giao dịch",
            "📊 Thống kê & Phân tích",
        ]
    )

    with tab1:
        st.subheader("🍽️ Menu hiện hành của nhà hàng")
        data = [
            [cat, item_name, p]
            for cat in menu
            for item_name, p in menu[cat].items()
        ]
        df_menu = pd.DataFrame(data, columns=["Phân loại", "Tên món", "Đơn giá (VNĐ)"])
        st.dataframe(df_menu, use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("💰 Doanh thu & Hóa đơn thực tế")
        df_history = load_history_from_db()

        if not df_history.empty:
            tong_doanh_thu = df_history["Thành tiền"].sum()
            tong_mon = df_history["Số lượng"].sum()

            col_met1, col_met2 = st.columns(2)
            with col_met1:
                st.metric("💰 Tổng doanh thu", f"{tong_doanh_thu:,.0f} VNĐ")
            with col_met2:
                st.metric("🍽️ Số lượng món đã phục vụ", f"{int(tong_mon)} phần")

            st.markdown("---")
            st.subheader("📅 Doanh thu theo ngày")

            df_history["Ngày"] = pd.to_datetime(df_history["Thời gian"]).dt.date
            df_daily = df_history.groupby("Ngày")["Thành tiền"].sum().reset_index()
            df_daily.columns = ["Ngày", "Doanh thu (VNĐ)"]

            col_chart_day, col_table_day = st.columns([1.5, 1])
            with col_chart_day:
                st.bar_chart(df_daily.set_index("Ngày")["Doanh thu (VNĐ)"])
            with col_table_day:
                st.dataframe(
                    df_daily.style.format({"Doanh thu (VNĐ)": "{:,.0f} VNĐ"}),
                    use_container_width=True,
                    hide_index=True
                )

            st.markdown("---")
            st.subheader("📋 Chi tiết lịch sử thanh toán thực tế")
            st.dataframe(
                df_history[["ID", "Thời gian", "Bàn", "Tên món", "Số lượng", "Thành tiền"]],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Hệ thống chưa ghi nhận giao dịch nào.")

    with tab3:
        st.subheader("📊 Thống kê & Phân tích bán hàng REAL-TIME")
        df_anal = load_history_from_db()

        if not df_anal.empty:
            df_anal["Thời gian"] = pd.to_datetime(df_anal["Thời gian"])
            df_anal["Giờ"] = df_anal["Thời gian"].dt.hour
            df_anal["Tháng-Năm"] = df_anal["Thời gian"].dt.strftime("%m/%Y")

            product_qty = df_anal.groupby("Tên món")["Số lượng"].sum()
            best_seller = product_qty.idxmax()
            best_seller_qty = int(product_qty.max())

            hourly_sales = df_anal.groupby("Giờ")["Số lượng"].sum()
            best_hour = int(hourly_sales.idxmax())
            best_hour_qty = int(hourly_sales.max())

            monthly_rev = df_anal.groupby("Tháng-Năm")["Thành tiền"].sum()
            best_month = monthly_rev.idxmax()
            best_month_rev = monthly_rev.max()

            col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
            with col_kpi1:
                st.info("🏆 MÓN BÁN CHẠY NHẤT")
                st.metric(label=best_seller, value=f"{best_seller_qty} phần")
            with col_kpi2:
                st.warning("⚡ KHUNG GIỜ BÁN NHIỀU NHẤT")
                st.metric(
                    label=f"{best_hour:02d}:00 - {(best_hour + 1) % 24:02d}:00",
                    value=f"{best_hour_qty} phần"
                )
            with col_kpi3:
                st.success("📅 THÁNG DOANH THU CAO NHẤT")
                st.metric(label=f"Tháng {best_month}", value=f"{best_month_rev:,.0f} VNĐ")

            st.markdown("---")
            st.subheader("🍔 Doanh thu & số lượng từng món")
            summary_mon = (
                df_anal.groupby("Tên món")
                .agg(Số_lượng_bán=("Số lượng", "sum"), Doanh_thu=("Thành tiền", "sum"))
                .reset_index()
                .sort_values(by="Số_lượng_bán", ascending=False)
            )

            col_chart1, col_table1 = st.columns([1.5, 1])
            with col_chart1:
                st.bar_chart(summary_mon.set_index("Tên món")["Số_lượng_bán"])
            with col_table1:
                st.dataframe(
                    summary_mon.style.format({"Doanh_thu": "{:,.0f} VNĐ"}),
                    use_container_width=True,
                    hide_index=True
                )
        else:
            st.info("Chưa có dữ liệu giao dịch để thống kê.")


# ============================================================
# 12. TRANG GROQ AI
# ============================================================
elif page == "🤖 Groq AI":

    st.title("🤖 Groq AI - Trợ lý dữ liệu nhà hàng")
    st.caption("Groq AI đọc dữ liệu từ Aiven MySQL và hỗ trợ trả lời phân tích siêu tốc.")

    col_status1, col_status2 = st.columns(2)
    with col_status1:
        if db_connected:
            st.success("🟢 Aiven MySQL: ĐÃ KẾT NỐI")
        else:
            st.error("🔴 Aiven MySQL: CHƯA KẾT NỐI")

    with col_status2:
        if GROQ_API_KEY and GROQ_API_KEY.startswith("gsk_"):
            st.success("🟢 Groq Key: ĐÃ CẤU HÌNH")
        else:
            st.error("🔴 Groq Key: CHƯA CẤU HÌNH (Cần Key gsk_...)")

    st.markdown("---")

    with st.expander("🛠️ Chẩn đoán kết nối Groq SDK"):
        st.write(f"Phiên bản code: **{APP_VERSION}**")
        masked_key = f"{GROQ_API_KEY[:6]}...{GROQ_API_KEY[-4:]}" if len(GROQ_API_KEY) > 10 else "Chưa điền"
        st.write(f"Key đang dùng: `{masked_key}`")
        st.write(f"Model cấu hình: `{GROQ_MODEL}`")

        if st.button("▶️ Chạy kiểm tra"):
            try:
                from groq import Groq
                test_client = Groq(api_key=GROQ_API_KEY)
                test_res = test_client.chat.completions.create(
                    messages=[{"role": "user", "content": "Xin chào"}],
                    model=GROQ_MODEL,
                )
                st.success("🟢 Kết nối thành công!")
                st.write(f"Phản hồi thử nghiệm: `{test_res.choices[0].message.content}`")
            except Exception as e:
                st.error(f"🔴 Lỗi chẩn đoán Groq SDK: {e}")

    st.markdown("---")

    if st.button("🗑️ Xóa lịch sử hội thoại"):
        st.session_state.chat_history = []
        st.rerun()

    st.markdown("---")

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_question = st.chat_input("Hỏi AI về dữ liệu nhà hàng...")

    if user_question:
        with st.chat_message("user"):
            st.markdown(user_question)

        with st.chat_message("assistant"):
            with st.spinner("🔎 Đang đọc dữ liệu MySQL và hỏi Groq AI..."):
                answer = ask_groq(user_question)
            st.markdown(answer)

        st.session_state.chat_history.append({"role": "user", "content": user_question})
        st.session_state.chat_history.append({"role": "assistant", "content": answer})
