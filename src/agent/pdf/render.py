from __future__ import annotations

# 内存字节缓冲，用于构建 PDF 二进制内容
from io import BytesIO

# A4 纸尺寸常量
from reportlab.lib.pagesizes import A4

# PDF 绘图画布
from reportlab.pdfgen import canvas


# 在固定宽度内进行英文按词换行绘制，返回绘制后的 y 坐标
def _draw_wrapped_text(
    c: canvas.Canvas,
    text: str,
    x: int,
    y: int,
    max_width: int,
    line_height: int = 14,
) -> int:
    # 按空格拆词，逐词拼接
    words = text.split()
    # 当前行的词列表
    current = []
    # 当前绘制光标 y
    cursor_y = y
    # 逐词尝试加入当前行
    for word in words:
        # 假设把当前词放入当前行后的候选行文本
        candidate = " ".join(current + [word])
        # 若候选行宽度未超限，则继续累积
        if c.stringWidth(candidate, "Helvetica", 11) <= max_width:
            current.append(word)
            continue

        # 超宽时先绘制当前行
        c.drawString(x, cursor_y, " ".join(current))
        # 光标下移一行
        cursor_y -= line_height
        # 新行从当前词开始
        current = [word]

    # 循环结束后，别忘记绘制最后一行
    if current:
        c.drawString(x, cursor_y, " ".join(current))
        cursor_y -= line_height
    # 返回绘制结束后的 y 位置，便于后续继续排版
    return cursor_y


# 渲染问答报告 PDF，返回 PDF 字节流
def render_pdf(
    record_id: str,
    prompt: str,
    answer: str,
    user_id: str,
    session_id: str,
    locale: str,
) -> bytes:
    # 创建内存缓冲区，不落地文件系统
    buffer = BytesIO()
    # 创建 A4 画布
    c = canvas.Canvas(buffer, pagesize=A4)
    # 取页面宽高
    width, height = A4
    # 统一页边距
    margin = 50
    # 文本可用最大宽度
    max_width = int(width - (margin * 2))
    # 从页面顶部向下排版
    y = int(height - margin)

    # 绘制标题
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, y, "Agent Response Report")
    y -= 24

    # 绘制基础元信息
    c.setFont("Helvetica", 11)
    c.drawString(margin, y, f"Record ID: {record_id}")
    y -= 16
    c.drawString(margin, y, f"User ID: {user_id}")
    y -= 16
    c.drawString(margin, y, f"Session ID: {session_id}")
    y -= 16
    c.drawString(margin, y, f"Locale: {locale}")
    y -= 24

    # 绘制 Prompt 小节标题
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Prompt")
    y -= 16
    # 绘制 Prompt 正文（自动换行）
    c.setFont("Helvetica", 11)
    y = _draw_wrapped_text(c, prompt, margin, y, max_width)
    # 小节间距
    y -= 12

    # 绘制 Answer 小节标题
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Answer")
    y -= 16
    # 绘制 Answer 正文（自动换行）
    c.setFont("Helvetica", 11)
    _draw_wrapped_text(c, answer, margin, y, max_width)

    # 结束当前页面
    c.showPage()
    # 将画布内容写入缓冲区
    c.save()
    # 返回完整 PDF 字节
    return buffer.getvalue()
