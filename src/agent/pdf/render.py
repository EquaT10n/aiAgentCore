from __future__ import annotations

# 内存字节缓冲，用于构建 PDF 二进制内容
from io import BytesIO

# A4 纸张尺寸常量
from reportlab.lib.pagesizes import A4
# PDF 画布
from reportlab.pdfgen import canvas


# 在固定宽度内按词换行绘制英文文本，返回绘制后 y 坐标
def _draw_wrapped_text(
    c: canvas.Canvas,
    text: str,
    x: int,
    y: int,
    max_width: int,
    line_height: int = 14,
) -> int:
    # 按空格拆词
    words = text.split()
    # 当前行词列表
    current = []
    # 当前绘制游标位置
    cursor_y = y

    for word in words:
        # 先假设把当前词加到本行
        candidate = " ".join(current + [word])
        # 如果宽度没超限，继续累积
        if c.stringWidth(candidate, "Helvetica", 11) <= max_width:
            current.append(word)
            continue
        # 超宽时先画当前行，再换行
        c.drawString(x, cursor_y, " ".join(current))
        cursor_y -= line_height
        current = [word]

    # 循环结束后补画最后一行
    if current:
        c.drawString(x, cursor_y, " ".join(current))
        cursor_y -= line_height
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
    # 在内存里构建 PDF，不落地临时文件
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # 版式参数
    margin = 50
    max_width = int(width - (margin * 2))
    y = int(height - margin)

    # 标题
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, y, "Agent Response Report")
    y -= 24

    # 元信息
    c.setFont("Helvetica", 11)
    c.drawString(margin, y, f"Record ID: {record_id}")
    y -= 16
    c.drawString(margin, y, f"User ID: {user_id}")
    y -= 16
    c.drawString(margin, y, f"Session ID: {session_id}")
    y -= 16
    c.drawString(margin, y, f"Locale: {locale}")
    y -= 24

    # Prompt 小节
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Prompt")
    y -= 16
    c.setFont("Helvetica", 11)
    y = _draw_wrapped_text(c, prompt, margin, y, max_width)
    y -= 12

    # Answer 小节
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Answer")
    y -= 16
    c.setFont("Helvetica", 11)
    _draw_wrapped_text(c, answer, margin, y, max_width)

    # 完成 PDF 输出
    c.showPage()
    c.save()
    return buffer.getvalue()
