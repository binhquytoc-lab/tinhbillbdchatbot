import pandas as pd
import streamlit as st
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# ============================================================
# 1. CẤU HÌNH TRỰC TIẾP TRONG APP.PY
# ============================================================
# BẠN CHỈ CẦN SỬA CÁC GIÁ TRỊ TRONG KHỐI NÀY.
#
# Lưu ý: không đăng API key/password thật lên GitHub công khai.
# Google hỗ trợ truyền API key trực tiếp vào genai.Client(...),
# nhưng khuyến cáo giữ key bí mật.

GEMINI_API_KEY = "AQ.Ab8RN6ISf86scOBuWCfgpmNxJcLA4yuVvZ1_aXZg6ZkjfOfZ4Q" # SỬA API KEY

AIVEN_HOST = "mysql-3a5ef2bc-binhquytoc.a.aivencloud.com" # SỬA HOST
AIVEN_PORT = 14483 # SỬA PORT
AIVEN_USER = "avnadmin" # SỬA USER
AIVEN_PASSWORD = "AVNS_TX2oBXmTGGjXba6p7j1" # SỬA PASSWORD
AIVEN_DATABASE = "defaultdb"

ADMIN_PASSWORD = "123456"

# Model Gemini hiện dùng
GEMINI_MODEL = "gemini-2.5-flash"


# ============================================================
# 2. IMPORT GEMINI
# ============================================================
try:
    from google import genai
except ImportError:
    genai = None


# ============================================================
# 3. CẤU HÌNH STREAMLIT
# ============================================================
st.set_page_config(
    page_title="Order Nhà Hàng + Gemini AI",
    page_icon="🍽️",
    layout="wide"
)


# ============================================================
# 4. KẾT NỐI AIVEN MYSQL
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
        connect_args={"connect_timeout": 15},
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
# 5. MENU NHÀ HÀNG
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
# 6. SESSION STATE
# ============================================================
if "order_dict" not in st.session_state:
    st.session_state.order_dict = {}

if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


# ============================================================
# 7. ĐỌC LỊCH SỬ GIAO DỊCH
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

        df = pd.read_sql(sql, engine)

        if not df.empty:
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
# 8. TẠO DỮ LIỆU MYSQL CHO GEMINI
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
# 9. GEMINI CLIENT
# ============================================================
@st.cache_resource
def get_gemini_client(api_key):
    if not api_key or genai is None:
        return None
    return genai.Client(api_key=api_key)


def ask_gemini(user_question):
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("DAN_"):
        return (
            "❌ Bạn chưa nhập Gemini API key.\n\n"
            "Mở đầu file app.py và thay:\n"
            'GEMINI_API_KEY = "DAN_GEMINI_API_KEY_CUA_BAN_VAO_DAY"\n'
            "bằng API key thật của bạn."
        )

    if genai is None:
        return (
            "❌ Chưa cài google-genai.\n\n"
            "Thêm dòng sau vào requirements.txt:\n"
            "google-genai"
        )

    try:
        client = get_gemini_client(GEMINI_API_KEY)

        if client is None:
            return "❌ Không thể khởi tạo Gemini Client."

        database_context = get_database_context()

        previous_messages = st.session_state.chat_history[-12:]

        history_text = ""
        for message in previous_messages:
            role = "Người dùng" if message["role"] == "user" else "Gemini"
            history_text += (
                f"\n{role}: {message['content']}\n"
            )

        system_instruction = """
Bạn là trợ lý AI cho hệ thống quản lý nhà hàng.

QUY TẮC:
1. Trả lời bằng tiếng Việt.
2. Với câu hỏi về doanh thu, đơn hàng, món bán chạy,
   số lượng, bàn, ngày, giờ hoặc dữ liệu nhà hàng,
   phải ưu tiên dữ liệu DATABASE được cung cấp.
3. Không tự bịa số liệu.
4. Nếu database không đủ dữ liệu, nói:
   "Dữ liệu hiện tại chưa đủ để xác định."
5. Có thể tính toán từ dữ liệu database được cung cấp.
6. Tiền phải hiển thị dễ đọc theo VNĐ.
7. Phân biệt dữ liệu thực tế và nhận xét/gợi ý.
8. Không tiết lộ API key, mật khẩu MySQL,
   hostname, username hoặc thông tin bí mật.
9. Chỉ đọc dữ liệu. Không được xóa, sửa hoặc thêm dữ liệu MySQL.
10. Trả lời ngắn gọn, rõ ràng, dùng bảng/bullet khi phù hợp.
"""

        prompt = f"""
{system_instruction}

=== DỮ LIỆU THỰC TẾ TỪ AIVEN MYSQL ===
{database_context}

=== LỊCH SỬ HỘI THOẠI ===
{history_text}

=== CÂU HỎI HIỆN TẠI ===
{user_question}
"""

        # SDK Google GenAI hiện tại
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )

        answer = getattr(response, "text", None)

        if not answer:
            return "Gemini không trả về nội dung."

        return answer

    except Exception as e:
        return (
            "❌ Lỗi khi gọi Gemini API:\n\n"
            f"{e}\n\n"
            "Nếu lỗi liên quan model/API key, hãy kiểm tra "
            "GEMINI_API_KEY và GEMINI_MODEL ở đầu file."
        )


# ============================================================
# 10. SIDEBAR
# ============================================================
st.sidebar.title("🍽️ QUẢN LÝ NHÀ HÀNG")

page = st.sidebar.radio(
    "📋 Chọn trang hệ thống",
    [
        "🍽️ Order",
        "🔑 Admin",
        "🤖 Gemini AI"
    ]
)

st.sidebar.markdown("---")

if db_connected:
    st.sidebar.success("🟢 MySQL: ĐÃ KẾT NỐI")
else:
    st.sidebar.error("🔴 MySQL: CHƯA KẾT NỐI")


# ============================================================
# 11. TRANG ORDER
# ============================================================
if page == "🍽️ Order":

    st.title("🍽️ Hệ thống Order Nhà Hàng_Dr Bình")
    st.caption(
        "Ghi nhận order và lưu dữ liệu trực tiếp lên Aiven MySQL"
    )

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

        if st.button(
            "➕ Thêm vào giỏ",
            use_container_width=True
        ):
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

            st.success(f"Đã thêm {item} vào giỏ!")
            st.rerun()

    with col2:
        st.subheader("🛒 Giỏ hàng hiện tại")

        if st.session_state.order_dict:

            df = pd.DataFrame.from_dict(
                st.session_state.order_dict,
                orient="index"
            )

            st.dataframe(
                df[
                    [
                        "Bàn",
                        "Tên món",
                        "Đơn giá",
                        "Số lượng",
                        "Thành tiền"
                    ]
                ],
                use_container_width=True,
                hide_index=True
            )

            tam_tinh = df["Thành tiền"].sum()

            giam_gia = (
                tam_tinh * 0.05
                if tam_tinh > 1_000_000
                else 0
            )

            tong_thanh_toan = tam_tinh - giam_gia

            st.write(f"**Tạm tính:** {tam_tinh:,.0f} VNĐ")

            if giam_gia > 0:
                st.write(
                    f"**Giảm giá 5%:** -{giam_gia:,.0f} VNĐ"
                )

            st.metric(
                "💰 Tổng thanh toán",
                f"{tong_thanh_toan:,.0f} VNĐ"
            )

            st.markdown("---")

            col_btn1, col_btn2 = st.columns(2)

            with col_btn1:
                if st.button(
                    "💳 Thanh toán",
                    use_container_width=True
                ):

                    if not db_connected:
                        st.error(
                            "Không thể thanh toán vì Aiven MySQL chưa kết nối."
                        )
                    else:
                        now_time = datetime.now()

                        records = []

                        for row in st.session_state.order_dict.values():
                            records.append(
                                {
                                    "created_at": now_time,
                                    "table_name": row["Bàn"],
                                    "item_name": row["Tên món"],
                                    "quantity": row["Số lượng"],
                                    "total_price": row["Thành tiền"],
                                }
                            )

                        try:
                            engine = get_db_engine()

                            df_to_save = pd.DataFrame(records)

                            df_to_save.to_sql(
                                "orders",
                                engine,
                                if_exists="append",
                                index=False
                            )

                            st.success("✅ Thanh toán thành công!")
                            st.success(
                                "Dữ liệu đã được lưu vào Aiven MySQL."
                            )

                            st.session_state.order_dict = {}

                            st.rerun()

                        except Exception as e:
                            st.error(f"❌ Lỗi lưu dữ liệu: {e}")

            with col_btn2:
                if st.button(
                    "🗑️ Xóa toàn bộ giỏ",
                    use_container_width=True
                ):
                    st.session_state.order_dict = {}
                    st.rerun()

        else:
            st.info(
                "🛒 Giỏ hàng đang trống. "
                "Hãy chọn món bên trái để lên đơn."
            )


# ============================================================
# 12. TRANG ADMIN
# ============================================================
elif page == "🔑 Admin":

    st.title("🔑 Trang Quản Trị & Phân Tích Doanh Thu")

    if not st.session_state.admin_logged_in:

        with st.form("admin_login_form"):

            password = st.text_input(
                "🔐 Nhập mật khẩu quản trị",
                type="password"
            )

            login_submitted = st.form_submit_button(
                "🔑 Đăng nhập"
            )

            if login_submitted:

                if password == ADMIN_PASSWORD:
                    st.session_state.admin_logged_in = True
                    st.success("Đăng nhập thành công!")
                    st.rerun()
                else:
                    st.error("❌ Mật khẩu không chính xác!")

        st.warning("Vui lòng nhập mật khẩu quản trị.")
        st.stop()

    col_header_title, col_header_btn = st.columns([4, 1])

    with col_header_title:
        st.success(
            "🟢 Xác thực quyền Quản trị viên thành công!"
        )

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

    # --------------------------------------------------------
    # TAB 1: MENU
    # --------------------------------------------------------
    with tab1:

        st.subheader("🍽️ Menu hiện hành của nhà hàng")

        data = []

        for category_name in menu:
            for item_name, price in menu[category_name].items():
                data.append(
                    [
                        category_name,
                        item_name,
                        price
                    ]
                )

        df_menu = pd.DataFrame(
            data,
            columns=[
                "Phân loại",
                "Tên món",
                "Đơn giá (VNĐ)"
            ]
        )

        st.dataframe(
            df_menu,
            use_container_width=True,
            hide_index=True
        )

    # --------------------------------------------------------
    # TAB 2: DOANH THU
    # --------------------------------------------------------
    with tab2:

        st.subheader("💰 Doanh thu & Hóa đơn thực tế")

        df_history = load_history_from_db()

        if not df_history.empty:

            tong_doanh_thu = df_history["Thành tiền"].sum()
            tong_mon = df_history["Số lượng"].sum()

            col_met1, col_met2 = st.columns(2)

            with col_met1:
                st.metric(
                    "💰 Tổng doanh thu",
                    f"{tong_doanh_thu:,.0f} VNĐ"
                )

            with col_met2:
                st.metric(
                    "🍽️ Số lượng món đã phục vụ",
                    f"{tong_mon} phần"
                )

            st.markdown("---")

            st.subheader("📅 Doanh thu theo ngày")

            df_history["Ngày"] = pd.to_datetime(
                df_history["Thời gian"]
            ).dt.date

            df_daily_revenue = (
                df_history
                .groupby("Ngày")["Thành tiền"]
                .sum()
                .reset_index()
            )

            df_daily_revenue.columns = [
                "Ngày",
                "Doanh thu (VNĐ)"
            ]

            col_chart_day, col_table_day = st.columns(
                [1.5, 1]
            )

            with col_chart_day:
                st.bar_chart(
                    df_daily_revenue.set_index("Ngày")[
                        "Doanh thu (VNĐ)"
                    ]
                )

            with col_table_day:
                st.dataframe(
                    df_daily_revenue.style.format(
                        {
                            "Doanh thu (VNĐ)": "{:,.0f} VNĐ"
                        }
                    ),
                    use_container_width=True,
                    hide_index=True
                )

            st.markdown("---")

            st.subheader(
                "📋 Chi tiết lịch sử thanh toán thực tế"
            )

            st.dataframe(
                df_history[
                    [
                        "ID",
                        "Thời gian",
                        "Bàn",
                        "Tên món",
                        "Số lượng",
                        "Thành tiền"
                    ]
                ],
                use_container_width=True,
                hide_index=True
            )

        else:
            st.info("Hệ thống chưa ghi nhận giao dịch nào.")

    # --------------------------------------------------------
    # TAB 3: PHÂN TÍCH
    # --------------------------------------------------------
    with tab3:

        st.subheader(
            "📊 Thống kê & Phân tích bán hàng REAL-TIME"
        )

        df_anal = load_history_from_db()

        if not df_anal.empty:

            df_anal["Thời gian"] = pd.to_datetime(
                df_anal["Thời gian"]
            )

            df_anal["Giờ"] = df_anal["Thời gian"].dt.hour

            df_anal["Tháng-Năm"] = (
                df_anal["Thời gian"]
                .dt.strftime("%m/%Y")
            )

            product_quantity = (
                df_anal
                .groupby("Tên món")["Số lượng"]
                .sum()
            )

            best_seller = product_quantity.idxmax()
            best_seller_qty = product_quantity.max()

            hourly_sales = (
                df_anal
                .groupby("Giờ")["Số lượng"]
                .sum()
            )

            best_hour = hourly_sales.idxmax()
            best_hour_qty = hourly_sales.max()

            monthly_revenue = (
                df_anal
                .groupby("Tháng-Năm")["Thành tiền"]
                .sum()
            )

            best_month = monthly_revenue.idxmax()
            best_month_rev = monthly_revenue.max()

            col_kpi1, col_kpi2, col_kpi3 = st.columns(3)

            with col_kpi1:
                st.info("🏆 MÓN BÁN CHẠY NHẤT")
                st.metric(
                    label=best_seller,
                    value=f"{best_seller_qty} phần"
                )

            with col_kpi2:
                st.warning("⚡ KHUNG GIỜ BÁN NHIỀU NHẤT")
                st.metric(
                    label=(
                        f"{best_hour:02d}:00 - "
                        f"{(best_hour + 1) % 24:02d}:00"
                    ),
                    value=f"{best_hour_qty} phần"
                )

            with col_kpi3:
                st.success("📅 THÁNG DOANH THU CAO NHẤT")
                st.metric(
                    label=f"Tháng {best_month}",
                    value=f"{best_month_rev:,.0f} VNĐ"
                )

            st.markdown("---")

            st.subheader("🍔 Doanh thu & số lượng từng món")

            summary_mon = (
                df_anal
                .groupby("Tên món")
                .agg(
                    Số_lượng_bán=("Số lượng", "sum"),
                    Doanh_thu=("Thành tiền", "sum")
                )
                .reset_index()
                .sort_values(
                    by="Số_lượng_bán",
                    ascending=False
                )
            )

            col_chart1, col_table1 = st.columns([1.5, 1])

            with col_chart1:
                st.bar_chart(
                    summary_mon.set_index("Tên món")[
                        "Số_lượng_bán"
                    ]
                )

            with col_table1:
                st.dataframe(
                    summary_mon.style.format(
                        {"Doanh_thu": "{:,.0f} VNĐ"}
                    ),
                    use_container_width=True,
                    hide_index=True
                )

            st.markdown("---")

            st.subheader("⏰ Số lượng món bán theo giờ")

            summary_gio = (
                df_anal
                .groupby("Giờ")
                .agg(
                    Số_lượng_món=("Số lượng", "sum"),
                    Doanh_thu=("Thành tiền", "sum")
                )
                .reset_index()
            )

            all_hours = pd.DataFrame({"Giờ": range(24)})

            summary_gio = (
                pd.merge(
                    all_hours,
                    summary_gio,
                    on="Giờ",
                    how="left"
                )
                .fillna(0)
            )

            col_chart2, col_info2 = st.columns([1.5, 1])

            with col_chart2:
                st.bar_chart(
                    summary_gio.set_index("Giờ")[
                        "Số_lượng_món"
                    ]
                )

            with col_info2:
                st.write(
                    "**Khung giờ bán nhiều nhất:** "
                    f"{best_hour:02d}:00 - "
                    f"{(best_hour + 1) % 24:02d}:00"
                )

                st.write(
                    f"**Số lượng:** {best_hour_qty} phần"
                )

                st.dataframe(
                    summary_gio[
                        summary_gio["Số_lượng_món"] > 0
                    ].style.format(
                        {"Doanh_thu": "{:,.0f} VNĐ"}
                    ),
                    use_container_width=True,
                    hide_index=True
                )

            st.markdown("---")

            st.subheader("📅 Doanh thu bán hàng theo tháng")

            df_anal["Tháng_Số"] = (
                df_anal["Thời gian"].dt.month
            )

            summary_thang = (
                df_anal
                .groupby(
                    ["Tháng_Số", "Tháng-Năm"]
                )
                .agg(
                    Số_lượng_bán=("Số lượng", "sum"),
                    Doanh_thu=("Thành tiền", "sum")
                )
                .reset_index()
                .sort_values("Tháng_Số")
            )

            col_chart3, col_table3 = st.columns([1.5, 1])

            with col_chart3:
                st.bar_chart(
                    summary_thang.set_index("Tháng-Năm")[
                        "Doanh_thu"
                    ]
                )

            with col_table3:
                st.dataframe(
                    summary_thang[
                        [
                            "Tháng-Năm",
                            "Số_lượng_bán",
                            "Doanh_thu"
                        ]
                    ].style.format(
                        {"Doanh_thu": "{:,.0f} VNĐ"}
                    ),
                    use_container_width=True,
                    hide_index=True
                )

        else:
            st.info("Chưa có dữ liệu giao dịch để thống kê.")


# ============================================================
# 13. TRANG GEMINI AI
# ============================================================
elif page == "🤖 Gemini AI":

    st.title("🤖 Gemini AI - Trợ lý dữ liệu nhà hàng")

    st.caption(
        "Gemini đọc dữ liệu hiện tại từ Aiven MySQL "
        "và trả lời câu hỏi về đơn hàng, doanh thu và bán hàng."
    )

    col_status1, col_status2 = st.columns(2)

    with col_status1:
        if db_connected:
            st.success("🟢 Aiven MySQL: ĐÃ KẾT NỐI")
        else:
            st.error("🔴 Aiven MySQL: CHƯA KẾT NỐI")

    with col_status2:
        if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("DAN_"):
            st.success("🟢 Gemini API: ĐÃ CẤU HÌNH")
        else:
            st.error("🔴 Gemini API: CHƯA CẤU HÌNH")

    st.markdown("---")

    with st.expander("💡 Bạn có thể hỏi Gemini những gì?"):
        st.markdown("""
        - Tổng doanh thu hiện tại là bao nhiêu?
        - Có bao nhiêu giao dịch?
        - Món nào bán nhiều nhất?
        - Bàn nào có doanh thu cao nhất?
        - Khung giờ nào bán nhiều nhất?
        - Doanh thu 30 ngày gần nhất?
        - Có bao nhiêu món đã bán?
        - Hãy phân tích tình hình bán hàng.
        - So sánh doanh thu giữa các món.
        - Tóm tắt tình hình kinh doanh.
        """)

    if st.button(
        "🗑️ Xóa lịch sử hội thoại"
    ):
        st.session_state.chat_history = []
        st.rerun()

    st.markdown("---")

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_question = st.chat_input(
        "Hỏi Gemini về dữ liệu nhà hàng..."
    )

    if user_question:

        st.session_state.chat_history.append(
            {
                "role": "user",
                "content": user_question
            }
        )

        with st.chat_message("user"):
            st.markdown(user_question)

        with st.chat_message("assistant"):

            with st.spinner(
                "🔎 Đang đọc dữ liệu MySQL và hỏi Gemini..."
            ):
                answer = ask_gemini(user_question)

            st.markdown(answer)

        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": answer
            }
        )
