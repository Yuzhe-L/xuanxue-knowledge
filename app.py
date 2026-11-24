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


def init_db():
    """第一次运行时创建 knowledge 表（已存在则跳过）。

    Base.metadata.create_all() 会自动判断表是否存在，不存在才创建，
    并且会根据连接的数据库类型生成对应的建表 SQL。
    """
    # conn.session 的 bind 就是当前连接的数据库引擎
    Base.metadata.create_all(conn.session.bind)


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
                "SELECT content, tags, created_at FROM knowledge "
                "WHERE content LIKE :kw ORDER BY id DESC"
            ),
            {"kw": f"%{keyword}%"},
        )
        # 把查询结果转成字典列表，方便后续逐条渲染
        return [dict(row._mapping) for row in result]


# ============================================================
# 第 6 块：页面标题
# ============================================================
st.title("🔮 玄学知识库与话术灵感系统")
st.caption("线下见客户时，随时检索干货、现场记录灵感")

# ============================================================
# 第 7 块：创建两个标签页（Tab）
# ============================================================
tab1, tab2 = st.tabs(["📝 录入干货", "🔍 检索灵感"])

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
