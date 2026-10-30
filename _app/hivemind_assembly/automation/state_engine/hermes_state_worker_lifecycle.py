# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import json
import time
from hivemind_assembly.automation.state_engine.hermes_state_runtime import RuntimeStoreError

def insert_session_row_in_transaction(self, conn, session_id, source, model=None, model_config=None, system_prompt=None, user_id=None, session_key=None, chat_id=None, chat_type=None, thread_id=None, parent_session_id=None, cwd=None, profile_name=None, git_repo_root=None, origin_json=None, display_name=None, transport_profile=None):
    """Connection-taking body of the keep-existing constructor upsert.

    The ordinary constructor should delegate here too. Worker identity is
    validated before entry; this helper never opens or commits a DB.
    """
    from hivemind_assembly.automation.state_engine.hermes_state_sessions import _UPSERT_KEEP_EXISTING_SQL
    from hivemind_assembly.automation.state_engine.hermes_state_mutation_retirement import RETIRED_PREFIX
    if conn.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone() is None and conn.execute('SELECT 1 FROM state_meta WHERE key=?', (RETIRED_PREFIX + session_id,)).fetchone():
        raise RuntimeStoreError('not_found')
    if not (profile_name or '').strip():
        profile_name = self._own_profile_name()
    system_prompt_hash = self._store_system_prompt(conn, system_prompt)
    conn.execute("INSERT INTO sessions (\n           id, source, created_source, user_id, session_key, chat_id, chat_type, thread_id,\n           model, model_config, system_prompt, system_prompt_hash,\n           parent_session_id, cwd, profile_name, transport_profile, git_repo_root,\n           origin_json, display_name, started_at\n        )\n           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n           ON CONFLICT(id) DO UPDATE SET\n               source = CASE\n                   WHEN sessions.source = 'unknown'\n                   THEN COALESCE(excluded.source, 'unknown')\n                   ELSE sessions.source\n               END,\n               model = COALESCE(sessions.model, excluded.model),\n               model_config = CASE\n                   WHEN excluded.model_config IS NOT NULL\n                        AND json_type(\n                            sessions.model_config, '$._reset_from'\n                        ) IS NOT NULL\n                        AND json_remove(\n                            sessions.model_config, '$._reset_from'\n                        ) = '{}'\n                   THEN json_set(\n                       excluded.model_config,\n                       '$._reset_from',\n                       json_extract(\n                           sessions.model_config, '$._reset_from'\n                       )\n                   )\n                   ELSE COALESCE(\n                       sessions.model_config, excluded.model_config\n                   )\n               END,\n               system_prompt_hash = COALESCE(\n                   sessions.system_prompt_hash,\n                   excluded.system_prompt_hash\n               ),\n               system_prompt = CASE\n                   WHEN sessions.system_prompt_hash IS NULL\n                        AND excluded.system_prompt_hash IS NOT NULL\n                   THEN NULL\n                   ELSE sessions.system_prompt\n               END,\n" + _UPSERT_KEEP_EXISTING_SQL, (session_id, source, source, user_id, session_key, chat_id, chat_type, thread_id, model, json.dumps(model_config) if model_config else None, system_prompt_hash, parent_session_id, cwd, profile_name, transport_profile, git_repo_root, origin_json, display_name, time.time()))
    if system_prompt_hash is not None:
        self._delete_unreferenced_system_prompts(conn)
    if parent_session_id:
        self._inherit_parent_session_metadata(conn, session_id)
