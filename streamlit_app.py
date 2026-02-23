import streamlit as st
import requests
import json
import pandas as pd
import os

st.set_page_config(
    page_title="KAI Comprehensive Analytics",
    page_icon="📊",
    layout="wide"
)

API_BASE = os.getenv("KAI_API_URL", "https://kai-forked-698617680311.asia-southeast2.run.app")

st.title("📊 KAI Comprehensive SQL Analytics")
st.markdown("Query your database using natural language.")

# --- HELPERS ---
@st.cache_data(ttl=1)
def fetch_connections():
    try:
        response = requests.get(f"{API_BASE}/api/v1/database-connections", timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return []

@st.cache_data(ttl=1)
def fetch_tables(db_conn_id):
    if not db_conn_id: return []
    try:
        response = requests.get(f"{API_BASE}/api/v1/table-descriptions?db_connection_id={db_conn_id}", timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return []

def add_connection(alias, uri, schemas):
    try:
        payload = {
            "alias": alias,
            "connection_uri": uri,
            "schemas": [s.strip() for s in schemas.split(",")] if schemas else []
        }
        res = requests.post(f"{API_BASE}/api/v1/database-connections", json=payload, timeout=10)
        return res.status_code in [200, 201], res.text
    except Exception as e:
        return False, str(e)

def format_connection_options(connections):
    if not connections:
        return {}
    return {c["id"]: f"{c.get('alias', 'Unnamed')} ({c['id']})" for c in connections}

# --- SIDEBAR: Configuration ---
with st.sidebar:
    st.header("1. Database Connection")
    
    # State management for connections
    connections = fetch_connections()
    conn_options = format_connection_options(connections)
    
    # Connection Selection
    db_conn_id = None
    if conn_options:
        selected_key = st.selectbox("Select Connection", options=list(conn_options.keys()), format_func=lambda x: conn_options[x])
        db_conn_id = selected_key
    else:
        st.warning("No connections found.")
        
    # Add Connection UI
    with st.expander("➕ Add New Connection"):
        with st.form("add_conn_form"):
            new_alias = st.text_input("Alias", placeholder="my_database")
            new_uri = st.text_input("Connection URI", type="password", placeholder="postgresql://user:pass@host:5432/db")
            new_schemas = st.text_input("Schemas (comma separated)", placeholder="public")
            if st.form_submit_button("Create Connection"):
                if new_alias and new_uri:
                    with st.spinner("Creating..."):
                        success, detail = add_connection(new_alias, new_uri, new_schemas)
                        if success:
                            st.success("Connection added!")
                            fetch_connections.clear()
                            st.rerun()
                        else:
                            st.error(f"Failed: {detail}")
                else:
                    st.error("Alias and URI are required.")
    
    st.markdown("---")
    
    st.header("2. Schema Browser")
    if db_conn_id:
        tables = fetch_tables(db_conn_id)
        if not tables:
            st.info("No tables found for this connection. Click 'Scan Schema' to discover tables.")
            
        with st.expander("🔍 View / Scan Schema", expanded=False):
            table_ids = [t['id'] for t in tables]
            
            if st.button("🔄 Scan Schema"):
                with st.spinner("Scanning database schema..."):
                    try:
                        res = requests.post(
                            f"{API_BASE}/api/v1/table-descriptions/sync-schemas",
                            json={"table_description_ids": table_ids, "instruction": "Generate detailed descriptions for tables and columns"},
                            timeout=60
                        )
                        if res.status_code in [200, 201]:
                            st.success("Schema scanned successfully!")
                            fetch_tables.clear()
                            st.rerun()
                        else:
                            st.error(f"Scan failed: {res.text}")
                    except Exception as e:
                        st.error(f"Error: {e}")
            
            if tables:
                for table in tables:
                    st.markdown(f"**{table.get('table_name')}** ({table.get('schema_name', 'public')})")
                    if table.get("table_description"):
                        st.caption(table.get("table_description"))
    else:
        st.info("Select or create a connection first.")
        
    st.markdown("---")
    
    st.header("3. LLM Configuration")
    model_family = st.selectbox("Model Family", ["google", "openai"], index=0)
    model_name = st.selectbox("Model Name", ["gemini-2.5-flash-lite", "gpt-4o-mini", "gemini-1.5-pro-preview-0409"], index=0)
    
    max_rows = st.number_input("Max Rows", min_value=10, max_value=1000, value=100)
    use_deep_agent = st.checkbox("Use Deep Agent", value=False)
    
# --- MAIN CHAT INTERFACE ---
if "history" not in st.session_state:
    st.session_state["history"] = []

# Display history
for entry in st.session_state["history"]:
    with st.chat_message("user"):
        st.write(entry["query"])
    with st.chat_message("assistant"):
        if "error" in entry:
            st.error(entry["error"])
        else:
            # Display Summary
            if entry.get("summary"):
                st.markdown(f"### Summary\n{entry['summary']}")
            
            # Display SQL
            st.code(entry["sql"], language="sql")
            st.caption(f"Status: {entry.get('sql_status', 'N/A')} | Row Count: {entry.get('row_count', 'N/A')} | Column Count: {entry.get('column_count', 'N/A')}")
            
            # Display Insights
            if entry.get("insights"):
                st.markdown("### Insights")
                for insight in entry["insights"]:
                    st.info(f"**{insight.get('title')}** (Significance: {insight.get('significance')})\n\n{insight.get('description')}")
                    
            # Display Execution Time
            if entry.get("execution_time"):
                st.caption(f"Execution Time: {entry['execution_time'].get('total', 0):.2f}s")

if not db_conn_id:
    st.warning("👈 Please configure a Database Connection in the sidebar to begin.")
    st.stop()
    
# Chat input
if query := st.chat_input("E.g., Kanal laporan mana yang paling sedikit digunakan masyarakat?"):
    # Add user message
    with st.chat_message("user"):
        st.write(query)
        
    with st.chat_message("assistant"):
        with st.spinner("Analyzing and generating SQL..."):
            
            # Extract schemas from selected connection for the payload
            selected_conn_data = next((c for c in connections if c["id"] == db_conn_id), {})
            schemas = selected_conn_data.get("schemas", ["public"])
            if not schemas:
                schemas = ["public"]

            # Construct payload
            payload = {
                "prompt": {
                    "text": query,
                    "db_connection_id": db_conn_id,
                    "schemas": schemas
                },
                "llm_config": {
                    "model_family": model_family,
                    "model_name": model_name
                },
                "max_rows": max_rows,
                "use_deep_agent": use_deep_agent
            }
            
            try:
                response = requests.post(
                    f"{API_BASE}/api/v1/analysis/comprehensive",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code in [200, 201]:
                    data = response.json()
                    
                     # Display Summary
                    if data.get("summary"):
                        st.markdown(f"### Summary\n{data['summary']}")
                    
                    st.code(data.get("sql", "No SQL generated"), language="sql")
                    st.caption(f"Status: {data.get('sql_status', 'N/A')} | Row Count: {data.get('row_count', 'N/A')} | Column Count: {data.get('column_count', 'N/A')}")
                    
                    # Display Insights
                    if data.get("insights"):
                        st.markdown("### Insights")
                        for insight in data["insights"]:
                            st.info(f"**{insight.get('title')}** (Significance: {insight.get('significance')})\n\n{insight.get('description')}")
                            
                    if data.get("execution_time"):
                        st.caption(f"Execution Time: {data['execution_time'].get('total', 0):.2f}s")
                    
                    st.session_state["history"].append({
                        "query": query,
                        "sql": data.get("sql", ""),
                        "sql_status": data.get("sql_status", ""),
                        "summary": data.get("summary", ""),
                        "insights": data.get("insights", []),
                        "row_count": data.get("row_count", 0),
                        "column_count": data.get("column_count", 0),
                        "execution_time": data.get("execution_time", {})
                    })
                else:
                    err_msg = f"Error {response.status_code}: {response.text}"
                    st.error(err_msg)
                    st.session_state["history"].append({
                        "query": query,
                        "error": err_msg
                    })
                    
            except Exception as e:
                st.error(f"Failed to connect: {str(e)}")
                st.session_state["history"].append({
                    "query": query,
                    "error": str(e)
                })
