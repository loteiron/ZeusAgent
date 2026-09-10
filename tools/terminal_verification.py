"""Evidence capture at execution boundaries; never executes or approves commands."""

import logging

logger = logging.getLogger(__name__)


def capture_before(command, cwd, session_id, *, local=True):
    try:
        from agent.verification_evidence import begin_verification

        return begin_verification(command=command, cwd=cwd, session_id=session_id, local=local)
    except Exception:
        logger.debug("Could not capture verification start", exc_info=True)
        return None


def record_process_completion(session):
    if session.verification_before is None:
        return
    try:
        from agent.verification_evidence import record_terminal_result

        # A recovered/lost process has no observed exit code. Never fabricate success.
        if session.exit_code is None or session.detached:
            return
        record_terminal_result(command=session.command, cwd=session.cwd,
                               session_id=session.parent_session_id or session.owner_task_id or session.task_id,
                               exit_code=session.exit_code, output=session.output_buffer,
                               workspace_before=session.verification_before,
                               workspace_after=session.verification_before if session.pid_scope != "host" else None)
    except Exception:
        logger.debug("Could not record background verification result", exc_info=True)


def record_execution_failure(command, cwd, session_id, before, output, *, local=True):
    if before is None:
        return
    try:
        from agent.verification_evidence import record_terminal_result

        record_terminal_result(command=command, cwd=cwd, session_id=session_id, exit_code=-1,
                               output=output, workspace_before=before,
                               workspace_after=before if not local else None)
    except Exception:
        logger.debug("Could not record failed verification execution", exc_info=True)
