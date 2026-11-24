# -*- coding: utf-8 -*-
"""
玄学知识库与话术灵感系统 V1
功能：录入干货 + 检索灵感
"""

import streamlit as st
from sqlalchemy import text, Column, Integer, String  # 用于建表时定义字段，自动适配不同数据库
from sqlalchemy.orm import declarative_base  # SQLAlchemy 声明式基类
from datetime import datetime  # 用于在 Python 里生成时间

Base = declarative_base()

# ============================================================
# 第 1 块：页面全局配置
# ============================================================
# layout="wide" 让页面在电脑上铺满整个宽度，看起来更舒服
st.set_page_config(
    page_title="玄学知识库",
    page_icon="🔮",
    layout="wide",   # 你明确要求开启的宽屏布局
)

# ============================================================
# 第 2 块：移动端适配 CSS
# ============================================================
# 这段 CSS 的作用：让按钮、输入框、文字在手机上变大，方便手指点击
st.markdown(
    """
    <style>
    /* 移动端（屏幕宽度小于 768px）时应用以下样式 */
    @media (max-width: 768px) {
        /* 整体字号放大，方便手机阅读 */
        .stApp {
            font-size: 16px;
        }

        /* 按钮变大变高，方便手指点击 */
        .stButton button {
            width: 100% !important;      /* 按钮占满整行 */
            height: 48px !important;     /* 高度 48px，接近手指最佳点击尺寸 */
            font-size: 17px !important;  /* 按钮文字变大 */
        }

        /* 文本输入框变高，字号变大 */
        .stTextInput input,
        .stTextArea textarea {
            font-size: 16px !important;
        }

        /* 多选框的文字变大 */
        .stMultiSelect label,
        .stMarkdown {
            font-size: 16px !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 第 3 块：连接数据库（本地 SQLite / 云端 PostgreSQL 自动切换）
# ============================================================
# 核心思路：
#   - 本地运行时，没有配置云端密钥 -> 自动用 SQLite（数据存在 xuanxue.db）
#   - 部署到 Streamlit Cloud 后，配置了 [connections.sql] 密钥 -> 自动用 PostgreSQL
#     这样数据就能永久保存在云端，不会因应用休眠或重部署而丢失。
#
# 判断依据：st.secrets 里有没有 "connections" 这个配置段。
# 注意：st.secrets 在本地没有 secrets.toml 文件时，直接访问会报错，
#       所以先用 try/except 包起来做安全判断。

def _has_cloud_db() -> bool:
    """判断当前是否处于「已配置云端数据库」的环境（即 Streamlit Cloud）。"""
    try:
        # 如果 secrets 里存在 connections 配置，说明已在云端配好了 PostgreSQL
        return "connections" in st.secrets
    except Exception:
        # 本地运行时，secrets 为空，返回 False -> 走 SQLite
        return False


if _has_cloud_db():
    # 云端：从 secrets 里读取 PostgreSQL 连接信息
    # 密钥格式（后面会在 Streamlit Cloud 的 Secrets 里配置）：
    #   [connections.sql]
    #   type = "sql"
    #   dialect = "postgresql"
    #   url = "postgresql://用户名:密码@主机:端口/数据库名"
    conn = st.connection("sql", type="sql", ttl=0)
else:
    # 本地：继续用 SQLite，你之前测试的方式完全不变
    conn = st.connection("sql", type="sql", url="sqlite:///xuanxue.db", ttl=0)


# ============================================================
# 第 4 块：初始化数据表
# ============================================================
# 用 SQLAlchemy 的声明式定义表结构，这样它会自动适配 SQLite 和 PostgreSQL
# 的语法差异（比如自增主键、字段类型等），一套代码两边通用。
class Knowledge(Base):
    __tablename__ = "knowledge"  # 表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 自增主键，两种数据库都支持
    content = Column(String, nullable=False)                    # 知识内容（必填）
    tags = Column(String)                                       # 标签，多个用逗号分隔
    created_at = Column(String)                                 # 创建时间，由 Python 生成


class Blessing(Base):
    __tablename__ = "blessings"  # 表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    content = Column(String, nullable=False)                    # 签文内容（必填）
    theme = Column(String, default="通用")                       # 主题：水逆/事业/感情/通用
    weight = Column(Integer, default=10)                        # 基础权重，越大越容易被抽中


def init_db():
    """第一次运行时创建 knowledge / blessings 表（已存在则跳过）。

    Base.metadata.create_all() 会自动判断表是否存在，不存在才创建，
    并且会根据连接的数据库类型生成对应的建表 SQL。
    """
    # conn.session 的 bind 就是当前连接的数据库引擎
    Base.metadata.create_all(conn.session.bind)
    # 初始化签库：如果 blessings 表为空，则预置一批好运签
    _seed_blessings()


def _seed_blessings():
    """给 blessings 表预置初始签文（仅在表为空时执行一次）。"""
    with conn.session as s:
        count = s.execute(text("SELECT COUNT(*) AS c FROM blessings")).first()
        if count.c > 0:
            return  # 已有数据，不重复插入

        # 预置签文：每条 = (内容, 主题, 基础权重)
        seeds = [
            ("水逆不是惩罚，是宇宙在提醒你放慢脚步，听听自己真正想要什么。", "水逆", 10),
            ("那些让你反复纠结的事，其实你心里早有答案，你只是需要一点勇气。", "水逆", 10),
            ("低潮是为了让你看清，谁是真的重要，什么才是真的想要。", "水逆", 10),
            ("别怕，所有的水逆都会过去，就像雨一定会停，天一定会亮。", "水逆", 10),
            ("事业上的瓶颈，是宇宙在告诉你：该换一条路了，而那条路更适合你。", "事业", 10),
            ("你现在的坚持，正在为将来的突破积蓄力量，别急着否定自己。", "事业", 10),
            ("机会总在不经意间出现，保持行动，好运才会找到你。", "事业", 10),
            ("感情里的等待不是白费，对的人值得你慢慢来。", "感情", 10),
            ("你会被温柔以待，也会遇到那个懂你所有言外之意的人。", "感情", 10),
            ("真诚永远是最强的磁场，你只管做自己，剩下的交给缘分。", "感情", 10),
            ("宇宙说：你值得被爱，也值得一切美好的东西。", "通用", 10),
            ("今天的好运正在派送中，请保持好心情查收。", "通用", 10),
            ("你已经做得很好了，允许自己偶尔慢一点。", "通用", 10),
            ("愿你今日所遇皆温柔，所行皆坦途。", "通用", 10),
            ("宇宙从不会辜负一个认真生活的人。", "通用", 10),
        ]
        for content, theme, weight in seeds:
            s.execute(
                text(
                    "INSERT INTO blessings (content, theme, weight) "
                    "VALUES (:content, :theme, :weight)"
                ),
                {"content": content, "theme": theme, "weight": weight},
            )
        s.commit()  # 提交，确保初始签文写入数据库


# 页面启动时调用一次，确保表存在
init_db()


# ============================================================
# 第 5 块：两个辅助函数（插入 / 查询）
# ============================================================
def insert_knowledge(content: str, tags: str):
    """插入一条干货记录，返回 None。"""
    with conn.session as s:
        s.execute(
            text(
                "INSERT INTO knowledge (content, tags, created_at) "
                "VALUES (:content, :tags, :created_at)"
            ),
            {
                "content": content,
                "tags": tags,
                # 时间由 Python 生成，格式统一，避免 SQLite/PostgreSQL 语法差异
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        s.commit()  # 提交事务，确保数据真正写入数据库文件


def get_total_count() -> int:
    """返回知识库总条数。"""
    with conn.session as s:
        row = s.execute(text("SELECT COUNT(*) AS total FROM knowledge")).first()
        return int(row.total)


def search_knowledge(keyword: str):
    """按关键词模糊查询，返回结果列表（每条是一个字典）。"""
    with conn.session as s:
        result = s.execute(
            text(
                "SELECT id, content, tags, created_at FROM knowledge "
                "WHERE content LIKE :kw ORDER BY id DESC"
            ),
            {"kw": f"%{keyword}%"},
        )
        # 把查询结果转成字典列表，方便后续逐条渲染
        return [dict(row._mapping) for row in result]


def get_all_knowledge():
    """返回知识库全部记录（最新的排在前面），用于「查看全部」页面。"""
    with conn.session as s:
        result = s.execute(
            text(
                "SELECT id, content, tags, created_at FROM knowledge "
                "ORDER BY id DESC"
            )
        )
        return [dict(row._mapping) for row in result]


def delete_knowledge(kid: int):
    """按 id 删除一条记录，返回 None。"""
    with conn.session as s:
        s.execute(
            text("DELETE FROM knowledge WHERE id = :kid"),
            {"kid": kid},
        )
        s.commit()  # 提交事务，确保删除真正生效


# ============================================================
# 第 5.5 块：每日一签 —— 加权抽签逻辑
# ============================================================
def draw_blessing(theme: str):
    """根据主题加权抽取一条签文，返回签文字典（含 content/theme）。

    加权思路（数据思维）：
      - 每条签本身有一个基础权重 weight（默认 10）
      - 如果签的主题 == 用户选择的主题，权重放大（这里 ×5）
      - 用 random.choices 按权重抽取，而不是 random.choice 纯随机
      这样「水逆」时，水逆主题的签被抽中的概率会明显更高，但又不绝对，
      保留了一点随机惊喜感。
    """
    import random  # 抽签需要用到随机，放在函数内引入

    # 读取全部签文
    with conn.session as s:
        result = s.execute(
            text("SELECT id, content, theme, weight FROM blessings")
        )
        rows = [dict(r._mapping) for r in result]

    if not rows:
        return None  # 签库为空

    # 计算每条签的「加权后权重」
    weighted_rows = []
    weights = []
    for r in rows:
        w = r["weight"] or 10  # 基础权重，空值兜底为 10
        if theme and r["theme"] == theme:
            w = w * 5  # 命中主题，权重放大 5 倍
        weighted_rows.append(r)
        weights.append(w)

    # 按权重随机抽取一条
    chosen = random.choices(weighted_rows, weights=weights, k=1)[0]
    return chosen


# ============================================================
# 第 6 块：页面标题
# ============================================================
st.title("🔮 玄学知识库与话术灵感系统")
st.caption("线下见客户时，随时检索干货、现场记录灵感")

# ============================================================
# 第 7 块：创建四个标签页（Tab）
# ============================================================
tab1, tab2, tab3, tab4 = st.tabs(["📝 录入干货", "🔍 检索灵感", "📚 查看全部", "🎴 每日一签"])

# ============================================================
# Tab 1：录入干货
# ============================================================
with tab1:
    st.subheader("录入一条新干货")

    # 文本输入框：粘贴知识内容，area 表示多行文本，方便粘贴长段话术
    content = st.text_area(
        "知识内容",
        placeholder="在这里粘贴你的干货、话术、案例……",
        height=200,
    )

    # 多选框：选择标签
    tags = st.multiselect(
        "选择标签",
        options=["#感情", "#事业", "#星盘", "#八字", "#破冰话术"],
    )

    # 保存按钮
    if st.button("💾 保存", type="primary"):
        # 校验：内容不能为空
        if not content.strip():
            st.error("内容不能为空，请先输入干货内容！")
        else:
            # 把多个标签合并成一个字符串，用逗号分隔
            tags_str = ", ".join(tags)
            insert_knowledge(content, tags_str)
            st.success("✅ 保存成功！")
            st.balloons()  # 保存成功放个气球动画，增加一点趣味

    # 显示当前知识库总条数，让用户知道存了多少
    total = get_total_count()
    st.info(f"📚 当前知识库共有 {total} 条记录")

# ============================================================
# Tab 2：检索灵感
# ============================================================
with tab2:
    st.subheader("检索灵感")

    # 搜索框：输入关键词
    keyword = st.text_input(
        "搜索关键词",
        placeholder="输入关键词，例如：破冰、复合、财运……",
    )

    if keyword:
        rows = search_knowledge(keyword)

        # 判断是否搜到结果
        if not rows:
            st.warning("😅 没有找到相关内容，换个关键词试试？")
        else:
            st.success(f"🔎 找到 {len(rows)} 条相关内容")

            # 用卡片形式逐条展示结果
            for row in rows:
                with st.container(border=True):
                    # 显示标签（如果有的话）
                    if row["tags"]:
                        st.markdown(f"**{row['tags']}**")
                    # 显示内容
                    st.markdown(row["content"])
                    # 底部小字显示创建时间
                    st.caption(f"🕐 {row['created_at']}")
    else:
        # 还没输入关键词时，给一个提示
        st.info("👆 在上方输入关键词开始搜索")

# ============================================================
# Tab 3：查看全部（浏览所有干货 + 删除）
# ============================================================
with tab3:
    st.subheader("查看全部干货")

    # 读取全部记录
    all_rows = get_all_knowledge()

    if not all_rows:
        st.info("📭 知识库还是空的，先去「录入干货」添加几条吧！")
    else:
        st.success(f"📚 共 {len(all_rows)} 条干货，最新在最上面")

        # 逐条展示，每条带一个删除按钮
        for row in all_rows:
            with st.container(border=True):
                # 用列布局：左边放内容，右边放删除按钮
                col_content, col_del = st.columns([6, 1])

                with col_content:
                    # 显示标签（如果有的话）
                    if row["tags"]:
                        st.markdown(f"**{row['tags']}**")
                    # 显示内容
                    st.markdown(row["content"])
                    # 底部小字显示编号 + 创建时间
                    st.caption(f"#{row['id']} · 🕐 {row['created_at']}")

                with col_del:
                    # 每个删除按钮用唯一的 key（用记录 id 区分），避免冲突
                    if st.button("🗑️ 删除", key=f"del_{row['id']}"):
                        # 用一个确认弹窗，防止误删
                        delete_knowledge(row["id"])
                        st.success(f"✅ 已删除 #{row['id']} 这条干货")
                        st.rerun()  # 删除后刷新页面，让列表立即更新

# ============================================================
# Tab 4：每日一签（盲盒翻牌 / 抽签社交神器）
# ============================================================
with tab4:
    st.subheader("🎴 每日一签 · 宇宙今日好运")

    # 特效 CSS：让签文卡片有一个「翻开/浮现」的动画，提升仪式感
    st.markdown(
        """
        <style>
        /* 签文卡片：渐变背景 + 阴影 + 圆角，营造抽签的仪式感 */
        .blessing-card {
            background: linear-gradient(135deg, #6a11cb 0%, #2575fc 100%);
            color: #ffffff;
            border-radius: 16px;
            padding: 32px 24px;
            text-align: center;
            font-size: 20px;
            line-height: 1.7;
            box-shadow: 0 8px 30px rgba(37, 117, 252, 0.35);
            margin: 16px 0;
            /* 翻牌动画：从半透明+上移，到清晰+归位 */
            animation: blessingIn 0.6s ease-out;
        }
        @keyframes blessingIn {
            0%   { opacity: 0; transform: translateY(20px) rotateX(25deg); }
            100% { opacity: 1; transform: translateY(0) rotateX(0); }
        }
        /* 签文主题小标签 */
        .blessing-theme {
            display: inline-block;
            background: rgba(255,255,255,0.25);
            border-radius: 999px;
            padding: 4px 14px;
            font-size: 13px;
            margin-bottom: 12px;
        }
        /* 移动端字号适配 */
        @media (max-width: 768px) {
            .blessing-card { font-size: 18px; padding: 24px 16px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 主题选择：可选「当前客户状态」，命中主题的签会高概率出现
    st.caption("先告诉宇宙，今天想给 TA 什么方向的好运 👇")
    theme = st.radio(
        "选择祝福主题",
        options=["通用", "水逆", "事业", "感情"],
        horizontal=True,
    )

    # 抽签按钮
    if st.button("✨ 抽一张宇宙给你的好运签", type="primary", use_container_width=True):
        blessing = draw_blessing(theme)

        if blessing is None:
            st.warning("签库还是空的，请联系管理员添加签文。")
        else:
            # 用自定义 HTML 卡片展示签文，配上翻牌动画特效
            st.markdown(
                f"""
                <div class="blessing-card">
                    <span class="blessing-theme">✨ {blessing['theme']} ✨</span>
                    <div>{blessing['content']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.balloons()  # 抽到签后放气球，情绪价值拉满

    # 未抽签时给一个引导文案
    st.caption("💡 客户咨询结束后，让 TA 抽一张签，作为今天的好心情收尾。")
