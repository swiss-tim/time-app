import streamlit as st
import pandas as pd
import altair as alt

@st.cache_data
def load_time_data():
    df = pd.read_csv("data/time.csv", on_bad_lines='skip')
    return df

df_time = load_time_data()
st.write(df_time.head())
st.write("Non-null activityStartDate:", df_time['activityStartDate'].notnull().sum())
st.write("Non-null activityEndDate:", df_time['activityEndDate'].notnull().sum())
st.write("Non-null activityDuration:", pd.to_numeric(df_time['activityDuration'], errors='coerce').notnull().sum())

st.subheader("Categories Over Time")

# --- Use correct column names from your CSV ---
required_cols = {'activityCategoryName', 'activityStartDate', 'activityEndDate', 'activityDuration'}
if required_cols.issubset(df_time.columns):
    df_time['activityStartDate'] = pd.to_datetime(df_time['activityStartDate'])
    df_time['activityEndDate'] = pd.to_datetime(df_time['activityEndDate'])
    df_time['activityDuration'] = pd.to_numeric(df_time['activityDuration'], errors='coerce')

    # Expand each row to daily records
    records = []
    for _, row in df_time.iterrows():
        days = (row['activityEndDate'] - row['activityStartDate']).days + 1
        if days <= 0 or pd.isna(row['activityDuration']):
            continue
        daily_duration = row['activityDuration'] / days
        for i in range(days):
            day = row['activityStartDate'] + pd.Timedelta(days=i)
            records.append({
                'date': day,
                'category': row['activityCategoryName'],
                'daily_duration': daily_duration
            })
    df_daily = pd.DataFrame(records)

    # --- Check for valid daily records ---
    if df_daily.empty or 'date' not in df_daily.columns:
        st.warning("No valid daily records found. Check your CSV data for valid dates and durations.")
    else:
        # --- Date range selector ---
        st.write("Select time range:")
        date_max = df_daily['date'].max()
        date_min = df_daily['date'].min()
        range_type = st.selectbox("Range", ["All", "Quarter", "Month", "Week", "Day"])

        if range_type == "All":
            date_from = date_min
        elif range_type == "Quarter":
            date_from = date_max - pd.DateOffset(months=3)
        elif range_type == "Month":
            date_from = date_max - pd.DateOffset(months=1)
        elif range_type == "Week":
            date_from = date_max - pd.DateOffset(weeks=1)
        elif range_type == "Day":
            date_from = date_max - pd.DateOffset(days=1)

        df_filtered = df_daily[df_daily['date'] >= date_from]

        # Display the filtered DataFrame if you want to see the data
        st.dataframe(df_filtered)

        chart = alt.Chart(df_filtered).mark_line().encode(
            x='date:T',
            y='daily_duration:Q',
            color='category:N',
            tooltip=['date:T', 'category:N', 'daily_duration:Q']
        ).properties(
            width=700,
            height=400,
            title='Category Daily Duration Over Time'
        )

        st.altair_chart(chart, use_container_width=True)
else:
    st.warning("CSV must have 'activityCategoryName', 'activityStartDate', 'activityEndDate', and 'activityDuration' columns.")

