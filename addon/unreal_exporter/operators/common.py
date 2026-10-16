"""Helpers shared by operators: runtime state storage and reporting."""

import os
import traceback

from .. import constants as C


def state(context):
    return getattr(context.window_manager, C.PROP_ATTR)


def settings(context):
    return getattr(context.scene, C.PROP_ATTR)


def store_issues(context, issues, asset_count):
    st = state(context)
    st.issues.clear()
    counts = {C.SEVERITY_ERROR: 0, C.SEVERITY_WARNING: 0, C.SEVERITY_INFO: 0}
    for issue in issues:
        item = st.issues.add()
        item.code = issue.code
        item.severity = issue.severity
        item.message = issue.message
        item.object_name = issue.object_id
        item.fix_id = issue.fix_id
        item.asset_id = issue.asset_id
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    st.issue_errors = counts[C.SEVERITY_ERROR]
    st.issue_warnings = counts[C.SEVERITY_WARNING]
    st.issue_infos = counts[C.SEVERITY_INFO]
    st.issues_index = 0
    st.validated = True
    st.validated_assets = asset_count


def store_result(context, result, root):
    st = state(context)
    st.results.clear()
    for record in result.files:
        item = st.results.add()
        item.asset_name = record.asset_name
        item.kind = record.kind
        item.relpath = record.relpath
        item.unreal_path = record.unreal_path
        item.status = record.status
        item.seconds = record.seconds
        item.message = record.error
    written = sum(1 for r in result.files if r.status == "written")
    seconds = sum(r.seconds for r in result.files)
    parts = ["%d of %d written in %.1fs" % (written, len(result.files), seconds)]
    if result.failures:
        parts.append("%d failure(s)" % len(result.failures))
    if result.cancelled:
        parts.append("cancelled")
    st.result_summary = ", ".join(parts)
    st.result_ok = result.ok
    st.result_dir = root
    st.last_plan_id = result.plan_id
    st.manifest_path = result.manifest_path
    st.script_path = result.script_path
    st.log_path = result.log_path
    st.receipt_summary = ""


def report_exception(operator, exc, what="Operation"):
    operator.report({"ERROR"}, "%s failed: %s" % (what, exc))
    print("[Unreal Export Bridge] %s failed:\n%s" % (what, traceback.format_exc()))


def issue_report(operator, prepared):
    """Summarize validation. Findings are a WARNING report, never ERROR: finding problems
    is the validator succeeding, and ERROR would make ``bpy.ops`` raise in scripts."""
    counts = prepared.counts
    operator.report(
        {"WARNING"} if (counts[C.SEVERITY_ERROR] or counts[C.SEVERITY_WARNING]) else {"INFO"},
        "Validation: %d asset(s), %d error(s), %d warning(s)" % (
            len(prepared.discovery.assets), counts[C.SEVERITY_ERROR], counts[C.SEVERITY_WARNING]),
    )


def exists(path):
    return bool(path) and os.path.exists(path)
