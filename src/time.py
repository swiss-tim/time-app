import streamlit as st
import pandas as pd
import altair as alt
import os
import io
import csv
import datetime
import plotly.graph_objects as go
import plotly.express as px  # <-- Add this import at the top with other imports

# Place this near the top of your file, after the imports, so it's available everywhere:
def hours_to_hhmm(hours):
    h = int(hours)
    m = int(round((hours - h) * 60))
    return f"{h:02d}:{m:02d}"

# --- Use caching for expensive IO / processing to make button clicks fast ---
@st.cache_data
def load_csv(path):
    # Load the CSV. Now includes activityName for grouping and notes.
    return pd.read_csv(
        path,
        usecols=['activityCategoryName', 'activityName', 'activityStartDate', 'activityDuration [ms]', 'note'],
        sep=',',
        engine='python'
    )

@st.cache_data
def build_split(df):
    # This function now correctly handles timezone-aware timestamps.
    records = []
    df = df.copy()
    df['activityDuration [ms]'] = pd.to_numeric(df['activityDuration [ms]'], errors='coerce')
    df = df[df['activityDuration [ms]'].notna()].copy()

    # --- FINAL, SIMPLIFIED TIMEZONE FIX ---
    # 1. Parse the date/time part of the string and completely ignore the timezone from the file.
    #    This creates a "naive" datetime object that represents the time exactly as written.
    df['activityStartDate'] = pd.to_datetime(df['activityStartDate'].str.replace(r' GMT[+-]\d{2}:\d{2} ', ' ', regex=True), errors='coerce')
    df.dropna(subset=['activityStartDate'], inplace=True)
    
    # All subsequent calculations will use this naive local time.

    for _, row in df.iterrows():
        start = row['activityStartDate'] # This is now a naive local time.
        duration_ms = float(row['activityDuration [ms]'])
        end = start + pd.Timedelta(milliseconds=duration_ms)
        current = start
        remaining_ms = duration_ms
        while current.date() < end.date():
            next_day = pd.Timestamp(year=current.year, month=current.month, day=current.day) + pd.Timedelta(days=1)
            ms_in_day = (next_day - current).total_seconds() * 1000
            records.append({
                'start': current,
                'end': next_day,
                'activityCategoryName': row['activityCategoryName'],
                'activityName': row['activityName'],  # <-- FIX: preserve activityName
                'note': row.get('note', ''),  # <-- FIX: preserve note
                'duration_hours': ms_in_day / (1000 * 60 * 60)
            })
            remaining_ms -= ms_in_day
            current = next_day
        records.append({
            'start': current,
            'end': end,
            'activityCategoryName': row['activityCategoryName'],
            'activityName': row['activityName'],  # <-- FIX: preserve activityName
            'note': row.get('note', ''),  # <-- FIX: preserve note
            'duration_hours': remaining_ms / (1000 * 60 * 60)
        })
    df_split_local = pd.DataFrame(records)
    if not df_split_local.empty:
        # The 'date' for grouping is derived directly from the naive start time.
        df_split_local['date'] = df_split_local['start'].dt.date
    return df_split_local

# --- Data Loader Section ---
st.title("Time Tracking App")
st.markdown("### Data Loader")

# File upload widget
uploaded_file = st.file_uploader(
    "Choose a CSV file to analyze",
    type=['csv'],
    help="Upload your time tracking data CSV file. If no file is uploaded, the default data will be used."
)

# Determine which file to use
if uploaded_file is not None:
    # Use uploaded file
    try:
        # Read the uploaded file
        df_raw = pd.read_csv(
            uploaded_file,
            usecols=['activityCategoryName', 'activityName', 'activityStartDate', 'activityDuration [ms]', 'note'],
            sep=',',
            engine='python'
        )
        
        # Validate the uploaded file has required columns
        required_columns = ['activityCategoryName', 'activityName', 'activityStartDate', 'activityDuration [ms]']
        missing_columns = [col for col in required_columns if col not in df_raw.columns]
        
        if missing_columns:
            st.error(f"❌ Uploaded file is missing required columns: {', '.join(missing_columns)}")
            st.info("Required columns: activityCategoryName, activityName, activityStartDate, activityDuration [ms]")
            st.info("Falling back to default data file.")
            # Fallback to default file
            csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'time.csv')
            df_raw = load_csv(csv_path)
        else:
            # Check if file has data
            if df_raw.empty:
                st.warning("⚠️ Uploaded file is empty. Falling back to default data file.")
                csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'time.csv')
                df_raw = load_csv(csv_path)
            else:
                st.success(f"✅ Successfully loaded {len(df_raw)} records from uploaded file: {uploaded_file.name}")
                
    except pd.errors.EmptyDataError:
        st.error("❌ Uploaded file is empty or invalid CSV format.")
        st.info("Falling back to default data file.")
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'time.csv')
        df_raw = load_csv(csv_path)
    except Exception as e:
        st.error(f"❌ Error loading uploaded file: {str(e)}")
        st.info("Falling back to default data file.")
        # Fallback to default file
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'time.csv')
        df_raw = load_csv(csv_path)
else:
    # Use default file
    csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'time.csv')
    df_raw = load_csv(csv_path)
    st.info("📁 Using default data file. Upload a CSV file above to analyze your own data.")

# Process the data
df_split = build_split(df_raw)

# Show data summary
if not df_split.empty:
    st.markdown("### Data Summary")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Records", len(df_raw))
    with col2:
        st.metric("Date Range", f"{df_split['date'].min()} to {df_split['date'].max()}")
    with col3:
        st.metric("Activity Categories", df_split['activityCategoryName'].nunique())
else:
    st.warning("⚠️ No valid data found in the selected file.")

# --- BUG FIX for disappearing data ---
# The pre-computed dictionary in session_state is removed to prevent intermittent lookup failures.
# Data will be filtered directly from the main df_split dataframe in the timeline_for_period function.

# --- faster navigation: use on_click handlers that only mutate session state ---
def shift_period_left(period):
    cur = st.session_state.get(f"current_{period}")
    if cur is None:
        st.session_state[f"current_{period}"] = df_split['date'].max()
        return
    if period == "Day":
        st.session_state[f"current_{period}"] = cur - datetime.timedelta(days=1)
    elif period == "Week":
        st.session_state[f"current_{period}"] = cur - datetime.timedelta(weeks=1)
    elif period == "Month":
        month = cur.month - 1 or 12
        year = cur.year - (1 if month == 12 else 0)
        st.session_state[f"current_{period}"] = datetime.date(year, month, min(cur.day, 28))
    elif period == "Year":
        st.session_state[f"current_{period}"] = cur.replace(year=cur.year - 1)

def shift_period_right(period):
    cur = st.session_state.get(f"current_{period}")
    if cur is None:
        st.session_state[f"current_{period}"] = df_split['date'].max()
        return
    if period == "Day":
        st.session_state[f"current_{period}"] = cur + datetime.timedelta(days=1)
    elif period == "Week":
        st.session_state[f"current_{period}"] = cur + datetime.timedelta(weeks=1)
    elif period == "Month":
        month = cur.month + 1
        year = cur.year + (1 if month > 12 else 0)
        month = month if month <= 12 else 1
        st.session_state[f"current_{period}"] = datetime.date(year, month, min(cur.day, 28))
    elif period == "Year":
        st.session_state[f"current_{period}"] = cur.replace(year=cur.year + 1)

# --- 2. Aggregate and Sort Data ---
if not df_split.empty:
    category_duration = df_split.groupby(['date', 'activityCategoryName'])['duration_hours'].sum().unstack(fill_value=0)
    category_duration = category_duration.round(9)

    yearly_totals = df_split.groupby('activityCategoryName')['duration_hours'].sum()
    total_duration_sorted = yearly_totals.sort_values(ascending=False)
    category_duration_sorted = category_duration[total_duration_sorted.index]

    global_category_order = [str(c) for c in total_duration_sorted.index]
else:
    global_category_order = []


# toggle to include/remove Sleep category (controls stacking + legend + pie)
include_sleep = st.checkbox("Include 'Sleep' category", value=True, key='include_sleep')

# active order used for all charts (remove sleep when toggle is off)
if include_sleep:
    active_category_order = global_category_order
else:
    active_category_order = [c for c in global_category_order if str(c).strip().lower() != 'sleep']

# --- 4. Streamlit Altair Chart (moved into tabs so it reflects the period table) ---

def timeline_for_period(period):
    # init current period pointer
    if f"current_{period}" not in st.session_state:
        st.session_state[f"current_{period}"] = df_split['date'].max() if not df_split.empty else datetime.date.today()

    # navigation buttons (fast: only mutate session_state)
    # Custom CSS to make buttons inline
    st.markdown("""
    <style>
    .stButton > button {
        display: inline-block;
        margin: 0 2px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Use actual Streamlit buttons
    col1, col2 = st.columns([1, 1])
    with col1:
        st.button("←", key=f"left_{period}", on_click=shift_period_left, args=(period,))
    with col2:
        st.button("→", key=f"right_{period}", on_click=shift_period_right, args=(period,))

    # --- BUG FIX for disappearing data ---
    # compute date range and fetch rows by filtering the main dataframe directly.
    start_date, end_date = get_period_dates(period, st.session_state.get(f"current_{period}"))
    if not df_split.empty:
        period_df = df_split[(df_split['date'] >= start_date) & (df_split['date'] <= end_date)].copy()
    else:
        period_df = pd.DataFrame(columns=df_split.columns)


    # optionally remove Sleep rows based on toggle
    if not include_sleep and not period_df.empty:
        period_df = period_df[period_df['activityCategoryName'].astype(str).str.lower() != 'sleep']

    # ensure date column exists
    if 'date' not in period_df.columns and 'start' in period_df.columns:
        period_df['date'] = period_df['start'].dt.date

    # Show copyable summary at the top
    if not period_df.empty:
        show_copyable_text(period, period_df)

    # --- Build chart from period_df ---
    if not period_df.empty:
        # Add formatted duration column for tooltips
        period_df['duration_hhmm'] = period_df['duration_hours'].apply(hours_to_hhmm)

        if period == "Day":
            period_df['start_dt'] = pd.to_datetime(period_df['start'])
            period_df['end_dt'] = pd.to_datetime(period_df['end'])
            period_df['Activity Category'] = period_df['activityCategoryName'].astype(str)
            period_df['Activity Category'] = pd.Categorical(
                period_df['Activity Category'],
                categories=active_category_order,
                ordered=True
            )
            rank_map = {cat: i for i, cat in enumerate(global_category_order)}
            period_df['cat_rank'] = period_df['Activity Category'].astype(str).map(rank_map)
            
            bars = alt.Chart(period_df).mark_bar(size=14).encode(
                x=alt.X('start_dt:T',
                        axis=alt.Axis(format='%H', title='', grid=True, tickCount=13, labelLimit=0)),
                x2='end_dt:T',
                y=alt.Y('Activity Category:N',
                        title=None,
                        axis=alt.Axis(labelLimit=0),
                        scale=alt.Scale(domain=active_category_order)),
                color=alt.Color(
                    'Activity Category:N',
                    scale=alt.Scale(domain=global_category_order, scheme='category20'),
                    legend=None
                ),
                tooltip=[
                    alt.Tooltip('activityCategoryName:N', title='Category'),
                    alt.Tooltip('start_dt:T', title='Start', format='%Y-%m-%d %H:%M'),
                    alt.Tooltip('end_dt:T', title='End', format='%Y-%m-%d %H:%M'),
                    alt.Tooltip('duration_hhmm:N', title='Duration (hh:mm)'),
                    alt.Tooltip('activityName:N', title='Activity')
                ]
            )
            chart_day = bars.properties(
                width=900,
                title=f'Day timeline ({st.session_state.get(f"current_{period}")})',
                padding={"left": 10, "top": 10, "right": 10, "bottom": 20}
            ).configure_view(
                discreteHeight={'step': 20}
            )
            st.altair_chart(chart_day, use_container_width=True)

        else:
            agg = period_df.groupby(['date', 'activityCategoryName'])['duration_hours'].sum().unstack(fill_value=0)
            agg = agg.sort_index()
            df_melt_period = agg.reset_index().melt(id_vars='date', var_name='Activity Category', value_name='Duration (hours)')
            df_melt_period['date'] = pd.to_datetime(df_melt_period['date'])
            df_melt_period['Duration (hours)'] = pd.to_numeric(df_melt_period['Duration (hours)'], errors='coerce').fillna(0)
            df_melt_period = df_melt_period[df_melt_period['Duration (hours)'] > 0]
            df_melt_period['Activity Category'] = pd.Categorical(
                df_melt_period['Activity Category'].astype(str),
                categories=active_category_order,
                ordered=True
            )
            rank_map = {cat: i for i, cat in enumerate(global_category_order)}
            df_melt_period['cat_rank'] = df_melt_period['Activity Category'].astype(str).map(rank_map)
            # Add formatted duration column for tooltips
            df_melt_period['duration_hhmm'] = df_melt_period['Duration (hours)'].apply(hours_to_hhmm)

            if df_melt_period.empty:
                st.info("No non-zero activity durations in this period to chart.")
            else:
                n_cats = df_melt_period['Activity Category'].nunique()
                height_px = max(300, 75 * max(1, n_cats))

                chart_period = alt.Chart(df_melt_period).mark_area().encode(
                    x='date:T',
                    y=alt.Y('Duration (hours):Q', stack='zero'),
                    color=alt.Color(
                        'Activity Category:N',
                        scale=alt.Scale(domain=global_category_order, scheme='category20'),
                        legend=alt.Legend(title='Activity Category', orient='bottom', direction='horizontal', columns=5)
                    ),
                    order=alt.Order('cat_rank:Q', sort='ascending'),
                    tooltip=[
                        alt.Tooltip('date:T', title='Date'),
                        alt.Tooltip('Activity Category:N', title='Category'),
                        alt.Tooltip('duration_hhmm:N', title='Duration (hh:mm)')
                    ]
                ).properties(
                    width=900,
                    height=height_px,
                    title=f'Activity Duration ({period})'
                )
                st.altair_chart(chart_period, use_container_width=True)
    else:
        st.info("No activities in this period to chart.")

    # --- Timeline (below chart) ---
    timeline_display = period_df.copy().sort_values(['start'], ascending=False)
    if not timeline_display.empty:
        # The 'start' and 'end' columns are already naive local times.
        timeline_display['Start Date'] = pd.to_datetime(timeline_display['start']).dt.strftime('%b-%d %a %H:%M')
        timeline_display['End Date'] = pd.to_datetime(timeline_display['end']).dt.strftime('%b-%d %a %H:%M')
    
    # Pie chart: show category share for the selected period using the same colors
    if not period_df.empty:
        pie_df = (period_df.groupby('activityCategoryName')['duration_hours']
                    .sum()
                    .rename_axis('Category')
                    .reset_index())
        pie_df['Category'] = pie_df['Category'].astype(str)
        pie_df = pie_df[pie_df['duration_hours'] > 0]

        if not pie_df.empty:
            pie_df['Percentage'] = (pie_df['duration_hours'] / pie_df['duration_hours'].sum() * 100).round(1)
            pie_labels = pie_df.apply(lambda r: f"{r['Category']}<br>{r['Percentage']}%", axis=1)
            # Use hours_to_hhmm for hover text
            pie_hovertext = pie_df.apply(lambda r: f"{r['Category']}<br>{r['Percentage']}%<br>{hours_to_hhmm(r['duration_hours'])} h", axis=1)

            # Define color_map here using Altair's category20 palette and global_category_order
            alt_category20 = [
                "#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a",
                "#d62728", "#ff9896", "#9467bd", "#c5b0d5", "#8c564b", "#c49c94",
                "#e377c2", "#f7b6d2", "#7f7f7f", "#c7c7c7", "#bcbd22", "#dbdb8d",
                "#17becf", "#9edae5"
            ]
            color_map = {cat: alt_category20[i % len(alt_category20)] for i, cat in enumerate(global_category_order)}
            pie_colors = [color_map.get(cat, "#CCCCCC") for cat in pie_df['Category']]

            fig = go.Figure()
            fig.add_trace(go.Pie(
                labels=pie_df['Category'],
                values=pie_df['duration_hours'],
                text=pie_labels,
                textinfo='label+percent',
                hoverinfo='text',
                hovertext=pie_hovertext,
                insidetextorientation='horizontal',
                marker=dict(colors=pie_colors),
                showlegend=False
            ))
            fig.update_traces(textposition='auto', insidetextorientation='horizontal')
            fig.update_layout(
                title=f'Category share ({period})',
                height=600,
                width=600,
                showlegend=False,
                legend=None
            )
            st.plotly_chart(fig, use_container_width=False)
    # table
    if not timeline_display.empty:
        cols = ['activityCategoryName']
        if 'activityName' in timeline_display.columns:
            cols.insert(0, 'activityName')
        if 'note' in timeline_display.columns:
            cols += ['note']
        cols += ['Start Date', 'End Date', 'duration_hours']
        cols = [c for c in cols if c in timeline_display.columns]
        st.subheader(f"Timeline ({period})")
        st.dataframe(timeline_display[cols].rename(columns={
            'activityName': 'Activity Name',
            'activityCategoryName': 'Category',
            'duration_hours': 'Duration (hours)',
            'note': 'Notes'
        }), height=300)

def show_copyable_text(period, period_df):
    # Get the date range for the selected tab
    start_date, end_date = get_period_dates(period, st.session_state.get(f"current_{period}"))
    df = period_df.copy()
    has_activity = 'activityName' in df.columns

    # Calculate total hours for percentage calculations
    total_hours = df['duration_hours'].sum()
    
    # Use the same order for categories as in the timeline
    ordered_cats = [cat for cat in global_category_order if cat in df['activityCategoryName'].unique()]
    lines = []
    for cat in ordered_cats:
        cat_df = df[df['activityCategoryName'] == cat]
        if cat_df.empty:
            continue
        total_cat_hours = cat_df['duration_hours'].sum()
        cat_percentage = int(round((total_cat_hours / total_hours) * 100)) if total_hours > 0 else 0
        lines.append(f"{cat_percentage:02d}% {hours_to_hhmm(total_cat_hours)}h {cat}")
        if has_activity:
            # Get activities with their total durations and sort by duration (descending)
            activity_durations = []
            for act in cat_df['activityName'].unique():
                act_df = cat_df[cat_df['activityName'] == act]
                act_hours = act_df['duration_hours'].sum()
                activity_durations.append((act, act_hours, act_df))
            
            # Sort by duration (longest first)
            activity_durations.sort(key=lambda x: x[1], reverse=True)
            
            for act, act_hours, act_df in activity_durations:
                # Calculate activity percentage of total time
                act_percentage = int(round((act_hours / total_hours) * 100)) if total_hours > 0 else 0
                
                # Collect unique notes for this activity
                notes = act_df['note'].dropna().astype(str).str.strip()
                notes = notes[notes != ''].unique()
                
                if len(notes) > 0:
                    notes_str = ', '.join(notes[:3])  # Limit to first 3 notes
                    if len(notes) > 3:
                        notes_str += f' (+{len(notes)-3} more)'
                    lines.append(f"   └─ {act_percentage:02d}% {hours_to_hhmm(act_hours)}h {act} ({notes_str})")
                else:
                    lines.append(f"   └─ {act_percentage:02d}% {hours_to_hhmm(act_hours)}h {act}")
        else:
            for _, row in cat_df.iterrows():
                lines.append(f"   └─ {hours_to_hhmm(row['duration_hours'])} h")
    text_block = "\n".join(lines)
    
    # Simple title without buttons
    st.subheader(f"📋 {period} ({start_date} to {end_date})")
    
    # Display the text in a simple, selectable format
    st.text_area(
        "Summary",
        text_block,
        height=350,
        key=f"summary_{period}",
        help="Select all text (Ctrl+A) and copy (Ctrl+C)"
    )

# --- add missing helper and tabs so charts update when session_state changes ---
def get_period_dates(period, current_date):
    # normalize to datetime.date
    if current_date is None:
        current_date = datetime.date.today()
    if isinstance(current_date, pd.Timestamp):
        current_date = current_date.date()
    if isinstance(current_date, datetime.datetime):
        current_date = current_date.date()

    if period == "Day":
        start = end = current_date
    elif period == "Week":
        start = current_date - datetime.timedelta(days=current_date.weekday())
        end = start + datetime.timedelta(days=6)
    elif period == "Month":
        start = current_date.replace(day=1)
        # get first day of next month then subtract one day
        next_month = (pd.Timestamp(start) + pd.Timedelta(days=32)).replace(day=1).date()
        end = next_month - datetime.timedelta(days=1)
    elif period == "Year":
        start = current_date.replace(month=1, day=1)
        end = current_date.replace(month=12, day=31)
    else:
        start = end = current_date
    return start, end

# create the tabs once (so with tab_day: ... works later)
tab_day, tab_week, tab_month, tab_year = st.tabs(["Day", "Week", "Month", "Year"])

# attach tabs (chart + timeline per tab)
with tab_day:
    timeline_for_period("Day")
with tab_week:
    timeline_for_period("Week")
with tab_month:
    timeline_for_period("Month")
with tab_year:
    timeline_for_period("Year")

