import os
import streamlit as st

from storage import AssignmentRepository, configure_logging, get_default_paths
from tracker import (
    add_assignment,
    days_until_due,
    delete_assignment,
    export_to_csv_string,
    generate_status_chart,
    get_summary_counts,
    mark_completed,
    refresh_overdue_statuses,
    search_assignments,
    sort_by_urgency,
)

PATHS = get_default_paths(os.path.dirname(os.path.abspath(__file__)))
configure_logging(PATHS["log_file"])


def get_timing_label(record: dict) -> str:
    try:
        diff = days_until_due(record["due_date"])
        if record.get("status") == "Completed":
            return "Done"
        if diff < 0:
            return f"{abs(diff)}d late"
        if diff == 0:
            return "Due today"
        return f"{diff}d left"
    except ValueError:
        return "Invalid date"


def persist_safely(repo: AssignmentRepository, records: list, action: str) -> bool:
    try:
        repo.save(records)
        return True
    except TimeoutError as exc:
        st.error(f"Storage is busy (lock timeout) while {action}: {exc}")
    except PermissionError as exc:
        st.error(f"Permission denied while {action}: {exc}")
    except OSError as exc:
        st.error(f"Disk/File error while {action}: {exc}")
    return False


def main() -> None:
    st.set_page_config(page_title="Assignment Deadline Tracker", page_icon="📚", layout="wide")
    st.title("📚 Assignment Deadline Tracker")
    st.caption("Modular Python web UI backed by AssignmentRepository & atomic JSON persistence")

    repo = AssignmentRepository(PATHS["data_file"])

    try:
        records, changed = refresh_overdue_statuses(repo.load())
        if changed:
            persist_safely(repo, records, "refreshing overdue statuses")
    except (TimeoutError, OSError) as exc:
        st.warning(f"Could not read existing storage ({exc}). Starting with an empty list.")
        records = []

    # Summary Metrics
    counts = get_summary_counts(records)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Assignments", counts["total"])
    col2.metric("Pending", counts["pending"])
    col3.metric("Overdue", counts["overdue"])
    col4.metric("Completed", counts["completed"])

    if counts["overdue"] > 0:
        st.warning(f"You have {counts['overdue']} overdue assignment(s)!")

    tab_view, tab_add, tab_manage, tab_export = st.tabs(
        ["📋 View & Search", "➕ Add Assignment", "✅ Complete / Delete", "📊 Export & Chart"]
    )

    # Tab 1: View & Search
    with tab_view:
        query = st.text_input("Search by ID, assignment name, course, or status", placeholder="e.g. CS101 or Overdue")
        filtered = sort_by_urgency(search_assignments(records, query))

        if not filtered:
            st.info("No matching assignments found.")
        else:
            table_rows = [
                {
                    "ID": r["id"],
                    "Assignment": r["assignment"],
                    "Course": r["course"],
                    "Due Date": r["due_date"],
                    "Status": r["status"],
                    "Timing": get_timing_label(r),
                }
                for r in filtered
            ]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

    # Tab 2: Add Assignment
    with tab_add:
        with st.form("add_assignment_form", clear_on_submit=True):
            title = st.text_input("Assignment Name *", placeholder="e.g. Data Structures Lab 3")
            course = st.text_input("Course Code", placeholder="e.g. CS201 (defaults to GENERAL)")
            due_date = st.date_input("Due Date *")
            submitted = st.form_submit_button("Add Assignment")

            if submitted:
                try:
                    updated, created = add_assignment(records, title, course, due_date.isoformat())
                    if persist_safely(repo, updated, "adding assignment"):
                        st.success(f"Added {created['id']}: {created['assignment']} [{created['status']}]")
                        st.rerun()
                except ValueError as exc:
                    st.error(f"Validation Error: {exc}")

    # Tab 3: Complete / Delete
    with tab_manage:
        if not records:
            st.info("No assignments available to update or delete.")
        else:
            sorted_records = sort_by_urgency(records)
            options = {
                f"{r['id']} — {r['assignment']} ({r['course']} | {r['status']})": r["id"]
                for r in sorted_records
            }
            selected_label = st.selectbox("Select an assignment", list(options.keys()))
            selected_id = options[selected_label]

            c_done, c_del = st.columns(2)
            with c_done:
                if st.button("✅ Mark as Completed", use_container_width=True):
                    try:
                        updated = mark_completed(records, selected_id)
                        if persist_safely(repo, updated, "marking completed"):
                            st.success(f"Marked {selected_id} as Completed.")
                            st.rerun()
                    except KeyError as exc:
                        st.error(str(exc))

            with c_del:
                if st.button("🗑️ Delete Assignment", type="secondary", use_container_width=True):
                    try:
                        updated = delete_assignment(records, selected_id)
                        if persist_safely(repo, updated, "deleting assignment"):
                            st.success(f"Deleted {selected_id}.")
                            st.rerun()
                    except KeyError as exc:
                        st.error(str(exc))

    # Tab 4: Export & Chart
    with tab_export:
        csv_data = export_to_csv_string(records)
        st.download_button(
            label="⬇️ Download CSV Report",
            data=csv_data,
            file_name="assignments.csv",
            mime="text/csv",
        )

        if st.button("📈 Generate Status Chart (PNG)"):
            if generate_status_chart(records, PATHS["chart_file"]) and os.path.exists(PATHS["chart_file"]):
                st.image(PATHS["chart_file"], caption="Assignment Status Breakdown")
                with open(PATHS["chart_file"], "rb") as img_file:
                    st.download_button(
                        label="⬇️ Download PNG Chart",
                        data=img_file.read(),
                        file_name="status_chart.png",
                        mime="image/png",
                    )
            else:
                st.warning("Install matplotlib (`pip install matplotlib`) to generate the status chart.")


if __name__ == "__main__":
    main()