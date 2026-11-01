import streamlit as st
from datetime import date
from sqlalchemy import func, select

from database.init_db import initialize_database
from database.connection import SessionLocal
from database.models import Category, Expense, Income
from services.expense_service import add_expense, list_expenses, delete_expense, update_expense
from services.income_service import add_income, list_incomes, update_income, delete_income
from utils.money import paise_to_rupees

st.set_page_config(page_title="AI Expense Tracker", page_icon="💰", layout="wide")
initialize_database()

st.title("💰 My Expense Tracker")
st.caption("Personal finance · INR · Asia/Kolkata")

def money(paise: int) -> str:
    return f"₹{paise_to_rupees(paise):,.2f}"

def get_category_names(db):
    return list(db.scalars(
        select(Category.name)
        .where(Category.type == "EXPENSE", Category.is_active.is_(True))
        .order_by(Category.name)
    ).all())

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "AI Assistant", "Add Expense", "Add Income", "Transactions"],
    key="page",
)

with SessionLocal() as db:
    today = date.today()

    if page == "AI Assistant":
        from frontend.chat import render_chat
        render_chat()

    elif page == "Dashboard":
        st.subheader("Overview")
        month_start = today.replace(day=1)
        expense_total = db.scalar(
            select(func.coalesce(func.sum(Expense.amount_paise), 0))
            .where(
                Expense.expense_date >= month_start,
                Expense.expense_date <= today,
            )
        ) or 0
        income_total = db.scalar(
            select(func.coalesce(func.sum(Income.amount_paise), 0))
            .where(
                Income.income_date >= month_start,
                Income.income_date <= today,
            )
        ) or 0
        expense_count = db.scalar(
            select(func.count(Expense.id))
            .where(
                Expense.expense_date >= month_start,
                Expense.expense_date <= today,
            )
        ) or 0

        c1, c2, c3 = st.columns(3)
        c1.metric("Income this month", money(income_total))
        c2.metric("Expenses this month", money(expense_total))
        c3.metric("Net cash flow", money(income_total - expense_total))
        st.caption(f"{today.strftime('%B %Y')} · {expense_count} expense transaction(s)")

        st.subheader("Spending by category")
        category_rows = db.execute(
            select(Category.name, func.sum(Expense.amount_paise))
            .join(Expense, Expense.category_id == Category.id)
            .where(
                Expense.expense_date >= month_start,
                Expense.expense_date <= today,
            )
            .group_by(Category.name)
            .order_by(func.sum(Expense.amount_paise).desc())
        ).all()

        if category_rows:
            import pandas as pd
            chart_data = pd.DataFrame(
                [{"Category": name, "Amount (₹)": total / 100} for name, total in category_rows]
            )
            st.bar_chart(chart_data.set_index("Category"))
        else:
            st.info("No expenses recorded this month yet.")

        st.subheader("Recent transactions")
        recent = db.scalars(
            select(Expense)
            .order_by(Expense.expense_date.desc(), Expense.id.desc())
            .limit(8)
        ).all()
        if recent:
            st.dataframe(
                [{
                    "Date": item.expense_date,
                    "Description": item.description,
                    "Category": item.category.name,
                    "Payment": item.payment_method or "—",
                    "Amount": money(item.amount_paise),
                } for item in recent],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Your transactions will appear here after you add an expense.")

    elif page == "Add Expense":
        st.subheader("Add an expense")
        categories = get_category_names(db)
        with st.form("expense_form", clear_on_submit=True):
            amount = st.number_input(
                "Amount (₹)", min_value=0.01, step=10.0, format="%.2f",
                key="add_expense_amount",
            )
            description = st.text_input(
                "Description", placeholder="e.g. Dinner",
                key="add_expense_description",
            )
            category = st.selectbox(
                "Category", categories, key="add_expense_category"
            )
            payment = st.selectbox(
                "Payment method",
                ["UPI", "Cash", "Debit Card", "Credit Card", "Net Banking", "Other"],
                key="add_expense_payment",
            )
            expense_date = st.date_input(
                "Expense date", value=today,
                key="add_expense_date"
            )
            notes = st.text_area(
                "Notes (optional)", key="add_expense_notes"
            )
            submitted = st.form_submit_button("Save expense", type="primary")

        if submitted:
            try:
                item = add_expense(
                    db, amount=amount, description=description,
                    category_name=category, expense_date=expense_date,
                    payment_method=payment, notes=notes or None, source="MANUAL",
                )
                st.success(f"Saved {money(item.amount_paise)} for {item.description}.")
            except ValueError as exc:
                st.error(str(exc))

    elif page == "Add Income":
        st.subheader("Add income")
        with st.form("income_form", clear_on_submit=True):
            amount = st.number_input(
                "Amount (₹)", min_value=0.01, step=500.0, format="%.2f",
                key="add_income_amount",
            )
            source = st.text_input(
                "Income source", placeholder="e.g. Salary",
                key="add_income_source",
            )
            income_date = st.date_input(
                "Received date", value=today,
                key="add_income_date"
            )
            notes = st.text_area(
                "Notes (optional)", key="add_income_notes"
            )
            submitted = st.form_submit_button("Save income", type="primary")

        if submitted:
            try:
                item = add_income(
                    db, amount=amount, source=source,
                    income_date=income_date,
                    notes=notes or None,
                )
                st.success(f"Saved income of {money(item.amount_paise)} from {item.source}.")
            except ValueError as exc:
                st.error(str(exc))

    elif page == "Transactions":
        st.subheader("Expense transactions")
        all_expenses = list_expenses(db)
        if not all_expenses:
            st.info("No expenses recorded yet.")
        else:
            st.dataframe(
                [{
                    "ID": item.id, "Date": item.expense_date,
                    "Description": item.description, "Category": item.category.name,
                    "Payment": item.payment_method or "—", "Amount": money(item.amount_paise),
                } for item in all_expenses],
                use_container_width=True, hide_index=True,
            )

            st.divider()
            st.markdown("### Edit an expense")
            expense_options = {
                f"#{item.id} · {item.description} · {money(item.amount_paise)} · {item.expense_date}": item.id
                for item in all_expenses
            }
            selected_expense_label = st.selectbox(
                "Choose an expense to edit", list(expense_options),
                key="edit_expense_select",
            )
            selected_expense = next(
                item for item in all_expenses
                if item.id == expense_options[selected_expense_label]
            )
            categories = get_category_names(db)
            payment_options = ["UPI", "Cash", "Debit Card", "Credit Card", "Net Banking", "Other"]
            current_payment = selected_expense.payment_method or "Other"
            if current_payment not in payment_options:
                payment_options.append(current_payment)

            with st.form("edit_expense_form"):
                edit_amount = st.number_input(
                    "Amount (₹)", min_value=0.01,
                    value=float(selected_expense.amount_paise / 100),
                    step=10.0, format="%.2f",
                    key="edit_expense_amount",
                )
                edit_description = st.text_input(
                    "Description", value=selected_expense.description,
                    key="edit_expense_description",
                )
                edit_category = st.selectbox(
                    "Category", categories,
                    index=categories.index(selected_expense.category.name),
                    key="edit_expense_category",
                )
                edit_payment = st.selectbox(
                    "Payment method", payment_options,
                    index=payment_options.index(current_payment),
                    key="edit_expense_payment",
                )
                edit_date = st.date_input(
                    "Expense date", value=selected_expense.expense_date,
                    key="edit_expense_date",
                )
                edit_notes = st.text_area(
                    "Notes", value=selected_expense.notes or "",
                    key="edit_expense_notes",
                )
                save_edit = st.form_submit_button("Save changes", type="primary")

            if save_edit:
                try:
                    updated = update_expense(
                        db, selected_expense.id,
                        amount=edit_amount,
                        description=edit_description, category_name=edit_category,
                        expense_date=edit_date, payment_method=edit_payment,
                        notes=edit_notes or None,
                    )
                    st.success(f"Updated expense #{updated.id}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

            st.divider()
            st.markdown("### Delete an expense")
            confirm = st.checkbox(
                "I understand this will permanently delete the selected expense.",
                key="confirm_delete_expense",
            )
            if st.button(
                "Delete selected expense", disabled=not confirm,
                key="delete_expense",
            ):
                if delete_expense(db, selected_expense.id):
                    st.success("Expense deleted.")
                    st.rerun()
                else:
                    st.error("That expense could not be found.")

        st.divider()
        st.subheader("Income transactions")
        incomes = list_incomes(db)
        if incomes:
            st.dataframe(
                [{
                    "ID": item.id, "Date": item.income_date,
                    "Source": item.source, "Amount": money(item.amount_paise),
                    "Notes": item.notes or "",
                } for item in incomes],
                use_container_width=True, hide_index=True,
            )
            st.markdown("### Edit income")
            income_options = {
                f"#{item.id} · {item.source} · {money(item.amount_paise)} · {item.income_date}": item.id
                for item in incomes
            }
            selected_income_label = st.selectbox(
                "Choose income to edit", list(income_options),
                key="edit_income_select",
            )
            selected_income = next(
                item for item in incomes
                if item.id == income_options[selected_income_label]
            )
            with st.form("edit_income_form"):
                income_amount = st.number_input(
                    "Amount (₹)", min_value=0.01,
                    value=float(selected_income.amount_paise / 100),
                    step=500.0, format="%.2f",
                    key="edit_income_amount",
                )
                income_source = st.text_input(
                    "Income source", value=selected_income.source,
                    key="edit_income_source",
                )
                income_date_edit = st.date_input(
                    "Received date", value=selected_income.income_date,
                    key="edit_income_date",
                )
                income_notes = st.text_area(
                    "Notes", value=selected_income.notes or "",
                    key="edit_income_notes",
                )
                save_income_edit = st.form_submit_button("Save income changes")
            if save_income_edit:
                try:
                    updated_income = update_income(
                        db, selected_income.id,
                        amount=income_amount,
                        source=income_source, income_date=income_date_edit,
                        notes=income_notes or None,
                    )
                    st.success(f"Updated income #{updated_income.id}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

            st.markdown("### Delete income")
            confirm_income_delete = st.checkbox(
                "I understand this will permanently delete the selected income.",
                key="confirm_delete_income",
            )
            if st.button(
                "Delete selected income",
                disabled=not confirm_income_delete,
                key="delete_income",
            ):
                if delete_income(db, selected_income.id):
                    st.success("Income deleted.")
                    st.rerun()
                else:
                    st.error("That income could not be found.")
        else:
            st.info("No income recorded yet.")
