from fpdf import FPDF
from io import BytesIO
import barcode
from barcode.writer import ImageWriter
from datetime import date

class InvoicePDF(FPDF):
    def header(self):
        self.set_fill_color(0, 0, 0)
        self.rect(0, 0, self.w, 4, "F")
        
    def footer(self):
        self.set_y(-15)
        self.set_draw_color(0, 0, 0)
        self.set_text_color(0, 0, 0)
        self.set_line_width(0.3)
        self.line(20, self.get_y(), self.w - 20, self.get_y())
        self.ln(3)
        self.set_font("Helvetica", "", 7)
        today_str = date.today().strftime("%d %b %Y")
        self.cell(0, 4, "eDining Management System  -  Generated on " + today_str + "  -  Page " + str(self.page_no()) + " of {nb}", align="C", ln=True)

def generate_bill_pdf(student, summary, cycle_info, hall_name, deposits_data, daily_meals, rates):
    pdf = InvoicePDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.add_page()
    
    mg = 20 
    pdf.set_margins(mg, 15, mg)
    pdf.set_auto_page_break(auto=True, margin=20)
    pw = pdf.w - 2 * mg

    c_black = (0, 0, 0)
    c_grey_bg = (245, 245, 245)
    
    pdf.set_text_color(*c_black)
    pdf.set_draw_color(*c_black)

    # Header
    pdf.set_y(15)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(120, 8, hall_name, ln=False)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, "INVOICE / STATEMENT", ln=True, align="R")
    
    y_sub = pdf.get_y()
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(120, 5, "Monthly Dining Billing", ln=False)

    # Barcode
    barcode_data = student["username"] + "-" + str(int(summary.get("cycle_balance", 0)))
    try:
        code128 = barcode.get("code128", barcode_data, writer=ImageWriter())
        bar_bytes = BytesIO()
        code128.write(bar_bytes, {
            "module_width": 0.25,
            "module_height": 8,
            "quiet_zone": 1,
            "write_text": False,
            "background": "white",
            "foreground": "black"
        })
        bar_bytes.seek(0)
        pdf.image(bar_bytes, x=mg + pw - 45, y=y_sub, w=45, h=10)
    except Exception:
        pass

    pdf.set_y(y_sub + 14)
    pdf.set_line_width(0.5)
    pdf.line(mg, pdf.get_y(), mg + pw, pdf.get_y())
    pdf.ln(6)

    # Info section
    y_info = pdf.get_y()
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(100, 4, "BILL TO:", ln=True)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(100, 6, student["name"], ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(100, 5, "Username/ID: " + student["username"], ln=True)
    pdf.cell(100, 5, "Room: " + student["room_number"], ln=True)

    pdf.set_xy(mg + 100, y_info)
    today_str = date.today().strftime("%d %b %Y")
    ref = "INV-" + student["username"] + "-" + cycle_info["month"][:3].upper()
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, "Date: " + today_str, ln=True, align="R")
    pdf.set_x(mg + 100)
    pdf.cell(0, 5, "Billing Cycle: " + cycle_info["month"], ln=True, align="R")
    pdf.set_x(mg + 100)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Ref: " + ref, ln=True, align="R")

    pdf.set_y(pdf.get_y() + 8)

    # Financial Summary
    pdf.set_fill_color(*c_grey_bg)
    pdf.set_line_width(0.3)
    pdf.rect(mg, pdf.get_y(), pw, 24, style="DF")
    pdf.set_y(pdf.get_y() + 4)
    col_w = pw / 3
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(col_w, 5, "TOTAL DEPOSITS", align="C")
    pdf.cell(col_w, 5, "TOTAL CHARGES", align="C")
    pdf.cell(col_w, 5, "ENDING BALANCE", align="C", ln=True)
    total_charges = summary["current_bill"] + summary["manager_fees"]
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(col_w, 8, "BDT %.2f" % summary["total_deposits"], align="C")
    pdf.cell(col_w, 8, "BDT %.2f" % total_charges, align="C")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(col_w, 8, "BDT %.2f" % summary["cycle_balance"], align="C", ln=True)
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 4, "Average Rate: BDT %.2f" % rates.get("final_rate", 0), ln=True)
    pdf.ln(8)

    # Deposit History
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Deposit History", ln=True)
    pdf.ln(2)
    c1, c2, c3 = 35, pw - 75, 40
    pdf.set_fill_color(*c_grey_bg)
    if deposits_data:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(c1, 8, "  Date", border=1, fill=True)
        pdf.cell(c2, 8, "  Description", border=1, fill=True)
        pdf.cell(c3, 8, "Amount  ", border=1, fill=True, align="R", ln=True)
        pdf.set_font("Helvetica", "", 8)
        total_dep = 0
        for d in deposits_data:
            pdf.cell(c1, 7, "  " + d["date"], border=1)
            pdf.cell(c2, 7, "  " + ((d.get("description") or "Account Deposit")[:55]), border=1)
            pdf.cell(c3, 7, "%.2f  " % d["amount"], border=1, align="R", ln=True)
            total_dep += d["amount"]
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(c1 + c2, 8, "  Total Deposits", border=1)
        pdf.cell(c3, 8, "BDT %.2f  " % total_dep, border=1, align="R", ln=True)
    else:
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 6, "No deposits recorded for this billing cycle.", ln=True)
    pdf.ln(8)

    # Daily Meal Log — include ALL days (active + off), matching the /search list
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Daily Meal Log", ln=True)
    pdf.ln(2)
    if daily_meals:
        w_date, w_stat, w_exp, w_meals, w_rate, w_cost = 26, 34, 30, 14, 30, 36
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(w_date, 8, " Date", border=1, fill=True)
        pdf.cell(w_stat, 8, " Status", border=1, fill=True)
        pdf.cell(w_exp, 8, " Expense", border=1, fill=True)
        pdf.cell(w_meals, 8, "Meals", border=1, fill=True, align="C")
        pdf.cell(w_rate, 8, " Rate", border=1, fill=True)
        pdf.cell(w_cost, 8, "Your Charge ", border=1, fill=True, align="R", ln=True)
        status_map = {"both": "Both", "lunch_only": "Lunch Only", "dinner_only": "Dinner Only", "off": "Off"}
        pdf.set_font("Helvetica", "", 8)
        for meal in daily_meals:
            pdf.cell(w_date, 7, " " + meal["date"], border=1)
            pdf.cell(w_stat, 7, " " + status_map.get(meal["status"], meal["status"].title()), border=1)
            pdf.cell(w_exp, 7, " %.2f" % meal.get("expense", 0.0), border=1)
            pdf.cell(w_meals, 7, str(meal.get("meal_count", 0)), border=1, align="C")
            pdf.cell(w_rate, 7, " %.2f" % meal.get("final_rate", 0.0), border=1)
            pdf.cell(w_cost, 7, "%.2f " % meal.get("day_cost", 0), border=1, align="R", ln=True)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(w_date + w_stat + w_exp + w_meals + w_rate, 8, " Total Charges", border=1)
        pdf.cell(w_cost, 8, "BDT %.2f " % total_charges, border=1, align="R", ln=True)
    else:
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 6, "No meal records for this cycle.", ln=True)

    # Signatures
    if pdf.get_y() > 255:
        pdf.add_page()
    else:
        pdf.ln(12)
    pdf.set_font("Helvetica", "", 9)
    sig_w = 65
    pdf.line(mg, pdf.get_y(), mg + sig_w, pdf.get_y())
    pdf.line(mg + pw - sig_w, pdf.get_y(), mg + pw, pdf.get_y())
    pdf.ln(2)
    pdf.cell(sig_w, 5, "Authorized Signature", align="C", ln=False)
    pdf.cell(pw - (sig_w * 2), 5, "", ln=False)
    pdf.cell(sig_w, 5, "Student Signature", align="C", ln=True)
    
    return bytes(pdf.output(dest="S"))
