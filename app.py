# -*- coding: utf-8 -*-
"""
玄学知识库与话术灵感系统 V1
功能：录入干货 + 检索灵感
"""

import streamlit as st
from sqlalchemy import text, Column, Integer, String  # 用于建表时定义字段，自动适配不同数据库
from sqlalchemy.orm import declarative_base  # SQLAlchemy 声明式基类
from datetime import datetime  # 用于在 Python 里生成时间
import requests  # 用于调用 DeepSeek 大模型 API

Base = declarative_base()

# ============================================================
# DeepSeek 大模型配置（System Prompt + 调用函数）
# ============================================================
# DeepSeek 的 API 接口兼容 OpenAI 格式，所以可以直接用 requests 调用。
# 接口地址：https://api.deepseek.com/chat/completions
# 模型名：deepseek-chat（也可用 deepseek-reasoner，推理更强但更慢）

# 这段是「系统提示词」，告诉大模型它此刻的角色和任务
# 产品定位：辅助真人咨询师与客户互动，AI 提供「提示卡」，而不是让咨询师照念长文。
# 因此要求 AI 严格按三个维度输出，并带固定标记，方便前端拆分成三个标签页展示。
SYSTEM_PROMPT = (
    "你现在是一位资深的玄学咨询师助手。你的任务是：根据用户提供的玄学干货和客户的命盘信息，"
    "为正在与客户面对面交流的真人咨询师，准备一张「现场提示卡」。"
    "注意：你输出的是给咨询师参考的要点，不是让咨询师逐字照念的演讲稿，务必精炼、可快速扫读。\n\n"
    "请严格按以下三个部分输出，每部分用指定的标记开头，格式如下：\n"
    "【核心断语】\n（一句话总结核心结论，可直接说给客户听，不超过30字）\n"
    "【互动提问】\n（给出2个能引导客户多说、增加互动感的问题，每个问题一行，用数字编号）\n"
    "【专业解释】\n（一段专业的玄学理论解释，带一点专业术语，体现权威性，用于客户追问原因时回答，100字左右）\n\n"
    "要求：\n"
    "1. 三个标记【核心断语】【互动提问】【专业解释】必须原样出现，不要改动或省略；\n"
    "2. 不要照搬原文，要融会贯通、有温度；\n"
    "3. 如果提供了客户的排盘信息（日主、格局、喜用神、当前大运等），务必结合这些盘面特征来组织内容。"
)


def generate_xuanxue_text(selected_notes: list, customer: str = None, pan_info: dict = None) -> str:
    """调用 DeepSeek 大模型，把选中的干货消化成一段专业话术。

    参数：
      selected_notes: 话术篮里的干货内容列表（字符串列表）
      customer:       当前客户称呼（可选，用于让回复更贴合客户）
      pan_info:       客户排盘核心信息字典（可选），如 {"日主":..., "格局":..., "喜用神":..., "当前大运":...}，
                      会作为命盘上下文一起发给 AI，让话术带上盘面特征

    返回：
      大模型生成的话术字符串；失败时抛出异常，由调用方处理。
    """
    # 1) 从 st.secrets 里安全读取 API Key（本地放 .streamlit/secrets.toml，云端放 Secrets）
    api_key = st.secrets.get("deepseek", {}).get("api_key", "")
    if not api_key:
        raise ValueError("未配置 DeepSeek API Key，请先在 secrets 里添加 deepseek.api_key")

    # 2) 把选中的干货内容拼成 Context（上下文）
    notes_text = "\n\n".join(
        f"{i}. {note}" for i, note in enumerate(selected_notes, 1)
    )

    # 3) 组装发送给大模型的 messages
    user_content = f"以下是我为客户准备的玄学干货素材：\n\n{notes_text}"
    if customer:
        user_content += f"\n\n当前客户：{customer}"

    # 3.5) 如果提供了排盘信息，拼进上下文，让 AI 的话术带上命盘特征
    if pan_info:
        # 只保留有内容的字段，避免空字段干扰 AI
        filled = {k: v for k, v in pan_info.items() if v and str(v).strip()}
        if filled:
            pan_lines = "\n".join(f"  - {k}：{v}" for k, v in filled.items())
            user_content += (
                f"\n\n该客户的排盘核心信息如下：\n{pan_lines}\n"
                f"请结合这些盘面特征来组织话术，让回复更贴合客户的命盘。"
            )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # 4) 调用 DeepSeek API
    resp = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": 0.8,   # 温度略高，让话术更有温度、不那么死板
            "max_tokens": 600,    # 200字左右，留足余量
        },
        timeout=60,  # 超时 60 秒，避免长时间卡住
    )

    # 5) 检查 HTTP 状态
    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek API 返回错误：{resp.status_code} - {resp.text}")

    # 6) 解析返回结果
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def parse_generated_result(text: str) -> dict:
    """把 AI 返回的文本按【核心断语】【互动提问】【专业解释】三个标记拆成字典。

    返回：{"核心断语": ..., "互动提问": ..., "专业解释": ...}
    如果某个标记缺失，对应值为空字符串；如果整个都解析失败，返回 None。
    """
    if not text:
        return None

    # 三个标记及其顺序
    markers = ["【核心断语】", "【互动提问】", "【专业解释】"]

    # 找到每个标记在文本中的位置
    positions = []
    for m in markers:
        idx = text.find(m)
        positions.append(idx)

    # 如果三个标记都没找到（AI 没按格式输出），返回 None 让调用方降级处理
    if all(p == -1 for p in positions):
        return None

    # 按位置切分文本
    result = {}
    for i, m in enumerate(markers):
        start = positions[i]
        if start == -1:
            result[m.strip("【】")] = ""
            continue
        # 内容从标记之后开始
        content_start = start + len(m)
        # 找到下一个出现的标记作为结束位置
        end = len(text)
        for j in range(i + 1, len(markers)):
            if positions[j] > start:
                end = positions[j]
                break
        result[m.strip("【】")] = text[content_start:end].strip()

    return result


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


class TagLibrary(Base):
    __tablename__ = "tags_library"  # 标签库表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    tag = Column(String, nullable=False, unique=True)           # 标签名（唯一，不重复）


class Customer(Base):
    __tablename__ = "customers"  # 客户表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    name = Column(String, nullable=False, unique=True)          # 客户姓名/称呼（唯一）
    birth_info = Column(String)                                 # 出生信息（生日/时辰，可选，为定盘预留）
    note = Column(String)                                       # 备注（可选）
    created_at = Column(String)                                 # 创建时间，由 Python 生成


class DrawRecord(Base):
    __tablename__ = "draw_records"  # 抽签记录表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    customer = Column(String)                                   # 客户称呼（关联 customers.name，可为空表示未选客户）
    draw_date = Column(String)                                  # 抽签日期（YYYY-MM-DD，用于「每日限抽一次」判断）
    theme = Column(String)                                      # 抽签时选的主题
    content = Column(String)                                    # 抽中的签文内容
    created_at = Column(String)                                 # 完整时间戳（含时分秒）


def init_db():
    """第一次运行时创建 knowledge / blessings / tags_library / customers / draw_records 表（已存在则跳过）。

    Base.metadata.create_all() 会自动判断表是否存在，不存在才创建，
    并且会根据连接的数据库类型生成对应的建表 SQL。
    """
    # conn.session 的 bind 就是当前连接的数据库引擎
    Base.metadata.create_all(conn.session.bind)
    # 初始化签库：如果 blessings 表为空，则预置一批好运签
    _seed_blessings()
    # 初始化标签库：如果 tags_library 表为空，则预置默认标签
    _seed_tags()


# 默认标签列表（首次启动时写入标签库，之后会随用户自定义不断扩充）
DEFAULT_TAGS = [
    "#阴阳", "#五行", "#天干", "#地支", "#六十甲子", "#十神", "#八字", "#星盘",
    "#感情", "#事业财运", "#健康", "#破冰话术", "#情绪安抚", "#每日一签",
]


def _seed_tags():
    """给 tags_library 表预置默认标签（仅在表为空时执行一次）。"""
    with conn.session as s:
        count = s.execute(text("SELECT COUNT(*) AS c FROM tags_library")).first()
        if count.c > 0:
            return  # 已有数据，不重复插入

        for tag in DEFAULT_TAGS:
            s.execute(
                text("INSERT INTO tags_library (tag) VALUES (:tag)"),
                {"tag": tag},
            )
        s.commit()


def get_all_tags():
    """读取标签库里的所有标签，返回标签名列表（供录入页面的多选框使用）。"""
    with conn.session as s:
        result = s.execute(text("SELECT tag FROM tags_library ORDER BY id"))
        return [row.tag for row in result]


def add_tags_to_library(tags_list):
    """把一批标签写入标签库（已存在的自动跳过），实现标签库动态扩充。

    tags_list: 标签字符串列表，例如 ['#感情', '#十二长生']
    """
    if not tags_list:
        return
    with conn.session as s:
        for tag in tags_list:
            tag = tag.strip()
            if not tag:
                continue
            # 先检查是否已存在，避免重复插入
            exists = s.execute(
                text("SELECT 1 FROM tags_library WHERE tag = :tag"),
                {"tag": tag},
            ).first()
            if not exists:
                s.execute(
                    text("INSERT INTO tags_library (tag) VALUES (:tag)"),
                    {"tag": tag},
                )
        s.commit()


def get_all_customers():
    """读取所有客户，返回列表（每条含 id/name/birth_info/note）。"""
    with conn.session as s:
        result = s.execute(
            text("SELECT id, name, birth_info, note FROM customers ORDER BY id DESC")
        )
        return [dict(row._mapping) for row in result]


def add_customer(name: str, birth_info: str = "", note: str = ""):
    """新建一个客户（姓名唯一，重复则忽略），返回是否成功。"""
    name = name.strip()
    if not name:
        return False
    with conn.session as s:
        # 检查是否已存在同名客户
        exists = s.execute(
            text("SELECT 1 FROM customers WHERE name = :name"),
            {"name": name},
        ).first()
        if exists:
            return False  # 已存在，不重复创建
        s.execute(
            text(
                "INSERT INTO customers (name, birth_info, note, created_at) "
                "VALUES (:name, :birth_info, :note, :created_at)"
            ),
            {
                "name": name,
                "birth_info": birth_info.strip(),
                "note": note.strip(),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        s.commit()
        return True


def _seed_blessings():
    """给 blessings 表预置初始签文。

    逻辑：表为空时插入全部种子；表已有数据时，只「增量补齐」缺失主题的签文
    （这样主题从 4 个扩充到 8 个后，老数据库也能自动补上新主题的签）。
    """
    # 预置签文：每条 = (内容, 主题, 基础权重)，覆盖 8 个主题
    seeds = [
        # 通用
        ("宇宙说：你值得被爱，也值得一切美好的东西。", "通用", 10),
        ("今天的好运正在派送中，请保持好心情查收。", "通用", 10),
        ("你已经做得很好了，允许自己偶尔慢一点。", "通用", 10),
        ("愿你今日所遇皆温柔，所行皆坦途。", "通用", 10),
        ("宇宙从不会辜负一个认真生活的人。", "通用", 10),
        # 水逆
        ("水逆不是惩罚，是宇宙在提醒你放慢脚步，听听自己真正想要什么。", "水逆", 10),
        ("那些让你反复纠结的事，其实你心里早有答案，你只是需要一点勇气。", "水逆", 10),
        ("低潮是为了让你看清，谁是真的重要，什么才是真的想要。", "水逆", 10),
        ("别怕，所有的水逆都会过去，就像雨一定会停，天一定会亮。", "水逆", 10),
        # 事业
        ("事业上的瓶颈，是宇宙在告诉你：该换一条路了，而那条路更适合你。", "事业", 10),
        ("你现在的坚持，正在为将来的突破积蓄力量，别急着否定自己。", "事业", 10),
        ("机会总在不经意间出现，保持行动，好运才会找到你。", "事业", 10),
        # 感情
        ("感情里的等待不是白费，对的人值得你慢慢来。", "感情", 10),
        ("你会被温柔以待，也会遇到那个懂你所有言外之意的人。", "感情", 10),
        ("真诚永远是最强的磁场，你只管做自己，剩下的交给缘分。", "感情", 10),
        # 财运
        ("财运正顺着你的努力悄悄靠近，稳住节奏，惊喜就在路上。", "财运", 10),
        ("你过去的付出正在结出果实，该你的，一分都不会少。", "财运", 10),
        ("舍得之间自有平衡，今天适合给未来的自己种下一颗财富的种子。", "财运", 10),
        # 健康
        ("身体是最诚实的伙伴，累了就歇一歇，它会陪你走更远的路。", "健康", 10),
        ("照顾好自己的身心，就是给未来最好的投资。", "健康", 10),
        ("愿你吃得香、睡得稳，元气满满地迎接每一天。", "健康", 10),
        # 学业
        ("你的努力不会被辜负，再坚持一下，柳暗花明就在前方。", "学业", 10),
        ("学习路上每一步都算数，今天的积累是明天的底气。", "学业", 10),
        ("别和别人的节奏比较，你有自己的时区，稳步向前就好。", "学业", 10),
        # 人际
        ("真诚的人总会被真诚对待，你种下的善意都会回到你身边。", "人际", 10),
        ("不必讨好所有人，做真实的自己，自然会吸引对的人。", "人际", 10),
        ("有些关系值得用心经营，有些则要学会体面告别，你心里清楚。", "人际", 10),
    ]

    with conn.session as s:
        count = s.execute(text("SELECT COUNT(*) AS c FROM blessings")).first()
        if count.c == 0:
            # 表为空：直接全量插入
            for content, theme, weight in seeds:
                s.execute(
                    text(
                        "INSERT INTO blessings (content, theme, weight) "
                        "VALUES (:content, :theme, :weight)"
                    ),
                    {"content": content, "theme": theme, "weight": weight},
                )
        else:
            # 表已有数据：只补齐「缺失主题」的签文，避免重复
            existing_themes = set(
                r.theme for r in s.execute(text("SELECT DISTINCT theme FROM blessings"))
            )
            for content, theme, weight in seeds:
                if theme not in existing_themes:
                    s.execute(
                        text(
                            "INSERT INTO blessings (content, theme, weight) "
                            "VALUES (:content, :theme, :weight)"
                        ),
                        {"content": content, "theme": theme, "weight": weight},
                    )
                    existing_themes.add(theme)  # 加入集合，避免同主题重复插入
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


def has_drawn_today(customer: str, today: str) -> bool:
    """判断某个客户「今天」是否已经抽过签。

    参数：
      customer: 客户称呼（可能为 None/空，表示未选客户）
      today:    当天日期字符串，格式 YYYY-MM-DD

    返回：True 表示今天已抽过，False 表示还没抽。
    """
    with conn.session as s:
        result = s.execute(
            text(
                "SELECT id FROM draw_records "
                "WHERE customer = :c AND draw_date = :d LIMIT 1"
            ),
            {"c": customer or "", "d": today},
        )
        return result.first() is not None


def save_draw_record(customer: str, today: str, theme: str, content: str):
    """把一次抽签记录写入 draw_records 表。

    参数：
      customer: 客户称呼
      today:    当天日期（YYYY-MM-DD）
      theme:    抽签时选的主题
      content:  抽中的签文
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn.session as s:
        s.execute(
            text(
                "INSERT INTO draw_records (customer, draw_date, theme, content, created_at) "
                "VALUES (:c, :d, :t, :ct, :ts)"
            ),
            {"c": customer or "", "d": today, "t": theme, "ct": content, "ts": now},
        )
        s.commit()


def _get_today_blessing(customer: str, today: str):
    """从 draw_records 读回某个客户「今天」抽到的签文（用于刷新后继续展示）。

    返回：{"theme": ..., "content": ...} 字典；没查到返回 None。
    """
    with conn.session as s:
        result = s.execute(
            text(
                "SELECT theme, content FROM draw_records "
                "WHERE customer = :c AND draw_date = :d "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"c": customer or "", "d": today},
        )
        row = result.first()
        if row is None:
            return None
        return {"theme": row.theme, "content": row.content}


# ============================================================
# 第 6 块：页面标题
# ============================================================
st.title("🔮 玄学知识库与话术灵感系统")
st.caption("线下见客户时，随时检索干货、现场记录灵感")

# ============================================================
# 第 6.2 块：模式切换（工作咨询 / 后台整理）
# ============================================================
# 作用：见客户时用「工作咨询」模式，界面清爽专业（只显示检索 + 每日一签）；
#       自己整理资料时切「后台整理」模式，显示全部功能（录入/检索/查看/抽签）。
app_mode = st.radio(
    "当前模式",
    ["🔮 工作咨询", "📚 后台整理"],
    horizontal=True,  # 横向排列，更像一个开关
)

# 判断当前是否处于「后台整理」模式（决定是否显示录入/查看等后台功能）
is_admin_mode = (app_mode == "📚 后台整理")

# ============================================================
# 第 6.5 块：当前咨询客户（选择 / 新建）
# ============================================================
# 作用：把「当前正在服务的客户」记下来，后续检索、AI 生成都能关联到他/她，
#       让整个系统从「备忘录」变成「咨询工作台」。

# 用 session_state 记住「当前选中的客户」，跨标签页、跨交互都能保持
if "current_customer" not in st.session_state:
    st.session_state.current_customer = None  # 初始为空，表示还没选客户

# 读取所有已有客户
customers = get_all_customers()
customer_names = [c["name"] for c in customers]

# 关键：如果用户在「选择已有客户」下拉框里切换了，同步更新当前客户
# （selectbox 的切换结果需要在 expander 里读取后才能判断，因此把「切换」的逻辑
#   放在 expander 内部处理，这里只负责初始化一个 selected 变量）

# ============================================================
# 顶部：醒目展示当前正在服务的客户（在 expander 外部）
# ============================================================
if st.session_state.current_customer:
    # 有客户时，用绿色 success 框醒目展示，一眼可见
    st.success(f"👤 当前客户：**{st.session_state.current_customer}**")

# ============================================================
# 折叠面板：切换或新建客户（选中后自动折叠，不占屏幕）
# ============================================================
# expanded 参数：没选客户时自动展开，方便首次选择；选好后自动折叠
with st.expander("切换或新建咨询客户", expanded=(st.session_state.current_customer is None)):
    # 读取已有客户（expander 内重新读一次，保证下拉框数据最新）
    customers = get_all_customers()
    customer_names = [c["name"] for c in customers]

    # 用两列布局：左=选择已有客户，右=新建客户
    col_select, col_new = st.columns([1, 1])

    with col_select:
        # 下拉框：选择已有客户
        if customer_names:
            # 计算当前选中客户在列表中的位置
            if st.session_state.current_customer in customer_names:
                cur_idx = customer_names.index(st.session_state.current_customer)
            else:
                cur_idx = 0
            selected = st.selectbox(
                "选择已有客户",
                options=customer_names,
                index=cur_idx,
                placeholder="请选择客户……",
                key="customer_select",
            )
        else:
            selected = None
            st.info("还没有客户，先在右侧新建一个吧")

    with col_new:
        # 输入框：新建客户（姓名 + 结构化选择的出生信息）
        new_name = st.text_input(
            "新建客户（姓名/称呼）",
            placeholder="例如：王女士、李总……",
            key="new_customer_name",
        )

        # 出生信息改为「下拉选择」，更规范、不容易填错格式
        # 用四列排布：年 / 月 / 日 / 时辰
        c_year, c_month, c_day, c_hour = st.columns([1.2, 1, 1, 1])
        with c_year:
            birth_year = st.selectbox(
                "出生年",
                options=list(range(1940, 2011)),  # 1940~2010
                index=None,
                placeholder="年份",
                key="birth_year",
            )
        with c_month:
            birth_month = st.selectbox(
                "月",
                options=list(range(1, 13)),  # 1~12
                index=None,
                placeholder="月",
                key="birth_month",
            )
        with c_day:
            birth_day = st.selectbox(
                "日",
                options=list(range(1, 32)),  # 1~31
                index=None,
                placeholder="日",
                key="birth_day",
            )
        with c_hour:
            # 十二时辰（子时=23:00~01:00，以此类推）
            birth_hour = st.selectbox(
                "时辰",
                options=["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"],
                index=None,
                placeholder="时辰",
                key="birth_hour",
            )

        # 组装出生信息字符串：只有完整填了年月日才拼接，时辰可选
        new_birth = ""
        if birth_year and birth_month and birth_day:
            new_birth = f"{birth_year}年{birth_month}月{birth_day}日"
            if birth_hour:
                new_birth += f" {birth_hour}时"

        if st.button("➕ 新建客户", key="btn_new_customer"):
            if not new_name.strip():
                st.error("请先填写客户姓名/称呼")
            else:
                ok = add_customer(new_name, new_birth)
                if ok:
                    st.session_state.current_customer = new_name.strip()
                    st.success(f"✅ 已新建客户「{new_name.strip()}」并设为当前客户")
                    st.rerun()
                else:
                    st.warning("⚠️ 该客户已存在，请在左侧下拉框选择")

    # 关键：如果用户在「选择已有客户」里切换了，同步更新当前客户
    if selected is not None and selected != st.session_state.current_customer:
        st.session_state.current_customer = selected
        st.rerun()

# ============================================================
# 第 7 块：创建标签页（Tab）——根据模式动态显示
# ============================================================
# 后台整理模式：显示全部 4 个 Tab（录入 / 检索 / 查看 / 抽签）
# 工作咨询模式：只显示「检索灵感」「每日一签」2 个 Tab（更清爽专业）
if is_admin_mode:
    tab_input, tab_search, tab_all, tab_sign = st.tabs(
        ["📝 录入干货", "🔍 检索灵感", "📚 查看全部", "🎴 每日一签"]
    )
else:
    tab_search, tab_sign = st.tabs(["🔍 检索灵感", "🎴 每日一签"])
    tab_input = tab_all = None  # 工作模式下这两个 tab 不存在，设为 None

# ============================================================
# Tab 1：录入干货（仅后台整理模式显示）
# ============================================================
if is_admin_mode:
    with tab_input:
        st.subheader("录入一条新干货")

        # 文本输入框：粘贴知识内容，area 表示多行文本，方便粘贴长段话术
        content = st.text_area(
            "知识内容",
            placeholder="在这里粘贴你的干货、话术、案例……",
            height=200,
        )

        # 多选框：选择标签
        # options 从「标签库」动态读取（这样用户自定义的新标签也会出现在这里）
        tag_options = get_all_tags()

        # 用两列布局：左=选择标签（占大头），右=自定义标签小按钮
        col_tags, col_custom = st.columns([5, 1], vertical_alignment="bottom")

        with col_tags:
            tags = st.multiselect(
                "选择标签",
                options=tag_options,
                placeholder="请选择分类标签（可多选）",  # 手机端友好提示，避免视觉拥挤
            )

        with col_custom:
            # 小按钮：点击后展开一个输入框，让用户输入新标签
            if st.button("➕ 标签", key="btn_show_custom_tag", use_container_width=True):
                # 切换「是否显示自定义标签输入框」的状态
                st.session_state.show_custom_tag = not st.session_state.get("show_custom_tag", False)

        # 自定义标签输入框：只有点击了「➕ 标签」按钮才显示，平时折叠起来不占空间
        custom_tag = ""
        if st.session_state.get("show_custom_tag", False):
            custom_tag = st.text_input(
                "自定义标签",
                placeholder="输入新标签，例如：十二长生",
                key="custom_tag_input",
            )

        # 保存按钮
        if st.button("💾 保存", type="primary"):
            # 校验：内容不能为空
            if not content.strip():
                st.error("内容不能为空，请先输入干货内容！")
            else:
                # 合并「已选标签」+「自定义标签」
                # 自定义标签自动补上 # 号（如果用户没写）
                all_tags = list(tags)  # 先复制已选的标签
                if custom_tag and custom_tag.strip():
                    new_tag = custom_tag.strip()
                    # 统一补上 # 前缀，保持标签格式一致
                    if not new_tag.startswith("#"):
                        new_tag = "#" + new_tag
                    all_tags.append(new_tag)

                # 去重，保持顺序
                seen = set()
                unique_tags = []
                for t in all_tags:
                    if t not in seen:
                        seen.add(t)
                        unique_tags.append(t)

                # 把标签合并成一个字符串，用逗号分隔
                tags_str = ", ".join(unique_tags)

                # 1) 写入知识库
                insert_knowledge(content, tags_str)
                # 2) 把（可能新增的）标签同步进标签库，供下次下拉框使用
                add_tags_to_library(unique_tags)

                # 保存成功后，收起自定义标签输入框（回到折叠状态）
                st.session_state.show_custom_tag = False

                st.success("✅ 保存成功！")
                st.balloons()  # 保存成功放个气球动画，增加一点趣味

        # 显示当前知识库总条数，让用户知道存了多少
        total = get_total_count()
        st.info(f"📚 当前知识库共有 {total} 条记录")

# ============================================================
# Tab 2：检索灵感（两种模式都显示）
# ============================================================
with tab_search:
    st.subheader("检索灵感")

    # 初始化「话术篮」会话状态（跨标签页、跨交互保持）
    if "basket" not in st.session_state:
        st.session_state.basket = {}  # 用字典存 {id: 内容}，方便去重

    # ============================================================
    # 排盘模块（仅工作咨询模式显示）
    # ============================================================
    # 作用：朋友看盘的流程是「先打开排盘软件看盘面 → 记下核心信息 → 再输出话术」。
    #       这里提供：① 一键跳转排盘软件；② 录入排盘核心信息（存 session_state）。
    if not is_admin_mode:
        # 用一个容器做一个漂亮的排盘模块
        with st.container(border=True):
            st.markdown("### 🔮 排盘辅助")

            # ① 一键跳转排盘软件（问真八字）
            # 用 HTML <a target="_blank"> 实现「新标签页打开」，手机端点击更可靠，
            # 避免 st.link_button 在当前页跳转被部分手机浏览器拦截导致"没反应"
            st.markdown(
                """
                <a href="https://pcbz.iwzwh.com/#/home/index" target="_blank" rel="noopener noreferrer"
                   style="display:inline-block;width:100%;padding:10px 0;text-align:center;
                          background:#6a11cb;color:#ffffff;border-radius:8px;text-decoration:none;
                          font-size:16px;font-weight:600;">
                   🔮 跳转排盘软件
                </a>
                """,
                unsafe_allow_html=True,
            )

            # ② 录入客户排盘核心信息（折叠面板，存 session_state）
            with st.expander("📝 录入客户排盘核心信息"):
                st.caption("看盘后随手记下核心信息，AI 生成话术时会自动带上这些盘面特征。")

                # 初始化排盘信息的 session_state（用一个字典存 4 个字段）
                if "pan_info" not in st.session_state:
                    st.session_state.pan_info = {
                        "日主": "",
                        "格局": "",
                        "喜用神": "",
                        "当前大运": "",
                    }

                # 四个文本输入框：日主 / 格局 / 喜用神 / 当前大运
                # 用两列布局，紧凑一点，适合手机
                col1, col2 = st.columns(2)
                with col1:
                    st.session_state.pan_info["日主"] = st.text_input(
                        "日主", value=st.session_state.pan_info["日主"], key="pan_rizhu"
                    )
                    st.session_state.pan_info["喜用神"] = st.text_input(
                        "喜用神", value=st.session_state.pan_info["喜用神"], key="pan_xiyong"
                    )
                with col2:
                    st.session_state.pan_info["格局"] = st.text_input(
                        "格局", value=st.session_state.pan_info["格局"], key="pan_geju"
                    )
                    st.session_state.pan_info["当前大运"] = st.text_input(
                        "当前大运", value=st.session_state.pan_info["当前大运"], key="pan_dayun"
                    )

                # 一键清空排盘信息
                if st.button("🗑️ 清空排盘信息", key="btn_clear_pan"):
                    st.session_state.pan_info = {
                        "日主": "",
                        "格局": "",
                        "喜用神": "",
                        "当前大运": "",
                    }
                    st.rerun()

        st.divider()  # 排盘模块和搜索区之间的分隔线

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

            # 用卡片形式逐条展示结果，每条带一个「加入话术篮」勾选框
            for row in rows:
                with st.container(border=True):
                    # 用列布局：左边 checkbox + 内容，右边标签/时间
                    col_check, col_body = st.columns([0.5, 9.5])

                    with col_check:
                        # 勾选框：加入话术篮
                        # 根据当前 id 是否已在篮中，决定默认勾选状态
                        checked = row["id"] in st.session_state.basket
                        add_flag = st.checkbox(
                            "加入话术篮",
                            value=checked,
                            key=f"basket_{row['id']}",
                            label_visibility="collapsed",  # 隐藏文字，只留勾选框
                        )

                    with col_body:
                        # 显示标签（如果有的话）
                        if row["tags"]:
                            st.markdown(f"**{row['tags']}**")
                        # 显示内容
                        st.markdown(row["content"])
                        # 底部小字显示创建时间
                        st.caption(f"🕐 {row['created_at']}")

                    # 根据勾选状态，更新话术篮
                    if add_flag:
                        st.session_state.basket[row["id"]] = row["content"]
                    else:
                        st.session_state.basket.pop(row["id"], None)

    else:
        # 还没输入关键词时，给一个提示
        st.info("👆 在上方输入关键词开始搜索")

    # ===== 话术篮汇总区（放在搜索区下方，始终可见） =====
    st.divider()  # 分隔线，把话术篮和搜索区分开

    basket_count = len(st.session_state.basket)
    st.markdown(f"### 🧺 话术篮（已选 {basket_count} 条）")

    if basket_count == 0:
        st.caption("还没选话术。去上面搜索，勾选想要的话术加入篮子。")
    else:
        # 展示篮子里选中的话术（作为 AI 的 Context 素材）
        for kid, kcontent in st.session_state.basket.items():
            with st.container(border=True):
                st.markdown(kcontent)

        customer = st.session_state.get("current_customer", None)

        # ===== 生成按钮区 =====
        # 「生成提示卡」和「重新生成」本质上都是调同一个函数，
        # 用两个按钮来触发（生成=首次，重新生成=再次）
        col_gen, col_regen, col_clear = st.columns([1.4, 1.2, 1])

        with col_gen:
            do_generate = st.button(
                "✨ 生成提示卡", key="btn_generate", type="primary", use_container_width=True
            )
        with col_regen:
            do_regen = st.button(
                "🔄 重新生成", key="btn_regen", use_container_width=True
            )
        with col_clear:
            if st.button("🗑️ 清空话术篮", key="btn_clear_basket", use_container_width=True):
                st.session_state.basket = {}
                st.session_state.pop("generated_text", None)  # 清空已生成结果
                st.rerun()

        # ===== 触发生成 =====
        if do_generate or do_regen:
            # 把话术篮里的内容按顺序转成列表，作为 Context
            selected_notes = list(st.session_state.basket.values())

            # 读取排盘信息（如果在工作咨询模式录入过，会作为上下文一起发给 AI）
            pan_info = st.session_state.get("pan_info", None)

            with st.spinner("🔮 正在消化干货，生成专业话术……"):
                try:
                    result = generate_xuanxue_text(selected_notes, customer, pan_info)
                    st.session_state.generated_text = result  # 存入会话状态，方便重新生成/复制
                except ValueError as e:
                    # API Key 未配置
                    st.error(str(e))
                    st.info(
                        "配置方法：在 `.streamlit/secrets.toml`（本地）或 Streamlit Cloud 的 "
                        "Secrets（云端）里添加：\n\n"
                        "```toml\n[deepseek]\napi_key = \"你的DeepSeek密钥\"\n```"
                    )
                except Exception as e:
                    # 其他错误（网络、API 异常等）
                    st.error(f"生成失败：{e}")

        # ===== 展示生成结果 =====
        if "generated_text" in st.session_state and st.session_state.generated_text:
            st.markdown("#### 💬 咨询提示卡")

            # 尝试把 AI 返回文本按三个维度拆分
            parsed = parse_generated_result(st.session_state.generated_text)

            if parsed:
                # 解析成功：用三个标签页分别展示
                tab_duanyu, tab_tiwen, tab_jieshi = st.tabs(
                    ["💡 核心断语", "🗣️ 互动提问", "📖 专业解释"]
                )

                with tab_duanyu:
                    if parsed["核心断语"]:
                        st.markdown(parsed["核心断语"])
                    else:
                        st.caption("（AI 未返回这部分内容）")

                with tab_tiwen:
                    if parsed["互动提问"]:
                        st.markdown(parsed["互动提问"])
                    else:
                        st.caption("（AI 未返回这部分内容）")

                with tab_jieshi:
                    if parsed["专业解释"]:
                        st.markdown(parsed["专业解释"])
                    else:
                        st.caption("（AI 未返回这部分内容）")
            else:
                # 解析失败（AI 没按格式输出）：降级为直接展示原文
                with st.container(border=True):
                    st.markdown(st.session_state.generated_text)

            # 复制结果按钮：用 HTML+JS 实现真正的一键复制到剪贴板
            import html as _html  # 用于转义 HTML 特殊字符

            # 把生成结果转义后嵌入 JS，避免引号/换行破坏代码
            result_escaped = _html.escape(st.session_state.generated_text)
            copy_html = f"""
            <button onclick="
                navigator.clipboard.writeText({result_escaped!r}).then(
                    () => {{
                        const b = document.getElementById('copy-btn-{id(st.session_state.generated_text)}');
                        b.innerText = '✅ 已复制';
                        setTimeout(() => b.innerText = '📋 复制这段结果', 2000);
                    }}
                );
            " id="copy-btn-{id(st.session_state.generated_text)}"
            style="width:100%;padding:8px 16px;border:1px solid #ccc;border-radius:8px;background:#fff;cursor:pointer;font-size:15px;">
            📋 复制这段结果
            </button>
            """
            st.components.v1.html(copy_html, height=50)

# ============================================================
# Tab 3：查看全部（仅后台整理模式显示）
# ============================================================
if is_admin_mode:
    with tab_all:
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
# Tab 4：每日一签（两种模式都显示）
# ============================================================
with tab_sign:
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

    # 主题选择：8 个主题，命中主题的签会高概率出现
    st.caption("先告诉宇宙，今天想给 TA 什么方向的好运 👇")
    theme = st.radio(
        "选择祝福主题",
        options=["通用", "水逆", "事业", "感情", "财运", "健康", "学业", "人际"],
        horizontal=True,
    )

    # ============================================================
    # 每日限抽一次逻辑（含跨天重置 + 防误触两段式 + 签文持久展示）
    # ============================================================
    # 1) 拿到当天日期（YYYY-MM-DD），用于「跨天自动重置」
    today = datetime.now().strftime("%Y-%m-%d")

    # 2) 当前客户（可能为空，表示还没选客户）
    current_customer = st.session_state.get("current_customer", None)

    # 3) 初始化「已抽签」状态（用「客户 + 日期」作为 key，跨天自动失效）
    draw_state_key = f"drawn_{current_customer or 'none'}_{today}"
    if draw_state_key not in st.session_state:
        # 先查数据库，看这个客户今天是否已经抽过（保证刷新后状态不丢）
        st.session_state[draw_state_key] = has_drawn_today(current_customer, today)

    already_drawn = st.session_state[draw_state_key]

    # 4) 初始化「抽到的签文」状态（用于已抽后继续展示签文，不因刷新而消失）
    #    同样带日期，跨天后自动清空
    blessing_state_key = f"blessing_{current_customer or 'none'}_{today}"
    if blessing_state_key not in st.session_state:
        # 若今天已抽过，从数据库把签文读回来展示；否则为空
        if already_drawn:
            st.session_state[blessing_state_key] = _get_today_blessing(current_customer, today)
        else:
            st.session_state[blessing_state_key] = None

    # ============================================================
    # 已抽签状态：展示签文 + 禁用提示
    # ============================================================
    if already_drawn:
        # 已抽过：展示签文（如果读到的话）
        saved_blessing = st.session_state.get(blessing_state_key)
        if saved_blessing:
            st.markdown(
                f"""
                <div class="blessing-card">
                    <span class="blessing-theme">✨ {saved_blessing['theme']} ✨</span>
                    <div>{saved_blessing['content']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.info("🔒 今日已抽签，明天再来吧！好运会继续等你的。")

    # ============================================================
    # 未抽签状态：两段式防误触
    #   第一段「✨ 抽签」→ 展开确认区 → 第二段「🎲 确认抽签」→ 真正抽签
    # ============================================================
    else:
        # 第一段：抽签入口按钮
        if "confirm_draw" not in st.session_state:
            st.session_state.confirm_draw = False

        if not st.session_state.confirm_draw:
            # 还没进入确认态：显示「抽签」按钮
            if st.button("✨ 抽一张好运签", type="primary", use_container_width=True):
                st.session_state.confirm_draw = True
                st.rerun()  # 刷新，展开确认区
        else:
            # 已进入确认态：显示「确认抽签」+「取消」
            st.warning("确认要给 TA 抽今天的签吗？抽完今天就不能再抽了哦。")
            col_confirm, col_cancel = st.columns([1, 1])
            with col_confirm:
                if st.button("🎲 确认抽签", type="primary", use_container_width=True):
                    blessing = draw_blessing(theme)
                    if blessing is None:
                        st.warning("签库还是空的，请联系管理员添加签文。")
                    else:
                        # 写入数据库 + 更新状态
                        save_draw_record(current_customer, today, blessing["theme"], blessing["content"])
                        st.session_state[draw_state_key] = True
                        st.session_state[blessing_state_key] = {
                            "theme": blessing["theme"],
                            "content": blessing["content"],
                        }
                        st.session_state.confirm_draw = False  # 复位确认态
                        st.balloons()  # 抽到签后放气球
                        st.rerun()  # 刷新，进入「已抽」状态展示签文
            with col_cancel:
                if st.button("取消", use_container_width=True):
                    st.session_state.confirm_draw = False
                    st.rerun()  # 刷新，收起确认区

        # 引导文案
        st.caption("💡 客户咨询结束后，让 TA 抽一张签，作为今天的好心情收尾。")
