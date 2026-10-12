import asyncio
import logging
import os
import sqlite3
import pandas as pd
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Для професійних PDF-звітів
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = "8946568480:AAHMU2cn3_6zBXZvfCTNQHv07yjjqGFAQ58"

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

DB_NAME = "university_bot.db"
scheduler = AsyncIOScheduler()

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                lesson_id TEXT PRIMARY KEY,
                name TEXT,
                day_of_week TEXT,
                time TEXT,
                link TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT UNIQUE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                lesson_name TEXT,
                student_name TEXT,
                timestamp TEXT
            )
        """)
        conn.commit()

init_db()

class AddLessonState(StatesGroup):
    waiting_for_id = State()
    waiting_for_name = State()
    waiting_for_day = State()
    waiting_for_time = State()
    waiting_for_link = State()

class AddStudentsState(StatesGroup):
    waiting_for_list = State()

def get_control_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📚 Дисципліни", callback_data="btn_lessons"),
                InlineKeyboardButton(text="➕ Додати дисципліну", callback_data="btn_add_lesson")
            ],
            [
                InlineKeyboardButton(text="👥 Студенти групи", callback_data="btn_students"),
                InlineKeyboardButton(text="➕ Додати студентів", callback_data="btn_add_students")
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="btn_stats"),
                InlineKeyboardButton(text="📄 PDF Звіт", callback_data="btn_pdf"),
                InlineKeyboardButton(text="📊 Excel Звіт", callback_data="btn_excel")
            ]
        ]
    )

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🎛 **Мега-панель університетського бота**\n\n"
        "Бот успішно запущено у хмарі! Керуйте розкладом, студентами та формуйте офіційні звіти у пару кліків.",
        reply_markup=get_control_panel_keyboard(),
        parse_mode="Markdown"
    )

@router.message(F.text == "🎛 Меню")
async def cmd_panel(message: Message):
    await message.answer("🎛 **Головна панель керування:**", reply_markup=get_control_panel_keyboard())

@router.callback_query(F.data.startswith("btn_"))
async def process_control_panel(callback: CallbackQuery, state: FSMContext):
    action = callback.data
    await callback.answer()

    if action == "btn_lessons":
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT lesson_id, name, day_of_week, time, link FROM schedule")
            lessons = cursor.fetchall()

        if not lessons:
            await callback.message.answer("⚠️ У розкладі ще немає дисциплін.")
            return
        
        text = "📌 **Розклад дисциплін:**\n\n"
        inline_kb = []
        for lid, name, day, time_slot, link in lessons:
            text += f"🔹 **ID {lid}:** {name}\n📅 День: `{day}` | ⏰ Час: `{time_slot}`\n🔗 `{link}`\n\n"
        
        inline_kb.append([InlineKeyboardButton(text="🔙 Головне меню", callback_data="btn_menu")])
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_kb), parse_mode="Markdown")

    elif action == "btn_add_lesson":
        await callback.message.answer("Введіть порядковий номер дисципліни (наприклад: `1`):")
        await state.set_state(AddLessonState.waiting_for_id)

    elif action == "btn_students":
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT date || lesson_name) FROM attendance")
            total_lessons_held = cursor.fetchone()[0]
            cursor.execute("SELECT full_name FROM students")
            students = cursor.fetchall()

        if not students:
            await callback.message.answer("⚠️ У базі ще немає студентів.")
            return

        text = f"👥 **Статистика групи (Загалом занять: {total_lessons_held}):**\n\n"
        for idx, (st_name,) in enumerate(students, 1):
            with sqlite3.connect(DB_NAME) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(DISTINCT date || lesson_name) FROM attendance WHERE student_name = ?", (st_name,))
                attended = cur.fetchone()[0]
            missed = max(0, total_lessons_held - attended)
            text += f"{idx}. **{st_name}** | 🟢 Був: *{attended}* | 🔴 Прогулів: *{missed}*\n   👉 `/student_{st_name}`\n\n"
        
        await callback.message.answer(text, parse_mode="Markdown")

    elif action == "btn_add_students":
        await callback.message.answer("📝 Надішліть список студентів (кожен з нового рядка):")
        await state.set_state(AddStudentsState.waiting_for_list)

    elif action == "btn_stats":
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT lesson_name, COUNT(DISTINCT date || student_name) FROM attendance GROUP BY lesson_name")
            data = cursor.fetchall()

        if not data:
            await callback.message.answer("📊 Статистика порожня.")
            return
        
        text = "📊 **Зведена аналітика по дисциплінах:**\n\n"
        for lesson, count in data:
            text += f"📖 **{lesson}**: загальних відвідувань зафіксовано — {count}\n"
        await callback.message.answer(text, parse_mode="Markdown")

    elif action == "btn_pdf":
        pdf_path = generate_pdf_report()
        if pdf_path and os.path.exists(pdf_path):
            await callback.message.answer_document(FSInputFile(pdf_path), caption="📄 Офіційний звіт у форматі PDF!")
        else:
            await callback.message.answer("⚠️ Немає даних для звіту.")

    elif action == "btn_excel":
        excel_path = generate_excel_report()
        if excel_path and os.path.exists(excel_path):
            await callback.message.answer_document(FSInputFile(excel_path), caption="📊 Місячний журнал у форматі Excel!")
        else:
            await callback.message.answer("⚠️ Немає даних для Excel журналу.")

    elif action == "btn_menu":
        await callback.message.answer("🎛 **Головне меню:**", reply_markup=get_control_panel_keyboard())

@router.message(AddLessonState.waiting_for_id)
async def process_lesson_id(message: Message, state: FSMContext):
    await state.update_data(lesson_id=message.text.strip())
    await message.answer("Введіть назву дисципліни (наприклад: `теорія управління`):")
    await state.set_state(AddLessonState.waiting_for_name)

@router.message(AddLessonState.waiting_for_name)
async def process_lesson_name(message: Message, state: FSMContext):
    await state.update_data(lesson_name=message.text.strip())
    await message.answer("Введіть день тижня (наприклад: `Понеділок`):")
    await state.set_state(AddLessonState.waiting_for_day)

@router.message(AddLessonState.waiting_for_day)
async def process_lesson_day(message: Message, state: FSMContext):
    await state.update_data(day_of_week=message.text.strip())
    await message.answer("Введіть час початку пари у форматі HH:MM (наприклад: `11:40`):")
    await state.set_state(AddLessonState.waiting_for_time)

@router.message(AddLessonState.waiting_for_time)
async def process_lesson_time(message: Message, state: FSMContext):
    await state.update_data(lesson_time=message.text.strip())
    await message.answer("Надішліть посилання на Google Meet для цієї дисципліни:")
    await state.set_state(AddLessonState.waiting_for_link)

@router.message(AddLessonState.waiting_for_link)
async def process_lesson_link(message: Message, state: FSMContext):
    data = await state.get_data()
    lesson_id = data['lesson_id']
    name = data['lesson_name']
    day = data['day_of_week']
    time_slot = data['lesson_time']
    link = message.text.strip()

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO schedule (lesson_id, name, day_of_week, time, link) VALUES (?, ?, ?, ?, ?)",
                       (lesson_id, name, day, time_slot, link))
        conn.commit()

    await state.clear()
    await message.answer(f"✅ Дисципліну «{name}» ({day} о {time_slot}) успішно збережено!", reply_markup=get_control_panel_keyboard())

@router.message(AddStudentsState.waiting_for_list)
async def process_students_list(message: Message, state: FSMContext):
    lines = message.text.strip().split("\n")
    added_count = 0
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        for line in lines:
            name = line.strip()
            if name:
                try:
                    cursor.execute("INSERT OR IGNORE INTO students (full_name) VALUES (?)", (name,))
                    added_count += 1
                except Exception:
                    pass
        conn.commit()
    
    await state.clear()
    await message.answer(f"✅ Додано студентів до бази: {added_count}", reply_markup=get_control_panel_keyboard())

@router.message(F.text.regexp(r"^/student_(.+)"))
async def student_profile(message: Message):
    raw_text = message.text.replace("/student_", "").split("@")[0].strip()
    
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT date || lesson_name) FROM attendance")
        total_lessons_held = cursor.fetchone()[0]
        cursor.execute("SELECT lesson_name, date, timestamp FROM attendance WHERE student_name = ?", (raw_text,))
        records = cursor.fetchall()

    attended = len(set(r[0] for r in records))
    missed = max(0, total_lessons_held - attended)

    text = f"👤 **Персональний профіль: {raw_text}**\n\n"
    text += f"📊 Всього занять у журналі: **{total_lessons_held}**\n"
    text += f"🟢 Відвідав: **{attended}**\n"
    text += f"🔴 Прогулів: **{missed}**\n\n"

    if not records:
        text += "❌ Занять у системі поки не зафіксовано.\n"
    else:
        text += "🕒 **Історія фіксацій:**\n"
        for lesson, date, time in records:
            text += f"• `{lesson}` ({date} о {time})\n"

    await message.answer(text, parse_mode="Markdown")

def generate_pdf_report():
    pdf_path = "university_attendance_report.pdf"
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, spaceAfter=15, alignment=1, textColor=colors.HexColor("#1A365D"))
    subtitle_style = ParagraphStyle('SubtitleStyle', parent=styles['Normal'], fontSize=10, spaceAfter=20, alignment=1, textColor=colors.HexColor("#4A5568"))

    elements.append(Paragraph("ОФІЦІЙНИЙ ЖУРНАЛ ВІДВІДУВАННЯ", title_style))
    elements.append(Paragraph(f"Дата формування: {datetime.now().strftime('%Y-%m-%d %H:%M')}", subtitle_style))
    elements.append(Spacer(1, 10))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT date, lesson_name, student_name, timestamp FROM attendance ORDER BY date, lesson_name")
        rows = cursor.fetchall()

    if not rows:
        return None

    table_data = [["Дата", "Дисципліна", "ПІБ Студента", "Час"]]
    for date, lesson, student, time in rows:
        table_data.append([date, lesson, student, time])

    t = Table(table_data, colWidths=[80, 160, 210, 70])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
    ]))

    elements.append(t)
    doc.build(elements)
    return pdf_path

def generate_excel_report():
    excel_path = "university_monthly_journal.xlsx"
    with sqlite3.connect(DB_NAME) as conn:
        df = pd.read_sql("SELECT date AS 'Дата', lesson_name AS 'Дисципліна', student_name AS 'ПІБ Студента', timestamp AS 'Час фіксації' FROM attendance", conn)
    
    if df.empty:
        return None

    df.to_excel(excel_path, index=False)
    return excel_path

async def main():
    scheduler.start()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
