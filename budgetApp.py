# -*- coding: utf-8 -*-
# SMART BUDGET APP by ChatGPT (Optimized & Robust Version)

import streamlit as st
import gspread
import pandas as pd
import calendar
from datetime import datetime, timedelta
import os # For checking if credentials file exists
from oauth2client.service_account import ServiceAccountCredentials # New import for Service Account

from io import BytesIO
import plotly.express as px

# --- Configuration and Setup ---

# Language support
# Set default language to Thai
lang_options = ["ภาษาไทย", "English"]
default_lang_index = lang_options.index("ภาษาไทย")
lang = st.sidebar.selectbox("🌐 Language / ภาษา", lang_options, index=default_lang_index)
def t(thai, eng): return thai if lang == "ภาษาไทย" else eng

# Define canonical (English) categories and their translations
CATEGORY_MAP = {
    "Food": "อาหาร",
    "Travel": "เดินทาง",
    "Utilities": "ของใช้",
    "Income": "รายได้",
    "Others": "อื่นๆ",
    "Fixed Expense": "ค่าใช้จ่ายประจำ"
}
REVERSE_CATEGORY_MAP = {v: k for k, v in CATEGORY_MAP.items()}

# Define standard columns for each DataFrame
STANDARD_COLS_MAIN = ['Date', 'Type', 'Category', 'Amount', 'Note']
STANDARD_COLS_FIXED = ["Name", "Amount"]
STANDARD_COLS_SAVING_GOALS = ["GoalName", "GoalAmount", "Emoji", "CurrentSaved", "TargetDate", "SavingFrequency", "SavingAmountPerFreq"]
STANDARD_COLS_MONTHLY_PLAN = ["MonthYear", "ItemType", "ItemName", "Amount", "Category", "IsPaid", "DatePaid"]

# --- Gspread Client & Worksheet Setup (Cached Resources) ---
@st.cache_resource
def get_gspread_client():
    """Authenticates and returns a gspread client using Service Account."""
    # Define the path for the Service Account JSON key file
    service_account_key_file = "service_account_key.json"

    # Check if the Service Account JSON key file exists
    if not os.path.exists(service_account_key_file):
        st.error(f"Error: '{service_account_key_file}' not found. Please follow the setup guide to create and download it, then place it in the same directory as your app.")
        st.stop() # Stop the app if the key file is missing

    try:
        # Authenticate using Service Account Credentials
        scope = [
            "https://spreadsheets.google.com/feeds", # For Google Sheets API
            "https://www.googleapis.com/auth/drive" # For Google Drive API (needed by gspread to open sheets)
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(service_account_key_file, scope)
        client = gspread.authorize(creds)
        st.success("Google Sheets API client initialized successfully using Service Account!")
        return client
    except Exception as e:
        st.error(f"Failed to authenticate with Google Sheets API using Service Account. Error: {e}")
        st.info("Please ensure your 'service_account_key.json' is valid and the Service Account has 'Editor' access to your Google Sheet.")
        st.stop() # Stop the app if authentication fails

@st.cache_resource
def get_worksheet(_client_obj, sheet_name, headers=None, rows=100, cols=5):
    """
    Returns a gspread worksheet. Creates it if not found, with specified headers.
    """
    try:
        return _client_obj.open("budget_data").worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = _client_obj.open("budget_data").add_worksheet(title=sheet_name, rows=rows, cols=cols)
        if headers:
            ws.append_row(headers)
        return ws

# Initialize gspread client and sheets
client = get_gspread_client()
sheet = client.open("budget_data").sheet1 # Main sheet is always sheet1

fixed_expenses_sheet = get_worksheet(client, "FixedExpenses", STANDARD_COLS_FIXED, rows=100, cols=5)
goals_sheet = get_worksheet(client, "SavingGoals", STANDARD_COLS_SAVING_GOALS, rows=100, cols=7)
monthly_plans_sheet = get_worksheet(client, "MonthlyPlans", STANDARD_COLS_MONTHLY_PLAN, rows=200, cols=7)

# --- Data Loading (Cached Data) ---
@st.cache_data(ttl=3600) # Cache data for 1 hour, or until invalidated
def load_data_from_sheet_cached(_worksheet, standard_cols, type_conversions=None):
    """
    Loads data from a gspread worksheet, ensures standard columns, and converts types.
    type_conversions: dict of column_name: type_function (e.g., 'Amount': float)
    """
    all_values = _worksheet.get_all_values()
    if not all_values:
        df_empty = pd.DataFrame(columns=standard_cols)
        # Ensure correct dtypes even for empty DataFrame
        if type_conversions:
            for col, type_func in type_conversions.items():
                if col in df_empty.columns:
                    if type_func == float: df_empty[col] = df_empty[col].astype(float)
                    elif type_func == datetime: df_empty[col] = pd.to_datetime(df_empty[col])
                    elif type_func == bool: df_empty[col] = df_empty[col].astype(bool)
                    elif type_func == str: df_empty[col] = df_empty[col].astype(str)
        return df_empty

    headers = all_values[0]
    headers = [h if h else f"Unnamed_Col_{i}" for i, h in enumerate(headers)] # Handle empty headers
    data_rows = all_values[1:]
    
    df_loaded = pd.DataFrame(data_rows, columns=headers)

    # Ensure all standard columns exist and fill with None if missing
    for col in standard_cols:
        if col not in df_loaded.columns:
            df_loaded[col] = None
    
    # Apply type conversions and fillna for common types
    if type_conversions:
        for col, type_func in type_conversions.items():
            if col in df_loaded.columns:
                if type_func == float:
                    df_loaded[col] = pd.to_numeric(df_loaded[col], errors='coerce').fillna(0.0)
                elif type_func == datetime:
                    # Explicitly convert to datetime and ensure datetime64[ns] dtype
                    df_loaded[col] = pd.to_datetime(df_loaded[col], errors='coerce')
                    # If after coercion, the dtype is not datetime64[ns], it means all values were unparseable or empty.
                    # In such a case, force the dtype to datetime64[ns] and fill with NaT.
                    if not pd.api.types.is_datetime64_any_dtype(df_loaded[col]):
                        df_loaded[col] = pd.Series([pd.NaT] * len(df_loaded), dtype='datetime64[ns]')
                elif type_func == bool:
                    df_loaded[col] = df_loaded[col].apply(lambda x: str(x).lower() == 'true' if pd.notna(x) else False)
                elif type_func == str: # For ensuring string type, like SavingFrequency
                    df_loaded[col] = df_loaded[col].fillna('').astype(str)
    
    # Return only standard columns in defined order
    # Filter out columns not in standard_cols to avoid unexpected columns from sheet
    df_filtered = df_loaded[[col for col in standard_cols if col in df_loaded.columns]]
    return df_filtered

# Initialize DataFrames in session state if not already present
if 'df_main' not in st.session_state:
    st.session_state.df_main = load_data_from_sheet_cached(sheet, STANDARD_COLS_MAIN, {
        'Date': datetime, 'Amount': float, 'Type': str, 'Category': str, 'Note': str
    })
    if not st.session_state.df_main.empty:
        st.session_state.df_main['Type'] = st.session_state.df_main['Type'].apply(lambda x: "Income" if x == "รายรับ" else ("Expense" if x == "รายจ่าย" else x))
        st.session_state.df_main['Category'] = st.session_state.df_main['Category'].apply(lambda x: REVERSE_CATEGORY_MAP.get(x, x))

if 'df_fixed_expenses' not in st.session_state:
    st.session_state.df_fixed_expenses = load_data_from_sheet_cached(fixed_expenses_sheet, STANDARD_COLS_FIXED, {
        'Amount': float, 'Name': str
    })

if 'df_saving_goals' not in st.session_state:
    st.session_state.df_saving_goals = load_data_from_sheet_cached(goals_sheet, STANDARD_COLS_SAVING_GOALS, {
        'GoalAmount': float, 'CurrentSaved': float, 'SavingAmountPerFreq': float,
        'TargetDate': datetime, 'GoalName': str, 'Emoji': str, 'SavingFrequency': str
    })

if 'df_monthly_plans' not in st.session_state:
    st.session_state.df_monthly_plans = load_data_from_sheet_cached(monthly_plans_sheet, STANDARD_COLS_MONTHLY_PLAN, {
        'MonthYear': datetime, 'Amount': float, 'IsPaid': bool, 'DatePaid': datetime,
        'ItemType': str, 'ItemName': str, 'Category': str
    })
    if not st.session_state.df_monthly_plans.empty:
        st.session_state.df_monthly_plans = st.session_state.df_monthly_plans.dropna(subset=['MonthYear'])

# Use these session state variables throughout the app
df = st.session_state.df_main
df_fixed_expenses = st.session_state.df_fixed_expenses
df_saving_goals = st.session_state.df_saving_goals
df_monthly_plans = st.session_state.df_monthly_plans


# --- Combine Main and Fixed Expenses for Unified Calculation ---
# Create an empty DataFrame for fixed expenses with the standard columns
df_fixed_expenses_for_calc = pd.DataFrame(columns=STANDARD_COLS_MAIN)

if not df_fixed_expenses.empty:
    temp_fixed_data = []
    today = datetime.today()
    for index, row in df_fixed_expenses.iterrows():
        temp_fixed_data.append({
            'Date': datetime(today.year, today.month, 1), # Assign current month's first day for calculation
            'Type': "Expense",
            'Category': "Fixed Expense",
            'Amount': row['Amount'],
            'Note': "Fixed Monthly Expense: " + str(row['Name']) # Ensure name is string
        })
    df_fixed_expenses_for_calc = pd.DataFrame(temp_fixed_data, columns=STANDARD_COLS_MAIN)
    df_fixed_expenses_for_calc['Date'] = pd.to_datetime(df_fixed_expenses_for_calc['Date'])

# Combine the main transactions with fixed expenses for dashboard calculations
df_combined = pd.concat([df, df_fixed_expenses_for_calc], ignore_index=True)
if not df_combined.empty:
    df_combined['Date'] = pd.to_datetime(df_combined['Date'])
    df_combined = df_combined.sort_values(by='Date').reset_index(drop=True)

    # Add helper columns for aggregation
    df_combined['Year'] = df_combined['Date'].dt.year
    df_combined['Month'] = df_combined['Date'].dt.month
    df_combined['Week'] = df_combined['Date'].dt.isocalendar().week
    df_combined['Day'] = df_combined['Date'].dt.day
    df_combined['MonthYearStr'] = df_combined['Date'].dt.strftime('%B %Y')
    df_combined['WeekYearStr'] = df_combined['Date'].dt.strftime('%Y-W%U') # %U for week number (Sunday as first day)

# --- Dashboard Metrics Calculation ---
def calculate_dashboard_metrics(df_combined_data, df_fixed_expenses_data):
    today = datetime.today()
    income = 0.0
    expense = 0.0
    balance = 0.0

    if not df_combined_data.empty:
        income = df_combined_data[df_combined_data['Type'] == "Income"]['Amount'].sum()
        expense = df_combined_data[df_combined_data['Type'] == "Expense"]['Amount'].sum()
        balance = income - expense

    total_fixed_expenses = df_fixed_expenses_data['Amount'].sum() if not df_fixed_expenses_data.empty else 0.0

    current_day = today.day
    current_month = today.month
    current_year = today.year

    target_month_for_daily_spend = current_month
    target_year_for_daily_spend = current_year

    # If today is past the 25th, calculate days until 25th of next month
    if current_day > 25:
        # Calculate next month and year
        if current_month == 12:
            target_month_for_daily_spend = 1
            target_year_for_daily_spend += 1
        else:
            target_month_for_daily_spend += 1
        
        # Date of 25th of next month
        target_date_for_daily_spend = datetime(target_year_for_daily_spend, target_month_for_daily_spend, 25)
        # Days remaining from today to 25th of next month
        days_until_25th = (target_date_for_daily_spend - today).days
    else:
        # If today is on or before the 25th, calculate days until 25th of current month
        target_date_for_daily_spend = datetime(current_year, current_month, 25)
        # Days remaining from today to 25th of current month
        days_until_25th = (target_date_for_daily_spend - today).days

    if days_until_25th <= 0: # Should not happen with the logic above, but as a safeguard
        days_until_25th = 1

    # Suggested daily spend is current balance divided by remaining days until the 25th
    suggested_daily = balance / days_until_25th
    if suggested_daily < 0:
        suggested_daily = 0.0
        
    remaining_after_fixed = balance - total_fixed_expenses

    return income, expense, balance, suggested_daily, total_fixed_expenses, remaining_after_fixed

income, expense, balance, suggested_daily, total_fixed_expenses, remaining_after_fixed = \
    calculate_dashboard_metrics(df_combined, df_fixed_expenses)

# --- Common UI Components ---
today = datetime.today() # Re-define today for broader use

# --- Theme Configuration (Only Dark Mode) ---
THEMES = {
    "Dark": {
        "bg_color": "#0E1117",
        "text_color": "#FAFAFA", # Light grey for dark theme
        "primary_color": "#2694E8",
        "secondary_color": "#6c757d",
        "accent_color": "#28a745", # Green for income/positive
        "warning_color": "#ffc107",
        "danger_color": "#dc3545", # Red for expenses/negative
        "border_color": "#333333",
        "card_bg_color": "#1A1D21"
    }
}

# Set theme directly to Dark
selected_theme = "Dark"
current_theme = THEMES[selected_theme]

# Inject custom CSS variables based on selected theme
st.markdown(f"""
<style>
:root {{
    --bg-color: {current_theme['bg_color']};
    --text-color: {current_theme['text_color']};
    --primary-color: {current_theme['primary_color']};
    --secondary-color: {current_theme['secondary_color']};
    --accent-color: {current_theme['accent_color']};
    --warning-color: {current_theme['warning_color']};
    --danger-color: {current_theme['danger_color']};
    --border-color: {current_theme['border_color']};
    --card-bg-color: {current_theme['card_bg_color']};
}}

body {{
    background-color: var(--bg-color);
    color: var(--text-color); /* Ensure body text uses theme color */
}}

.stApp {{
    background-color: var(--bg-color);
    color: var(--text-color); /* Ensure stApp text uses theme color */
}}

/* General text color for all elements, to catch most cases */
.stText, .stMarkdown, .stLabel, h1, h2, h3, h4, h5, h6 {{
    color: var(--text-color);
}}

/* Specifically target Streamlit input elements and their text */
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stDateInput > div > div > input,
.stSelectbox > div > div > div > div > span, /* Selected value in selectbox */
.stRadio > label > div > div > p, /* Radio button labels */
.stSelectbox > label > div > p /* Selectbox label */
{{
    color: var(--text-color);
}}

/* Ensure all text within Streamlit components uses the theme's text color */
div[data-testid="stVerticalBlock"] p,
div[data-testid="stHorizontalBlock"] p,
div[data-testid="stExpander"] p,
div[data-testid="stMetric"] div,
div[data-testid="stMetric"] label,
div[data-testid="stTabs"] button,
div[data-testid="stSidebar"] div,
div[data-testid="stSidebar"] p,
div[data-testid="stSidebar"] label
{{
    color: var(--text-color);
}}


.stContainer {{
    background-color: var(--card-bg-color);
    border: 1px solid var(--border-color);
    border-radius: 15px;
    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
}}

/* Custom styling for dashboard metrics */
.metric-container {{
    background-color: var(--card-bg-color);
    border-radius: 10px;
    padding: 10px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    border: 1px solid var(--border-color);
}}

.metric-label {{
    font-size: 0.9em;
    color: var(--text-color);
    margin-bottom: 5px;
    font-weight: normal;
}}

.metric-value {{
    font-size: 1.5em;
    font-weight: bold;
}}

.metric-value.income {{
    color: var(--accent-color); /* Green */
}}

.metric-value.expense {{
    color: var(--danger-color); /* Red */
}}

.metric-value.balance.positive {{
    color: var(--accent-color); /* Green for positive balance */
}}
.metric-value.balance.negative {{
    color: var(--danger-color); /* Red for negative balance */
}}

.metric-value.spendable.positive {{
    color: var(--accent-color); /* Green for positive spendable */
}}
.metric-value.spendable.negative {{
    color: var(--danger_color); /* Red for negative spendable */
}}


.goals-grid {{
    display: flex; /* CSS property for flexbox */
    flex-wrap: wrap;
    justify-content: center;
    gap: 10px; /* Smaller space between cards */
    margin-bottom: 20px;
}}

/* Streamlit's st.container with border=True will have its own styling.
   We'll apply custom styles to elements *inside* the container. */
.goal-card-content {{
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    padding: 5px; /* Reduced padding inside the container */
    width: 100%; /* Take full width of its parent column/container */
}}

.goal-emoji {{
    font-size: 2em; /* Smaller emoji */
    margin-bottom: 3px; /* Reduced margin */
}}

.goal-name {{
    font-weight: bold;
    font-size: 0.95em; /* Smaller name font */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    width: 100%; /* Ensure it takes full width */
}}

.goal-amounts {{
    font-size: 0.8em; /* Smaller font for amounts */
    color: var(--text-color);
    margin-top: 3px; /* Reduced margin */
}}

/* Streamlit's st.progress handles its own styling. No need for custom .goal-progress-container/.goal-progress-bar */

.goal-status {{
    font-size: 0.75em; /* Smaller font for status */
    color: #555;
    margin-bottom: 3px; /* Reduced margin */
}}

.goal-required-saving {{
    font-size: 0.7em; /* Even smaller font for required saving */
    color: #777;
    margin-top: 3px; /* Reduced margin */
}}

/* Streamlit's st.button styling */
.stButton>button {{
    width: 100%;
    border-radius: 8px; /* Slightly smaller border radius */
    background-color: var(--primary-color); /* Use theme primary color */
    color: white;
    padding: 6px 8px; /* Reduced padding */
    text-align: center;
    text-decoration: none;
    display: inline-block;
    font-size: 0.8em; /* Smaller font for button */
    margin-top: 8px; /* Reduced margin */
    cursor: pointer;
    border: none;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    transition: background-color 0.2s ease-in-out;
}}

.stButton>button:hover {{
    background-color: var(--secondary-color); /* Use theme secondary color for hover */
}}

/* Styles for tabs to look like embossed buttons */
div[data-testid="stTabs"] button {{
    background-color: var(--card-bg-color);
    color: var(--text-color);
    border: 1px solid var(--border-color);
    border-radius: 10px; /* Rounded corners for tabs */
    padding: 10px 15px;
    margin: 5px;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.2), inset -2px -2px 5px rgba(255,255,255,0.05); /* Embossed effect */
    transition: all 0.2s ease-in-out;
    font-weight: bold;
}}

div[data-testid="stTabs"] button:hover {{
    background-color: var(--primary-color);
    color: white;
    box-shadow: 3px 3px 8px rgba(0,0,0,0.3), inset -3px -3px 8px rgba(255,255,255,0.1);
}}

div[data-testid="stTabs"] button[aria-selected="true"] {{
    background-color: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
    box-shadow: inset 2px 2px 5px rgba(0,0,0,0.3), 2px 2px 5px rgba(0,0,0,0.2); /* Pressed effect */
}}

/* Style for the main balance metric at the top */
.main-balance-container {{
    background-color: #1A1D21; /* Slightly lighter than main bg for contrast */
    border-radius: 15px;
    padding: 20px;
    text-align: center;
    margin-bottom: 20px;
    box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    border: 1px solid #333333;
}}

.main-balance-label {{
    font-size: 1.2em;
    color: #FAFAFA;
    margin-bottom: 10px;
    font-weight: normal;
}}

.main-balance-value {{
    font-size: 3em; /* Larger font for main balance */
    font-weight: bold;
    color: var(--accent-color); /* Green for positive balance */
    text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
}}

.main-balance-value.negative {{
    color: var(--danger-color); /* Red for negative balance */
}}

</style>
""", unsafe_allow_html=True)

st.markdown(f"<h1 style='text-align:center;'>{t('📒 แอพบันทึกรายรับรายจ่าย', '📒 Budget Tracker App')}</h1>", unsafe_allow_html=True)

# --- Emoji List for Selectbox ---
EMOJI_OPTIONS = [
    "💰", "🏠", "✈️", "🚗", "🎓", "💍", "👶", "🏥", "💻", "�",
    "📚", "🎁", "💖", "🍔", "☕", "🛒", "💡", "📈", "🏖️", "🎉"
]

# --- Display Main Balance at the very top ---
with st.container():
    st.markdown("<div class='main-balance-container'>", unsafe_allow_html=True)
    balance_class = "positive" if balance >= 0 else "negative"
    balance_sign = "+" if balance >= 0 else ""
    st.markdown(f"<div class='main-balance-label'>{t('ยอดเงินคงเหลือทั้งหมด', 'Total Balance')}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='main-balance-value {balance_class}'>{balance_sign}฿{balance:,.2f}</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# --- Saving Goals Section (Moved to top, visible on all tabs) ---
def display_saving_goals(df_goals):
    st.markdown(f"### {t('เป้าหมายการออมของคุณ', 'Your Saving Goals')}")
    if not df_goals.empty:
        num_cols_for_goals = 4 # Try 4 columns for a more compact horizontal layout
        cols = st.columns(num_cols_for_goals) 
        
        for idx, goal in df_goals.iterrows():
            with cols[idx % num_cols_for_goals]:
                with st.container(border=True): # Each goal is in a bordered container
                    st.markdown("<div class='goal-card-content'>", unsafe_allow_html=True) 
                    
                    goal_name = str(goal['GoalName']) if pd.notna(goal['GoalName']) else t("ไม่ระบุชื่อ", "No Name")
                    goal_amount = float(goal['GoalAmount']) if pd.notna(goal['GoalAmount']) else 0.0
                    current_saved = float(goal['CurrentSaved']) if pd.notna(goal['CurrentSaved']) else 0.0
                    emoji = str(goal['Emoji']) if pd.notna(goal['Emoji']) else "💰"
                    target_date = goal['TargetDate']
                    saving_freq = str(goal['SavingFrequency']) if pd.notna(goal['SavingFrequency']) else 'Daily'
                    saving_amount_per_freq = float(goal['SavingAmountPerFreq']) if pd.notna(goal['SavingAmountPerFreq']) else 0.0

                    progress_percent = (current_saved / goal_amount) * 100 if goal_amount > 0 else 0
                    progress_percent = min(100, max(0, progress_percent)) # Clamp between 0 and 100
                    
                    status_text = ""
                    target_date_display = ""
                    days_remaining_for_goal = 0

                    if pd.notna(target_date):
                        target_date_display = target_date.strftime('%Y-%m-%d')
                        days_remaining_for_goal = (target_date.date() - today.date()).days
                    
                    if current_saved >= goal_amount:
                        status_text = t("ถึงเป้าแล้ว!", "Goal Reached!")
                    elif pd.isna(target_date):
                        status_text = t("วันที่เป้าหมายไม่ถูกต้อง", "Invalid Target Date")
                    elif days_remaining_for_goal < 0:
                        status_text = t("เกินกำหนด", "Overdue")
                    else:
                        status_text = t("เหลือ", "Remaining") + f" {days_remaining_for_goal} {t('วัน', 'days')}"

                    freq_translation = {
                        'Daily': t('วัน', 'day'),
                        'Weekly': t('สัปดาห์', 'week'),
                        'Monthly': t('เดือน', 'month')
                    }
                    
                    display_freq = freq_translation.get(saving_freq, saving_freq.lower() if saving_freq else '')

                    st.markdown(f"<div class='goal-emoji'>{emoji}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='goal-name'>{goal_name}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='goal-amounts'>฿{current_saved:,.2f} / ฿{goal_amount:,.2f}</div>", unsafe_allow_html=True)
                    
                    st.progress(progress_percent / 100, text=f"{progress_percent:.1f}%")
                    
                    st.markdown(f"<div class='goal-status'>{status_text}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='goal-required-saving'>{t('สิ้นสุด:', 'End:')} {target_date_display}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='goal-required-saving'>{t('ต้องออม:', 'Required:')} ฿{saving_amount_per_freq:,.2f} {t('ต่อ', 'per')} {display_freq}</div>", unsafe_allow_html=True)
                    
                    if st.button(t('ออมเงิน', 'Save Money'), key=f"save_money_goal_{idx}", use_container_width=True):
                        st.session_state['selected_goal_to_save_idx'] = idx
                        st.rerun()

                    st.markdown("</div>", unsafe_allow_html=True) 

    else:
        st.info(t("ยังไม่มีเป้าหมายการออม เพิ่มเป้าหมายแรกของคุณได้เลย!", "No saving goals yet. Add your first goal!"))

# Display saving goals at the top
display_saving_goals(st.session_state.df_saving_goals)


# --- Sidebar: Manage Saving Goals ---
st.sidebar.markdown("---")
st.sidebar.markdown(f"### {t('จัดการเป้าหมายการออม', 'Manage Saving Goals')}")

def add_new_goal_form():
    with st.sidebar.expander(t("เพิ่มเป้าหมายใหม่", "Add New Goal")):
        with st.form("add_goal_form"):
            goal_name = st.text_input(t("ชื่อเป้าหมาย", "Goal Name"))
            goal_amount = st.number_input(t("จำนวนเป้าหมาย (บาท)", "Goal Amount (THB)"), min_value=0.0, step=1.0, format="%.2f")
            
            # Emoji Selectbox
            default_emoji_index = EMOJI_OPTIONS.index("💰") if "💰" in EMOJI_OPTIONS else 0
            goal_emoji = st.selectbox(t("อีโมจิ", "Emoji"), options=EMOJI_OPTIONS, index=default_emoji_index)

            target_date = st.date_input(t("วันที่สิ้นสุดเป้าหมาย", "Target End Date"), value=today + timedelta(days=365))
            saving_frequency = st.selectbox(t("ความถี่ในการออม", "Saving Frequency"), ["Daily", "Weekly", "Monthly"])

            days_to_target = (target_date - today.date()).days if target_date else 0
            saving_amount_per_freq = 0.0
            if days_to_target > 0 and goal_amount > 0:
                remaining_to_save = goal_amount
                if saving_frequency == "Daily":
                    saving_amount_per_freq = remaining_to_save / days_to_target
                elif saving_frequency == "Weekly":
                    weeks_to_target = days_to_target / 7
                    saving_amount_per_freq = remaining_to_save / weeks_to_target if weeks_to_target > 0 else remaining_to_save
                elif saving_frequency == "Monthly":
                    months_to_target = days_to_target / 30.44
                    saving_amount_per_freq = remaining_to_save / months_to_target if months_to_target > 0 else 0.0
            
            display_freq_add_form = t('วัน' if saving_frequency == 'Daily' else ('สัปดาห์' if saving_frequency == 'Weekly' else 'เดือน'), saving_frequency.lower() if saving_frequency else '')
            st.info(f"{t('ต้องออม', 'Required saving')}: ฿{saving_amount_per_freq:,.2f} {t('ต่อ', 'per')} {display_freq_add_form}")

            add_goal_submitted = st.form_submit_button(t("➕ เพิ่มเป้าหมาย", "➕ Add Goal"))
            if add_goal_submitted and goal_name and goal_amount > 0 and target_date:
                try:
                    goals_sheet.append_row([goal_name, goal_amount, goal_emoji, 0.0, str(target_date), saving_frequency, saving_amount_per_freq])
                    st.success(t("เพิ่มเป้าหมายสำเร็จแล้ว!", "Goal added successfully!"))
                    st.cache_data.clear() # Invalidate cache to reload goals
                    st.session_state.df_saving_goals = load_data_from_sheet_cached(goals_sheet, STANDARD_COLS_SAVING_GOALS, {
                        'GoalAmount': float, 'CurrentSaved': float, 'SavingAmountPerFreq': float,
                        'TargetDate': datetime, 'GoalName': str, 'Emoji': str, 'SavingFrequency': str
                    }) # Reload into session state
                except gspread.exceptions.GSpreadException as e:
                    st.error(f"{t('เกิดข้อผิดพลาดในการบันทึกเป้าหมาย (ตรวจสอบสิทธิ์การเข้าถึง Google Sheet และชื่อคอลัมน์):', 'Error saving goal (check Google Sheet permissions and column names):')} {e}")
                except Exception as e:
                    st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิดในการบันทึกเป้าหมาย:', 'An unexpected error occurred while saving goal:')} {e}")
                st.rerun()

def edit_delete_goals_section(df_goals):
    if not df_goals.empty:
        st.sidebar.markdown(f"#### {t('แก้ไข/ลบเป้าหมาย', 'Edit/Delete Goals')}")
        df_saving_goals_display = df_goals.copy()
        # Ensure TargetDate is datetime type for data_editor
        if 'TargetDate' in df_saving_goals_display.columns and not pd.api.types.is_datetime64_any_dtype(df_saving_goals_display['TargetDate']):
            df_saving_goals_display['TargetDate'] = pd.to_datetime(df_saving_goals_display['TargetDate'], errors='coerce')
        
        edited_goals_df = st.sidebar.data_editor(
            df_saving_goals_display, # Read from session state
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "CurrentSaved": st.column_config.NumberColumn(t("ออมแล้ว", "Saved"), format="%.2f", disabled=True),
                "SavingAmountPerFreq": st.column_config.NumberColumn(t("ต้องออมต่อความถี่", "Required/Freq"), format="%.2f", disabled=True),
                "TargetDate": st.column_config.DateColumn(t("วันที่สิ้นสุด", "Target Date"), format="YYYY-MM-DD"),
                "SavingFrequency": st.column_config.SelectboxColumn(t("ความถี่", "Frequency"), options=["Daily", "Weekly", "Monthly"]),
                "Emoji": st.column_config.SelectboxColumn(t("อีโมจิ", "Emoji"), options=EMOJI_OPTIONS) # Emoji Selectbox
            },
            key="edit_goals_data_editor" # Add a key
        )
        st.session_state.df_saving_goals = edited_goals_df # Crucial: update session state immediately

        if st.sidebar.button("💾 " + t("บันทึกการแก้ไขเป้าหมาย", "Save Goal Edits")):
            try:
                goals_sheet.clear()
                goals_sheet.append_row(STANDARD_COLS_SAVING_GOALS)
                for _, row in st.session_state.df_saving_goals.iterrows(): # Use session state for saving
                    # Ensure essential fields are not empty before saving
                    if pd.notna(row['GoalName']) and pd.notna(row['GoalAmount']) and pd.notna(row['TargetDate']):
                        # Ensure TargetDate is a datetime object before accessing .date()
                        edited_target_date_dt = pd.to_datetime(row['TargetDate']).date()
                        edited_days_to_target = (edited_target_date_dt - today.date()).days
                        edited_saving_amount_per_freq = 0.0
                        if edited_days_to_target > 0 and row['GoalAmount'] > row['CurrentSaved']:
                            edited_remaining_to_save = row['GoalAmount'] - row['CurrentSaved']
                            if str(row['SavingFrequency']) == "Daily":
                                edited_saving_amount_per_freq = edited_remaining_to_save / edited_days_to_target
                            elif str(row['SavingFrequency']) == "Weekly":
                                edited_weeks_to_target = edited_days_to_target / 7
                                edited_saving_amount_per_freq = edited_remaining_to_save / edited_weeks_to_target if edited_weeks_to_target > 0 else edited_remaining_to_save
                            elif str(row['SavingFrequency']) == "Monthly":
                                edited_months_to_target = edited_days_to_target / 30.44
                                edited_saving_amount_per_freq = edited_remaining_to_save / edited_months_to_target if edited_months_to_target > 0 else edited_remaining_to_save

                        goals_sheet.append_row([
                            str(row['GoalName']),
                            float(row['GoalAmount']),
                            str(row['Emoji']),
                            float(row['CurrentSaved']),
                            str(edited_target_date_dt), # Save as string
                            str(row['SavingFrequency']),
                            float(edited_saving_amount_per_freq)
                        ])
                st.sidebar.success(t("อัปเดตเป้าหมายสำเร็จแล้ว", "Goals updated successfully"))
                st.cache_data.clear() # Invalidate cache to reload goals
                st.session_state.df_saving_goals = load_data_from_sheet_cached(goals_sheet, STANDARD_COLS_SAVING_GOALS, {
                    'GoalAmount': float, 'CurrentSaved': float, 'SavingAmountPerFreq': float,
                    'TargetDate': datetime, 'GoalName': str, 'Emoji': str, 'SavingFrequency': str
                }) # Reload into session state
            except gspread.exceptions.GSpreadException as e:
                st.sidebar.error(f"{t('เกิดข้อผิดพลาดในการบันทึกการแก้ไขเป้าหมาย:', 'Error saving goal edits:')} {e}")
            except Exception as e:
                st.sidebar.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิดในการบันทึกการแก้ไขเป้าหมาย:', 'An unexpected error occurred while saving goal:')} {e}")
            st.rerun()

add_new_goal_form()
edit_delete_goals_section(st.session_state.df_saving_goals)

def save_money_to_goal_section(df_goals):
    st.markdown("---")
    st.markdown(f"### {t('ออมเงินเข้าเป้าหมาย', 'Save Money to Goal')}")
    
    if df_goals.empty:
        st.info(t("ไม่มีเป้าหมายให้บันทึกเงินออม โปรดเพิ่มเป้าหมายก่อน", "No goals to save money to. Please add goals first."))
        return

    goal_options_for_save = [f"{row['Emoji']} {row['GoalName']}" for idx, row in df_goals.iterrows()]
    
    # Check if a goal was selected from a card button
    selected_goal_idx_from_card = st.session_state.get('selected_goal_to_save_idx', None)
    default_select_index = 0
    if selected_goal_idx_from_card is not None and selected_goal_idx_from_card < len(goal_options_for_save):
        pre_selected_display_string = f"{df_goals.iloc[selected_goal_idx_from_card]['Emoji']} {df_goals.iloc[selected_goal_idx_from_card]['GoalName']}"
        try:
            default_select_index = goal_options_for_save.index(pre_selected_display_string)
        except ValueError:
            default_select_index = 0
        st.session_state['selected_goal_to_save_idx'] = None # Reset after use
    
    selected_goal_to_save_display = st.selectbox(
        t("เลือกเป้าหมายที่จะออม", "Select Goal to Save"),
        goal_options_for_save,
        index=default_select_index,
        key="goal_selector_for_save"
    )
    
    save_amount_for_goal = st.number_input(t("จำนวนเงินที่จะออม", "Amount to Save"), min_value=0.0, step=1.0, format="%.2f")
    save_goal_money_button = st.button(t("💰 ออมเงินตอนนี้", "💰 Save Money Now"))

    if save_goal_money_button and save_amount_for_goal > 0 and selected_goal_to_save_display:
        selected_goal_row_idx = [i for i, opt in enumerate(goal_options_for_save) if opt == selected_goal_to_save_display][0]
        goal_to_update = df_goals.iloc[selected_goal_row_idx].copy()
        
        st.session_state.df_saving_goals.loc[selected_goal_row_idx, 'CurrentSaved'] += save_amount_for_goal # Update session state
        
        try:
            sheet.append_row([
                str(today.date()),
                "Expense",
                f"Saving Goal: {goal_to_update['GoalName']}",
                save_amount_for_goal,
                f"Saved for goal: {goal_to_update['GoalName']}"
            ])

            goals_sheet.clear()
            goals_sheet.append_row(STANDARD_COLS_SAVING_GOALS)
            for _, row in st.session_state.df_saving_goals.iterrows(): # Use session state for saving
                target_date_str_for_save = ''
                if pd.notna(row['TargetDate']):
                    target_date_str_for_save = str(row['TargetDate'].date())

                goals_sheet.append_row([
                    str(row['GoalName']), float(row['GoalAmount']), str(row['Emoji']),
                    float(row['CurrentSaved']), target_date_str_for_save, str(row['SavingFrequency']), float(row['SavingAmountPerFreq'])
                ])
            st.success(f"{t('ออมเงิน', 'Saved')} ฿{save_amount_for_goal:,.2f} {t('เข้าเป้าหมาย', 'to goal')} '{goal_to_update['GoalName']}' {t('แล้ว!', 'successfully!')}")
            st.cache_data.clear()
            st.session_state.df_main = load_data_from_sheet_cached(sheet, STANDARD_COLS_MAIN, { # Reload main df
                'Date': datetime, 'Amount': float, 'Type': str, 'Category': str, 'Note': str
            })
            if not st.session_state.df_main.empty:
                st.session_state.df_main['Type'] = st.session_state.df_main['Type'].apply(lambda x: "Income" if x == "รายรับ" else ("Expense" if x == "รายจ่าย" else x))
                st.session_state.df_main['Category'] = st.session_state.df_main['Category'].apply(lambda x: REVERSE_CATEGORY_MAP.get(x, x))
            
            st.session_state.df_saving_goals = load_data_from_sheet_cached(goals_sheet, STANDARD_COLS_SAVING_GOALS, { # Reload goals df
                'GoalAmount': float, 'CurrentSaved': float, 'SavingAmountPerFreq': float,
                'TargetDate': datetime, 'GoalName': str, 'Emoji': str, 'SavingFrequency': str
            })
        except gspread.exceptions.GSpreadException as e:
            st.error(f"{t('เกิดข้อผิดพลาดในการบันทึกเงินออม:', 'Error saving money:')} {e}")
        except Exception as e:
            st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิดในการบันทึกเงินออม:', 'An unexpected error occurred:')} {e}")
        st.rerun()

save_money_to_goal_section(st.session_state.df_saving_goals)


# --- Tabbed Interface ---
tab_titles = [
    t("บันทึกและภาพรวม", "Add & Overview"),
    t("ค่าใช้จ่ายประจำ", "Fixed Expenses"),
    t("รายการทั้งหมด", "All Entries"),
    t("วางแผนสำหรับเดือนหน้า", "Plan for Next Month")
]

tab1, tab2, tab3, tab4 = st.tabs(tab_titles)


# --- Tab 1: Add Entry Form & Dashboard/Graphs ---
with tab1:
    st.markdown(f"### 📝 {t('กรอกข้อมูลรายรับ/รายจ่าย', 'Add Entry')}")
    with st.form("entry_form"):
        cols = st.columns(2)
        date = cols[0].date_input("📅 " + t("วันที่", "Date"), value=today)
        
        entry_type_options = [t("รายรับ", "Income"), t("รายจ่าย", "Expense")]
        entry_type_selected = cols[1].radio("📌 " + t("ประเภท", "Type"), entry_type_options, horizontal=True)
        
        existing_categories_for_select = sorted([
            cat for cat in df_combined['Category'].unique().tolist()
            if cat != "Fixed Expense" and cat in CATEGORY_MAP.keys()
        ] if not df_combined.empty else [])
        
        for cat_en in CATEGORY_MAP.keys():
            if cat_en not in existing_categories_for_select and cat_en != "Fixed Expense":
                existing_categories_for_select.append(cat_en)
        existing_categories_for_select.sort()

        category_options_display = [t(CATEGORY_MAP.get(cat, cat), cat) for cat in existing_categories_for_select]
        category_options_display.append(t("เพิ่มหมวดหมู่ใหม่...", "Add New Category..."))

        category_selected_display = st.selectbox("🗂 " + t("หมวดหมู่", "Category"), category_options_display)
        
        category_to_save = ""
        if category_selected_display == t("เพิ่มหมวดหมู่ใหม่...", "Add New Category..."):
            new_category_name = st.text_input(t("ชื่อหมวดหมู่ใหม่", "New Category Name"), "")
            category_to_save = new_category_name if new_category_name else "Others"
        else:
            category_to_save = next((k for k, v in CATEGORY_MAP.items() if v == category_selected_display), category_selected_display)

        amount = st.number_input("💰 " + t("จำนวนเงิน", "Amount"), min_value=0.0, step=1.0, format="%.2f")
        note = st.text_input("📝 " + t("หมายเหตุ (ถ้ามี)", "Note (optional)"), "")
        submitted = st.form_submit_button(t("✅ บันทึก", "✅ Save"))
        
        if submitted:
            type_to_save = "Income" if entry_type_selected == t("รายรับ", "Income") else "Expense"
            try:
                sheet.append_row([str(date), type_to_save, category_to_save, amount, note])
                st.success(t("บันทึกเรียบร้อยแล้ว!", "Entry saved!"))
                st.cache_data.clear() # Invalidate cache
                st.session_state.df_main = load_data_from_sheet_cached(sheet, STANDARD_COLS_MAIN, { # Reload main df
                    'Date': datetime, 'Amount': float, 'Type': str, 'Category': str, 'Note': str
                })
                if not st.session_state.df_main.empty:
                    st.session_state.df_main['Type'] = st.session_state.df_main['Type'].apply(lambda x: "Income" if x == "รายรับ" else ("Expense" if x == "รายจ่าย" else x))
                    st.session_state.df_main['Category'] = st.session_state.df_main['Category'].apply(lambda x: REVERSE_CATEGORY_MAP.get(x, x))
            except gspread.exceptions.GSpreadException as e:
                st.error(f"{t('เกิดข้อผิดพลาดในการบันทึกรายการ:', 'Error saving entry:')} {e}")
            except Exception as e:
                st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิด:', 'An unexpected error occurred:')} {e}")
            st.rerun()

    st.markdown("---")
    st.markdown(f"### 📊 {t('สรุปรายรับรายจ่าย', 'Dashboard')}")

    col1, col2, col3, col4 = st.columns(4)

    # Custom display for Income
    with col1:
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-label">{"รายรับ" if lang == "ภาษาไทย" else "Income"}</div>
            <div class="metric-value income">+฿{income:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    # Custom display for Expense
    with col2:
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-label">{"รายจ่าย" if lang == "ภาษาไทย" else "Expense"}</div>
            <div class="metric-value expense">-฿{expense:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    # Custom display for Balance
    with col3:
        balance_sign = "+" if balance >= 0 else "" # No explicit '+' for positive balance
        balance_class = "positive" if balance >= 0 else "negative"
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-label">{"คงเหลือ" if lang == "ภาษาไทย" else "Balance"}</div>
            <div class="metric-value balance {balance_class}">{balance_sign}฿{balance:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    # Custom display for Spendable/Day
    with col4:
        spendable_sign = "+" if suggested_daily >= 0 else "" # No explicit '+' for positive spendable
        spendable_class = "positive" if suggested_daily >= 0 else "negative"
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-label">{"ยอดเงินที่ใช้ได้ต่อวัน" if lang == "ภาษาไทย" else "Spendable/Day"}</div>
            <div class="metric-value spendable {spendable_class}">{spendable_sign}฿{suggested_daily:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"### 📈 {t('ภาพรวมกราฟ', 'Interactive Graphs Overview')}")

    # New selectors for graph aggregation and period
    graph_aggregation_options = [t("รายวัน", "Daily"), t("รายสัปดาห์", "Weekly"), t("รายเดือน", "Monthly"), t("รายปี", "Yearly")]
    selected_graph_aggregation = st.radio(t("แสดงกราฟแบบ", "Show graphs by"), graph_aggregation_options, horizontal=True, key="graph_aggregation_radio")

    graph_period_options = [t("เดือนปัจจุบัน", "Current Month"), t("3 เดือนล่าสุด", "Last 3 Months"), t("ปีปัจจุบัน", "Current Year"), t("ทั้งหมด", "All Time")]
    selected_graph_period = st.selectbox(t("ช่วงเวลาสำหรับกราฟ", "Period for graphs"), graph_period_options, key="graph_period_selectbox")

    # Filter df_combined based on selected_graph_period
    df_filtered_for_graphs = df_combined.copy()
    if selected_graph_period == t("เดือนปัจจุบัน", "Current Month"):
        df_filtered_for_graphs = df_filtered_for_graphs[
            (df_filtered_for_graphs['Date'].dt.year == today.year) &
            (df_filtered_for_graphs['Date'].dt.month == today.month)
        ]
    elif selected_graph_period == t("3 เดือนล่าสุด", "Last 3 Months"):
        three_months_ago = today - timedelta(days=90)
        df_filtered_for_graphs = df_filtered_for_graphs[df_filtered_for_graphs['Date'] >= three_months_ago]
    elif selected_graph_period == t("ปีปัจจุบัน", "Current Year"):
        df_filtered_for_graphs = df_filtered_for_graphs[df_filtered_for_graphs['Date'].dt.year == today.year]
    # "All Time" means no further filtering needed

    # Expense Distribution (Pie Chart)
    expense_df_for_chart = df_filtered_for_graphs[df_filtered_for_graphs['Type'] == "Expense"]
    if not expense_df_for_chart.empty:
        st.markdown(f"#### {t('สัดส่วนรายจ่ายตามหมวดหมู่', 'Expense Distribution by Category')}")
        expense_df_display = expense_df_for_chart.copy()
        expense_df_display['Category_Display'] = expense_df_display['Category'].apply(lambda x: CATEGORY_MAP.get(x, x))

        fig_pie = px.pie(expense_df_display, values='Amount', names='Category_Display',
                         title=t('สัดส่วนรายจ่าย', 'Expense Categories'),
                         hole=0.3)
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info(t("ยังไม่มีข้อมูลรายจ่ายสำหรับแสดงกราฟวงกลมในช่วงเวลาที่เลือก", "No expense data to display pie chart for the selected period."))

    # Spending Over Time (Bar Chart)
    st.markdown(f"#### {t('ยอดใช้จ่ายตามช่วงเวลา', 'Spending Over Time')}")
    if not df_filtered_for_graphs.empty and 'Date' in df_filtered_for_graphs.columns and not df_filtered_for_graphs['Date'].empty:
        # Aggregate based on selected_graph_aggregation
        if selected_graph_aggregation == t("รายวัน", "Daily"):
            spending_summary = df_filtered_for_graphs[df_filtered_for_graphs['Type'] == "Expense"].groupby(df_filtered_for_graphs['Date'].dt.date).agg(
                total_spending=('Amount', 'sum')
            ).reset_index()
            spending_summary.rename(columns={'Date': 'period'}, inplace=True)
            x_label = t('วันที่', 'Date')
        elif selected_graph_aggregation == t("รายสัปดาห์", "Weekly"):
            spending_summary = df_filtered_for_graphs[df_filtered_for_graphs['Type'] == "Expense"].groupby(df_filtered_for_graphs['Date'].dt.to_period('W')).agg(
                total_spending=('Amount', 'sum')
            ).reset_index()
            spending_summary['period'] = spending_summary['Date'].dt.start_time.dt.strftime('%Y-W%U')
            x_label = t('สัปดาห์', 'Week')
        elif selected_graph_aggregation == t("รายเดือน", "Monthly"):
            spending_summary = df_filtered_for_graphs[df_filtered_for_graphs['Type'] == "Expense"].groupby(df_filtered_for_graphs['Date'].dt.to_period('M')).agg(
                total_spending=('Amount', 'sum')
            ).reset_index()
            spending_summary['period'] = spending_summary['Date'].dt.start_time.dt.strftime('%B %Y')
            x_label = t('เดือน', 'Month')
        else: # Yearly
            spending_summary = df_filtered_for_graphs[df_filtered_for_graphs['Type'] == "Expense"].groupby(df_filtered_for_graphs['Date'].dt.to_period('Y')).agg(
                total_spending=('Amount', 'sum')
            ).reset_index()
            spending_summary['period'] = spending_summary['Date'].dt.start_time.dt.strftime('%Y')
            x_label = t('ปี', 'Year')

        if not spending_summary.empty:
            fig_bar = px.bar(spending_summary, x='period', y='total_spending',
                               title=t('ยอดใช้จ่าย', 'Total Spending'),
                               labels={'total_spending': t('ยอดใช้จ่าย (บาท)', 'Spending (THB)'), 'period': x_label},
                               color_discrete_sequence=[current_theme['danger_color']]) # Use danger color for spending
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info(f"{t('ยังไม่มีข้อมูลรายจ่ายสำหรับแสดงกราฟยอดใช้จ่ายแบบ', 'No expense data to display spending chart by')} {selected_graph_aggregation} {t('ในช่วงเวลาที่เลือก', 'for the selected period.')}")
    else:
        st.info(f"{t('ยังไม่มีข้อมูลรายจ่ายสำหรับแสดงกราฟยอดใช้จ่ายแบบ', 'No expense data to display spending chart by')} {selected_graph_aggregation} {t('ในช่วงเวลาที่เลือก', 'for the selected period.')}")

    st.markdown("---")
    st.markdown(f"#### 🗓 {t('มุมมองรายการ', 'Entries View')}")

    view_by_options_table = [t("วัน", "Day"), t("สัปดาห์", "Week"), t("เดือน", "Month")]
    selected_view_by_table = st.radio(t("แสดงรายการแบบ", "Show entries by"), view_by_options_table, horizontal=True, key="table_view_by_radio")

    df_table_view = df_combined.copy() # Start with all combined data

    if selected_view_by_table == t("วัน", "Day"):
        selected_date_table = st.date_input(t("เลือกวันที่", "Select Date"), value=today, key="table_date_input")
        # Fix for AttributeError: 'datetime.date' object has no attribute 'date'
        df_table_view = df_table_view[df_table_view['Date'].dt.date == selected_date_table]
        display_period_title = selected_date_table.strftime('%Y-%m-%d')
    elif selected_view_by_table == t("สัปดาห์", "Week"):
        # Get all unique week strings (e.g., '2023-W01')
        unique_weeks = sorted(df_table_view['WeekYearStr'].dropna().unique().tolist(), reverse=True)
        if unique_weeks:
            # Find the current week's string
            current_week_str = today.strftime('%Y-W%U')
            default_week_index = unique_weeks.index(current_week_str) if current_week_str in unique_weeks else 0
            selected_week_str = st.selectbox(t("เลือกสัปดาห์", "Select Week"), options=unique_weeks, index=default_week_index, key="table_week_selectbox")
            df_table_view = df_table_view[df_table_view['WeekYearStr'] == selected_week_str]
            display_period_title = selected_week_str
        else:
            st.info(t("ไม่มีข้อมูลสำหรับมุมมองรายสัปดาห์", "No data for weekly view."))
            df_table_view = pd.DataFrame(columns=STANDARD_COLS_MAIN) # Empty DF
    else: # Default to Month
        unique_months = sorted(df_table_view['MonthYearStr'].dropna().unique().tolist(), reverse=True)
        if unique_months:
            current_month_str = today.strftime('%B %Y')
            default_month_index = unique_months.index(current_month_str) if current_month_str in unique_months else 0
            selected_month_str = st.selectbox(t("เลือกเดือน", "Select Month"), options=unique_months, index=default_month_index, key="table_month_selectbox")
            df_table_view = df_table_view[df_table_view['MonthYearStr'] == selected_month_str]
            display_period_title = selected_month_str
        else:
            st.info(t("ไม่มีข้อมูลสำหรับมุมมองรายเดือน", "No data for monthly view."))
            df_table_view = pd.DataFrame(columns=STANDARD_COLS_MAIN) # Empty DF

    # Filter out saving goals from the table view
    df_table_view = df_table_view[~df_table_view['Category'].astype(str).str.startswith("Saving Goal:")]

    if not df_table_view.empty:
        st.markdown(f"##### {t('รายการสำหรับ', 'Entries for')} {display_period_title}")
        # Translate Type and Category columns for display
        df_table_view['Type'] = df_table_view['Type'].apply(lambda x: t("รายรับ", "Income") if x == "Income" else t("รายจ่าย", "Expense"))
        df_table_view['Category'] = df_table_view['Category'].apply(lambda x: CATEGORY_MAP.get(x, x))
        
        # Rename columns for display in the dataframe
        df_table_view = df_table_view.rename(columns={
            'Type': t('ประเภท', 'Type'),
            'Category': t('หมวดหมู่', 'Category'),
            'Date': t('วันที่', 'Date'),
            'Amount': t('จำนวนเงิน', 'Amount'),
            'Note': t('หมายเหตุ', 'Note')
        })

        # Apply conditional styling for 'Amount' column
        def color_amount_cell(value, row_type_val):
            if row_type_val == t("รายรับ", "Income"):
                return f"color: {current_theme['accent_color']}; font-weight: bold;"
            elif row_type_val == t("รายจ่าย", "Expense"):
                return f"color: {current_theme['danger_color']}; font-weight: bold;"
            return ""

        styled_df_table_view = df_table_view.style.apply(
            lambda row: [color_amount_cell(row[t('จำนวนเงิน', 'Amount')], row[t('ประเภท', 'Type')]) if col == t('จำนวนเงิน', 'Amount') else "" for col in df_table_view.columns],
            axis=1
        )
        
        st.dataframe(styled_df_table_view.set_properties(
            subset=[t('จำนวนเงิน', 'Amount')], **{'text-align': 'right'} # Optional: align amount to right
        ), use_container_width=True)
    else:
        st.info(t("ไม่มีข้อมูลสำหรับช่วงเวลาที่เลือก", "No data for the selected period."))


# --- Tab 2: Fixed Monthly Expenses Section ---
with tab2:
    st.markdown(f"### {t('ค่าใช้จ่ายประจำเดือน (Fix)', 'Fixed Monthly Expenses')}")

    if not st.session_state.df_fixed_expenses.empty:
        st.markdown(f"#### {t('รายการค่าใช้จ่าย Fix', 'Your Fixed Expenses')}")
        edited_fixed_df = st.data_editor(
            st.session_state.df_fixed_expenses, # Read from session state
            num_rows="dynamic", 
            use_container_width=True,
            key="fixed_expenses_editor" # Add a key
        )
        st.session_state.df_fixed_expenses = edited_fixed_df # Crucial: update session state immediately

        if st.button("💾 " + t("บันทึกค่าใช้จ่าย Fix", "Save Fixed Expenses")):
            try:
                fixed_expenses_sheet.clear()
                fixed_expenses_sheet.append_row(STANDARD_COLS_FIXED)
                for _, row in st.session_state.df_fixed_expenses.iterrows(): # Use session state for saving
                    # Ensure name and amount are not empty
                    if pd.notna(row['Name']) and pd.notna(row['Amount']) and row['Amount'] > 0:
                        fixed_expenses_sheet.append_row([str(row['Name']), float(row['Amount'])])
                st.success(t("อัปเดตค่าใช้จ่าย Fix สำเร็จแล้ว", "Fixed expenses updated successfully"))
                st.cache_data.clear() # Invalidate cache
                st.session_state.df_fixed_expenses = load_data_from_sheet_cached(fixed_expenses_sheet, STANDARD_COLS_FIXED, {
                    'Amount': float, 'Name': str
                }) # Reload into session state
            except gspread.exceptions.GSpreadException as e:
                st.error(f"{t('เกิดข้อผิดพลาดในการบันทึกค่าใช้จ่าย Fix:', 'Error saving fixed expenses:')} {e}")
            except Exception as e:
                st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิด:', 'An unexpected error occurred:')} {e}")
            st.rerun()
    else:
        st.info(t("ยังไม่มีค่าใช้จ่าย Fix เพิ่มรายการได้เลย!", "No fixed expenses yet. Add some!"))

    with st.form("add_fixed_expense_form"):
        st.markdown(f"#### {t('เพิ่มค่าใช้จ่าย Fix ใหม่', 'Add New Fixed Expense')}")
        fixed_name = st.text_input(t("ชื่อค่าใช้จ่าย", "Expense Name"))
        fixed_amount = st.number_input(t("จำนวนเงิน", "Amount"), min_value=0.0, step=1.0, format="%.2f")
        add_fixed_submitted = st.form_submit_button(t("➕ เพิ่มค่าใช้จ่าย Fix", "➕ Add Fixed Expense"))

        if add_fixed_submitted and fixed_name and fixed_amount > 0:
            try:
                fixed_expenses_sheet.append_row([fixed_name, fixed_amount])
                st.success(t("เพิ่มค่าใช้จ่าย Fix เรียบร้อยแล้ว!", "Fixed expense added successfully!"))
                st.cache_data.clear() # Invalidate cache
                st.session_state.df_fixed_expenses = load_data_from_sheet_cached(fixed_expenses_sheet, STANDARD_COLS_FIXED, {
                    'Amount': float, 'Name': str
                }) # Reload into session state
            except gspread.exceptions.GSpreadException as e:
                st.error(f"{t('เกิดข้อผิดพลาดในการเพิ่มค่าใช้จ่าย Fix:', 'Error adding fixed expense:')} {e}")
            except Exception as e:
                st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิด:', 'An unexpected error occurred:')} {e}")
            st.rerun()
        elif add_fixed_submitted:
            st.warning(t("กรุณากรอกชื่อและจำนวนเงินสำหรับค่าใช้จ่าย Fix", "Please enter a name and amount for the fixed expense."))

    st.markdown("---")
    st.markdown(f"### {t('ยอดเงินคงเหลือสำหรับเดือนหน้า', 'Remaining for Next Month')}")
    st.metric(t("คงเหลือหลังหักค่าใช้จ่าย Fix", "Balance After Fixed Expenses"), f"฿{remaining_after_fixed:,.2f}")


# --- Tab 3: All Entries (Editable Table) ---
with tab3:
    st.markdown(f"### {t('รายการทั้งหมด (ลบ/แก้ไข)', 'All Entries (Edit/Delete)')}")
    
    df_display_main = st.session_state.df_main.copy() # Use session state for display
    if 'Date' in df_display_main.columns:
        df_display_main['Date'] = df_display_main['Date'].dt.strftime('%Y-%m-%d')
    df_display_main['Type'] = df_display_main['Type'].apply(lambda x: t("รายรับ", "Income") if x == "Income" else t("รายจ่าย", "Expense"))
    df_display_main['Category'] = df_display_main['Category'].apply(lambda x: CATEGORY_MAP.get(x, x))

    edited_df = st.data_editor(
        df_display_main, 
        num_rows="dynamic", 
        use_container_width=True,
        key="main_entries_editor" # Add a key
    )
    st.session_state.df_main_edited_temp = edited_df # Store edited data in a temp session state variable

    if st.button("💾 " + t("บันทึกการแก้ไข", "Save Main Entries")):
        try:
            sheet.clear()
            sheet.append_row(STANDARD_COLS_MAIN)
            for _, row in st.session_state.df_main_edited_temp.iterrows(): # Use temp session state for saving
                date_str = str(row['Date']) if pd.notna(row['Date']) else ''
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    date_obj = None
                
                type_to_save = "Income" if row['Type'] == t("รายรับ", "Income") else "Expense"
                category_to_save = next((k for k, v in CATEGORY_MAP.items() if v == row['Category']), str(row['Category']))

                if date_obj and pd.notna(row['Amount']):
                    sheet.append_row([str(date_obj), type_to_save, category_to_save, float(row['Amount']), str(row['Note']) if pd.notna(row['Note']) else ''])
            st.success(t("อัปเดตรายการหลักสำเร็จแล้ว", "Main entries updated successfully"))
            st.cache_data.clear() # Invalidate cache
            st.session_state.df_main = load_data_from_sheet_cached(sheet, STANDARD_COLS_MAIN, { # Reload main df
                'Date': datetime, 'Amount': float, 'Type': str, 'Category': str, 'Note': str
            })
            if not st.session_state.df_main.empty:
                st.session_state.df_main['Type'] = st.session_state.df_main['Type'].apply(lambda x: "Income" if x == "รายรับ" else ("Expense" if x == "รายจ่าย" else x))
                st.session_state.df_main['Category'] = st.session_state.df_main['Category'].apply(lambda x: REVERSE_CATEGORY_MAP.get(x, x))
        except gspread.exceptions.GSpreadException as e:
            st.error(f"{t('เกิดข้อผิดพลาดในการบันทึกการแก้ไข:', 'Error saving edits:')} {e}")
        except Exception as e:
            st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิด:', 'An unexpected error occurred:')} {e}")
        st.rerun()

# --- Tab 4: Plan for Next Month (New Tab) ---
with tab4:
    st.markdown(f"### {t('วางแผนสำหรับเดือนหน้า', 'Plan for Next Month')}")

    next_month_date_obj = today.replace(day=1) + timedelta(days=32)
    next_month_date_obj = next_month_date_obj.replace(day=1)
    
    all_plan_months_periods = set()
    if not st.session_state.df_monthly_plans.empty:
        all_plan_months_periods.update(st.session_state.df_monthly_plans['MonthYear'].dt.to_period('M').unique().tolist())
    
    current_period = pd.Period(year=today.year, month=today.month, freq='M')
    next_period = pd.Period(year=next_month_date_obj.year, month=next_month_date_obj.month, freq='M')
    
    all_plan_months_periods.add(current_period)
    all_plan_months_periods.add(next_period)
    
    sorted_plan_months_dates = sorted([p.start_time for p in all_plan_months_periods], reverse=True)
    
    month_options_display = [
        f"{t(calendar.month_name[m.month], m.strftime('%B'))} {m.year}" for m in sorted_plan_months_dates
    ]
    
    default_next_month_display = f"{t(calendar.month_name[next_month_date_obj.month], next_month_date_obj.strftime('%B'))} {next_month_date_obj.year}"
    
    try:
        default_index = month_options_display.index(default_next_month_display)
    except ValueError:
        default_index = 0

    selected_plan_month_display = st.selectbox(
        t("เลือกเดือนที่ต้องการวางแผน", "Select Month to Plan"),
        options=month_options_display,
        index=default_index,
        key="select_plan_month"
    )
    
    try:
        if lang == "ภาษาไทย":
            thai_month_name_map = {
                "มกราคม": "January", "กุมภาพันธ์": "February", "มีนาคม": "March",
                "เมษายน": "April", "พฤษภาคม": "May", "มิถุนายน": "June",
                "กรกฎาคม": "July", "สิงหาคม": "August", "กันยายน": "September",
                "ตุลาคม": "October", "พฤศจิกายน": "November", "ธันวาคม": "December"
            }
            thai_month_part = selected_plan_month_display.split(' ')[0]
            english_month_part = thai_month_name_map.get(thai_month_part, thai_month_part)
            selected_plan_month = datetime.strptime(f"{english_month_part} {selected_plan_month_display.split(' ')[1]}", "%B %Y")
        else:
            selected_plan_month = datetime.strptime(selected_plan_month_display, "%B %Y")
    except ValueError:
        st.error(t("เกิดข้อผิดพลาดในการแยกวิเคราะห์วันที่", "Error parsing date. Please select month again."))
        selected_plan_month = next_month_date_obj

    current_month_plan_df = st.session_state.df_monthly_plans[ # Use session state
        (st.session_state.df_monthly_plans['MonthYear'].dt.year == selected_plan_month.year) &
        (st.session_state.df_monthly_plans['MonthYear'].dt.month == selected_plan_month.month)
    ].copy()

    planned_income_for_month = current_month_plan_df[
        (current_month_plan_df['ItemType'] == "Income")
    ]['Amount'].sum()

    with st.form("plan_income_form"):
        st.markdown(f"#### {t('รายได้ที่คาดว่าจะได้รับเดือน', 'Expected Income for')} {selected_plan_month_display}")
        new_planned_income = st.number_input(
            t("จำนวนเงินเดือนที่คาดว่าจะได้รับ", "Expected Monthly Salary"),
            min_value=0.0,
            value=float(planned_income_for_month),
            step=1.0,
            format="%.2f",
            key="planned_income_input"
        )
        save_income_plan = st.form_submit_button(t("💾 บันทึกรายได้ที่คาดไว้", "💾 Save Expected Income"))
        if save_income_plan:
            try:
                # Filter out existing income for this month from session state df
                df_monthly_plans_updated = st.session_state.df_monthly_plans[
                    ~((st.session_state.df_monthly_plans['MonthYear'].dt.year == selected_plan_month.year) &
                      (st.session_state.df_monthly_plans['MonthYear'].dt.month == selected_plan_month.month) &
                      (st.session_state.df_monthly_plans['ItemType'] == "Income"))
                ].copy() # Make a copy to avoid SettingWithCopyWarning

                new_income_row = {
                    "MonthYear": selected_plan_month,
                    "ItemType": "Income",
                    "ItemName": "Expected Salary",
                    "Amount": new_planned_income,
                    "Category": "",
                    "IsPaid": False,
                    "DatePaid": None
                }
                st.session_state.df_monthly_plans = pd.concat([df_monthly_plans_updated, pd.DataFrame([new_income_row])], ignore_index=True) # Update session state
                
                monthly_plans_sheet.clear()
                monthly_plans_sheet.append_row(STANDARD_COLS_MONTHLY_PLAN)
                for _, row in st.session_state.df_monthly_plans.iterrows(): # Use session state for saving
                    monthly_plans_sheet.append_row([
                        str(row['MonthYear'].date()), str(row['ItemType']), str(row['ItemName']),
                        float(row['Amount']), str(row['Category']), bool(row['IsPaid']),
                        str(row['DatePaid'].date()) if pd.notna(row['DatePaid']) else ''
                    ])
                st.success(t("บันทึกแผนรายได้สำเร็จแล้ว!", "Planned income saved successfully!"))
                st.cache_data.clear()
                st.session_state.df_monthly_plans = load_data_from_sheet_cached(monthly_plans_sheet, STANDARD_COLS_MONTHLY_PLAN, {
                    'MonthYear': datetime, 'Amount': float, 'IsPaid': bool, 'DatePaid': datetime,
                    'ItemType': str, 'ItemName': str, 'Category': str
                }) # Reload into session state
                if not st.session_state.df_monthly_plans.empty:
                    st.session_state.df_monthly_plans = st.session_state.df_monthly_plans.dropna(subset=['MonthYear'])
            except gspread.exceptions.GSpreadException as e:
                st.error(f"{t('เกิดข้อผิดพลาดในการบันทึกแผนรายได้:', 'Error saving planned income:')} {e}")
            except Exception as e:
                st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิด:', 'An unexpected error occurred:')} {e}")
            st.rerun()

    st.markdown(f"#### {t('ค่าใช้จ่ายที่วางแผนไว้เดือน', 'Planned Expenses for')} {selected_plan_month_display}")

    existing_planned_expenses = current_month_plan_df[
        (current_month_plan_df['ItemType'] == "Expense")
    ].copy()

    fixed_expenses_to_add = []
    if not st.session_state.df_fixed_expenses.empty: # Use session state
        for idx, row in st.session_state.df_fixed_expenses.iterrows():
            fixed_name = str(row['Name'])
            if not ((existing_planned_expenses['ItemName'] == fixed_name) & 
                    (existing_planned_expenses['Category'] == "Fixed Expense")).any():
                fixed_expenses_to_add.append({
                    "MonthYear": selected_plan_month,
                    "ItemType": "Expense",
                    "ItemName": fixed_name,
                    "Amount": float(row['Amount']),
                    "Category": "Fixed Expense",
                    "IsPaid": False,
                    "DatePaid": None
                })
    
    df_fixed_expenses_as_planned = pd.DataFrame(fixed_expenses_to_add, columns=STANDARD_COLS_MONTHLY_PLAN)
    df_fixed_expenses_as_planned['MonthYear'] = pd.to_datetime(df_fixed_expenses_as_planned['MonthYear'])
    df_fixed_expenses_as_planned['IsPaid'] = df_fixed_expenses_as_planned['IsPaid'].astype(bool)

    planned_expense_editor_cols = ['ItemName', 'Amount', 'Category', 'IsPaid']
    existing_planned_expenses_for_editor = existing_planned_expenses[planned_expense_editor_cols].copy()
    existing_planned_expenses_for_editor['Category'] = existing_planned_expenses_for_editor['Category'].apply(lambda x: CATEGORY_MAP.get(x, x))

    fixed_expenses_for_editor = df_fixed_expenses_as_planned[['ItemName', 'Amount', 'Category', 'IsPaid']].copy()
    fixed_expenses_for_editor['Category'] = fixed_expenses_for_editor['Category'].apply(lambda x: CATEGORY_MAP.get(x, x))

    initial_planned_expenses_for_editor = pd.concat([existing_planned_expenses_for_editor, fixed_expenses_for_editor], ignore_index=True)
    
    edited_planned_expenses_df = st.data_editor(
        initial_planned_expenses_for_editor,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "IsPaid": st.column_config.CheckboxColumn(t("จ่ายแล้ว", "Paid"), default=False, disabled=True),
            "Amount": st.column_config.NumberColumn(t("จำนวนเงิน", "Amount"), format="%.2f"),
            "Category": st.column_config.SelectboxColumn(
                t("หมวดหมู่", "Category"),
                options=[t(v, k) for k,v in CATEGORY_MAP.items() if k != "Fixed Expense"],
                required=True,
            )
        },
        key="planned_expenses_editor" # Add a key
    )
    st.session_state.df_monthly_plans_edited_temp = edited_planned_expenses_df # Store edited data in temp session state

    if st.button("💾 " + t("บันทึกแผนค่าใช้จ่าย", "💾 Save Planned Expenses")):
        try:
            # Filter out existing expenses for this month from session state df
            df_monthly_plans_updated = st.session_state.df_monthly_plans[
                ~((st.session_state.df_monthly_plans['MonthYear'].dt.year == selected_plan_month.year) &
                  (st.session_state.df_monthly_plans['MonthYear'].dt.month == selected_plan_month.month) &
                  (st.session_state.df_monthly_plans['ItemType'] == "Expense"))
            ].copy() # Make a copy

            updated_expense_plan_rows = []
            for _, row in st.session_state.df_monthly_plans_edited_temp.iterrows(): # Use temp session state for saving
                if pd.notna(row['ItemName']) and pd.notna(row['Amount']) and row['Amount'] > 0:
                    category_to_save = next((k for k, v in CATEGORY_MAP.items() if v == row['Category']), str(row['Category']))
                    
                    existing_item = current_month_plan_df[ # Use current_month_plan_df for existing status
                        (current_month_plan_df['ItemName'] == str(row['ItemName'])) &
                        (current_month_plan_df['Category'] == category_to_save)
                    ]
                    
                    is_paid_status = False
                    date_paid_status = None
                    if not existing_item.empty:
                        is_paid_status = bool(existing_item['IsPaid'].iloc[0])
                        date_paid_status = existing_item['DatePaid'].iloc[0] if pd.notna(existing_item['DatePaid'].iloc[0]) else None
                    
                    updated_expense_plan_rows.append({
                        "MonthYear": selected_plan_month,
                        "ItemType": "Expense",
                        "ItemName": str(row['ItemName']),
                        "Amount": float(row['Amount']),
                        "Category": category_to_save,
                        "IsPaid": is_paid_status,
                        "DatePaid": date_paid_status
                    })
            
            st.session_state.df_monthly_plans = pd.concat([df_monthly_plans_updated, pd.DataFrame(updated_expense_plan_rows)], ignore_index=True) # Update session state

            monthly_plans_sheet.clear()
            monthly_plans_sheet.append_row(STANDARD_COLS_MONTHLY_PLAN)
            for _, row in st.session_state.df_monthly_plans.iterrows(): # Use session state for saving
                monthly_plans_sheet.append_row([
                    str(row['MonthYear'].date()), str(row['ItemType']), str(row['ItemName']),
                    float(row['Amount']), str(row['Category']), bool(row['IsPaid']),
                    str(row['DatePaid'].date()) if pd.notna(row['DatePaid']) else ''
                ])
            st.success(t("บันทึกแผนค่าใช้จ่ายสำเร็จแล้ว!", "Planned expenses saved successfully!"))
            st.cache_data.clear()
            st.session_state.df_monthly_plans = load_data_from_sheet_cached(monthly_plans_sheet, STANDARD_COLS_MONTHLY_PLAN, { # Reload monthly plans df
                'MonthYear': datetime, 'Amount': float, 'IsPaid': bool, 'DatePaid': datetime,
                'ItemType': str, 'ItemName': str, 'Category': str
            })
            if not st.session_state.df_monthly_plans.empty:
                st.session_state.df_monthly_plans = st.session_state.df_monthly_plans.dropna(subset=['MonthYear'])
        except gspread.exceptions.GSpreadException as e:
            st.error(f"{t('เกิดข้อผิดพลาดในการบันทึกแผนค่าใช้จ่าย:', 'Error saving planned expenses:')} {e}")
        except Exception as e:
            st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิด:', 'An unexpected error occurred:')} {e}")
        st.rerun()

    st.markdown("---")
    st.markdown(f"### {t('จัดการการจ่ายเงินประจำเดือน', 'Monthly Payment Management')}")

    if today.day >= 25 and selected_plan_month.year == today.year and selected_plan_month.month == today.month:
        st.warning(t("ถึงเวลาจัดการค่าใช้จ่ายเดือน", "It's time to manage expenses for") + f" {t(calendar.month_name[today.month], today.strftime('%B'))} {today.year}!")
        
        current_month_actionable_expenses = st.session_state.df_monthly_plans[ # Use session state
            (st.session_state.df_monthly_plans['MonthYear'].dt.year == today.year) &
            (st.session_state.df_monthly_plans['MonthYear'].dt.month == today.month) &
            (st.session_state.df_monthly_plans['ItemType'] == "Expense") &
            (st.session_state.df_monthly_plans['IsPaid'] == False)
        ].copy()

        if not current_month_actionable_expenses.empty:
            st.markdown(f"#### {t('รายการที่ต้องจ่าย', 'Items to Pay')}")
            
            actionable_display_df = current_month_actionable_expenses[['ItemName', 'Amount', 'Category', 'IsPaid']].copy()
            actionable_display_df['Category'] = actionable_display_df['Category'].apply(lambda x: CATEGORY_MAP.get(x, x))
            
            edited_actionable_df = st.data_editor(
                actionable_display_df,
                num_rows="fixed",
                use_container_width=True,
                column_config={
                    "IsPaid": st.column_config.CheckboxColumn(t("จ่ายแล้ว", "Paid"), default=False),
                    "Amount": st.column_config.NumberColumn(t("จำนวนเงิน", "Amount"), format="%.2f", disabled=True),
                    "Category": st.column_config.SelectboxColumn(
                        t("หมวดหมู่", "Category"),
                        options=[t(v, k) for k,v in CATEGORY_MAP.items()],
                        disabled=True
                    )
                },
                key="actionable_expenses_editor"
            )
            st.session_state.df_monthly_plans_actionable_temp = edited_actionable_df # Store edited data in temp session state

            if st.button("✅ " + t("อัปเดตสถานะการจ่ายเงิน", "✅ Update Payment Status")):
                try:
                    for index, row in st.session_state.df_monthly_plans_actionable_temp.iterrows(): # Use temp session state for saving
                        original_item_name = str(row['ItemName'])
                        original_category_display = str(row['Category'])
                        original_category_canonical = next((k for k, v in CATEGORY_MAP.items() if v == original_category_display), original_category_display)
                        original_amount = float(row['Amount'])
                        new_is_paid_status = bool(row['IsPaid'])

                        mask = (st.session_state.df_monthly_plans['MonthYear'].dt.year == today.year) & \
                               (st.session_state.df_monthly_plans['MonthYear'].dt.month == today.month) & \
                               (st.session_state.df_monthly_plans['ItemType'] == "Expense") & \
                               (st.session_state.df_monthly_plans['ItemName'] == original_item_name) & \
                               (st.session_state.df_monthly_plans['Category'] == original_category_canonical) & \
                               (st.session_state.df_monthly_plans['Amount'] == original_amount)
                        
                        if new_is_paid_status and not st.session_state.df_monthly_plans.loc[mask, 'IsPaid'].iloc[0]:
                            st.session_state.df_monthly_plans.loc[mask, 'IsPaid'] = True # Update session state
                            st.session_state.df_monthly_plans.loc[mask, 'DatePaid'] = datetime.now() # Update session state

                            sheet.append_row([
                                str(datetime.now().date()),
                                "Expense",
                                original_category_canonical,
                                original_amount,
                                "Paid planned expense: " + original_item_name
                            ])
                            st.success("Expense '" + original_item_name + "' paid!")
                    
                    monthly_plans_sheet.clear()
                    monthly_plans_sheet.append_row(STANDARD_COLS_MONTHLY_PLAN)
                    for _, row in st.session_state.df_monthly_plans.iterrows(): # Use session state for saving
                        monthly_plans_sheet.append_row([
                            str(row['MonthYear'].date()), str(row['ItemType']), str(row['ItemName']),
                            float(row['Amount']), str(row['Category']), bool(row['IsPaid']),
                            str(row['DatePaid']) if pd.notna(row['DatePaid']) else ''
                        ])
                    st.cache_data.clear()
                    st.session_state.df_monthly_plans = load_data_from_sheet_cached(monthly_plans_sheet, STANDARD_COLS_MONTHLY_PLAN, { # Reload monthly plans df
                        'MonthYear': datetime, 'Amount': float, 'IsPaid': bool, 'DatePaid': datetime,
                        'ItemType': str, 'ItemName': str, 'Category': str
                    })
                    if not st.session_state.df_monthly_plans.empty:
                        st.session_state.df_monthly_plans = st.session_state.df_monthly_plans.dropna(subset=['MonthYear'])
                    st.session_state.df_main = load_data_from_sheet_cached(sheet, STANDARD_COLS_MAIN, { # Reload main df
                        'Date': datetime, 'Amount': float, 'Type': str, 'Category': str, 'Note': str
                    })
                    if not st.session_state.df_main.empty:
                        st.session_state.df_main['Type'] = st.session_state.df_main['Type'].apply(lambda x: "Income" if x == "รายรับ" else ("Expense" if x == "รายจ่าย" else x))
                        st.session_state.df_main['Category'] = st.session_state.df_main['Category'].apply(lambda x: REVERSE_CATEGORY_MAP.get(x, x))
                except gspread.exceptions.GSpreadException as e:
                    st.error(f"{t('เกิดข้อผิดพลาดในการอัปเดตสถานะการจ่ายเงิน:', 'Error updating payment status:')} {e}")
                except Exception as e:
                    st.error(f"{t('เกิดข้อผิดพลาดที่ไม่คาดคิด:', 'An unexpected error occurred:')} {e}")
                st.rerun()
        else:
            st.info(t("ไม่มีค่าใช้จ่ายที่ต้องจัดการสำหรับเดือนนี้", "No expenses to manage for this month."))
    elif today.day < 25:
        st.info(t("การจัดการการจ่ายเงินสำหรับเดือน " + t(calendar.month_name[today.month], today.strftime('%B')) + " จะปรากฏขึ้นตั้งแต่วันที่ 25 ของทุกเดือน", "Payment management for " + today.strftime('%B') + " will appear from the 25th of each month."))
    else:
        st.info(t("ส่วนนี้ใช้สำหรับจัดการการจ่ายเงินของเดือนปัจจุบันเท่านั้น", "This section is for managing payments of the current month only."))


# --- Export Section ---
st.markdown("---")
with st.expander("📤 " + t("ส่งออกเป็น Excel", "Export to Excel")):
    def get_excel_download_button(df_to_export, filename, label):
        towrite = BytesIO()
        df_to_export.to_excel(towrite, index=False, engine='openpyxl')
        towrite.seek(0)
        st.download_button(label=label, data=towrite, file_name=filename)
    
    # Export main budget data
    df_export = df.copy()
    if 'Type' in df_export.columns:
        df_export['Type'] = df_export['Type'].apply(lambda x: t("รายรับ", "Income") if x == "Income" else t("รายจ่าย", "Expense"))
    if 'Category' in df_export.columns:
        df_export['Category'] = df_export['Category'].apply(lambda x: CATEGORY_MAP.get(x, x))
    get_excel_download_button(df_export, "budget_data.xlsx", "📥 Download Budget Data")

    # Export fixed expenses
    if not df_fixed_expenses.empty:
        get_excel_download_button(df_fixed_expenses, "fixed_expenses.xlsx", "📥 Download Fixed Expenses")

    # Export monthly plans
    if not df_monthly_plans.empty:
        df_monthly_plans_export = df_monthly_plans.copy()
        df_monthly_plans_export['Category'] = df_monthly_plans_export['Category'].apply(lambda x: CATEGORY_MAP.get(x, x))
        get_excel_download_button(df_monthly_plans_export, "monthly_plans.xlsx", "📥 Download Monthly Plans")


# Smart Tip
st.markdown("---")
st.markdown(f"#### {t('คำแนะนำอัจฉริยะ', 'Smart Suggestion')}")
if balance < 0:
    st.warning(t("⚠️ คุณใช้เงินเกินรายรับ! ควรลดค่าใช้จ่าย.", "⚠️ You're overspending! Reduce expenses."))
elif income > 0 and expense / income > 0.7:
    st.info(t("💡 รายจ่ายมากกว่า 70% ของรายรับ ลองทบทวนเป้าหมาย.", "💡 Expenses >70% of income. Recheck your goals."))
else:
    st.success(t("👍 คุณบริหารเงินได้ดี!", "👍 Great money management!"))

st.markdown("<hr>", unsafe_allow_html=True)
st.caption("💡 Powered by ChatGPT - Designed for real-life daily use")
�
